"""
Emitido · Cruce SAT - reporte Streamlit

Compara `raw_sat.cfdi_emitidos` (fuente independiente del ERP) contra
`Comprobante_Digital` (cualquier módulo). CAVEAT DE COBERTURA importante:
`raw_sat.cfdi_emitidos` solo tiene backfill hasta enero 2026 -- para
periodos posteriores este cruce va a mostrar casi todo como "solo mpro",
que es el backfill pendiente, NO un hallazgo real. Ver
emitidos/cruce_sat/README.md.

Lógica de negocio en src/cruce_sat.py (compartida con Recibido · Cruce SAT).

Corre standalone con:
  streamlit run pages/emitido_cruce_sat.py --server.port 8511
"""
import os
import sys

import pandas as pd
import streamlit as st

PAGES_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(PAGES_DIR))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

from cruce_sat import calcular_periodos  # noqa: E402

PERIODOS_DISPONIBLES = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
PERIODO_CON_BACKFILL = "2026-01"

COLS_DISPLAY = {
    "uuid": "UUID CFDI", "periodo": "Periodo", "fecha": "Fecha", "rfc_emisor": "RFC Emisor",
    "nombre_emisor": "Emisor (Trivasa)", "subtotal": "Subtotal CFDI", "total": "Total CFDI",
    "modulos_mpro": "Módulo(s) en mpro", "n_modulos_mpro": "# módulos",
    "cd_monto_primero": "Monto en mpro", "estatus": "Estatus",
}
COLS_TABLA = ["uuid", "fecha", "subtotal", "total", "modulos_mpro", "n_modulos_mpro"]


@st.cache_data(ttl=1800, show_spinner="Consultando SAT y mpro (cruce de existencia)...")
def cargar(periodos: tuple[str, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    return calcular_periodos(list(periodos), "emitido")


def descarga_excel(df: pd.DataFrame, cols: list[str], nombre: str) -> bytes:
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df[cols].rename(columns=COLS_DISPLAY).to_excel(writer, index=False, sheet_name=nombre[:31])
    return buf.getvalue()


def render():
    st.title("Emitido · Cruce SAT")
    st.caption("Existencia: raw_sat.cfdi_emitidos (SAT) vs Comprobante_Digital (mpro, cualquier módulo)")
    st.markdown(
        "¿El ERP registró, en **algún módulo**, cada CFDI que Trivasa timbró como emisor? "
        "Chequeo de existencia, sin importar el importe."
    )
    st.warning(
        f"**Cobertura limitada**: `raw_sat.cfdi_emitidos` solo tiene backfill hasta "
        f"**{PERIODO_CON_BACKFILL}**. Para periodos posteriores este cruce muestra casi todo "
        f"como *solo mpro* -- es el backfill pendiente, no un hallazgo real. Interpretar con "
        f"cuidado fuera de {PERIODO_CON_BACKFILL}."
    )

    with st.sidebar:
        st.subheader("Periodo")
        periodos_sel = st.multiselect(
            "Periodos a incluir (2026)", PERIODOS_DISPONIBLES,
            default=[PERIODO_CON_BACKFILL], key="emcs_periodos")

    if not periodos_sel:
        st.info("Selecciona al menos un periodo en la barra lateral.")
        return

    try:
        detalle, resumen_df = cargar(tuple(sorted(periodos_sel)))
    except Exception as exc:
        st.error(f"No se pudo consultar la base de datos.\n\nError: {exc}")
        return

    if detalle.empty:
        st.warning("Sin datos para los periodos seleccionados.")
        return

    n_solo_mpro = int((detalle["estatus"] == "SOLO_MPRO").sum())
    if len(detalle) and n_solo_mpro / len(detalle) > 0.5:
        st.error(
            f"{n_solo_mpro:,} de {len(detalle):,} ({n_solo_mpro/len(detalle)*100:.0f}%) salió "
            f"*solo mpro* -- confirma el patrón de backfill pendiente, no un hallazgo real, "
            f"para los periodos seleccionados fuera de {PERIODO_CON_BACKFILL}."
        )

    en_ambos = detalle[detalle["estatus"] == "EN_AMBOS"]
    solo_sat = detalle[detalle["estatus"] == "SOLO_SAT"]
    solo_mpro = detalle[detalle["estatus"] == "SOLO_MPRO"]

    k1, k2, k3 = st.columns(3)
    k1.metric("En ambos", f"{len(en_ambos):,}")
    k2.metric("Solo SAT (hueco candidato)", f"{len(solo_sat):,}")
    k3.metric("Solo mpro", f"{len(solo_mpro):,}",
              help="Puede ser backfill de raw_sat.cfdi_emitidos pendiente -- ver advertencia arriba.")

    tab_sat, tab_mpro, tab_resumen, tab_docs = st.tabs(
        ["Solo SAT (falta en mpro)", "Solo mpro (falta en SAT)", "Resumen", "Documentación"])

    with tab_sat:
        if solo_sat.empty:
            st.success("Ninguno.")
        else:
            st.dataframe(solo_sat[COLS_TABLA].rename(columns=COLS_DISPLAY),
                         width="stretch", height=520, hide_index=True)
            st.download_button(
                "Descargar Excel (solo SAT)",
                data=descarga_excel(solo_sat, COLS_TABLA, "solo_sat"),
                file_name=f"cruce_sat_emitidos_solo_sat_{'-'.join(periodos_sel)}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_mpro:
        cols_mpro = ["uuid", "modulos_mpro", "n_modulos_mpro", "cd_monto_primero"]
        if solo_mpro.empty:
            st.success("Ninguno.")
        else:
            st.dataframe(solo_mpro[cols_mpro].rename(columns=COLS_DISPLAY),
                         width="stretch", height=520, hide_index=True)
            st.download_button(
                "Descargar Excel (solo mpro)",
                data=descarga_excel(solo_mpro, cols_mpro, "solo_mpro"),
                file_name=f"cruce_sat_emitidos_solo_mpro_{'-'.join(periodos_sel)}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_resumen:
        st.dataframe(resumen_df, width="stretch", hide_index=True)

    with tab_docs:
        st.markdown(
            "Caveat de cobertura, metodología y resultado ya validado (enero con backfill real, "
            "marzo como ejemplo de 100% *solo mpro* por falta de backfill) en "
            "`emitidos/cruce_sat/README.md`. Lógica de negocio en `src/cruce_sat.py`."
        )


st.set_page_config(page_title="Emitido · Cruce SAT", layout="wide")
render()
