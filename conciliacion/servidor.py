"""Servidor HTTP del reporte: sirve la interfaz y /api/reporte con caché por periodo."""
import base64
import datetime as dt
import gzip
import hmac
import fcntl
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

from . import actualizar
from .config import Mpro, Servidor
from .db import consultar
from .dialecto import BACKEND
from .posproceso import describir_criterios
from .reporte import construir, construir_emitidos, construir_traslados
from .resumen import consultar_mpro, consultar_retenciones, consultar_sat, diferencias, resumir
from .vista import VISTAS, a_datos

MAX_DIAS = 366
ERROR_BD = "Error consultando la base de Mpro; reintenta o avisa a TI."


CONSTRUCTORES = {"recibidos": construir, "emitidos": construir_emitidos, "traslados": construir_traslados}
SENTIDOS = tuple(CONSTRUCTORES)


class Cache:
    """DataFrame por (ini, fin) con TTL; JSON comprimido por (vista, agrupar, excluidos)."""

    def __init__(self, engine: Engine, etiqueta: str, ttl_seg: int, maximo: int, engine_sat: Engine | None = None, sentido: str = "recibidos"):
        self.engine, self.etiqueta, self.ttl, self.maximo = engine, etiqueta, ttl_seg, maximo
        self.sentido = sentido  # recibidos | emitidos (ventas, NC y cobranza de cliente) | traslados
        self.emitidos = sentido == "emitidos"
        self.engine_sat = engine_sat
        self._items: dict = {}
        self._res: dict = {}
        self._lock = threading.Lock()  # protege los diccionarios; cada periodo tiene además su propio candado
        self._lock_res = threading.Lock()
        self._locks: dict = {}
        self.datos = lambda: None  # marca de frescura de los datos; si cambia, el caché ya no vale

    def _candado(self, ini: str, fin: str) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault((ini, fin), threading.Lock())

    def _entrada(self, ini: str, fin: str, refrescar: bool) -> tuple[dict, bool]:
        """Entrada de caché del periodo (la construye si falta o venció). Llamar con el candado del periodo tomado."""
        c = self._items.get((ini, fin))
        vigente = c is not None and not refrescar and c.get("datos") == self.datos() and time.time() - c["t"] < self.ttl
        if not vigente:
            t0 = time.time()
            ff = (dt.date.fromisoformat(fin) + dt.timedelta(days=1)).isoformat()
            d = CONSTRUCTORES[self.sentido](self.engine, ini, ff, self.engine_sat)
            c = {"t": time.time(), "d": d, "gz": {}, "datos": self.datos(),
                 "seg": round(time.time() - t0, 1), "generado": dt.datetime.now(actualizar.TZ).strftime("%Y-%m-%d %H:%M:%S")}
            with self._lock:
                self._items[(ini, fin)] = c
                while len(self._items) > self.maximo:
                    self._items.pop(min(self._items, key=lambda k: self._items[k]["t"]))
        return c, vigente

    def resumen(self, ini: str, fin: str, refrescar: bool) -> dict:
        """Agregados directos (Postgres SAT + Comprobante_Digital); no construye el reporte completo."""
        with self._lock_res:
            c = self._res.get((ini, fin))
            vigente = c is not None and not refrescar and c.get("datos") == self.datos() and time.time() - c["t"] < self.ttl
            if not vigente:
                ff = (dt.date.fromisoformat(fin) + dt.timedelta(days=1)).isoformat()
                sat = self.engine_sat
                r = resumir(consultar_sat(sat, ini, ff) if sat is not None else None, consultar_mpro(self.engine, ini, ff, False),
                            consultar_mpro(self.engine, ini, ff, True), consultar_retenciones(sat, ini, ff) if sat is not None else None)
                c = self._res[(ini, fin)] = {"t": time.time(), "r": r, "datos": self.datos(), "generado": dt.datetime.now(actualizar.TZ).strftime("%Y-%m-%d %H:%M:%S")}
                while len(self._res) > self.maximo:
                    self._res.pop(min(self._res, key=lambda k: self._res[k]["t"]))
            return {**c["r"], "meta": {"fuente": self.etiqueta, "ini": ini, "fin": fin, "generado": c["generado"], "cache": vigente}}

    def diferencias(self, ini: str, fin: str) -> dict:
        """Lista de documentos con diferencia (requiere el reporte completo del periodo; es lo lento)."""
        with self._candado(ini, fin):
            c, _ = self._entrada(ini, fin, False)
            return diferencias(c["d"])

    def reporte(self, ini: str, fin: str, vista: str, agrupar: bool, excluidos: bool, refrescar: bool) -> tuple[bytes, bool]:
        """Devuelve (JSON gzip, vino_de_caché)."""
        with self._candado(ini, fin):
            c, vigente = self._entrada(ini, fin, refrescar)
            clave = (vista, agrupar, excluidos)
            if vigente and clave in c["gz"]:
                return c["gz"][clave], True
            datos = a_datos(c["d"], vista, agrupar, excluidos, self.emitidos, self.sentido == "traslados")
            datos["meta"] = {"fuente": self.etiqueta, "ini": ini, "fin": fin, "filas": len(datos["rows"]),
                             "vista": vista, "agrupar": datos["agrupar"], "excluidos": excluidos, "generado": c["generado"],
                             "seg_consulta": c["seg"], "sat": "SAT_UUID" in c["d"], "sentido": self.sentido}
            gz = gzip.compress(json.dumps(datos, ensure_ascii=False, separators=(",", ":")).encode(), 5)
            c["gz"][clave] = gz
            return gz, vigente


