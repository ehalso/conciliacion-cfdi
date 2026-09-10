"""
CONT-5 -- Layout de Gastos por Cuenta Contable, con XML adjunto
(exploratorio, solo config 0450 -- ver PROGRESS.md). Mismo universo que
CONT-4, grano mas grueso (colapsa GRD_ID) -- para comparar lado a lado.

Corre dentro de la app multipagina: streamlit run streamlit_app.py --server.port 8506
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)
from reporte_ui_config import render  # noqa: E402

render(numero="CONT-5", titulo="Layout de Gastos por Cuenta Contable (XML)", grano="cuenta", key_prefix="cont5")
