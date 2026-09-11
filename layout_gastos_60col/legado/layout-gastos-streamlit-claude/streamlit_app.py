"""
Layout de registro de gastos - reporte Streamlit (v1.1)

Requerimiento: docs/00_requerimiento.md (auditoria Bates y Asociados, Ismael Valdez /
Contabilidad y Finanzas). Modelo de datos: docs/02_modelo_datos.md. Bugs conocidos del Excel de
referencia que esta version corrige: docs/01_hallazgos_excel_referencia.md. Reconciliacion:
docs/03_hito_v1.md. Catalogo SAT de forma de pago: docs/05_hito_v1_1.md.

Corre standalone con:
  streamlit_venv/bin/streamlit run streamlit_app.py --server.port 8502
o incrustado en hub_app.py (menu compartido con el reporte de Consumo Interno).
"""
import io
import os
import sys
from datetime import date

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))

from scripts.layout_gastos_v1 import (  # noqa: E402
    extract_header,
    extract_poliza,
    group_by_cuenta_contable,
    merge_header_poliza,
)
from scripts.catalogs import enrich_forma_pago  # noqa: E402
from scripts.layout_gastos_v0_1 import extract as extract_v0_1  # noqa: E402
from scripts.layout_gastos_v0_2 import (  # noqa: E402
    extract as extract_v0_2,
    validar as validar_v0_2,
    ORIGENES_SIN_JOIN as ORIGENES_SIN_JOIN_V0_2,
)
from scripts.layout_gastos_v0_3 import (  # noqa: E402
    extract as extract_v0_3,
    validar as validar_v0_3,
    ORIGENES_SIN_JOIN as ORIGENES_SIN_JOIN_V0_3,
)
from scripts.layout_gastos_v0_4_1 import (  # noqa: E402
    extract as extract_v0_4_1,
    validar as validar_v0_4_1,
    ORIGENES_SIN_JOIN as ORIGENES_SIN_JOIN_V0_4_1,
    TOLERANCIA as TOLERANCIA_V0_4_1,
)
from scripts.layout_gastos_v0_4_2 import (  # noqa: E402
    extract as extract_v0_4_2,
    validar as validar_v0_4_2,
    ORIGENES_SIN_JOIN as ORIGENES_SIN_JOIN_V0_4_2,
    TOLERANCIA as TOLERANCIA_V0_4_2,
)
from scripts.layout_gastos_v0_5 import (  # noqa: E402
    extract as extract_v0_5,
    validar as validar_v0_5,
    ORIGENES_SIN_JOIN as ORIGENES_SIN_JOIN_V0_5,
    TOLERANCIA as TOLERANCIA_V0_5,
)
from scripts.layout_gastos_v0_5_1 import (  # noqa: E402
    extract as extract_v0_5_1,
    validar as validar_v0_5_1,
    ORIGENES_SIN_JOIN as ORIGENES_SIN_JOIN_V0_5_1,
    TOLERANCIA as TOLERANCIA_V0_5_1,
)

VERSION = "v1.1"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")


def _is_standalone():
    return __name__ == "__main__" or not hasattr(st, "_layout_gastos_embedded")


@st.cache_data(ttl=3600, show_spinner="Consultando TRIVASADB3...")
def load_data(start_date: str, end_date_exclusive: str):
    cached_header = os.path.join(DATA_DIR, "header_2025_01.parquet")
    cached_poliza = os.path.join(DATA_DIR, "poliza_2025_01.parquet")
    if (
        start_date == "2025-01-01"
        and end_date_exclusive == "2025-02-01"
        and os.path.exists(cached_header)
        and os.path.exists(cached_poliza)
    ):
        header = pd.read_parquet(cached_header)
        poliza = pd.read_parquet(cached_poliza)
    else:
        header = extract_header(start_date, end_date_exclusive)
        poliza = extract_poliza(start_date, end_date_exclusive)
    header = enrich_forma_pago(header)
    detail = merge_header_poliza(header, poliza)
    return header, poliza, detail


@st.cache_data(ttl=1800, show_spinner="Consultando TRIVASADB3 (v0.1, por documento)...")
def load_data_v0_1(fecha_ini: str, fecha_fin_excl: str):
    return extract_v0_1(fecha_ini, fecha_fin_excl)


@st.cache_data(ttl=1800, show_spinner="Consultando TRIVASADB3 (v0.2, cargo/abono)...")
def load_data_v0_2(fecha_ini: str, fecha_fin_excl: str):
    return extract_v0_2(fecha_ini, fecha_fin_excl)


@st.cache_data(ttl=1800, show_spinner="Consultando TRIVASADB3 (v0.3, atribución por CECO)...")
def load_data_v0_3(fecha_ini: str, fecha_fin_excl: str):
    return extract_v0_3(fecha_ini, fecha_fin_excl)


@st.cache_data(ttl=1800, show_spinner="Consultando TRIVASADB3 (v0.4.1, reparto proporcional)...")
def load_data_v0_4_1(fecha_ini: str, fecha_fin_excl: str):
    return extract_v0_4_1(fecha_ini, fecha_fin_excl)


@st.cache_data(ttl=1800, show_spinner="Consultando TRIVASADB3 (v0.4.2, + reversiones)...")
def load_data_v0_4_2(fecha_ini: str, fecha_fin_excl: str):
    return extract_v0_4_2(fecha_ini, fecha_fin_excl)


@st.cache_data(ttl=1800, show_spinner="Consultando TRIVASADB3 (v0.5, SQL puro)...")
def load_data_v0_5(fecha_ini: str, fecha_fin: str):
    return extract_v0_5(fecha_ini, fecha_fin)


@st.cache_data(ttl=1800, show_spinner="Consultando TRIVASADB3 (v0.5.1, por documento -- puede tardar en rangos amplios)...")
def load_data_v0_5_1(fecha_ini: str, fecha_fin: str):
    return extract_v0_5_1(fecha_ini, fecha_fin)


