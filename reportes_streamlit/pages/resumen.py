"""
Resumen - reporte Streamlit (placeholder)

Pendiente hasta que Recibido/Emitido/Retención tengan sus páginas
suficientemente estables -- cuando se construya, reusará los `calcular()`
ya cacheados de esas secciones (sin disparar queries nuevas) para armar
tarjetas de KPI por dominio y periodo.

Corre standalone con:
  streamlit run pages/resumen.py --server.port 8513
"""
import streamlit as st

st.set_page_config(page_title="Resumen", layout="wide")

st.title("Resumen")
st.info(
    "Pendiente. Cuando se construya: KPI por dominio para el periodo seleccionado "
    "(% cuadre Recibido, % cuadre Emitido, faltantes de Retención), reusando los "
    "`calcular()` ya cacheados de las otras secciones -- no dispara queries nuevas."
)
st.markdown(
    "Mientras tanto, entra directo a:\n\n"
    "- **Recibido** → Conciliación (nivel póliza) / Cruce SAT\n"
    "- **Emitido** → Conciliación (documento vs CFDI) / Cruce SAT\n"
    "- **Retención** → Cruce SAT"
)
