"""
Layout de Gastos - reporte Streamlit (placeholder)

Ya existe como app completa y separada en
reportes_streamlit/layout_gastos_poliza/ (CONT-1/2/4/5/6, RPTRV79-01/02/05)
-- integrarla como sub-páginas de esta sección queda pendiente a propósito
(2026-09-10); por ahora solo se crea la sección en el hub.

Corre standalone con:
  streamlit run pages/layout_gastos.py --server.port 8514
"""
import streamlit as st

st.set_page_config(page_title="Layout de Gastos", layout="wide")

st.title("Layout de Gastos")
st.info(
    "Integración a este hub pendiente. Ya existe como app completa y separada: "
    "`reportes_streamlit/layout_gastos_poliza/` (CONT-1/2/4/5/6, RPTRV79-01/02/05) -- "
    "correr con `streamlit run layout_gastos_poliza/streamlit_app.py --server.port 8506` "
    "mientras se integra aquí."
)