def render_v0_1():
    st.title("Layout de registro de gastos · v0.1")
    st.caption(
        "Replica del reporte nativo MPRO \"Facturas de gastos (por documento)\" "
        "(RPAG008_99.asp) -- validado contra un export real de enero 2026 "
        "(diferencia de centavos en 7,043 filas). Ver docs/11_hito_v0_1.md."
    )

    with st.sidebar:
        st.subheader("Periodo")
        c1, c2 = st.columns(2)
        start = c1.date_input("Desde", value=date(2026, 1, 1), key="v01_start")
        end_incl = c2.date_input("Hasta", value=date(2026, 1, 31), key="v01_end")
        st.caption("Empresa: 0001 - TRIVASA S.A. DE C.V. (fijo)")

    if start > end_incl:
        st.error("La fecha 'Desde' debe ser anterior o igual a 'Hasta'.")
        return

    fecha_fin_excl = (pd.Timestamp(end_incl) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = load_data_v0_1(str(start), fecha_fin_excl)

    with st.sidebar:
        st.subheader("Filtros")
        origenes = sorted(df["origen"].fillna("(vacío / manual)").replace("", "(vacío / manual)").unique().tolist())
        origen_sel = st.multiselect(
            "Origen (Gr_Tabla)", origenes, default=[],
            help="CONSUMO_INTERNO y GASTO_REGISTRO_NOMINA vienen incluidos aqui -- "
                 "a diferencia de v1.1, que los excluye por diseño (ver docs/00).",
        )
        solo_con_comprobante = st.checkbox("Solo con comprobante (CFDI)", value=False)

    df_f = df.copy()
    df_f["origen_mostrar"] = df_f["origen"].fillna("(vacío / manual)").replace("", "(vacío / manual)")
    if origen_sel:
        df_f = df_f[df_f["origen_mostrar"].isin(origen_sel)]
    if solo_con_comprobante:
        df_f = df_f[df_f["tiene_comprobante"] == 1]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Folios", f"{df_f['folio'].nunique():,}")
    k2.metric("Importe", f"$ {df_f['importe'].sum():,.2f}")
    k3.metric("Impuestos", f"$ {df_f['impuestos'].sum():,.2f}")
    k4.metric("Total", f"$ {df_f['total'].sum():,.2f}")

    tab_reporte, tab_origen, tab_docs = st.tabs(["Reporte", "Por origen", "Documentación"])

    columnas = ["folio", "fecha_registro", "fecha_documento", "referencia",
                "proveedor_clave", "proveedor_nombre", "comentario", "moneda",
                "tipo_cambio", "importe", "impuestos", "total", "origen",
                "tiene_comprobante", "uuid"]

    with tab_reporte:
        st.dataframe(df_f[columnas], width="stretch", height=520, hide_index=True)
        st.caption(f"{len(df_f):,} filas de {len(df):,} totales en el periodo")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_f[columnas].to_excel(writer, index=False, sheet_name="Layout_v0_1")
        st.download_button(
            "Descargar Excel",
            data=buf.getvalue(),
            file_name=f"layout_gastos_v0_1_{start}_{end_incl}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with tab_origen:
        st.markdown(
            "`CONSUMO_INTERNO` y `GASTO_REGISTRO_NOMINA` están incluidos aquí porque este "
            "reporte replica el nativo de MPRO tal cual -- son los que **v1.1 excluye** "
            "para la auditoría externa."
        )
        por_origen = df.copy()
        por_origen["origen_mostrar"] = por_origen["origen"].fillna("(vacío / manual)").replace("", "(vacío / manual)")
        resumen = por_origen.groupby("origen_mostrar", as_index=False).agg(
            folios=("folio", "nunique"), filas=("folio", "size"), total=("total", "sum"),
        ).sort_values("total", ascending=False)
        st.dataframe(resumen, width="stretch", hide_index=True)

    with tab_docs:
        for fname in ("11_hito_v0_1.md",):
            path = os.path.join(DOCS_DIR, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    st.markdown(f.read())


def render_v0_2():
    st.title("Layout de registro de gastos · v0.2")
    st.caption(
        "Como v0.1, pero agrega Cargo/Abono/Cuenta contable del importe (subtotal, sin "
        "impuestos), con reglas distintas por origen -- validado origen por origen "
        "contra enero 2026 (99.7% de comprobación, 5 de 1,624 filas sin cuadrar). "
        "Ver docs/12_hito_v0_2.md."
    )

    with st.sidebar:
        st.subheader("Periodo")
        c1, c2 = st.columns(2)
        start = c1.date_input("Desde", value=date(2026, 1, 1), key="v02_start")
        end_incl = c2.date_input("Hasta", value=date(2026, 1, 31), key="v02_end")
        st.caption("Empresa: 0001 - TRIVASA S.A. DE C.V. (fijo)")

    if start > end_incl:
        st.error("La fecha 'Desde' debe ser anterior o igual a 'Hasta'.")
        return

    fecha_fin_excl = (pd.Timestamp(end_incl) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = load_data_v0_2(str(start), fecha_fin_excl)
    agg, resumen = validar_v0_2(df)

    with st.sidebar:
        st.subheader("Filtros")
        origenes = sorted(df["origen"].fillna("(vacío)").replace("", "(vacío)").unique().tolist())
        origen_sel = st.multiselect(
            "Origen (Gr_Tabla)", origenes, default=[],
            help="CONSUMO_INTERNO y GASTO_REGISTRO_NOMINA vienen sin Cargo/Abono/Cuenta "
                 "por diseño -- no se les intenta ningún join de póliza.",
        )
        solo_con_comprobante = st.checkbox("Solo con comprobante (CFDI)", value=False)

    df_f = df.copy()
    df_f["origen_mostrar"] = df_f["origen"].fillna("(vacío)").replace("", "(vacío)")
    if origen_sel:
        df_f = df_f[df_f["origen_mostrar"].isin(origen_sel)]
    if solo_con_comprobante:
        df_f = df_f[df_f["tiene_comprobante"] == 1]

    # ojo: en folios multi-Grd_ID con 2+ cuentas contables, la fila del ultimo Grd_ID se
    # repite una vez por cuenta (para poder mostrar cada cuenta contable en su propia
    # fila) -- "importe" es un dato por documento, no por linea de poliza, asi que
    # sumarlo tal cual sobre df_f lo infla. Se deduplica por (folio, grd_id) solo para
    # el KPI; la tabla de abajo si muestra cada cuenta contable en su propia fila.
    importe_dedup = df_f.drop_duplicates(subset=["folio", "grd_id"])["importe"].sum()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Folios", f"{df_f['folio'].nunique():,}")
    k2.metric("Importe", f"$ {importe_dedup:,.2f}")
    k3.metric("Cargo (póliza)", f"$ {df_f['cargo'].sum():,.2f}")
    k4.metric("Abono (póliza)", f"$ {df_f['abono'].sum():,.2f}")

    tab_reporte, tab_comprobacion, tab_docs = st.tabs(["Reporte", "Comprobación", "Documentación"])

    columnas = ["folio", "grd_id", "fecha_registro", "fecha_documento", "referencia",
                "proveedor_clave", "proveedor_nombre", "comentario", "moneda",
                "tipo_cambio", "importe", "origen", "cuenta_registro",
                "nombre_cuenta_registro", "cargo", "abono", "tiene_comprobante", "uuid"]

    with tab_reporte:
        st.dataframe(df_f[columnas], width="stretch", height=520, hide_index=True)
        st.caption(f"{len(df_f):,} filas de {len(df):,} totales en el periodo")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_f[columnas].to_excel(writer, index=False, sheet_name="Layout_v0_2")
        st.download_button(
            "Descargar Excel",
            data=buf.getvalue(),
            file_name=f"layout_gastos_v0_2_{start}_{end_incl}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with tab_comprobacion:
        st.markdown(
            "Comprobación por origen: **Cargo − Abono debe igualar el Importe**. "
            "`CONSUMO_INTERNO`/`GASTO_REGISTRO_NOMINA` no aplican (sin join, por diseño). "
            "Para folios con más de un `Grd_ID`, la póliza solo baja a nivel folio -- la "
            "comprobación de esos se hace sumando el importe de todo el folio, no por fila."
        )
        st.dataframe(resumen, width="stretch", hide_index=True)

        no_match = agg[
            (~agg["origen"].isin(ORIGENES_SIN_JOIN_V0_2)) & (agg["diferencia"].abs() > 0.5)
        ].sort_values("diferencia", key=abs, ascending=False)
        st.markdown(f"**{len(no_match)} filas/folios que no cuadran** (diferencia > $0.50):")
        st.dataframe(no_match, width="stretch", height=250, hide_index=True)
        st.caption(
            "3 de estos son reclasificaciones manuales con Importe en negativo (folios "
            "01-0034998, 01-0034999, 05-0181359) donde la póliza sí trae Cargo y Abono a "
            "la vez -- se dejan marcados como discrepancia a propósito, sin forzar la "
            "regla de validación, para que Contabilidad los revise caso por caso. Ver "
            "docs/12_hito_v0_2.md."
        )

    with tab_docs:
        for fname in ("12_hito_v0_2.md",):
            path = os.path.join(DOCS_DIR, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    st.markdown(f.read())


def render_v0_3():
    st.title("Layout de registro de gastos · v0.3")
    st.caption(
        "Como v0.2, pero atribuye Cargo/Abono/Cuenta al documento (Grd_ID) exacto usando "
        "Gasto_Registro_Control (desglose por centro de costo) en vez de pegar todo al "
        "último documento del folio -- 99.45%-100% de comprobación por origen, 4 de 1,793 "
        "filas sin cuadrar (mismos 3 casos manuales de v0.2 + 1 de redondeo). "
        "Ver docs/13_hito_v0_3.md."
    )

    with st.sidebar:
        st.subheader("Periodo")
        c1, c2 = st.columns(2)
        start = c1.date_input("Desde", value=date(2026, 1, 1), key="v03_start")
        end_incl = c2.date_input("Hasta", value=date(2026, 1, 31), key="v03_end")
        st.caption("Empresa: 0001 - TRIVASA S.A. DE C.V. (fijo)")

    if start > end_incl:
        st.error("La fecha 'Desde' debe ser anterior o igual a 'Hasta'.")
        return

    fecha_fin_excl = (pd.Timestamp(end_incl) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = load_data_v0_3(str(start), fecha_fin_excl)
    agg, resumen = validar_v0_3(df)

    with st.sidebar:
        st.subheader("Filtros")
        origenes = sorted(df["origen"].fillna("(vacío)").replace("", "(vacío)").unique().tolist())
        origen_sel = st.multiselect(
            "Origen (Gr_Tabla)", origenes, default=[],
            help="CONSUMO_INTERNO y GASTO_REGISTRO_NOMINA vienen sin Cargo/Abono/Cuenta "
                 "por diseño -- no se les intenta ningún join de póliza.",
        )
        solo_con_comprobante = st.checkbox("Solo con comprobante (CFDI)", value=False)

    df_f = df.copy()
    df_f["origen_mostrar"] = df_f["origen"].fillna("(vacío)").replace("", "(vacío)")
    if origen_sel:
        df_f = df_f[df_f["origen_mostrar"].isin(origen_sel)]
    if solo_con_comprobante:
        df_f = df_f[df_f["tiene_comprobante"] == 1]

    importe_dedup = df_f.drop_duplicates(subset=["folio", "grd_id"])["importe"].sum()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Folios", f"{df_f['folio'].nunique():,}")
    k2.metric("Importe", f"$ {importe_dedup:,.2f}")
    k3.metric("Cargo (póliza)", f"$ {df_f['cargo'].sum():,.2f}")
    k4.metric("Abono (póliza)", f"$ {df_f['abono'].sum():,.2f}")

    tab_reporte, tab_comprobacion, tab_docs = st.tabs(["Reporte", "Comprobación", "Documentación"])

    columnas = ["folio", "grd_id", "fecha_registro", "fecha_documento", "referencia",
                "proveedor_clave", "proveedor_nombre", "comentario", "moneda",
                "tipo_cambio", "importe", "origen", "cuenta_registro",
                "nombre_cuenta_registro", "cargo", "abono", "metodo_atribucion",
                "tiene_comprobante", "uuid"]

    with tab_reporte:
        st.dataframe(df_f[columnas], width="stretch", height=520, hide_index=True)
        st.caption(f"{len(df_f):,} filas de {len(df):,} totales en el periodo")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_f[columnas].to_excel(writer, index=False, sheet_name="Layout_v0_3")
        st.download_button(
            "Descargar Excel",
            data=buf.getvalue(),
            file_name=f"layout_gastos_v0_3_{start}_{end_incl}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with tab_comprobacion:
        st.markdown(
            "Comprobación por origen: **Cargo − Abono debe igualar el Importe**. "
            "`CONSUMO_INTERNO`/`GASTO_REGISTRO_NOMINA` no aplican (sin join, por diseño). "
            "Si un folio tiene algún documento sin cobertura de centro de costo, TODO el "
            "folio se valida a nivel folio completo (ver columna `metodo_atribucion` en "
            "el Reporte para saber qué documentos se resolvieron de forma exacta)."
        )
        st.dataframe(resumen, width="stretch", hide_index=True)

        no_match = agg[
            (~agg["origen"].isin(ORIGENES_SIN_JOIN_V0_3)) & (agg["diferencia"].abs() > 0.5)
        ].sort_values("diferencia", key=abs, ascending=False)
        st.markdown(f"**{len(no_match)} filas/folios que no cuadran** (diferencia > $0.50):")
        st.dataframe(no_match, width="stretch", height=250, hide_index=True)
        st.caption(
            "3 de estos son reclasificaciones manuales con Importe en negativo (folios "
            "01-0034998, 01-0034999, 05-0181359) donde la póliza sí trae Cargo y Abono a "
            "la vez -- se dejan marcados como discrepancia a propósito, sin forzar la "
            "regla de validación, para que Contabilidad los revise caso por caso. Ver "
            "docs/13_hito_v0_3.md."
        )

    with tab_docs:
        for fname in ("13_hito_v0_3.md", "12_hito_v0_2.md"):
            path = os.path.join(DOCS_DIR, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    st.markdown(f.read())


def render_v0_4_1():
    st.title("Layout de registro de gastos · v0.4.1")
    st.caption(
        "Como v0.3, pero agrega reparto proporcional (Gasto_Registro_Control) para casos "
        "donde la póliza combina 2+ documentos en 1 sola línea, y una salvaguarda que "
        "re-enruta a folio completo cualquier folio que no cuadre por documento -- solo "
        "4 folios (de miles) siguen usando el respaldo, todos de un solo documento, cero "
        "con ambigüedad real. Deja marcados como excepción los folios de reclasificación "
        "manual con Importe negativo (ver v0.4.2 para el ajuste que los resuelve). "
        "Ver docs/14_hito_v0_4.md."
    )

    with st.sidebar:
        st.subheader("Periodo")
        c1, c2 = st.columns(2)
        start = c1.date_input("Desde", value=date(2026, 1, 1), key="v041_start")
        end_incl = c2.date_input("Hasta", value=date(2026, 1, 31), key="v041_end")
        st.caption("Empresa: 0001 - TRIVASA S.A. DE C.V. (fijo)")

    if start > end_incl:
        st.error("La fecha 'Desde' debe ser anterior o igual a 'Hasta'.")
        return

    fecha_fin_excl = (pd.Timestamp(end_incl) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = load_data_v0_4_1(str(start), fecha_fin_excl)
    agg, resumen = validar_v0_4_1(df)

    with st.sidebar:
        st.subheader("Filtros")
        origenes = sorted(df["origen"].fillna("(vacío)").replace("", "(vacío)").unique().tolist())
        origen_sel = st.multiselect(
            "Origen (Gr_Tabla)", origenes, default=[],
            help="CONSUMO_INTERNO y GASTO_REGISTRO_NOMINA vienen sin Cargo/Abono/Cuenta "
                 "por diseño -- no se les intenta ningún join de póliza.",
        )
        solo_con_comprobante = st.checkbox("Solo con comprobante (CFDI)", value=False)

    df_f = df.copy()
    df_f["origen_mostrar"] = df_f["origen"].fillna("(vacío)").replace("", "(vacío)")
    if origen_sel:
        df_f = df_f[df_f["origen_mostrar"].isin(origen_sel)]
    if solo_con_comprobante:
        df_f = df_f[df_f["tiene_comprobante"] == 1]

    importe_dedup = df_f.drop_duplicates(subset=["folio", "grd_id"])["importe"].sum()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Folios", f"{df_f['folio'].nunique():,}")
    k2.metric("Importe", f"$ {importe_dedup:,.2f}")
    k3.metric("Cargo (póliza)", f"$ {df_f['cargo'].sum():,.2f}")
    k4.metric("Abono (póliza)", f"$ {df_f['abono'].sum():,.2f}")

    tab_reporte, tab_comprobacion, tab_docs = st.tabs(["Reporte", "Comprobación", "Documentación"])

    columnas = ["folio", "grd_id", "fecha_registro", "fecha_documento", "referencia",
                "proveedor_clave", "proveedor_nombre", "comentario", "moneda",
                "tipo_cambio", "importe", "origen", "cuenta_registro",
                "nombre_cuenta_registro", "cargo", "abono", "metodo_atribucion",
                "tiene_comprobante", "uuid"]

    with tab_reporte:
        st.dataframe(df_f[columnas], width="stretch", height=520, hide_index=True)
        st.caption(f"{len(df_f):,} filas de {len(df):,} totales en el periodo")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_f[columnas].to_excel(writer, index=False, sheet_name="Layout_v0_4_1")
        st.download_button(
            "Descargar Excel",
            data=buf.getvalue(),
            file_name=f"layout_gastos_v0_4_1_{start}_{end_incl}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with tab_comprobacion:
        st.markdown(
            "Comprobación por origen: **Cargo − Abono debe igualar el Importe**. "
            "`CONSUMO_INTERNO`/`GASTO_REGISTRO_NOMINA` no aplican (sin join, por diseño). "
            "`metodo_atribucion` en el Reporte indica cómo se resolvió cada fila: "
            "`centro_costo` (exacto, por valor), `centro_costo_proporcional` (exacto a "
            "nivel grupo, reparto proporcional entre documentos), `folio_completo` "
            "(respaldo, solo cuando no hay centro de costo con qué repartir)."
        )
        st.dataframe(resumen, width="stretch", hide_index=True)

        no_match = agg[
            (~agg["origen"].isin(ORIGENES_SIN_JOIN_V0_4_1)) & (agg["diferencia"].abs() > TOLERANCIA_V0_4_1)
        ].sort_values("diferencia", key=abs, ascending=False)

        st.markdown(f"### {len(no_match):,} de {len(agg):,} filas no cuadran (diferencia > $0.50)")

        if len(no_match):
            resumen_motivo = (
                no_match["motivo"].value_counts().rename_axis("Motivo").reset_index(name="Filas")
            )
            st.dataframe(resumen_motivo, width="stretch", hide_index=True)

            sin_explicar = no_match[no_match["motivo"] == "Sin explicación automática -- revisar a mano"]
            if len(sin_explicar):
                st.error(
                    f"{len(sin_explicar)} fila(s) **sin explicación automática** -- no encajan "
                    "en ningún patrón conocido (ni redondeo, ni reclasificación manual). "
                    "Revisar caso por caso, podría ser un problema nuevo."
                )
            else:
                st.success(
                    "Todas las discrepancias de este periodo tienen una explicación conocida "
                    "(redondeo o reclasificación manual con signo invertido) -- ninguna parece "
                    "requerir revisión urgente."
                )

            st.dataframe(
                no_match[["origen", "folio", "grd_id", "importe", "cargo", "abono", "neto",
                          "diferencia", "motivo"]],
                width="stretch", height=280, hide_index=True,
            )
        else:
            st.success("Todo cuadra en el periodo seleccionado -- 0 discrepancias.")

        st.caption(
            "`Ruido de redondeo`: diferencia ≤ $5, atribuible a centavos de conversión de "
            "moneda o reparto entre cuentas, no a un error real. `Reclasificación/ajuste "
            "manual con Importe negativo`: el Importe de cabecera viene en negativo (una "
            "reversión) pero Cargo y Abono de la póliza casi se cancelan entre sí (neto ≈ 0, "
            "como una reclasificación real) -- la regla Cargo−Abono==Importe no tiene forma "
            "de cuadrar con esa convención de signos; en v0.4.1 se dejan marcados sin forzar "
            "la regla (ver v0.4.2 para el fix). Ver docs/14_hito_v0_4.md."
        )

    with tab_docs:
        for fname in ("14_hito_v0_4.md", "13_hito_v0_3.md", "12_hito_v0_2.md"):
            path = os.path.join(DOCS_DIR, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    st.markdown(f.read())


def render_v0_4_2():
    st.title("Layout de registro de gastos · v0.4.2")
    st.caption(
        "Como v0.4.1, más un ajuste para reversiones contables reales (Importe negativo, "
        "usa Abono en vez de Cargo) y un fallback para la cuenta \"Gastos a cuenta de "
        "costo estandar\" -- 99.96% de comprobación en todo 2025 (solo 7 de 18,046 filas "
        "sin cuadrar, todas de ruido de redondeo menor a $1 -- 0 sin explicación). "
        "Ver docs/16_hito_v0_4_2_abono_gastos_a_cuenta.md."
    )

    with st.sidebar:
        st.subheader("Periodo")
        c1, c2 = st.columns(2)
        start = c1.date_input("Desde", value=date(2026, 1, 1), key="v042_start")
        end_incl = c2.date_input("Hasta", value=date(2026, 1, 31), key="v042_end")
        st.caption("Empresa: 0001 - TRIVASA S.A. DE C.V. (fijo)")

    if start > end_incl:
        st.error("La fecha 'Desde' debe ser anterior o igual a 'Hasta'.")
        return

    fecha_fin_excl = (pd.Timestamp(end_incl) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    df = load_data_v0_4_2(str(start), fecha_fin_excl)
    agg, resumen = validar_v0_4_2(df)

    with st.sidebar:
        st.subheader("Filtros")
        origenes = sorted(df["origen"].fillna("(vacío)").replace("", "(vacío)").unique().tolist())
        origen_sel = st.multiselect(
            "Origen (Gr_Tabla)", origenes, default=[],
            help="CONSUMO_INTERNO y GASTO_REGISTRO_NOMINA vienen sin Cargo/Abono/Cuenta "
                 "por diseño -- no se les intenta ningún join de póliza.",
        )
        solo_con_comprobante = st.checkbox("Solo con comprobante (CFDI)", value=False)

    df_f = df.copy()
    df_f["origen_mostrar"] = df_f["origen"].fillna("(vacío)").replace("", "(vacío)")
    if origen_sel:
        df_f = df_f[df_f["origen_mostrar"].isin(origen_sel)]
    if solo_con_comprobante:
        df_f = df_f[df_f["tiene_comprobante"] == 1]

    importe_dedup = df_f.drop_duplicates(subset=["folio", "grd_id"])["importe"].sum()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Folios", f"{df_f['folio'].nunique():,}")
    k2.metric("Importe", f"$ {importe_dedup:,.2f}")
    k3.metric("Cargo (póliza)", f"$ {df_f['cargo'].sum():,.2f}")
    k4.metric("Abono (póliza)", f"$ {df_f['abono'].sum():,.2f}")

    tab_reporte, tab_comprobacion, tab_docs = st.tabs(["Reporte", "Comprobación", "Documentación"])

    columnas = ["folio", "grd_id", "fecha_registro", "fecha_documento", "referencia",
                "proveedor_clave", "proveedor_nombre", "comentario", "moneda",
                "tipo_cambio", "importe", "origen", "cuenta_registro",
                "nombre_cuenta_registro", "cargo", "abono", "metodo_atribucion",
                "ajuste_reversion", "tiene_comprobante", "uuid"]

    with tab_reporte:
        st.dataframe(df_f[columnas], width="stretch", height=520, hide_index=True)
        st.caption(f"{len(df_f):,} filas de {len(df):,} totales en el periodo")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_f[columnas].to_excel(writer, index=False, sheet_name="Layout_v0_4_2")
        st.download_button(
            "Descargar Excel",
            data=buf.getvalue(),
            file_name=f"layout_gastos_v0_4_2_{start}_{end_incl}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with tab_comprobacion:
        st.markdown(
            "Comprobación por origen: **Cargo − Abono debe igualar el Importe**. "
            "`CONSUMO_INTERNO`/`GASTO_REGISTRO_NOMINA` no aplican (sin join, por diseño). "
            "`metodo_atribucion` en el Reporte indica cómo se resolvió cada fila: "
            "`centro_costo` (exacto, por valor), `centro_costo_proporcional` (exacto a "
            "nivel grupo, reparto proporcional entre documentos), `folio_completo` "
            "(respaldo, solo cuando no hay centro de costo con qué repartir). "
            "`ajuste_reversion` marca las filas donde se puso el Cargo en 0 por ser la "
            "contrapartida de una reversión contable real (ver docs/15)."
        )
        st.dataframe(resumen, width="stretch", hide_index=True)

        no_match = agg[
            (~agg["origen"].isin(ORIGENES_SIN_JOIN_V0_4_2)) & (agg["diferencia"].abs() > TOLERANCIA_V0_4_2)
        ].sort_values("diferencia", key=abs, ascending=False)

        st.markdown(f"### {len(no_match):,} de {len(agg):,} filas no cuadran (diferencia > $0.50)")

        if len(no_match):
            resumen_motivo = (
                no_match["motivo"].value_counts().rename_axis("Motivo").reset_index(name="Filas")
            )
            st.dataframe(resumen_motivo, width="stretch", hide_index=True)

            sin_explicar = no_match[no_match["motivo"] == "Sin explicación automática -- revisar a mano"]
            if len(sin_explicar):
                st.error(
                    f"{len(sin_explicar)} fila(s) **sin explicación automática** -- no encajan "
                    "en ningún patrón conocido (ni redondeo, ni reclasificación manual). "
                    "Revisar caso por caso, podría ser un problema nuevo."
                )
            else:
                st.success(
                    "Todas las discrepancias de este periodo tienen una explicación conocida "
                    "(redondeo o falta de póliza capturada) -- ninguna parece requerir "
                    "revisión urgente."
                )

            st.dataframe(
                no_match[["origen", "folio", "grd_id", "importe", "cargo", "abono", "neto",
                          "diferencia", "motivo"]],
                width="stretch", height=280, hide_index=True,
            )
        else:
            st.success("Todo cuadra en el periodo seleccionado -- 0 discrepancias.")

        st.caption(
            "`Ruido de redondeo`: diferencia ≤ $5, atribuible a centavos de conversión de "
            "moneda o reparto entre cuentas, no a un error real. `Reclasificación/ajuste "
            "manual con Importe negativo`: solo aparece cuando un folio de este tipo no "
            "tiene ninguna línea de póliza capturada en absoluto (nada que ajustar) -- en "
            "el resto de los casos, v0.4.2 ya los resuelve. Ver docs/15_hito_v0_4_reversiones.md."
        )

    with tab_docs:
        for fname in ("16_hito_v0_4_2_abono_gastos_a_cuenta.md", "15_hito_v0_4_reversiones.md",
                      "14_hito_v0_4.md", "13_hito_v0_3.md", "12_hito_v0_2.md"):
            path = os.path.join(DOCS_DIR, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    st.markdown(f.read())


def render_v0_5():
    st.title("Layout de registro de gastos · v0.5")
    st.caption(
        "Versión SQL pura (una sola consulta, sin post-proceso en pandas) -- basada en "
        "el query de otro programador que el usuario compartió, simplificada y con los "
        "casos especiales de v0.2-v0.4.2 hardcodeados. Atribuye Cargo/Abono a nivel de "
        "FOLIO COMPLETO (como v0.2), no por documento individual (como v0.4.2) -- más "
        "simple de mantener, pero pierde el desglose fino en folios multi-documento. "
        "99.90% de comprobación en todo 2025 (15 de 15,047 filas sin cuadrar, todas de "
        "redondeo) en solo ~22s. Ver docs/17_hito_v0_5_sql.md y sql/layout_gastos_v0_5.sql."
    )

    with st.sidebar:
        st.subheader("Periodo")
        c1, c2 = st.columns(2)
        start = c1.date_input("Desde", value=date(2026, 1, 1), key="v05_start")
        end_incl = c2.date_input("Hasta", value=date(2026, 1, 31), key="v05_end")
        st.caption("Empresa: 0001 - TRIVASA S.A. DE C.V. (fijo)")

    if start > end_incl:
        st.error("La fecha 'Desde' debe ser anterior o igual a 'Hasta'.")
        return

    df = load_data_v0_5(str(start), str(end_incl))
    agg, resumen = validar_v0_5(df)

    with st.sidebar:
        st.subheader("Filtros")
        origenes = sorted(df["origen"].fillna("(vacío)").replace("", "(vacío)").unique().tolist())
        origen_sel = st.multiselect(
            "Origen (Gr_Tabla)", origenes, default=[],
            help="CONSUMO_INTERNO y GASTO_REGISTRO_NOMINA vienen sin Cargo/Abono/Cuenta "
                 "por diseño -- no se les intenta ningún join de póliza.",
        )
        solo_con_comprobante = st.checkbox("Solo con comprobante (CFDI)", value=False)

    df_f = df.copy()
    df_f["origen_mostrar"] = df_f["origen"].fillna("(vacío)").replace("", "(vacío)")
    if origen_sel:
        df_f = df_f[df_f["origen_mostrar"].isin(origen_sel)]
    if solo_con_comprobante:
        df_f = df_f[df_f["tiene_comprobante"] == 1]

    importe_dedup = df_f.drop_duplicates(subset=["folio", "grd_id"])["importe"].sum()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Folios", f"{df_f['folio'].nunique():,}")
    k2.metric("Importe", f"$ {importe_dedup:,.2f}")
    k3.metric("Cargo (póliza)", f"$ {df_f['cargo'].sum():,.2f}")
    k4.metric("Abono (póliza)", f"$ {df_f['abono'].sum():,.2f}")

    tab_reporte, tab_comprobacion, tab_docs = st.tabs(["Reporte", "Comprobación", "Documentación"])

    columnas = ["folio", "grd_id", "fecha_registro", "fecha_documento", "referencia",
                "proveedor_clave", "proveedor_nombre", "comentario", "moneda",
                "tipo_cambio", "importe", "origen", "cuenta_registro",
                "nombre_cuenta_registro", "cargo", "abono", "tiene_comprobante", "uuid"]

    with tab_reporte:
        st.dataframe(df_f[columnas], width="stretch", height=520, hide_index=True)
        st.caption(f"{len(df_f):,} filas de {len(df):,} totales en el periodo")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_f[columnas].to_excel(writer, index=False, sheet_name="Layout_v0_5")
        st.download_button(
            "Descargar Excel",
            data=buf.getvalue(),
            file_name=f"layout_gastos_v0_5_{start}_{end_incl}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with tab_comprobacion:
        st.markdown(
            "Comprobación por origen: **Cargo − Abono debe igualar el Importe**. "
            "`CONSUMO_INTERNO`/`GASTO_REGISTRO_NOMINA` no aplican (sin join, por diseño). "
            "A diferencia de v0.4.2, aquí no hay columna `metodo_atribucion` -- el Cargo/"
            "Abono siempre está a nivel folio completo (pegado al último documento)."
        )
        st.dataframe(resumen, width="stretch", hide_index=True)

        no_match = agg[
            (~agg["origen"].isin(ORIGENES_SIN_JOIN_V0_5)) & (agg["diferencia"].abs() > TOLERANCIA_V0_5)
        ].sort_values("diferencia", key=abs, ascending=False)

        st.markdown(f"### {len(no_match):,} de {len(agg):,} filas no cuadran (diferencia > $0.50)")

        if len(no_match):
            resumen_motivo = (
                no_match["motivo"].value_counts().rename_axis("Motivo").reset_index(name="Filas")
            )
            st.dataframe(resumen_motivo, width="stretch", hide_index=True)

            sin_explicar = no_match[no_match["motivo"] == "Sin explicación automática -- revisar a mano"]
            if len(sin_explicar):
                st.error(
                    f"{len(sin_explicar)} fila(s) **sin explicación automática** -- no encajan "
                    "en ningún patrón conocido (ni redondeo, ni reclasificación manual). "
                    "Revisar caso por caso, podría ser un problema nuevo."
                )
            else:
                st.success(
                    "Todas las discrepancias de este periodo tienen una explicación conocida "
                    "(redondeo) -- ninguna parece requerir revisión urgente."
                )

            st.dataframe(
                no_match[["origen", "folio", "grd_id", "importe", "cargo", "abono", "neto",
                          "diferencia", "motivo"]],
                width="stretch", height=280, hide_index=True,
            )
        else:
            st.success("Todo cuadra en el periodo seleccionado -- 0 discrepancias.")

        st.caption(
            "`Ruido de redondeo`: diferencia ≤ $5, atribuible a centavos, no a un error "
            "real. Ver docs/17_hito_v0_5_sql.md."
        )

    with tab_docs:
        for fname in ("17_hito_v0_5_sql.md", "16_hito_v0_4_2_abono_gastos_a_cuenta.md",
                      "15_hito_v0_4_reversiones.md"):
            path = os.path.join(DOCS_DIR, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    st.markdown(f.read())
        sql_path = os.path.join(os.path.dirname(__file__), "sql", "layout_gastos_v0_5.sql")
        if os.path.exists(sql_path):
            with open(sql_path, encoding="utf-8") as f:
                with st.expander("sql/layout_gastos_v0_5.sql (listo para entregar)", expanded=False):
                    st.code(f.read(), language="sql")


def render_v0_5_1():
    st.title("Layout de registro de gastos · v0.5.1")
    st.caption(
        "Como v0.5, pero reparte el Cargo/Abono ENTRE los documentos de un folio "
        "multi-documento usando Gasto_Registro_Control (en vez de concentrarlo todo en "
        "el último) -- mismo mecanismo de v0.4.2 (emparejamiento por valor + reparto "
        "proporcional), sin la salvaguarda de re-enrutado (no hace falta una vez que se "
        "empareja por valor). Mismo resultado de comprobación que v0.5 (99.90% en 2025), "
        "y ya casi la misma velocidad tras materializar las CTEs pesadas en tablas "
        "#temporales (~24s para todo 2025, vs 22s de v0.5 -- antes tardaba 14 minutos "
        "porque SQL Server recalculaba el join de póliza 5 veces por CTEs no "
        "materializadas). Ver docs/18_hito_v0_5_1_granularidad.md."
    )

    with st.sidebar:
        st.subheader("Periodo")
        c1, c2 = st.columns(2)
        start = c1.date_input("Desde", value=date(2026, 1, 1), key="v051_start")
        end_incl = c2.date_input("Hasta", value=date(2026, 1, 31), key="v051_end")
        st.caption("Empresa: 0001 - TRIVASA S.A. DE C.V. (fijo)")

    if start > end_incl:
        st.error("La fecha 'Desde' debe ser anterior o igual a 'Hasta'.")
        return

    df = load_data_v0_5_1(str(start), str(end_incl))
    agg, resumen = validar_v0_5_1(df)

    with st.sidebar:
        st.subheader("Filtros")
        origenes = sorted(df["origen"].fillna("(vacío)").replace("", "(vacío)").unique().tolist())
        origen_sel = st.multiselect(
            "Origen (Gr_Tabla)", origenes, default=[],
            help="CONSUMO_INTERNO y GASTO_REGISTRO_NOMINA vienen sin Cargo/Abono/Cuenta "
                 "por diseño -- no se les intenta ningún join de póliza.",
        )
        solo_con_comprobante = st.checkbox("Solo con comprobante (CFDI)", value=False)

    df_f = df.copy()
    df_f["origen_mostrar"] = df_f["origen"].fillna("(vacío)").replace("", "(vacío)")
    if origen_sel:
        df_f = df_f[df_f["origen_mostrar"].isin(origen_sel)]
    if solo_con_comprobante:
        df_f = df_f[df_f["tiene_comprobante"] == 1]

    importe_dedup = df_f.drop_duplicates(subset=["folio", "grd_id"])["importe"].sum()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Folios", f"{df_f['folio'].nunique():,}")
    k2.metric("Importe", f"$ {importe_dedup:,.2f}")
    k3.metric("Cargo (póliza)", f"$ {df_f['cargo'].sum():,.2f}")
    k4.metric("Abono (póliza)", f"$ {df_f['abono'].sum():,.2f}")

    tab_reporte, tab_comprobacion, tab_docs = st.tabs(["Reporte", "Comprobación", "Documentación"])

    columnas = ["folio", "grd_id", "fecha_registro", "fecha_documento", "referencia",
                "proveedor_clave", "proveedor_nombre", "comentario", "moneda",
                "tipo_cambio", "importe", "origen", "cuenta_registro",
                "nombre_cuenta_registro", "cargo", "abono", "tiene_comprobante", "uuid"]

    with tab_reporte:
        st.dataframe(df_f[columnas], width="stretch", height=520, hide_index=True)
        st.caption(f"{len(df_f):,} filas de {len(df):,} totales en el periodo")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_f[columnas].to_excel(writer, index=False, sheet_name="Layout_v0_5_1")
        st.download_button(
            "Descargar Excel",
            data=buf.getvalue(),
            file_name=f"layout_gastos_v0_5_1_{start}_{end_incl}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with tab_comprobacion:
        st.markdown(
            "Comprobación por origen: **Cargo − Abono debe igualar el Importe**. "
            "`CONSUMO_INTERNO`/`GASTO_REGISTRO_NOMINA` no aplican (sin join, por diseño)."
        )
        st.dataframe(resumen, width="stretch", hide_index=True)

        no_match = agg[
            (~agg["origen"].isin(ORIGENES_SIN_JOIN_V0_5_1)) & (agg["diferencia"].abs() > TOLERANCIA_V0_5_1)
        ].sort_values("diferencia", key=abs, ascending=False)

        st.markdown(f"### {len(no_match):,} de {len(agg):,} filas no cuadran (diferencia > $0.50)")

        if len(no_match):
            resumen_motivo = (
                no_match["motivo"].value_counts().rename_axis("Motivo").reset_index(name="Filas")
            )
            st.dataframe(resumen_motivo, width="stretch", hide_index=True)

            sin_explicar = no_match[no_match["motivo"] == "Sin explicación automática -- revisar a mano"]
            if len(sin_explicar):
                st.error(
                    f"{len(sin_explicar)} fila(s) **sin explicación automática** -- no encajan "
                    "en ningún patrón conocido (ni redondeo, ni reclasificación manual). "
                    "Revisar caso por caso, podría ser un problema nuevo."
                )
            else:
                st.success(
                    "Todas las discrepancias de este periodo tienen una explicación conocida "
                    "(redondeo) -- ninguna parece requerir revisión urgente."
                )

            st.dataframe(
                no_match[["origen", "folio", "grd_id", "importe", "cargo", "abono", "neto",
                          "diferencia", "motivo"]],
                width="stretch", height=280, hide_index=True,
            )
        else:
            st.success("Todo cuadra en el periodo seleccionado -- 0 discrepancias.")

        st.caption(
            "`Ruido de redondeo`: diferencia ≤ $5, atribuible a centavos, no a un error "
            "real. Ver docs/18_hito_v0_5_1_granularidad.md."
        )

    with tab_docs:
        for fname in ("18_hito_v0_5_1_granularidad.md", "17_hito_v0_5_sql.md",
                      "16_hito_v0_4_2_abono_gastos_a_cuenta.md", "15_hito_v0_4_reversiones.md"):
            path = os.path.join(DOCS_DIR, fname)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    st.markdown(f.read())
        sql_path = os.path.join(os.path.dirname(__file__), "sql", "layout_gastos_v0_5_1.sql")
        if os.path.exists(sql_path):
            with open(sql_path, encoding="utf-8") as f:
                with st.expander("sql/layout_gastos_v0_5_1.sql (listo para entregar)", expanded=False):
                    st.code(f.read(), language="sql")


def render_v1_1():
    st.title("Layout de registro de gastos")
    st.caption(f"Version {VERSION} · auditoria Contabilidad y Finanzas (Bates y Asociados)")

    with st.sidebar:
        st.subheader("Periodo")
        c1, c2 = st.columns(2)
        start = c1.date_input("Desde", value=date(2025, 1, 1), key="lg_start")
        end = c2.date_input("Hasta (excl.)", value=date(2025, 2, 1), key="lg_end")
        vista = st.radio(
            "Vista",
            ["Agrupada por cuenta contable", "Detalle (base)"],
            help="La vista agrupada suma Cargo/Abono por cuenta contable, colapsando "
                 "centro de costo -- corrige el bug documentado en docs/01.",
        )
        st.divider()
        st.caption("Fuente: Gasto_Registro (TRIVASADB3). Excluye CONSUMO_INTERNO y "
                   "GASTO_REGISTRO_NOMINA por diseno (ver docs/00).")

    if start >= end:
        st.error("La fecha 'Desde' debe ser anterior a 'Hasta'.")
        return

    header, poliza, detail = load_data(str(start), str(end))

    total_subtotal = header["Subtotal Neto"].sum()
    total_cargo = poliza["Cargo"].sum()
    total_abono = poliza["Abono"].sum()
    total_neto = total_cargo - total_abono
    brecha = (total_neto - total_subtotal) / total_subtotal * 100 if total_subtotal else 0
    n_folios = header["Operacion (ID)"].nunique()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Folios de gasto", f"{n_folios:,}")
    k2.metric("Subtotal Neto (cabecera)", f"$ {total_subtotal:,.2f}")
    k3.metric("Cargo - Abono (poliza)", f"$ {total_neto:,.2f}")
    k4.metric("Brecha de comprobacion", f"{brecha:+.2f}%",
              help="(Cargo - Abono) vs Subtotal Neto. Ver docs/03_hito_v1.md para el detalle de la "
                   "reconciliacion y los casos residuales conocidos.")

    tab_reporte, tab_comprobacion, tab_docs = st.tabs(["Reporte", "Comprobacion", "Documentacion"])

    with tab_reporte:
        if vista.startswith("Agrupada"):
            df = group_by_cuenta_contable(header, poliza)
        else:
            df = detail

        proveedores = sorted(df["Nombre del proveedor"].dropna().unique().tolist())
        filtro_prov = st.multiselect("Filtrar por proveedor", proveedores)
        if filtro_prov:
            df = df[df["Nombre del proveedor"].isin(filtro_prov)]

        st.dataframe(df, width='stretch', height=520)
        st.caption(f"{len(df):,} filas")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Layout")
        st.download_button(
            "Descargar Excel",
            data=buf.getvalue(),
            file_name=f"layout_gastos_{VERSION}_{start}_{end}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with tab_comprobacion:
        st.markdown(
            "Comprobacion pedida por el requerimiento: *la suma de cargos y abonos del reporte "
            "debe ser igual al reporte nativo de gastos*. Aqui se compara `Subtotal Neto` "
            "(cabecera, `Gasto_Registro_Documento`) contra `Cargo - Abono` (poliza) por operacion."
        )
        hs = header.groupby("Operacion (ID)")["Subtotal Neto"].sum().rename("subtotal_neto")
        ps = poliza.groupby("Operacion (ID)")[["Cargo", "Abono"]].sum()
        cmp = pd.concat([hs, ps], axis=1).fillna(0)
        cmp["neto_poliza"] = cmp["Cargo"] - cmp["Abono"]
        cmp["diferencia"] = cmp["neto_poliza"] - cmp["subtotal_neto"]
        cmp = cmp.reset_index().sort_values("diferencia", key=abs, ascending=False)
        st.dataframe(cmp.head(100), width='stretch', height=400)
        st.caption(f"{(cmp['diferencia'].abs() > 1).sum()} folios con diferencia > $1 de "
                   f"{len(cmp)} totales.")

    with tab_docs:
        for fname in sorted(os.listdir(DOCS_DIR)):
            if fname.endswith(".md"):
                with open(os.path.join(DOCS_DIR, fname), encoding="utf-8") as f:
                    with st.expander(fname, expanded=False):
                        st.markdown(f.read())


if _is_standalone():
    st.set_page_config(page_title="Layout de Gastos", layout="wide")

with st.sidebar:
    version_sel = st.radio(
        "Versión del reporte",
        [
            "v0.1 · Reporte nativo (por documento)",
            "v0.2 · + Cargo/Abono/Cuenta contable",
            "v0.3 · Atribución exacta por CECO",
            "v0.4.1 · Reparto proporcional + salvaguarda",
            "v0.4.2 · + Reversiones contables",
            "v0.5 · SQL puro (folio completo)",
            "v0.5.1 · SQL puro (por documento)",
            "v1.1 · Detalle + cuenta contable",
        ],
        index=0,
    )
    st.divider()

if version_sel.startswith("v0.1"):
    render_v0_1()
elif version_sel.startswith("v0.2"):
    render_v0_2()
elif version_sel.startswith("v0.3"):
    render_v0_3()
elif version_sel.startswith("v0.4.1"):
    render_v0_4_1()
elif version_sel.startswith("v0.4.2"):
    render_v0_4_2()
elif version_sel.startswith("v0.5.1"):
    render_v0_5_1()
elif version_sel.startswith("v0.5"):
    render_v0_5()
else:
    render_v1_1()
