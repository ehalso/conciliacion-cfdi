"""
reporte_ui_consolidado.py -- UI del layout de gastos de 60 columnas
(auditoría externa, Bates y Asociados -- ver layout_gastos_60col/README.md).

A diferencia de CONT-1/CONT-2 (rank-pairing, layout_gastos_lib.reporte_
completo) y CONT-4/CONT-5 (Poliza_Configuracion, layout_gastos_config_lib),
este consolidado usa el bloque de póliza por JOIN DIRECTO
(`24_bloque_poliza_directo.py`, `Pd_Referencia = Gr_Folio`) -- validado
"100% reconciliado" contra el reporte nativo de mpro (ver README del
proyecto), reemplaza a `reconstruir_config()` como fuente para este
entregable. La lógica de los 4 bloques (póliza, impuestos, proveedor/pago,
XML/concepto) vive en `layout_gastos_poliza/{21,22,23,24,25}_*.py` -- este
módulo solo la importa (vía `importlib`, los nombres empiezan con dígito)
y la envuelve en UI, no la duplica.

`resumen_qa`/`resumen_por_folio` (misma pestaña de Reconciliación que
CONT-1/2/4/5) son genéricas a nivel folio -- solo necesitan FOLIO/ORIGEN/
CARGO/ABONO/IMPORTE_FOLIO, no dependen del grano de la tabla de Datos.
"""
import os
import sys
from importlib import import_module

import pandas as pd
import streamlit as st
from sqlalchemy import text

LAYOUT_GASTOS_POLIZA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "layout_gastos_poliza")
sys.path.insert(0, LAYOUT_GASTOS_POLIZA_DIR)

m25 = import_module("25_consolidado_final")
from layout_gastos_lib import IMPORTE_FOLIO_SQL, IMPORTE_FOLIO_SQL_NOMINA, resumen_qa, resumen_por_folio  # noqa: E402
from connection_205_trivasadb3 import engine  # noqa: E402

VERSION = "v1"


@st.cache_data(ttl=1800, show_spinner="Consultando TRIVASADB3 (.205) -- 4 bloques (póliza, impuestos, "
                                       "proveedor/pago, XML)...")
def _cargar_consolidado(fecha_ini: str, fecha_fin: str):
    df = m25.construir(fecha_ini, fecha_fin)
    faltantes = [c for c in m25.ORDEN_COLUMNAS if c not in df.columns]
    cols = [c for c in m25.ORDEN_COLUMNAS if c in df.columns]
    return df[cols].reset_index(drop=True), faltantes


@st.cache_data(ttl=1800, show_spinner=False)
def _cargar_importe_folio(fecha_ini: str, fecha_fin: str) -> pd.DataFrame:
    """IMPORTE_FOLIO (normal + nómina) para el mismo periodo -- base de la
    reconciliación, independiente de los 4 bloques del consolidado."""
    p = {"fecha_ini": fecha_ini, "fecha_fin": fecha_fin}
    normal = pd.read_sql(text(IMPORTE_FOLIO_SQL), engine, params=p)
    nomina = pd.read_sql(text(IMPORTE_FOLIO_SQL_NOMINA), engine, params=p)
    imp = pd.concat([normal, nomina], ignore_index=True)
    imp["FOLIO"] = imp["FOLIO"].str.strip()
    return imp