def criterios(engine) -> dict:
    """Criterios de exclusión (informativo): reglas de `posproceso` con el nombre de cada Tipo de gasto del catálogo."""
    try:
        with engine.connect() as con:
            d = consultar(con, "SELECT Tg_Cve_Tipo_Gasto AS CLAVE, Tg_Descripcion AS DESCRIPCION FROM Tipo_Gasto")
        d.columns = [c.upper() for c in d.columns]
        tipos = {str(c).strip(): str(x).strip() for c, x in zip(d.CLAVE, d.DESCRIPCION)}
    except Exception as e:
        print("ERROR criterios", repr(e), flush=True)
        tipos = {}
    return {"criterios": describir_criterios(tipos)}


PERIODO_DEFECTO = ("2026-01-01", "2026-01-31")  # el mismo que trae la interfaz al abrir


def periodos_a_precalentar(hoy: dt.date) -> list[tuple[str, str]]:
    """El periodo con el que abre la interfaz y el mes en curso."""
    ini = hoy.replace(day=1)
    fin = (ini + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
    return [PERIODO_DEFECTO] + [(ini.isoformat(), fin.isoformat())] * ((ini.isoformat(), fin.isoformat()) != PERIODO_DEFECTO)


def precalentar(cache: Cache, espera_seg: int = 60) -> None:
    """Hilo: cuando los datos cambian (o al arrancar) arma en caché el periodo por defecto y el mes en curso, fuera de la ventana de crons."""
    ultima = object()
    while True:
        try:
            marca = cache.datos()
            if marca != ultima and not actualizar.en_ventana_cron():
                for ini, fin in periodos_a_precalentar(dt.date.today()):
                    cache.reporte(ini, fin, "layout", True, False, False)
                ultima = marca
        except Exception as e:
            print("ERROR precalentado", repr(e), flush=True)
        time.sleep(espera_seg)


PIPELINES_INGEST = ("trivasa_gastos_cxp", "comprobante_digital_compra")


def estado_ingest(engine: Engine) -> dict:
    """Estado del refresco + `datos`: última vez que corrió el ingest (botón o cron)."""
    d = actualizar.leer_estado()
    if d.get("estado") == "corriendo":
        try:  # dice "corriendo" pero nadie tiene el lock: el proceso murió
            with open(actualizar.STATE_DIR / "actualizar.lock", "w") as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            d = {**d, "estado": "error", "error": "El refresco se interrumpió."}
        except OSError:
            pass
    try:
        with engine.connect() as con:
            cron = con.scalar(text("SELECT max(inserted_at) FROM _dlt_loads WHERE status=0 AND schema_name IN :n").bindparams(
                bindparam("n", expanding=True)), {"n": list(PIPELINES_INGEST)})
        if cron:
            cron = cron.astimezone(actualizar.TZ).isoformat(timespec="seconds")
    except Exception:
        cron = None
    d["ahora"] = time.time()
    d["datos"] = max(filter(None, [d.get("ultima_ok"), cron]), default=None)
    return d


def lanzar_ingest() -> None:
    """Corre el refresco en su propia unidad systemd: si el OOM killer lo mata, el servidor sigue vivo."""
    cmd = [sys.executable, "-m", "conciliacion.actualizar"]
    log = actualizar.STATE_DIR / "actualizar.log"
    actualizar.STATE_DIR.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["systemd-run", "--user", "--collect", "--quiet", "--unit=conciliacion-actualizar",
                        "--property=OOMScoreAdjust=500", f"--property=StandardOutput=append:{log}",
                        f"--property=StandardError=append:{log}", f"--working-directory={Path(__file__).resolve().parent.parent}",
                        *(f"--setenv={k}={v}" for k, v in os.environ.items() if k in ("BI_CORE", "STATE_DIR")), *cmd],
                       capture_output=True, text=True)
    if r.returncode != 0 and "already" not in r.stderr and "ya existe" not in r.stderr:  # sin bus de usuario: proceso suelto
        subprocess.Popen(cmd, cwd=Path(__file__).resolve().parent.parent, start_new_session=True,
                         stdout=open(log, "a"), stderr=subprocess.STDOUT)


