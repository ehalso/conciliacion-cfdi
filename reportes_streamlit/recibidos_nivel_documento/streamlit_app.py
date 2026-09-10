"""
Recibidos, nivel documento -- home (multipagina)

Separado del hub de layout_gastos_poliza el 2026-09-10 (antes era CONT-6
ahí, "promoción de adjuntar-xml/04_conciliacion_mpro_vs_xml.py") -- vive
aquí porque envuelve `recibidos/nivel_documento/`, no `layout_gastos_poliza/`.

Corre con:
  streamlit run streamlit_app.py --server.port 8509
"""
import streamlit as st

st.set_page_config(page_title="Recibidos · nivel documento", layout="wide")

st.title("Recibidos · nivel documento, grano documento con XML")
st.caption(
    "Versión de CONT-1/CONT-2 (mismo universo Gasto_Registro) a grano "
    "documento (Grd_ID) con XML adjunto, en vez de Póliza/Cuenta/CECO -- "
    "reusa la lógica de recibidos/nivel_documento/04_conciliacion_mpro_vs_xml.py."
)
st.page_link("pages/1_CONT-6_Documento_con_XML.py", label="Abrir CONT-6", icon="🧾")