def render():
    st.title("Layout de Gastos · 60 columnas (auditoría externa)")
    st.caption(f"Versión {VERSION} · Consolidado final, join directo de póliza")
    st.markdown(
        "Requerimiento original de **Bates y Asociados** (auditoría externa trimestral) -- "
        "une 4 bloques ya validados por separado (póliza, impuestos, proveedor/pago, XML) "
        "sobre el grano de detalle real (`FOLIO x POLIZA x CUENTA x CECO`). El bloque de "
        "póliza usa **join directo** `Pd_Referencia = Gr_Folio` (no rank-pairing) -- Cargo/"
        "Abono exactos, sin ambigüedad. Detalle completo en la pestaña **Documentación**."
    )

    with st.sidebar:
        st.subheader("Periodo")
        fecha_ini = st.date_input("Desde", value=pd.Timestamp("2026-01-01").date(), key="c60_ini")
        fecha_fin = st.date_input("Hasta", value=pd.Timestamp("2026-01-31").date(), key="c60_fin")

    if fecha_ini > fecha_fin:
        st.error("La fecha 'Desde' debe ser anterior o igual a 'Hasta'.")
        return

    # Limite superior EXCLUSIVO en los 4 bloques (Gr_Fecha < fecha_fin) -- el
    # sidebar es inclusivo, se traduce aqui (mismo patron que CONT-1/2/4/5).
    ff_excl = str(fecha_fin + pd.Timedelta(days=1))
    fi = str(fecha_ini)

    try:
        df, faltantes = _cargar_consolidado(fi, ff_excl)
        imp = _cargar_importe_folio(fi, ff_excl)
    except Exception as exc:
        st.error(
            "No se pudo consultar la base de datos. Verifica las credenciales en .env "
            "(MSSQL_205_USER/PASSWORD -- ver .env.example) y que haya red hacia la LAN de "
            f"Trivasa.\n\nError: {exc}"
        )
        return

    if df.empty:
        st.warning("Sin folios para el periodo seleccionado.")
        return

    if faltantes:
        st.warning(f"Columnas del Word sin fuente identificada (no aparecen en este consolidado): {faltantes}")

    with st.sidebar:
        st.subheader("Filtros")
        origenes_todos = sorted(df["ORIGEN"].dropna().unique().tolist())
        origenes_sel = st.multiselect("Origen", origenes_todos, key="c60_origenes")
        busca = st.text_input("Buscar folio, proveedor, UUID o CECO", key="c60_busca")

    df_f = df.copy()
    if origenes_sel:
        df_f = df_f[df_f["ORIGEN"].isin(origenes_sel)]
    if busca:
        q = busca.strip().upper()
        campos = ["FOLIO", "NOMBRE_PROVEEDOR", "RFC_PROVEEDOR", "UUID", "CECO", "CECO_DESCRIPCION"]
        mask = pd.Series(False, index=df_f.index)
        for c in campos:
            if c in df_f.columns:
                mask |= df_f[c].astype(str).str.upper().str.contains(q, na=False)
        df_f = df_f[mask]

    if df_f.empty:
        st.info("Ningún registro con los filtros actuales.")
        return

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Filas (filtrado)", f"{len(df_f):,}")
    k2.metric("Folios", f"{df_f['FOLIO'].nunique():,}")
    k3.metric("Columnas", f"{len(df_f.columns)} / 60")
    k4.metric("Cargo − Abono", f"${(df_f['CARGO'].sum() - df_f['ABONO'].sum()):,.2f}")

    tab_datos, tab_recon, tab_docs = st.tabs(["Datos", "Reconciliación", "Documentación"])

    with tab_datos:
        st.dataframe(df_f, width="stretch", height=560, hide_index=True)
        import io
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_f.to_excel(writer, index=False, sheet_name="Layout 60 columnas")
        st.download_button(
            "Descargar Excel (filtrado)", data=buf.getvalue(),
            file_name=f"layout_gastos_60col_{fecha_ini}_{fecha_fin}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_recon:
        st.markdown(
            "Compara, **por folio**, `Cargo - Abono` (bloque de póliza, join directo) contra "
            "el importe nativo del folio (`Gasto_Registro_Documento`) -- mismo criterio de "
            "cuadre (`< $1`) que CONT-1/CONT-2, aplicado aquí sobre el bloque validado por "
            "join directo en vez de rank-pairing."
        )
        base_recon = df_f[["FOLIO", "ORIGEN", "CARGO", "ABONO"]].merge(imp, on="FOLIO", how="left")
        qa = resumen_qa(base_recon)
        for _, row in qa.iterrows():
            if row.pct >= 99.9:
                st.success(f"**{row.ORIGEN}** -- {int(row.cuadran):,}/{int(row.folios):,} folios ({row.pct}%)")
            elif row.pct >= 95:
                st.warning(f"**{row.ORIGEN}** -- {int(row.cuadran):,}/{int(row.folios):,} folios ({row.pct}%)")
            else:
                st.error(f"**{row.ORIGEN}** -- {int(row.cuadran):,}/{int(row.folios):,} folios ({row.pct}%)")
        st.dataframe(qa, width="stretch", hide_index=True)

        pf = resumen_por_folio(base_recon)
        mal_folio = pf[~pf.CUADRA].sort_values("DIFERENCIA", key=lambda s: s.abs(), ascending=False)
        st.markdown(f"**Folios que no cuadran:** {len(mal_folio):,}")
        if len(mal_folio):
            st.dataframe(mal_folio, width="stretch", hide_index=True)

    with tab_docs:
        st.markdown(
            "**Requerimiento:** auditoría externa trimestral (Bates y Asociados), pedido de "
            "Contabilidad -- transcrito completo en `layout_gastos_60col/legado/layout-gastos-"
            "streamlit-claude/docs/00_requerimiento.md`.\n\n"
            "**4 bloques** (`layout_gastos_poliza/`): `24_bloque_poliza_directo.py` (Póliza/"
            "Cuenta/CECO/Cargo/Abono -- join directo `Pd_Referencia = Gr_Folio`, reemplaza a "
            "`reconstruir_config()`), `19_bloque_impuestos.py` + `21_impuestos_por_ceco.py` "
            "(Subtotales/IVA/retenciones, atribuidos por CECO vía `Grc_Factor`), "
            "`22_bloque_proveedor_pago.py` (Proveedor/cobro/pago), "
            "`23_bloque_xml_concepto.py` (UUID/XML + Concepto/Uso CFDI). "
            "`25_consolidado_final.py` los une por `FOLIO` (impuestos también por `CECO`).\n\n"
            "**Validado contra el reporte nativo de mpro** (no solo internamente): 7 orígenes "
            "(incluye NOMINA/CONSUMO_INTERNO), enero 2026 -- 4,494 folios, SUBTOTAL_NETO/"
            "IMPUESTO/TOTAL coinciden exacto a $0.00; Cargo−Abono con diferencia de $56.59 "
            "(0.00014%, redondeo a centavos entre `Poliza_Detalle` y los campos nativos de "
            "`Gasto_Registro_Documento`, no un problema de datos).\n\n"
            "**Pendiente conocido:** de las 60 columnas del Word, 52 tienen columna con fuente "
            "identificada -- `DESCUENTO`, `DESCUENTO_GLOBAL` y `FACTURA_REF` van como "
            "placeholder `NULL` (sin fuente en el sistema); las 8 restantes ni siquiera "
            "aparecen todavía. `MONTO_COBRADO` infla ~41.6% cuando un `Cxp_Folio` se comparte "
            "entre varios folios (factura consolidada) -- sin prorratear por ahora. Vista "
            "agrupada por cuenta contable (segunda vista que pide el Word) aún no construida "
            "-- solo existe la vista detalle. Detalle completo en `layout_gastos_60col/"
            "README.md` y `layout_gastos_poliza/PROGRESS.md`."
        )


