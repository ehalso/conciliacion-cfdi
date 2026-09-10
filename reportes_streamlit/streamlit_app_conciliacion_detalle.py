"""
TEMP-2 · Conciliación CFDI <-> mpro - con detalle de línea (baseline universal)

Misma conciliación que streamlit_app_conciliacion.py (TEMP-1), más la vista
de detalle de línea: para las CFDI que cuadran por la vía "cargo = base
CFDI", muestra las líneas reales de Poliza_Detalle / Gasto_Registro_Control
que suman el cargo agregado ya validado. Logica de negocio en
baseline_universal.calcular() / detalle_regla1() - este script solo la
envuelve en UI, no la duplica.

Orden de pestañas: Detalle primero, Conciliacion segunda (a diferencia de
TEMP-1) — pedido explícito para comparar ambos layouts. Se navega junto con
TEMP-1 desde streamlit_app.py (barra lateral, pages/).

Metodologia completa: docs/investigacion_pendientes.md, docs/pendientes.md,
docs/hallazgos.md (punto 27), PROGRESS.md.

Corre standalone con:
  streamlit run streamlit_app_conciliacion_detalle.py --server.port 8508

Requiere credenciales de conexión directa a BD (igual que main.py /
baseline_universal.py) en un .env local — ver .env.example y
src/bridge_client.py para el detalle.
"""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from streamlit_common import (  # noqa: E402
    PERIODOS_DISPONIBLES, VIA_CON_DETALLE, COLS_DISPLAY, DETALLE_COLS_DISPLAY, COLS_BASE,
    cargar_periodos, cargar_detalle_periodo, cargar_detalle_uuid, descarga_excel, aplica_filtros,
    calcular_universo, calcular_no_en_mpro, render_kpis, render_tab_no_en_mpro)

VERSION = "v2"

COLS_DETALLE = ["uuid", "periodo", "rfc_emisor", "nombre_emisor", "origen", "documento",
                "tipo", "importe", "cuenta", "cuenta_descripcion", "concepto", "centro_costo",
                "subtotal", "cargo_agregado"]


def _is_standalone():
    return not hasattr(st, "_reconciliacion_embedded")


