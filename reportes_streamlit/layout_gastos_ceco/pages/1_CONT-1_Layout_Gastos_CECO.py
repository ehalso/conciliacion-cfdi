"""
CONT-1 -- Layout de Gastos por CECO (6 origenes, sin nomina).

Corre dentro de la app multipagina: streamlit run streamlit_app.py --server.port 8506
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)
from reporte_ui import render  # noqa: E402

render(numero="CONT-1", titulo="Layout de Gastos por CECO", incluir_nomina=False, key_prefix="cont1")
