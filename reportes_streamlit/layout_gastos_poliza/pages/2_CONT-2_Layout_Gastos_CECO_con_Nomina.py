"""
CONT-2 -- Layout de Gastos por CECO (7 origenes, incluye GASTO_REGISTRO_NOMINA).

Corre dentro de la app multipagina: streamlit run streamlit_app.py --server.port 8506
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)
from reporte_ui import render  # noqa: E402

render(numero="CONT-2", titulo="Layout de Gastos por CECO (con Nómina)", incluir_nomina=True, key_prefix="cont2")
