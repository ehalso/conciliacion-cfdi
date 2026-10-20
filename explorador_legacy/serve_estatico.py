"""Sirve una carpeta estática con basic auth (mismas credenciales que los serve.py originales) en un puerto fijo. Uso: serve_estatico.py PUERTO CARPETA"""
import base64, os, re, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
port, carpeta = int(sys.argv[1]), sys.argv[2]
src = open(os.path.join(carpeta, "serve.py")).read() if os.path.exists(os.path.join(carpeta, "serve.py")) else ""
m = re.search(r'b"([^"]+:[^"]+)"', src)
OK = "Basic " + base64.b64encode(m.group(1).encode()).decode()
class H(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Authorization") != OK:
            self.send_response(401); self.send_header("WWW-Authenticate", 'Basic realm="legacy"'); self.end_headers(); return
        super().do_GET()
os.chdir(carpeta)
ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
