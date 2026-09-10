"""
reporte_ui.py -- UI compartida del reporte Layout de Gastos por CECO.

Una sola funcion `render()`, parametrizada por `incluir_nomina`, para que
las dos paginas (`pages/1_CONT-1_...py`, `pages/2_CONT-2_...py`) sean
wrappers delgados -- la logica de la tabla/filtros/tabs vive una sola vez
aqui, no duplicada por pagina.
"""
import io
import os
import sys
from datetime import date, timedelta

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "layout_gastos_poliza"))
from layout_gastos_lib import reporte_completo, resumen_qa, resumen_por_folio  # noqa: E402

VERSION = "v1"


@st.cache_data(ttl=1800, show_spinner="Consultando TRIVASADB3 (.205)...")
def _cargar_reporte(fecha_ini: str, fecha_fin: str, incluir_nomina: bool):
    return reporte_completo(fecha_ini, fecha_fin, incluir_nomina=incluir_nomina)


def render(numero: str, titulo: str, incluir_nomina: bool, key_prefix: str):
    st.title(f"{numero} · {titulo}")
    st.caption(f"Version {VERSION} · Reconciliacion Gasto_Registro_Control vs. Poliza_Detalle")
    if incluir_nomina:
        st.markdown(
            "Incluye `CONTROL_COMBUSTIBLE`, `GASTO_DIRECTO`, `GASTO_RECLASIFICACION`, "
            "`ORDEN_COMPRA`, `VIAJE`, `CONSUMO_INTERNO` y **`GASTO_REGISTRO_NOMINA`**. "
            "Nomina se empareja distinto a los demas -- ver pestana Documentacion."
        )
    else:
        st.markdown(
            "Incluye `CONTROL_COMBUSTIBLE`, `GASTO_DIRECTO`, `GASTO_RECLASIFICACION`, "
            "`ORDEN_COMPRA`, `VIAJE` y `CONSUMO_INTERNO`. Excluye `GASTO_REGISTRO_NOMINA` "
            f"-- ver **CONT-2** para la version que sí lo incluye."
        )

    with st.sidebar:
        st.subheader("Periodo")
        fecha_ini = st.date_input("Desde", value=date(2026, 1, 1), key=f"{key_prefix}_ini")
        fecha_fin = st.date_input("Hasta", value=date(2026, 1, 31), key=f"{key_prefix}_fin")

    if fecha_ini > fecha_fin:
        st.error("La fecha 'Desde' debe ser anterior o igual a 'Hasta'.")
        return

    # Ambas fechas del sidebar son inclusivas -- la capa de datos usa
    # limite superior EXCLUSIVO (Gr_Fecha < fecha_fin), se traduce aqui.
    datos = _cargar_reporte(str(fecha_ini), str(fecha_fin + timedelta(days=1)), incluir_nomina)

    with st.sidebar:
        st.subheader("Filtros")
        origenes = sorted(datos["ORIGEN"].dropna().unique())
        f_origen = st.multiselect("Origen", origenes, default=origenes, key=f"{key_prefix}_origen")
        buscar = st.text_input("Buscar (folio, póliza, CECO, cuenta, tipo de gasto)", key=f"{key_prefix}_buscar")

    df = datos[datos.ORIGEN.isin(f_origen)].copy()
    if buscar:
        campos = ["FOLIO", "POLIZA", "CECO", "CECO_DESCRIPCION", "CUENTA", "CUENTA_DESCRIPCION", "TIPO_GASTO_DESCRIPCION"]
        mask = pd.Series(False, index=df.index)
        for c in campos:
            mask |= df[c].astype(str).str.contains(buscar, case=False, na=False)
        df = df[mask]

    k1, k2, k3 = st.columns(3)
    k1.metric("Filas", f"{len(df):,}")
    k2.metric("Folios", f"{df.FOLIO.nunique():,}")
    pct = 100 * df.CUADRA.sum() / len(df) if len(df) else 0
    k3.metric("% cuadra vs. lado operativo", f"{pct:.2f}%",
              help="Compara el importe de la poliza real contra la estimacion de Gasto_Registro_Control (Grc_Importe). Ver pestana Reconciliacion.")

    k4, k5, k6 = st.columns(3)
    k4.metric("Σ Cargo", f"${df.CARGO.sum():,.2f}")
    k5.metric("Σ Abono", f"${df.ABONO.sum():,.2f}")
    # IMPORTE_FOLIO es 1 valor por folio, repetido en cada una de sus N
    # filas (una por CECO x TIPO_GASTO) -- deduplicar por FOLIO antes de
    # sumar, si no se cuenta cada folio varias veces.
    importe_mpro = df.drop_duplicates("FOLIO")["IMPORTE_FOLIO"].sum()
    k6.metric("Importe reporte MPRO", f"${importe_mpro:,.2f}",
              help="Importe nativo por folio (Gasto_Registro_Documento), no Cargo-Abono de poliza -- "
                   "misma cifra que reporta MPRO. 1 valor por folio, no por linea.")

    tab_datos, tab_recon, tab_docs = st.tabs(["Datos", "Reconciliacion", "Documentacion"])

    columnas_reporte = [
        "FOLIO", "POLIZA", "ORIGEN", "TIPO_GASTO", "TIPO_GASTO_DESCRIPCION",
        "CECO", "CECO_DESCRIPCION", "CUENTA", "CUENTA_DESCRIPCION",
        "CARGO", "ABONO",
    ]

    with tab_datos:
        st.dataframe(df[columnas_reporte], width="stretch", height=560, hide_index=True)
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df[columnas_reporte].to_excel(writer, index=False, sheet_name="Layout Gastos CECO")
        st.download_button(
            "Descargar Excel (filtrado)", data=buf.getvalue(),
            file_name=f"layout_gastos_ceco_{numero}_{fecha_ini}_{fecha_fin}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{key_prefix}_download",
        )

    with tab_recon:
        st.markdown(
            "Compara, **por folio**, `Cargo - Abono` (sumado sobre todas sus líneas de "
            "CECO x Tipo de Gasto) contra el importe nativo del folio (`Importe reporte "
            "MPRO`). Diferencia < $1 se considera cuadrado -- más simple y más robusta "
            "que comparar línea por línea (evita depender del rank-pairing y su residual "
            "conocido, ver pestaña Documentación)."
        )
        qa = resumen_qa(df)
        for _, row in qa.iterrows():
            if row.pct >= 99.9:
                st.success(f"**{row.ORIGEN}** -- {int(row.cuadran):,}/{int(row.folios):,} folios ({row.pct}%)")
            elif row.pct >= 95:
                st.warning(f"**{row.ORIGEN}** -- {int(row.cuadran):,}/{int(row.folios):,} folios ({row.pct}%)")
            else:
                st.error(f"**{row.ORIGEN}** -- {int(row.cuadran):,}/{int(row.folios):,} folios ({row.pct}%)")
        st.dataframe(qa, width="stretch", hide_index=True)

        pf = resumen_por_folio(df)
        mal_folio = pf[~pf.CUADRA].sort_values("DIFERENCIA", key=lambda s: s.abs(), ascending=False)
        st.markdown(f"**Folios que no cuadran:** {len(mal_folio):,}")
        if len(mal_folio):
            tabla_mal = mal_folio.rename(columns={"IMPORTE_FOLIO": "IMPORTE REPORTE MPRO"})[
                ["FOLIO", "ORIGEN", "CARGO", "ABONO", "IMPORTE REPORTE MPRO", "DIFERENCIA"]
            ]
            st.dataframe(tabla_mal, width="stretch", hide_index=True)

    with tab_docs:
        texto_nomina = ""
        if incluir_nomina:
            texto_nomina = (
                "\n\n**`GASTO_REGISTRO_NOMINA` (solo en CONT-2):** no usa rank-pairing como "
                "los demas origenes -- no existe FK real `Tipo_Gasto -> Cuenta_Contable` "
                "(`Tg_Cuenta_Contable` vacio en los 249 tipos de gasto), ni siquiera una "
                "correspondencia posicional confiable (cada folio reparte el gasto en muchas "
                "mas cuentas 6xxx por concepto que lineas de `Grc_ID`). Se empareja por **join "
                "directo de texto** `(FOLIO, CECO, Tg_Descripcion = Cc_Descripcion normalizado)` "
                "-- confirmado 1:1 exacto, sin huerfanos de ningun lado (6,591/6,591, "
                "enero-marzo 2026). Igual que los demas origenes, `CARGO`/`ABONO` salen de "
                "`Pd_Tipo` real -- confirmado que nomina es 100% Cargo, 0% Abono con centro "
                "real (antes, `13_reconciliacion_nomina_ceco.py` solo miraba `Pd_Tipo=1`, "
                "sin confirmar que no hubiera Abono)."
            )
        st.markdown(
            "**Metodologia completa:** `PROGRESS.md` (camino recorrido, casos por origen, "
            "residual conocido) y `RESUMEN_CASOS.md` (tabla de casos de negocio por origen), "
            "en este mismo directorio.\n\n"
            "**Grano del reporte:** 1 fila por `(FOLIO, CECO, TIPO_GASTO)`, con la linea real "
            "de poliza que le corresponde por posicion dentro de `(FOLIO, CECO)` (rank-pairing) "
            "-- no existe llave real entre `Gasto_Registro_Control` y `Poliza_Detalle` (ver "
            "`07_reconciliacion_completa_ceco.py`).\n\n"
            "**CARGO/ABONO:** leidos directo de `Pd_Tipo` (1=Cargo, 2=Abono) de "
            "`Poliza_Detalle` -- nunca inferidos con una regla de reversion. Confirmado "
            "2026-09-03 que nunca coexisten !=0 en la misma fila, ni siquiera en el folio "
            "residual de `GASTO_RECLASIFICACION` con signos mezclados por centro.\n\n"
            "**Residual conocido:** ~9 filas / 3 folios en el trimestre (<0.06% del universo) "
            "donde el conteo de lineas no coincide exacto entre los dos lados -- aparecen "
            "marcadas `TIPO_GASTO`/`CUENTA` = `(residual)`. Ver `PROGRESS.md` para el detalle "
            "folio por folio." + texto_nomina
        )
