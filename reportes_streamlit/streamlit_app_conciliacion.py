"""
TEMP-1 · Conciliación CFDI <-> mpro - reporte Streamlit (baseline universal)

Interfaz interactiva sobre el metodo vigente de conciliacion de CFDI
recibidos: para cada CFDI se suma el cargo de TODOS los documentos con los
que aparece etiquetado en mpro (Comprobante_Digital), sin importar el
origen, y se compara contra la base fiscal del CFDI via una cascada de
once vias de cuadre. Logica de negocio en baseline_universal.calcular() -
este script solo la envuelve en UI, no la duplica.

Este es el reporte "solo conciliacion", sin la vista de detalle de linea
(ver streamlit_app_conciliacion_detalle.py / TEMP-2 para esa version).
Ambos se navegan desde streamlit_app.py (barra lateral, pages/).

Metodologia completa: docs/investigacion_pendientes.md, docs/pendientes.md,
PROGRESS.md.

Corre standalone con:
  streamlit run streamlit_app_conciliacion.py --server.port 8507

Requiere credenciales de conexión directa a BD (igual que main.py /
baseline_universal.py) en un .env local — ver .env.example y
src/bridge_client.py para el detalle.
"""
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from streamlit_common import (  # noqa: E402
    PERIODOS_DISPONIBLES, COLS_DISPLAY, COLS_BASE, cargar_periodos, descarga_excel, aplica_filtros,
    calcular_universo, calcular_no_en_mpro, render_kpis, render_tab_no_en_mpro)

VERSION = "v1"


def _is_standalone():
    return not hasattr(st, "_reconciliacion_embedded")


def render():
    st.title("TEMP-1 · Conciliacion CFDI <-> mpro")
    st.caption(f"Version {VERSION} · Baseline universal (recibidos, todos los origenes)")
    st.markdown(
        "Para cada CFDI se suma el cargo de **todos** los documentos de mpro con los que "
        "aparece etiquetado (sin importar el origen/modulo) y se compara contra su base "
        "fiscal `(SubTotal - Descuento + IEPS + impuestos locales) x tipo de cambio` "
        "mediante una cascada de once vias de cuadre. Chequeo de **un solo lado** (cargo) "
        "— no exige que el abono/pago tambien cuadre. Detalle en la pestaña "
        "**Documentacion**."
    )

    with st.sidebar:
        st.subheader("Periodo")
        periodos_sel = st.multiselect(
            "Periodos a incluir (2026)", PERIODOS_DISPONIBLES,
            default=["2026-02"], key="rc_periodos",
            help="Rango validado mientras el pipeline corre contra mssql_205: enero-junio 2026.")

    if not periodos_sel:
        st.info("Selecciona al menos un periodo en la barra lateral.")
        return

    try:
        resumen = cargar_periodos(tuple(sorted(periodos_sel)))
    except Exception as exc:
        st.error(
            "No se pudo consultar la base de datos. Verifica las credenciales en .env "
            "(PG_USER/PG_PASSWORD, MSSQL_205_USER/PASSWORD, MSSQL_207_USER/PASSWORD — "
            "ver .env.example) y que haya red hacia la LAN de Trivasa.\n\n"
            f"Error: {exc}"
        )
        return

    if resumen.empty:
        st.warning("Sin datos para los periodos seleccionados.")
        return

    universo = calcular_universo(resumen)
    no_en_mpro = calcular_no_en_mpro(resumen)

    with st.sidebar:
        st.subheader("Filtros")
        origenes_todos = sorted({
            o.strip() for lista in universo["origenes"].dropna() for o in str(lista).split(",") if o.strip()
        })
        origenes_sel = st.multiselect("Origen en mpro", origenes_todos, key="rc_origenes")
        busca = st.text_input("Buscar RFC, proveedor o UUID", key="rc_busca")

    universo_f = aplica_filtros(universo, origenes_sel, busca)
    no_en_mpro_f = aplica_filtros(no_en_mpro, origenes_sel, busca)
    conciliados_f = universo_f[universo_f["cuadra_agregado"]]
    pendientes_f = universo_f[~universo_f["cuadra_agregado"]]

    render_kpis(universo, universo_f, conciliados_f, pendientes_f, no_en_mpro)

    tab_conc, tab_pend, tab_no_mpro, tab_vias, tab_docs = st.tabs(
        ["Conciliados", "Pendientes", "No encontrados en mpro", "Por via / motivo", "Documentacion"])

    with tab_conc:
        cols = COLS_BASE + ["cuadra_via"]
        st.dataframe(conciliados_f[cols].rename(columns=COLS_DISPLAY),
                     width="stretch", height=520, hide_index=True)
        st.download_button(
            "Descargar Excel (conciliados, filtrado)",
            data=descarga_excel(conciliados_f, cols, "conciliados"),
            file_name=f"conciliados_{'-'.join(periodos_sel)}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_pend:
        cols = COLS_BASE + ["motivo_pendiente"]
        st.dataframe(pendientes_f[cols].rename(columns=COLS_DISPLAY),
                     width="stretch", height=520, hide_index=True)
        st.download_button(
            "Descargar Excel (pendientes, filtrado)",
            data=descarga_excel(pendientes_f, cols, "pendientes"),
            file_name=f"pendientes_{'-'.join(periodos_sel)}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_no_mpro:
        render_tab_no_en_mpro(no_en_mpro_f, periodos_sel)

    with tab_vias:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Conciliados por via de cuadre**")
            vias = conciliados_f["cuadra_via"].value_counts()
            if not vias.empty:
                st.bar_chart(vias)
            else:
                st.caption("Sin conciliados con los filtros actuales.")
        with c2:
            st.markdown("**Pendientes por motivo**")
            motivos = pendientes_f["motivo_pendiente"].value_counts()
            if not motivos.empty:
                st.bar_chart(motivos)
            else:
                st.caption("Sin pendientes con los filtros actuales.")
        if len(periodos_sel) > 1:
            st.markdown("**% conciliado por periodo**")
            por_periodo = universo_f.groupby("periodo")["cuadra_agregado"].mean().mul(100).round(1)
            st.bar_chart(por_periodo)

    with tab_docs:
        st.markdown(
            "Metodologia completa, con evidencia caso por caso y la cascada de once vias "
            "de cuadre, en:\n\n"
            "- `docs/investigacion_pendientes.md` — hallazgos que subieron el % de cuadre y "
            "clasificacion de los pendientes que quedan.\n"
            "- `docs/pendientes.md` — que falta y por que, por origen/tema.\n"
            "- `docs/hallazgos.md` — bitacora numerada de bugs y patrones confirmados.\n"
            "- `PROGRESS.md` — estado actual y como retomar el trabajo.\n\n"
            "Este reporte solo envuelve en UI el resultado de "
            "`baseline_universal.calcular()` — la logica de conciliacion vive ahi, no aqui.\n\n"
            "**No encontrados en mpro**: CFDI con valor monetario real que jamas se etiquetaron "
            "en `Comprobante_Digital` — no entran ni a Conciliados ni a Pendientes porque no hay "
            "nada de mpro contra que compararlos."
        )


if _is_standalone():
    st.set_page_config(page_title="TEMP-1 · Conciliacion CFDI", layout="wide")

render()
