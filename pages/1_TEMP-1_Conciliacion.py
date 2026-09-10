"""Página de navegación (multipágina nativa de Streamlit) hacia
streamlit_app_conciliacion.py (TEMP-1) — no duplica su código, lo ejecuta
tal cual con `runpy` para que streamlit_app_conciliacion.py siga siendo
corrible standalone (`streamlit run streamlit_app_conciliacion.py`) además
de aparecer en esta barra de navegación."""
import os
import runpy

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "streamlit_app_conciliacion.py")
runpy.run_path(TARGET)
