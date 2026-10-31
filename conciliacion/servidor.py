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
from .dialecto import BACKEND
from .reporte import construir
from .vista import VISTAS, a_datos

MAX_DIAS = 366
ERROR_BD = "Error consultando la base de Mpro; reintenta o avisa a TI."


class Cache:
    """DataFrame por (ini, fin) con TTL; JSON comprimido por (vista, agrupar)."""

    def __init__(self, engine: Engine, etiqueta: str, ttl_seg: int, maximo: int, engine_sat: Engine | None = None):
        self.engine, self.etiqueta, self.ttl, self.maximo = engine, etiqueta, ttl_seg, maximo
        self.engine_sat = engine_sat
        self._items: dict = {}
        self._lock = threading.Lock()
        self.datos = lambda: None  # marca de frescura de los datos; si cambia, el caché ya no vale

    def reporte(self, ini: str, fin: str, vista: str, agrupar: bool, refrescar: bool) -> tuple[bytes, bool]:
        """Devuelve (JSON gzip, vino_de_caché)."""
        with self._lock:
            c = self._items.get((ini, fin))
            vigente = c is not None and not refrescar and c.get("datos") == self.datos() and time.time() - c["t"] < self.ttl
            if vigente and (vista, agrupar) in c["gz"]:
                return c["gz"][(vista, agrupar)], True
            if not vigente:
                t0 = time.time()
                ff = (dt.date.fromisoformat(fin) + dt.timedelta(days=1)).isoformat()
                c = {"t": time.time(), "d": construir(self.engine, ini, ff, self.engine_sat), "gz": {}, "datos": self.datos(),
                     "seg": round(time.time() - t0, 1), "generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                self._items[(ini, fin)] = c
                while len(self._items) > self.maximo:
                    self._items.pop(min(self._items, key=lambda k: self._items[k]["t"]))
            datos = a_datos(c["d"], vista, agrupar)
            datos["meta"] = {"fuente": self.etiqueta, "ini": ini, "fin": fin, "filas": len(datos["rows"]),
                             "vista": vista, "agrupar": datos["agrupar"], "generado": c["generado"],
                             "seg_consulta": c["seg"], "sat": "SAT_UUID" in c["d"]}
            gz = gzip.compress(json.dumps(datos, ensure_ascii=False, separators=(",", ":")).encode(), 5)
            c["gz"][(vista, agrupar)] = gz
            return gz, vigente


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


def _parametros(q: dict) -> tuple[str, str, str, bool]:
    ini, fin = q["ini"][0], q["fin"][0]
    a, z = dt.date.fromisoformat(ini), dt.date.fromisoformat(fin)
    if z < a or (z - a).days > MAX_DIAS:
        raise ValueError("Rango inválido (máx. 1 año, fin >= inicio).")
    vista = q.get("vista", ["layout"])[0]
    if vista not in VISTAS:
        raise ValueError("vista debe ser layout o ceco.")
    return ini, fin, vista, q.get("agrupar", ["1"])[0] != "0"


def crear_servidor(cfg: Servidor, mpro: Mpro, engine: Engine, engine_sat: Engine | None = None) -> ThreadingHTTPServer:
    esperado = "Basic " + base64.b64encode(f"{cfg.usuario}:{cfg.clave}".encode()).decode()
    pagina = (resources.files("conciliacion") / "static" / "index.html").read_bytes()
    cache = Cache(engine, mpro.etiqueta, cfg.ttl_seg, cfg.max_cache, engine_sat)
    habilitado = BACKEND == "postgres"
    memo = {"t": 0.0, "v": None}

    def estado() -> dict:
        if time.time() - memo["t"] > 15 or memo["v"].get("estado") == "corriendo":
            memo.update(t=time.time(), v={**estado_ingest(engine), "habilitado": habilitado})
        return memo["v"]

    if habilitado:
        cache.datos = lambda: estado().get("datos")

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
                return self._enviar(200, pagina, "text/html; charset=utf-8")
            if u.path == "/api/estado":
                memo["t"] = 0.0
                return self._enviar(200, json.dumps(estado(), ensure_ascii=False).encode(), "application/json; charset=utf-8",
                                    [("Cache-Control", "no-store")])
            if u.path != "/api/reporte":
                return self._enviar(404, b"No encontrado", "text/plain; charset=utf-8")
            q = parse_qs(u.query)
            try:
                ini, fin, vista, agrupar = _parametros(q)
            except (KeyError, ValueError) as e:
                return self._enviar(400, str(e).encode(), "text/plain; charset=utf-8")
            try:
                gz, hit = cache.reporte(ini, fin, vista, agrupar, False)
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
                lanzar_ingest()
                time.sleep(1.5)
                memo["t"] = 0.0
            return self._enviar(202, json.dumps(estado(), ensure_ascii=False).encode(), "application/json; charset=utf-8")

    return ThreadingHTTPServer(("0.0.0.0", cfg.puerto), Manejador)