def _periodo(q: dict) -> tuple[str, str]:
    ini, fin = q["ini"][0], q["fin"][0]
    a, z = dt.date.fromisoformat(ini), dt.date.fromisoformat(fin)
    if z < a or (z - a).days > MAX_DIAS:
        raise ValueError("Rango inválido (máx. 1 año, fin >= inicio).")
    return ini, fin


def _parametros(q: dict) -> tuple[str, str, str, bool, str, bool]:
    ini, fin = _periodo(q)
    vista = q.get("vista", ["layout"])[0]
    if vista not in VISTAS:
        raise ValueError("vista debe ser layout o ceco.")
    sentido = q.get("sentido", ["recibidos"])[0]
    if sentido not in SENTIDOS:
        raise ValueError("sentido debe ser recibidos, emitidos o traslados.")
    if sentido != "recibidos" and BACKEND != "mssql":
        raise ValueError("Ventas y traslados solo están disponibles con CONC_BACKEND=mssql (el warehouse no replica Factura/Nota_Credito/Traslado/Cliente).")
    return ini, fin, vista, q.get("agrupar", ["1"])[0] != "0", sentido, q.get("excluidos", ["0"])[0] == "1"


def crear_servidor(cfg: Servidor, mpro: Mpro, engine: Engine, engine_sat: Engine | None = None, precalienta: bool = False) -> ThreadingHTTPServer:
    esperado = "Basic " + base64.b64encode(f"{cfg.usuario}:{cfg.clave}".encode()).decode()
    pagina = (resources.files("conciliacion") / "static" / "index.html").read_bytes()
    cache = Cache(engine, mpro.etiqueta, cfg.ttl_seg, cfg.max_cache, engine_sat)
    caches = {"recibidos": cache}
    caches.update({s: Cache(engine, mpro.etiqueta, cfg.ttl_seg, cfg.max_cache, engine_sat, s) for s in SENTIDOS[1:]})
    habilitado = BACKEND == "postgres"
    memo = {"t": 0.0, "v": None}

    def estado() -> dict:
        if time.time() - memo["t"] > 15 or memo["v"].get("estado") == "corriendo":
            memo.update(t=time.time(), v={**estado_ingest(engine), "habilitado": habilitado})
        return memo["v"]

    if habilitado:
        for c in caches.values():
            c.datos = lambda: estado().get("datos")
    if precalienta:
        threading.Thread(target=precalentar, args=(cache,), daemon=True).start()

    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _enviar(self, codigo: int, cuerpo: bytes, tipo: str, extra=()):
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_GET(self):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), esperado):
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="Trivasa"')
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                return self._enviar(200, pagina, "text/html; charset=utf-8", [("Cache-Control", "no-store")])
            if u.path == "/api/estado":
                memo["t"] = 0.0
                return self._enviar(200, json.dumps(estado(), ensure_ascii=False).encode(), "application/json; charset=utf-8",
                                    [("Cache-Control", "no-store")])
            if u.path == "/api/criterios":
                return self._enviar(200, json.dumps(criterios(engine), ensure_ascii=False).encode(), "application/json; charset=utf-8",
                                    [("Cache-Control", "no-store")])
            if u.path not in ("/api/reporte", "/api/resumen", "/api/diferencias"):
                return self._enviar(404, b"No encontrado", "text/plain; charset=utf-8")
            q = parse_qs(u.query)
            if u.path in ("/api/resumen", "/api/diferencias"):
                try:
                    ini, fin = _periodo(q)
                except (KeyError, ValueError) as e:
                    return self._enviar(400, str(e).encode(), "text/plain; charset=utf-8")
                try:
                    r = cache.resumen(ini, fin, "refresh" in q) if u.path == "/api/resumen" else cache.diferencias(ini, fin)
                except Exception as e:
                    print("ERROR", repr(e), flush=True)
                    return self._enviar(500, ERROR_BD.encode(), "text/plain; charset=utf-8")
                return self._enviar(200, json.dumps(r, ensure_ascii=False, separators=(",", ":")).encode(),
                                    "application/json; charset=utf-8", [("Cache-Control", "no-store")])
            try:
                ini, fin, vista, agrupar, sentido, excluidos = _parametros(q)
            except (KeyError, ValueError) as e:
                return self._enviar(400, str(e).encode(), "text/plain; charset=utf-8")
            try:
                gz, hit = caches[sentido].reporte(ini, fin, vista, agrupar, excluidos, False)
            except Exception as e:
                print("ERROR", repr(e), flush=True)
                return self._enviar(500, ERROR_BD.encode(), "text/plain; charset=utf-8")
            acepta_gz = "gzip" in self.headers.get("Accept-Encoding", "")
            if hit:
                d = json.loads(gzip.decompress(gz))
                d["meta"]["cache"] = True
                cuerpo = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode()
                cuerpo = gzip.compress(cuerpo, 3) if acepta_gz else cuerpo
            else:
                cuerpo = gz if acepta_gz else gzip.decompress(gz)
            extra = [("Cache-Control", "no-store")] + ([("Content-Encoding", "gzip")] if acepta_gz else [])
            return self._enviar(200, cuerpo, "application/json; charset=utf-8", extra)

        def do_POST(self):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), esperado):
                self.send_response(401)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            # Header propio: obliga preflight CORS y evita que otro sitio dispare el POST con las credenciales del navegador.
            if urlparse(self.path).path != "/api/actualizar" or self.headers.get("X-Conciliacion") != "1" or not habilitado:
                return self._enviar(404 if not habilitado else 403, b"No permitido", "text/plain; charset=utf-8")
            if estado().get("estado") != "corriendo":
                if actualizar.en_ventana_cron():
                    return self._enviar(409, json.dumps({"motivo": actualizar.MOTIVO_VENTANA}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                lanzar_ingest()
                time.sleep(1.5)
                memo["t"] = 0.0
            return self._enviar(202, json.dumps(estado(), ensure_ascii=False).encode(), "application/json; charset=utf-8")

    return ThreadingHTTPServer(("0.0.0.0", cfg.puerto), Manejador)
