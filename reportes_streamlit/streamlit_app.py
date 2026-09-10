"""Home del hub de reportes de conciliación CFDI <-> mpro. Streamlit arma
la navegación de la barra lateral solo a partir de los archivos en
`pages/` (no hace falta st.navigation manual) — este archivo es la primera
entrada, las demás son TEMP-1 y TEMP-2.

Corre con:
  streamlit run streamlit_app.py --server.port 8507
"""
import streamlit as st

st.set_page_config(page_title="Conciliación CFDI <-> mpro", layout="wide")

st.title("Conciliación CFDI <-> mpro")
st.markdown(
    "Elige un reporte en la barra lateral:\n\n"
    "- **TEMP-1 Conciliacion** — el reporte original: Conciliados, Pendientes, "
    "No encontrados en mpro, Por vía/motivo, Documentación.\n"
    "- **TEMP-2 Detalle** — lo mismo que TEMP-1, más una pestaña de **Detalle de línea** "
    "(primera pestaña) que muestra las líneas reales de póliza / control de gasto que "
    "suman el cargo de cada CFDI (solo vía *cargo = base CFDI* por ahora), con filtros "
    "adicionales de cuenta contable y centro de costo.\n\n"
    "Ambos corren sobre el mismo método vigente de conciliación "
    "(`baseline_universal.calcular()`) — la diferencia es solo de presentación, para "
    "comparar cuál layout es más útil."
)