def render():
    st.title("TEMP-2 · Conciliacion CFDI <-> mpro")
    st.caption(f"Version {VERSION} · Baseline universal + detalle de línea (regla 1)")
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

    # Detalle (regla 1): se carga aqui, antes de las pestañas, para poder
    # ofrecer filtros de cuenta/centro de costo en la barra lateral con
    # los valores reales ya en mano.
    regla1_f = conciliados_f[conciliados_f["cuadra_via"] == VIA_CON_DETALLE]
    with st.spinner("Cargando detalle de línea del periodo..."):
        detalle_partes = [cargar_detalle_periodo(p) for p in periodos_sel]
    detalle_periodo = pd.concat(detalle_partes, ignore_index=True) if detalle_partes else pd.DataFrame()
    detalle_base = detalle_periodo[detalle_periodo["uuid"].isin(regla1_f["uuid"])].merge(
        regla1_f[["uuid", "rfc_emisor", "nombre_emisor", "subtotal", "cargo_agregado"]],
        on="uuid", how="left") if not detalle_periodo.empty else pd.DataFrame(columns=COLS_DETALLE)

    with st.sidebar:
        st.subheader("Filtros de detalle")
        cuentas_todas = sorted(detalle_base["cuenta_descripcion"].dropna().unique().tolist()) \
            if "cuenta_descripcion" in detalle_base else []
        centros_todos = sorted(detalle_base["centro_costo"].dropna().unique().tolist()) \
            if "centro_costo" in detalle_base else []
        cuentas_sel = st.multiselect("Cuenta contable", cuentas_todas, key="rc_cuentas",
                                      help="Solo aplica a la pestaña Detalle (regla 1).")
        centros_sel = st.multiselect("Centro de costo", centros_todos, key="rc_centros",
                                      help="Solo aplica a la pestaña Detalle (regla 1).")

    detalle_f = detalle_base.copy()
    if cuentas_sel:
        detalle_f = detalle_f[detalle_f["cuenta_descripcion"].isin(cuentas_sel)]
    if centros_sel:
        detalle_f = detalle_f[detalle_f["centro_costo"].isin(centros_sel)]

    render_kpis(universo, universo_f, conciliados_f, pendientes_f, no_en_mpro)

    # Orden pedido: Detalle primero, Conciliacion segunda.
    tab_detalle, tab_conc, tab_pend, tab_no_mpro, tab_vias, tab_docs = st.tabs(
        ["Detalle (regla 1)", "Conciliados", "Pendientes", "No encontrados en mpro",
         "Por via / motivo", "Documentacion"])

    with tab_detalle:
        n_conciliados_total = len(conciliados_f)
        pct_cubierto = f"{len(regla1_f)/n_conciliados_total*100:.1f}%" if n_conciliados_total else "—"
        st.caption(
            f"Líneas de póliza / control de gasto que suman el cargo de cada CFDI, solo para "
            f"la vía **{VIA_CON_DETALLE}** ({len(regla1_f):,} de {n_conciliados_total:,} conciliados "
            f"filtrados, {pct_cubierto}) — las diez vías especiales quedan pendientes "
            f"(ver pestaña Documentación)."
        )

        if regla1_f.empty:
            st.info("Ningún CFDI conciliado por esta vía con los filtros actuales.")
        elif detalle_f.empty:
            st.info("Ninguna línea con los filtros de cuenta/centro de costo actuales.")
        else:
            # Sanity en vivo (sobre detalle_base, sin los filtros de cuenta/
            # centro de costo, que son solo de visualización): la suma de
            # líneas debe reproducir cargo_agregado (validado 2026-09-09,
            # ver docs/hallazgos.md #27).
            suma_por_uuid = detalle_base.groupby("uuid")["importe"].sum()
            referencia = regla1_f.set_index("uuid")["cargo_agregado"]
            diff = (suma_por_uuid - referencia.reindex(suma_por_uuid.index)).abs()
            n_mal = int((diff > 0.01).sum())
            if n_mal:
                st.warning(f"{n_mal} CFDI donde la suma de líneas no reproduce el cargo agregado — revisar.")
            else:
                st.success(f"Suma de líneas verificada contra el cargo agregado: {len(suma_por_uuid):,} CFDI OK.")

            st.dataframe(detalle_f[COLS_DETALLE].rename(columns=DETALLE_COLS_DISPLAY),
                         width="stretch", height=520, hide_index=True)
            st.download_button(
                "Descargar Excel (detalle de línea, filtrado)",
                data=descarga_excel(detalle_f, COLS_DETALLE, "detalle", cols_display=DETALLE_COLS_DISPLAY),
                file_name=f"detalle_regla1_{'-'.join(periodos_sel)}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_conc:
        cols = COLS_BASE + ["cuadra_via"]
        tabla_conc = conciliados_f[cols].reset_index(drop=True)
        evento = st.dataframe(
            tabla_conc.rename(columns=COLS_DISPLAY), width="stretch", height=520, hide_index=True,
            on_select="rerun", selection_mode="single-row", key="rc_tabla_conciliados")
        st.download_button(
            "Descargar Excel (conciliados, filtrado)",
            data=descarga_excel(conciliados_f, cols, "conciliados"),
            file_name=f"conciliados_{'-'.join(periodos_sel)}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        filas_sel = evento.selection.rows if evento and evento.selection else []
        if filas_sel:
            fila = tabla_conc.iloc[filas_sel[0]]
            st.divider()
            st.markdown(f"**Detalle de línea — `{fila['uuid']}`** ({fila['nombre_emisor']})")
            if fila["cuadra_via"] != VIA_CON_DETALLE:
                st.info(
                    f"Este CFDI cuadró por la vía **{fila['cuadra_via']}** — el detalle de línea "
                    f"solo está implementado para la vía **{VIA_CON_DETALLE}** por ahora."
                )
            else:
                with st.spinner("Consultando líneas de póliza..."):
                    det_uuid = cargar_detalle_uuid(fila["uuid"])
                if det_uuid.empty:
                    st.warning("Sin líneas encontradas (inesperado — revisar).")
                else:
                    st.dataframe(det_uuid.drop(columns=["uuid"]).rename(columns=DETALLE_COLS_DISPLAY),
                                 width="stretch", hide_index=True)
                    suma = det_uuid["importe"].sum()
                    st.caption(f"Suma de líneas: ${suma:,.2f}  ·  Cargo agregado reportado: "
                               f"${fila['cargo_agregado']:,.2f}")

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
            "**Detalle de linea** (pestaña *Detalle (regla 1)*, y el drill-down al seleccionar "
            "una fila en *Conciliados*): muestra las lineas reales de `Poliza_Detalle` / "
            "`Gasto_Registro_Control` que suman el cargo agregado de cada CFDI. Cubre solo la "
            "vía *cargo = base CFDI* (~96% de los conciliados) — las diez vías especiales "
            "(arrendamiento, folios hermanos, cheque agrupado, etc.) jalan lineas de documentos "
            "que no son propios del CFDI y quedan pendientes. Logica en "
            "`baseline_universal.detalle_regla1()` / `src/extract_detalle_lineas.py`; validado "
            "en vivo contra `cargo_agregado` con 100% de coincidencia — ver "
            "`docs/hallazgos.md` punto 27. Los filtros de Cuenta contable / Centro de costo de "
            "la barra lateral solo afectan la pestaña Detalle.\n\n"
            "**No encontrados en mpro**: CFDI con valor monetario real que jamas se etiquetaron "
            "en `Comprobante_Digital` — no entran ni a Conciliados ni a Pendientes porque no hay "
            "nada de mpro contra que compararlos."
        )


if _is_standalone():
    st.set_page_config(page_title="TEMP-2 · Conciliacion CFDI (detalle)", layout="wide")

render()
