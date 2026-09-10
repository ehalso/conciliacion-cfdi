"""
CONT-6 -- version de CONT-1/CONT-2 (mismo universo, solo Gasto_Registro) a
grano documento (Grd_ID) con XML adjunto en vez de Poliza/Cuenta/CECO.
Reusa (restringido a origenes=['GASTO_REGISTRO']) la logica de
`adjuntar-xml/04_conciliacion_mpro_vs_xml.py` -- ver PROGRESS.md
(entrada 2026-09-08/09).

Corre dentro de la app multipagina: streamlit run streamlit_app.py --server.port 8506
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)
from reporte_ui_xml_documento import render  # noqa: E402

render(numero="CONT-6", titulo="Layout de Gastos por Documento con XML", key_prefix="cont6")
