"""
CONT-4 -- Layout de Gastos por Documento, conciliado 1:1 contra XML
(exploratorio, solo config 0450 -- ver PROGRESS.md).

Corre dentro de la app multipagina: streamlit run streamlit_app.py --server.port 8506
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)
from reporte_ui_config import render  # noqa: E402

render(numero="CONT-4", titulo="Layout de Gastos por Documento (XML)", grano="documento", key_prefix="cont4")
