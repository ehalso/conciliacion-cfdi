"""
Retención · Cruce SAT - reporte Streamlit

Envuelve `retencion/cruce_sat/retencion_reconciliation.py`: compara
`raw_sat.cfdi_retencion` (fuente independiente del ERP, cobertura histórica
completa 2016-2026) contra `Comprobante_Digital` -- detecta constancias de
retención timbradas que el ERP nunca registró. Hallazgo ya validado: 29
constancias faltantes en H1 2026 (docs/emitidos_retenciones.md).

Corre standalone con:
  streamlit run pages/retencion_cruce_sat.py --server.port 8512
"""
import os
import sys

import pandas as pd
import streamlit as st

PAGES_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(PAGES_DIR))
sys.path.insert(0, os.path.join(REPO_ROOT, "retencion", "cruce_sat"))

from retencion_reconciliation import calcular  # noqa: E402

PERIODOS_DISPONIBLES = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]

COLS_DISPLAY = {
    "uuid": "UUID CFDI", "fecha": "Fecha", "rfc_emisor": "RFC Emisor (retenido)",
    "rfc_receptor": "RFC Receptor", "cve_retenc": "Clave retención",
    "monto_total_operacion": "Monto operación", "monto_total_retenido": "Monto retenido",
    "modulos_mpro": "Módulo(s) en mpro", "folio_constancia": "Folio constancia",
    "monto_constancia": "Monto en mpro", "diff": "Diferencia", "estatus": "Estatus",
}
COLS_TABLA = ["uuid", "fecha", "rfc_emisor", "cve_retenc", "monto_total_operacion",
              "monto_total_retenido", "modulos_mpro", "estatus"]


@st.cache_data(ttl=1800, show_spinner="Consultando SAT y mpro (retención)...")
def cargar(periodos: tuple[str, ...], tolerancia: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    return calcular(list(periodos), tolerancia=tolerancia)


def descarga_excel(df: pd.DataFrame, cols: list[str], nombre: str) -> bytes:
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df[cols].rename(columns=COLS_DISPLAY).to_excel(writer, index=False, sheet_name=nombre[:31])
    return buf.getvalue()


def render():
    st.title("Retención · Cruce SAT")
    st.caption("raw_sat.cfdi_retencion (SAT) vs Comprobante_Digital, Cd_Tabla='CONSTANCIA_RETENCION' (mpro)")
    st.markdown(
        "Clasifica cada CFDI de retención (mayormente ISR de arrendamiento, clave 16) en: "
        "**Conciliado** (existe y el monto cuadra), **Stub Gasto_Registro sin monto** (tiene "
        "fila en mpro pero con `Cd_Monto=0` por diseño -- no es un faltante real, el importe "
        "vive en `Gasto_Registro_Documento`) o **Sin mapeo en mpro** (el hueco real: se timbró "
        "y el ERP no lo registró en ningún módulo)."
    )

    with st.sidebar:
        st.subheader("Periodo")
        periodos_sel = st.multiselect(
            "Periodos a incluir (2026)", PERIODOS_DISPONIBLES,
            default=["2026-01", "2026-02"], key="rt_periodos")
        tolerancia = st.number_input("Tolerancia ($)", min_value=0.0, value=1.0, step=1.0, key="rt_tol")

    if not periodos_sel:
        st.info("Selecciona al menos un periodo en la barra lateral.")
        return

    try:
        detalle, resumen_df = cargar(tuple(sorted(periodos_sel)), str(tolerancia))
    except Exception as exc:
        st.error(f"No se pudo consultar la base de datos.\n\nError: {exc}")
        return

    if detalle.empty:
        st.warning("Sin CFDI de retención para los periodos seleccionados.")
        return

    sin_mapeo = detalle[detalle["estatus"] == "SIN_MAPEO_MPRO"]
    conciliado = detalle[detalle["estatus"] == "CONCILIADO"]
    stub = detalle[detalle["estatus"] == "STUB_GASTO_REGISTRO_SIN_MONTO"]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Timbradas (SAT)", f"{len(detalle):,}")
    k2.metric("Conciliadas", f"{len(conciliado):,}")
    k3.metric("Stub sin monto (no es hueco)", f"{len(stub):,}")
    k4.metric("Faltantes reales (sin mapeo)", f"{len(sin_mapeo):,}",
              f"${sin_mapeo['monto_total_operacion'].sum():,.0f}" if not sin_mapeo.empty else None,
              delta_color="inverse")

    tab_faltan, tab_todo, tab_resumen, tab_docs = st.tabs(
        ["Faltantes (sin mapeo)", "Todo", "Resumen por estatus", "Documentación"])

    with tab_faltan:
        if sin_mapeo.empty:
            st.success("Ninguna constancia faltante en los periodos seleccionados.")
        else:
            st.dataframe(sin_mapeo[COLS_TABLA].rename(columns=COLS_DISPLAY),
                         width="stretch", height=520, hide_index=True)
            st.download_button(
                "Descargar Excel (faltantes)",
                data=descarga_excel(sin_mapeo, COLS_TABLA, "faltantes"),
                file_name=f"retencion_faltantes_{'-'.join(periodos_sel)}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_todo:
        st.dataframe(detalle[COLS_TABLA].rename(columns=COLS_DISPLAY),
                     width="stretch", height=520, hide_index=True)

    with tab_resumen:
        st.dataframe(resumen_df, width="stretch", hide_index=True)

    with tab_docs:
        st.markdown(
            "Hallazgo documentado: **29 constancias de retención timbradas que el ERP no "
            "tiene en H1 2026** (14 en enero, 15 en febrero, mismo patrón: retención de "
            "intereses, clave 16, mismo lote de timbrado). Detalle completo en "
            "`docs/emitidos_retenciones.md`. Nota de consolidación: este cruce se construyó "
            "dos veces en paralelo el mismo día (2026-09-10) por dos sesiones distintas -- se "
            "conservó `retencion_reconciliation.py` porque distingue el estatus "
            "*Stub Gasto_Registro sin monto* de un faltante real."
        )


st.set_page_config(page_title="Retención · Cruce SAT", layout="wide")
render()
