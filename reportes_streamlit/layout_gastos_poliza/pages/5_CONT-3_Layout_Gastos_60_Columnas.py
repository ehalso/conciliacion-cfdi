"""
CONT-3 -- Layout de Gastos, 60 columnas (auditoría externa, Bates y Asociados).

Corre dentro de la app multipagina: streamlit run streamlit_app.py --server.port 8506
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)
from reporte_ui_consolidado import render  # noqa: E402

render()
