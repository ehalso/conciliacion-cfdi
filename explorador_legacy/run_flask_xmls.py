"""Levanta la webapp Flask de consulta_xmls_gastos (por_ordenar) en un puerto fijo distinto del 8600 hardcodeado."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/_deps")
d = os.path.expanduser("~/por_ordenar/exploracion/consulta_xmls_gastos/webapp")
os.chdir(d); sys.path.insert(0, d); sys.path.insert(0, os.path.dirname(d))
import server
from waitress import serve
serve(server.app, host="0.0.0.0", port=int(sys.argv[1]))
