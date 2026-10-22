"""Reporte de gastos con formato de poliza, consultando en vivo la BD .207 (TRIVASADB).

GET /               -> plantilla.html (selector de fechas, carga por fetch)
GET /api/reporte    -> ?ini=AAAA-MM-DD&fin=AAAA-MM-DD[&vista=layout|ceco][&agrupar=0|1][&refresh=1]  JSON {cols,rows,meta} (gzip)
                       Incluye Gasto, Compra, Indirecto, NC proveedor, CxP libre y CxP orden compra (columna Tipo). Vista por defecto: layout, agrupada por cuenta.
Variables: APP_USER, APP_PASS, APP_PORT, TTL_SEG (cache, default 600).
Credenciales de BD: shared.db_credentials.ealcocer() de trivasa-bi-core (no se escriben en disco).
"""
import base64, datetime as dt, gzip, json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

aqui = os.path.dirname(os.path.abspath(__file__))
USER, PASS = os.environ.get('APP_USER'), os.environ.get('APP_PASS')
if not USER or not PASS:
    sys.exit('Define APP_USER y APP_PASS (basic auth).')
OK = 'Basic ' + base64.b64encode(f'{USER}:{PASS}'.encode()).decode()
TTL = int(os.environ.get('TTL_SEG', 600))

sys.path.insert(0, os.path.expanduser('~/ehalso/trivasa-bi-core'))
from shared import db_credentials
_u, _p = db_credentials.ealcocer()
os.environ['MSSQL_207_USER'], os.environ['MSSQL_207_PASSWORD'] = _u, _p
os.environ['MPRO_HOST'], os.environ['MPRO_DB'] = '192.168.117.207', 'TRIVASADB'
sys.path.insert(0, os.path.join(aqui, '..', 'layout_gastos_poliza'))
sys.path.insert(0, aqui)
import build_reporte as b
from exportar_datos import a_datos

HTML = open(os.path.join(aqui, 'plantilla.html'), 'rb').read()
MAX_CACHE = 6
cache, lock = {}, threading.Lock()

def reporte(ini, fin, vista, agrupar, refresh):
    """Devuelve (gz, desde_cache). El DataFrame de (ini, fin) se consulta una vez y se reutiliza para cada vista."""
    k, kv = (ini, fin), (vista, agrupar)
    with lock:
        c = cache.get(k)
        if c and not refresh and time.time() - c['t'] < TTL:
            if kv in c['gz']:
                return c['gz'][kv], True
            hit = True
        else:
            t0 = time.time()
            ff = (dt.date.fromisoformat(fin) + dt.timedelta(days=1)).isoformat()
            d = b.post(b.construir_todo(ini, ff))
            c = {'t': time.time(), 'd': d, 'gz': {}, 'seg': round(time.time() - t0, 1),
                 'generado': dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            cache[k] = c
            while len(cache) > MAX_CACHE:
                cache.pop(min(cache, key=lambda x: cache[x]['t']))
            hit = False
        datos = a_datos(c['d'], vista, agrupar)
        datos['meta'] = {'fuente': '.207 TRIVASADB', 'ini': ini, 'fin': fin, 'filas': len(datos['rows']), 'vista': vista,
                         'agrupar': datos['agrupar'], 'generado': c['generado'], 'seg_consulta': c['seg']}
        gz = gzip.compress(json.dumps(datos, ensure_ascii=False, separators=(',', ':')).encode(), 5)
        c['gz'][kv] = gz
        return gz, hit

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body, ctype, extra=()):
        self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body)))
        for k, v in extra: self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.headers.get('Authorization') != OK:
            self.send_response(401); self.send_header('WWW-Authenticate', 'Basic realm="Trivasa"'); self.send_header('Content-Length', '0'); self.end_headers(); return
        u = urlparse(self.path)
        if u.path in ('/', '/index.html'):
            return self.send(200, HTML, 'text/html; charset=utf-8')
        if u.path == '/api/reporte':
            q = parse_qs(u.query)
            try:
                ini, fin = q['ini'][0], q['fin'][0]
                a, z = dt.date.fromisoformat(ini), dt.date.fromisoformat(fin)
                if z < a or (z - a).days > 366: raise ValueError('Rango invalido (max. 1 año, fin >= inicio).')
                vista = q.get('vista', ['layout'])[0]
                if vista not in ('layout', 'ceco'): raise ValueError('vista debe ser layout o ceco.')
                agrupar = q.get('agrupar', ['1'])[0] != '0'
            except Exception as e:
                return self.send(400, str(e).encode(), 'text/plain; charset=utf-8')
            try:
                gz, hit = reporte(ini, fin, vista, agrupar, 'refresh' in q)
            except Exception as e:
                print('ERROR', repr(e), flush=True)
                return self.send(500, b'Error consultando .207; reintenta o avisa a TI.', 'text/plain; charset=utf-8')
            body = gz if 'gzip' in self.headers.get('Accept-Encoding', '') else gzip.decompress(gz)
            ex = [('Cache-Control', 'no-store')] + ([('Content-Encoding', 'gzip')] if body is gz else [])
            if hit:  # marca de cache dentro del JSON sin recomprimir todo
                d = json.loads(gzip.decompress(gz)); d['meta']['cache'] = True
                body = json.dumps(d, ensure_ascii=False, separators=(',', ':')).encode()
                if 'gzip' in self.headers.get('Accept-Encoding', ''): body = gzip.compress(body, 3)
                ex = [('Cache-Control', 'no-store')] + ([('Content-Encoding', 'gzip')] if 'gzip' in self.headers.get('Accept-Encoding', '') else [])
            return self.send(200, body, 'application/json; charset=utf-8', ex)
        self.send(404, b'No encontrado', 'text/plain; charset=utf-8')

s = ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('APP_PORT', 0))), H)
print(s.server_address[1], flush=True)
s.serve_forever()
