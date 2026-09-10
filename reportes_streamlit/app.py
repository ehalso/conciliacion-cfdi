"""Hub de reportes de conciliación CFDI <-> mpro.

Entrypoint único con `st.navigation` agrupado en secciones (sidebar) --
cada entrada es una página independiente (`st.Page`), no una pestaña: se
usa página aparte cuando dos reportes corren queries/métodos distintos
(grano o tabla origen distintos); pestañas (`st.tabs`), dentro de la
propia página, cuando es la misma carga de datos solo cortada distinto.

Corre con:
  streamlit run app.py --server.port 8507
"""
import streamlit as st

# Nota: NO se llama st.set_page_config() aquí -- pg.run() ejecuta la página
# seleccionada dentro de este mismo run, y cada página (pages/*.py) llama su
# propio st.set_page_config() con su título -- llamarlo también aquí
# lanzaría StreamlitAPIException (solo se puede llamar una vez por run).

pg = st.navigation({
    "Resumen": [
        st.Page("pages/resumen.py", title="Resumen", icon="🏠"),
    ],
    "Recibido": [
        st.Page("pages/recibido_conciliacion.py", title="Conciliación (nivel póliza)", icon="📊"),
        st.Page("pages/recibido_cruce_sat.py", title="Cruce SAT", icon="🔍"),
    ],
    "Emitido": [
        st.Page("pages/emitido_conciliacion.py", title="Conciliación (documento vs CFDI)", icon="📊"),
        st.Page("pages/emitido_cruce_sat.py", title="Cruce SAT", icon="🔍"),
    ],
    "Retención": [
        st.Page("pages/retencion_cruce_sat.py", title="Cruce SAT", icon="🔍"),
    ],
    "Layout de Gastos": [
        st.Page("pages/layout_gastos.py", title="Layout de Gastos", icon="🧮"),
    ],
})
pg.run()
