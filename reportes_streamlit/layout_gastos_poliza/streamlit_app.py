"""
Layout de Gastos por CECO -- home (multipagina)

Punto de entrada de la app multipagina. La UI real vive en `pages/`:
  CONT-1 -- 6 origenes, sin nomina.
  CONT-2 -- 7 origenes, incluye GASTO_REGISTRO_NOMINA.
  CONT-4 -- exploratorio: grano documento, reconciliado 1:1 contra XML.
  CONT-5 -- exploratorio: grano cuenta contable, XML agregado.

Consolidación 2026-09-10: este hub antes también traía CONT-6 (promoción de
`recibidos/nivel_documento/04_conciliacion_mpro_vs_xml.py`) y las 3 páginas
de RPTRV79 (auditoría de compras) en el mismo Streamlit. Se separaron a sus
propios hubs, cada uno junto al código que envuelve:
  CONT-6      -> reportes_streamlit/recibidos_nivel_documento/ (puerto 8509 sugerido)
  RPTRV79-0X  -> repo separado github.com/ehalso/reportes-mpro,
                 reportes_streamlit/ ahí (puerto 8508 sugerido)

Corre con:
  streamlit run streamlit_app.py --server.port 8506
"""
import streamlit as st

st.set_page_config(page_title="Layout de Gastos por CECO", layout="wide")

st.title("Layout de Gastos por CECO")
st.caption("Reconciliacion Gasto_Registro_Control vs. Poliza_Detalle -- elige una version en el sidebar o abajo.")

st.markdown(
    "**CONT-1/CONT-2**: mismo grano `(FOLIO, CECO, TIPO_GASTO)`, misma tecnica "
    "(`Pd_Tipo` real, sin regla de reversion, rank-pairing). Universo completo (6-7 "
    "origenes). **CONT-4/CONT-5**: exploratorio, reemplazan rank-pairing por "
    "reconstruccion real via `Poliza_Configuracion` -- solo cubren la config `0450` "
    "(la dominante de `GASTO_DIRECTO`/`CONTROL_COMBUSTIBLE`/`VIAJE`/`ORDEN_COMPRA`)."
)

col1, col2 = st.columns(2)
with col1:
    st.subheader("CONT-1")
    st.markdown(
        "6 origenes: `CONTROL_COMBUSTIBLE`, `GASTO_DIRECTO`, `GASTO_RECLASIFICACION`, "
        "`ORDEN_COMPRA`, `VIAJE`, `CONSUMO_INTERNO`."
    )
    st.page_link("pages/1_CONT-1_Layout_Gastos_CECO.py", label="Abrir CONT-1", icon="📊")
with col2:
    st.subheader("CONT-2")
    st.markdown(
        "Los mismos 6 + **`GASTO_REGISTRO_NOMINA`** (emparejado por texto, "
        "no rank-pairing -- ver pestaña Documentación dentro del reporte)."
    )
    st.page_link("pages/2_CONT-2_Layout_Gastos_CECO_con_Nomina.py", label="Abrir CONT-2", icon="📊")

col3, col4 = st.columns(2)
with col3:
    st.subheader("CONT-4 · exploratorio")
    st.markdown(
        "Grano **documento** `(FOLIO, GRD_ID, CUENTA)` -- llave real via `Poliza_"
        "Configuracion`, conciliado 1:1 contra XML (`Comprobante_Digital`). Solo "
        "config `0450`."
    )
    st.page_link("pages/3_CONT-4_Layout_Gastos_por_Documento_XML.py", label="Abrir CONT-4", icon="🧾")
with col4:
    st.subheader("CONT-5 · exploratorio")
    st.markdown(
        "Grano **cuenta contable** `(FOLIO, CUENTA)` -- mismo universo que CONT-4, "
        "colapsado; XML agregado. Para comparar los dos granos lado a lado."
    )
    st.page_link("pages/4_CONT-5_Layout_Gastos_por_Cuenta_Contable_XML.py", label="Abrir CONT-5", icon="🧾")
