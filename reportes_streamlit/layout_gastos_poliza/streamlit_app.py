"""
Layout de Gastos por CECO -- home (multipagina)

Punto de entrada de la app multipagina. La UI real vive en `pages/`:
  CONT-1 -- 6 origenes, sin nomina.
  CONT-2 -- 7 origenes, incluye GASTO_REGISTRO_NOMINA.
  CONT-4 -- exploratorio: grano documento, reconciliado 1:1 contra XML.
  CONT-5 -- exploratorio: grano cuenta contable, XML agregado.
  CONT-6 -- grano documento (7 modulos que reciben CFDI de proveedor),
    XML adjunto -- promocion de adjuntar-xml/04_conciliacion_mpro_vs_xml.py.
  RPTRV79-01/02/05 -- recreaciones del reporte de auditoria de compras de
    mpro (Agrupar=01/02/05), promovidas desde ../funcionales-auditoria/.

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

st.subheader("CONT-6")
st.markdown(
    "Grano **documento** `(ORIGEN, FOLIO, DOC_ID)` -- 7 módulos de MPro que reciben CFDI de "
    "proveedor (no solo `Gasto_Registro`), cuadre a nivel **grupo** (componente conexa). "
    "Promoción de `adjuntar-xml/04_conciliacion_mpro_vs_xml.py`, metodología más madura que "
    "CONT-4/CONT-5."
)
st.page_link("pages/8_CONT-6_Layout_Gastos_por_Documento_con_XML.py", label="Abrir CONT-6", icon="🧾")

st.divider()
st.header("RPTRV79 · Auditoria de Compras (mpro)")
st.caption(
    "Recreaciones del selector RPTRV79.asp (reporte de auditoria de compras nativo "
    "de mpro) -- 3 de las 11 variantes de 'Agrupar', ver `funcionales-auditoria/README.md`."
)

col5, col6, col7 = st.columns(3)
with col5:
    st.subheader("RPTRV79-01")
    st.markdown("Compras -- tabla `Compra`.")
    st.page_link("pages/5_Auditoria_Compras_RPTRV79-01.py", label="Abrir RPTRV79-01", icon="🧮")
with col6:
    st.subheader("RPTRV79-02")
    st.markdown("Compra Indirecto -- tabla `Compra_Indirecto`.")
    st.page_link("pages/6_Auditoria_Compra_Indirectos_RPTRV79-02.py", label="Abrir RPTRV79-02", icon="🧮")
with col7:
    st.subheader("RPTRV79-05")
    st.markdown("CXP Libre -- tabla `Cuenta_X_Pagar`.")
    st.page_link("pages/7_Auditoria_CXP_Libre_RPTRV79-05.py", label="Abrir RPTRV79-05", icon="🧮")
