import base64, sys, os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
USER, PASS = os.environ.get("APP_USER"), os.environ.get("APP_PASS")
if not USER or not PASS:
    sys.exit("Define APP_USER y APP_PASS (basic auth).")
OK = "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()
class H(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Authorization") != OK:
            self.send_response(401); self.send_header("WWW-Authenticate",'Basic realm="Trivasa"'); self.end_headers(); return
        super().do_GET()
os.chdir(os.path.dirname(os.path.abspath(__file__)))
s = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("APP_PORT", 0))), H)
print(s.server_address[1], flush=True)
s.serve_forever()
