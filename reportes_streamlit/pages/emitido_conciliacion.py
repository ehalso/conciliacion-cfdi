"""
Emitido · Conciliación (documento vs CFDI) - reporte Streamlit

Envuelve `emitidos/nivel_documento/conciliacion_emitidos_documento.py`
(el "Reporte 01": FACTURA/NOTA_CREDITO/retención vs el documento de mpro
que las generó, 100.00% H1 2026 -- ver docs/emitidos_retenciones.md). NO es
`emitidos/nivel_poliza/baseline_universal_emitido.py` (chequeo a nivel
póliza contable, cobertura real ~1% por cómo postea VENTA -- ver su propio
docstring): a diferencia de recibidos, en emitidos el reporte de mayor
cobertura es el de nivel documento, no el de nivel póliza.

Por qué el emitido no tiene problema de importes por construcción: el CFDI
se genera DESDE el documento de mpro (factura, nota de crédito), así que la
relación es 1:1 estricta y el importe no puede diferir si no hay
corrupción de datos.

Corre standalone con:
  streamlit run pages/emitido_conciliacion.py --server.port 8510
"""
import os
import sys

import pandas as pd
import streamlit as st

PAGES_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(PAGES_DIR))
sys.path.insert(0, os.path.join(REPO_ROOT, "emitidos", "nivel_documento"))

from conciliacion_emitidos_documento import conciliar, ESTATUS_CUADRA, ESTATUS_EXPLICADO  # noqa: E402

PERIODOS_DISPONIBLES = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]

COLS_DISPLAY = {
    "uuid": "UUID CFDI", "periodo": "Periodo", "origen": "Origen mpro", "folio": "Folio",
    "fecha_timbrado": "Fecha timbrado", "cfdi_importe": "Importe CFDI",
    "mpro_comparable": "Importe mpro", "dif": "Diferencia", "estatus": "Estatus",
}
COLS_TABLA = ["uuid", "periodo", "origen", "folio", "fecha_timbrado", "cfdi_importe",
              "mpro_comparable", "dif", "estatus"]


@st.cache_data(ttl=1800, show_spinner="Consultando mpro (documento vs CFDI emitido)...")
def cargar_periodo(periodo: str) -> pd.DataFrame:
    return conciliar(periodo)


def cargar_periodos(periodos: tuple[str, ...]) -> pd.DataFrame:
    partes = [cargar_periodo(p) for p in periodos]
    partes = [p for p in partes if not p.empty]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def descarga_excel(df: pd.DataFrame, cols: list[str], nombre: str) -> bytes:
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df[cols].rename(columns=COLS_DISPLAY).to_excel(writer, index=False, sheet_name=nombre[:31])
    return buf.getvalue()


def render():
    st.title("Emitido · Conciliación (documento vs CFDI)")
    st.caption("Reporte 01 · Factura, nota de crédito y retenciones vs el documento de mpro que las generó")
    st.markdown(
        "¿El CFDI que se timbró es exactamente el que generó el documento de mpro? Relación "
        "1:1 estricta (el CFDI se genera DESDE el documento) -- por construcción no debería "
        "haber diferencia de importe. Válido para `FACTURA`, `NOTA_CREDITO`, `CONSTANCIA_"
        "RETENCION` y `GASTO_REGISTRO` (solo filas de retención de intereses)."
    )

    with st.sidebar:
        st.subheader("Periodo")
        periodos_sel = st.multiselect(
            "Periodos a incluir (2026)", PERIODOS_DISPONIBLES,
            default=["2026-01"], key="ec_periodos")

    if not periodos_sel:
        st.info("Selecciona al menos un periodo en la barra lateral.")
        return

    try:
        todo = cargar_periodos(tuple(sorted(periodos_sel)))
    except Exception as exc:
        st.error(f"No se pudo consultar la base de datos.\n\nError: {exc}")
        return

    if todo.empty:
        st.warning("Sin CFDI emitidos para los periodos seleccionados.")
        return

    with st.sidebar:
        st.subheader("Filtros")
        origenes_sel = st.multiselect("Origen mpro", sorted(todo["origen"].unique()), key="ec_origenes")
        busca = st.text_input("Buscar UUID o folio", key="ec_busca")

    df = todo.copy()
    if origenes_sel:
        df = df[df["origen"].isin(origenes_sel)]
    if busca:
        q = busca.strip().upper()
        df = df[df["uuid"].astype(str).str.upper().str.contains(q, na=False)
                | df["folio"].astype(str).str.upper().str.contains(q, na=False)]

    conciliable = df[~df["estatus"].isin(ESTATUS_EXPLICADO)]
    cuadra = conciliable["estatus"].isin(ESTATUS_CUADRA)

    k1, k2, k3 = st.columns(3)
    k1.metric("Universo (filtrado)", f"{len(df):,}")
    k2.metric("Conciliables (sin ambos cancelados)", f"{len(conciliable):,}")
    k3.metric("Cuadran", f"{int(cuadra.sum()):,}",
              f"{cuadra.mean()*100:.2f}%" if len(conciliable) else None)

    tab_todo, tab_dif, tab_resumen, tab_docs = st.tabs(
        ["Todo (filtrado)", "Con diferencia", "Resumen por estatus", "Documentación"])

    with tab_todo:
        st.dataframe(df[COLS_TABLA].rename(columns=COLS_DISPLAY),
                     width="stretch", height=520, hide_index=True)
        st.download_button(
            "Descargar Excel (filtrado)",
            data=descarga_excel(df, COLS_TABLA, "conciliacion_emitidos"),
            file_name=f"emitido_conciliacion_{'-'.join(periodos_sel)}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_dif:
        con_dif = conciliable[~cuadra]
        if con_dif.empty:
            st.success("Ninguno con los filtros actuales -- 100% cuadra.")
        else:
            st.dataframe(con_dif[COLS_TABLA].rename(columns=COLS_DISPLAY),
                         width="stretch", height=520, hide_index=True)

    with tab_resumen:
        resumen_estatus = df.groupby("estatus").size().rename("conteo").reset_index()
        st.dataframe(resumen_estatus, width="stretch", hide_index=True)

    with tab_docs:
        st.markdown(
            "Metodología completa, hallazgos y la nota de por qué NO se usa "
            "`baseline_universal_emitido.py` (nivel póliza, cobertura ~1% por cómo VENTA "
            "postea dos pólizas separadas sin aislar el documento) en "
            "`docs/emitidos_retenciones.md`. Lógica de negocio en "
            "`emitidos/nivel_documento/conciliacion_emitidos_documento.py` -- este script solo "
            "la envuelve en UI, no la duplica."
        )


st.set_page_config(page_title="Emitido · Conciliación", layout="wide")
render()
