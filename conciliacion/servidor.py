"""Servidor HTTP del reporte: sirve la interfaz y /api/reporte con caché por periodo."""
import base64
import datetime as dt
import gzip
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from sqlalchemy.engine import Engine

from .config import Mpro, Servidor
from .reporte import construir
from .resumen import consultar_mpro_emitidos, consultar_retenciones, consultar_sat, resumir
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

    def _entrada(self, ini: str, fin: str, refrescar: bool) -> tuple[dict, bool]:
        """Entrada de caché del periodo (la construye si falta o venció). Llamar con el candado tomado."""
        c = self._items.get((ini, fin))
        vigente = c is not None and not refrescar and time.time() - c["t"] < self.ttl
        if not vigente:
            t0 = time.time()
            ff = (dt.date.fromisoformat(fin) + dt.timedelta(days=1)).isoformat()
            c = {"t": time.time(), "d": construir(self.engine, ini, ff, self.engine_sat), "gz": {},
                 "seg": round(time.time() - t0, 1), "generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            self._items[(ini, fin)] = c
            while len(self._items) > self.maximo:
                self._items.pop(min(self._items, key=lambda k: self._items[k]["t"]))
        return c, vigente

    def resumen(self, ini: str, fin: str, refrescar: bool) -> dict:
        with self._lock:
            c, vigente = self._entrada(ini, fin, refrescar)
            if "resumen" not in c:
                ff = (dt.date.fromisoformat(fin) + dt.timedelta(days=1)).isoformat()
                sat = self.engine_sat
                c["resumen"] = resumir(c["d"], consultar_sat(sat, ini, ff) if sat is not None else None, consultar_mpro_emitidos(self.engine, ini, ff),
                                       consultar_retenciones(sat, ini, ff) if sat is not None else None)
            return {**c["resumen"], "meta": {"fuente": self.etiqueta, "ini": ini, "fin": fin, "generado": c["generado"], "cache": vigente}}

    def reporte(self, ini: str, fin: str, vista: str, agrupar: bool, refrescar: bool) -> tuple[bytes, bool]:
        """Devuelve (JSON gzip, vino_de_caché)."""
        with self._lock:
            c, vigente = self._entrada(ini, fin, refrescar)
            if vigente and (vista, agrupar) in c["gz"]:
                return c["gz"][(vista, agrupar)], True
            datos = a_datos(c["d"], vista, agrupar)
            datos["meta"] = {"fuente": self.etiqueta, "ini": ini, "fin": fin, "filas": len(datos["rows"]),
                             "vista": vista, "agrupar": datos["agrupar"], "generado": c["generado"],
                             "seg_consulta": c["seg"], "sat": "SAT_UUID" in c["d"]}
            gz = gzip.compress(json.dumps(datos, ensure_ascii=False, separators=(",", ":")).encode(), 5)
            c["gz"][(vista, agrupar)] = gz
            return gz, vigente


def _periodo(q: dict) -> tuple[str, str]:
    ini, fin = q["ini"][0], q["fin"][0]
    a, z = dt.date.fromisoformat(ini), dt.date.fromisoformat(fin)
    if z < a or (z - a).days > MAX_DIAS:
        raise ValueError("Rango inválido (máx. 1 año, fin >= inicio).")
    return ini, fin


def _parametros(q: dict) -> tuple[str, str, str, bool]:
    ini, fin = _periodo(q)
    vista = q.get("vista", ["layout"])[0]
    if vista not in VISTAS:
        raise ValueError("vista debe ser layout o ceco.")
    return ini, fin, vista, q.get("agrupar", ["1"])[0] != "0"


def crear_servidor(cfg: Servidor, mpro: Mpro, engine: Engine, engine_sat: Engine | None = None) -> ThreadingHTTPServer:
    esperado = "Basic " + base64.b64encode(f"{cfg.usuario}:{cfg.clave}".encode()).decode()
    pagina = (resources.files("conciliacion") / "static" / "index.html").read_bytes()
    cache = Cache(engine, mpro.etiqueta, cfg.ttl_seg, cfg.max_cache, engine_sat)

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
            if u.path not in ("/api/reporte", "/api/resumen"):
                return self._enviar(404, b"No encontrado", "text/plain; charset=utf-8")
            q = parse_qs(u.query)
            if u.path == "/api/resumen":
                try:
                    ini, fin = _periodo(q)
                except (KeyError, ValueError) as e:
                    return self._enviar(400, str(e).encode(), "text/plain; charset=utf-8")
                try:
                    r = cache.resumen(ini, fin, "refresh" in q)
                except Exception as e:
                    print("ERROR", repr(e), flush=True)
                    return self._enviar(500, ERROR_BD.encode(), "text/plain; charset=utf-8")
                return self._enviar(200, json.dumps(r, ensure_ascii=False, separators=(",", ":")).encode(),
                                    "application/json; charset=utf-8", [("Cache-Control", "no-store")])
            try:
                ini, fin, vista, agrupar = _parametros(q)
            except (KeyError, ValueError) as e:
                return self._enviar(400, str(e).encode(), "text/plain; charset=utf-8")
            try:
                gz, hit = cache.reporte(ini, fin, vista, agrupar, "refresh" in q)
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

    return ThreadingHTTPServer(("0.0.0.0", cfg.puerto), Manejador)
