"""Sirve index.html y extra.json con autenticación básica. Uso: APP_USER=.. APP_PASS=.. PORT=32836 python3 serve.py"""
import base64, os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
OK = "Basic " + base64.b64encode(f"{os.environ['APP_USER']}:{os.environ['APP_PASS']}".encode()).decode()
PERMITIDOS = {"/", "/index.html", "/extra.json"}
class H(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Authorization") != OK:
            self.send_response(401); self.send_header("WWW-Authenticate", 'Basic realm="Trivasa"'); self.end_headers(); return
        if self.path.split("?")[0] not in PERMITIDOS:
            self.send_error(404); return
        super().do_GET()
os.chdir(os.path.dirname(os.path.abspath(__file__)))
ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", 32836))), H).serve_forever()
