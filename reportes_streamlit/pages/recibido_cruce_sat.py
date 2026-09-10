"""
Recibido · Cruce SAT - reporte Streamlit

Compara `raw_sat.cfdi_recibidos` (fuente independiente del ERP -- el XML
que el PAC deja en el share del SAT) contra `Comprobante_Digital`
(cualquier módulo): detecta un CFDI recibido que el ERP nunca registró en
ningún módulo, y el caso simétrico. Chequeo de EXISTENCIA, no de importe --
ver la sección Conciliación (nivel póliza) para el chequeo de importe.

Lógica de negocio en src/cruce_sat.py -- este script solo la envuelve en UI.

Metodología y hallazgos ya validados: recibidos/cruce_sat/README.md.

Corre standalone con:
  streamlit run pages/recibido_cruce_sat.py --server.port 8509
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

COLS_DISPLAY = {
    "uuid": "UUID CFDI",
    "periodo": "Periodo",
    "fecha": "Fecha",
    "rfc_emisor": "RFC Emisor",
    "nombre_emisor": "Proveedor",
    "subtotal": "Subtotal CFDI",
    "total": "Total CFDI",
    "modulos_mpro": "Módulo(s) en mpro",
    "n_modulos_mpro": "# módulos",
    "cd_monto_primero": "Monto en mpro",
    "estatus": "Estatus",
}
COLS_TABLA = ["uuid", "fecha", "rfc_emisor", "nombre_emisor", "subtotal", "total",
              "modulos_mpro", "n_modulos_mpro"]


@st.cache_data(ttl=1800, show_spinner="Consultando SAT y mpro (cruce de existencia)...")
def cargar(periodos: tuple[str, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    return calcular_periodos(list(periodos), "recibido")


def descarga_excel(df: pd.DataFrame, cols: list[str], nombre: str) -> bytes:
    import io
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df[cols].rename(columns=COLS_DISPLAY).to_excel(writer, index=False, sheet_name=nombre[:31])
    return buf.getvalue()


def render():
    st.title("Recibido · Cruce SAT")
    st.caption("Existencia: raw_sat.cfdi_recibidos (SAT) vs Comprobante_Digital (mpro, cualquier módulo)")
    st.markdown(
        "¿El ERP registró, en **algún módulo**, cada CFDI que el PAC timbró para Trivasa como "
        "receptor? Chequeo de existencia, sin importar el valor monetario ni si ya cuadra en "
        "póliza. Complementa a *Conciliación (nivel póliza)*, que solo pregunta por el importe "
        "de los que sí están etiquetados."
    )

    with st.sidebar:
        st.subheader("Periodo")
        periodos_sel = st.multiselect(
            "Periodos a incluir (2026)", PERIODOS_DISPONIBLES,
            default=["2026-02"], key="rcs_periodos")

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

    with st.sidebar:
        st.subheader("Filtros")
        busca = st.text_input("Buscar RFC, proveedor o UUID", key="rcs_busca")
        solo_monto_real = st.checkbox("Solo con valor monetario (subtotal > $1)", value=True, key="rcs_monto")

    def _filtra(df):
        d = df.copy()
        if busca:
            q = busca.strip().upper()
            d = d[
                d["rfc_emisor"].astype(str).str.upper().str.contains(q, na=False)
                | d["nombre_emisor"].astype(str).str.upper().str.contains(q, na=False)
                | d["uuid"].astype(str).str.upper().str.contains(q, na=False)
            ]
        return d

    en_ambos = detalle[detalle["estatus"] == "EN_AMBOS"]
    solo_sat = detalle[detalle["estatus"] == "SOLO_SAT"]
    solo_mpro = detalle[detalle["estatus"] == "SOLO_MPRO"]
    if solo_monto_real:
        solo_sat = solo_sat[solo_sat["subtotal"] > 1]

    solo_sat_f = _filtra(solo_sat)
    solo_mpro_f = _filtra(solo_mpro)

    k1, k2, k3 = st.columns(3)
    k1.metric("En ambos", f"{len(en_ambos):,}")
    k2.metric("Solo SAT (hueco candidato)", f"{len(solo_sat_f):,}",
              help="CFDI que el PAC timbró y el ERP no etiquetó en ningún módulo.")
    k3.metric("Solo mpro", f"{len(solo_mpro_f):,}",
              help="Etiquetado en el ERP con un UUID que no aparece en la fuente independiente del SAT.")

    tab_sat, tab_mpro, tab_resumen, tab_docs = st.tabs(
        ["Solo SAT (falta en mpro)", "Solo mpro (falta en SAT)", "Resumen", "Documentación"])

    with tab_sat:
        if solo_sat_f.empty:
            st.success("Ninguno con los filtros actuales.")
        else:
            st.dataframe(solo_sat_f[COLS_TABLA].rename(columns=COLS_DISPLAY),
                         width="stretch", height=520, hide_index=True)
            st.download_button(
                "Descargar Excel (solo SAT, filtrado)",
                data=descarga_excel(solo_sat_f, COLS_TABLA, "solo_sat"),
                file_name=f"cruce_sat_recibidos_solo_sat_{'-'.join(periodos_sel)}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_mpro:
        cols_mpro = ["uuid", "modulos_mpro", "n_modulos_mpro", "cd_monto_primero"]
        if solo_mpro_f.empty:
            st.success("Ninguno con los filtros actuales.")
        else:
            st.dataframe(solo_mpro_f[cols_mpro].rename(columns=COLS_DISPLAY),
                         width="stretch", height=520, hide_index=True)
            st.download_button(
                "Descargar Excel (solo mpro, filtrado)",
                data=descarga_excel(solo_mpro_f, cols_mpro, "solo_mpro"),
                file_name=f"cruce_sat_recibidos_solo_mpro_{'-'.join(periodos_sel)}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_resumen:
        st.dataframe(resumen_df, width="stretch", hide_index=True)

    with tab_docs:
        st.markdown(
            "Metodología, gotcha resuelto (filtro de RFC) y resultado ya validado en "
            "`recibidos/cruce_sat/README.md`. Lógica de negocio en `src/cruce_sat.py` -- "
            "compartida con la sección equivalente de Emitido."
        )


st.set_page_config(page_title="Recibido · Cruce SAT", layout="wide")
render()
