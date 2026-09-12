"""
Unificación · Conciliación inversa (mpro -> SAT) - reporte Streamlit

El reporte de Recibido (pages/recibido_conciliacion.py) parte del CFDI del
SAT y busca su documento en mpro. Este hace el ejercicio contrario: parte
del layout unificado de mpro (cinco tablas -- Gasto_Registro, Compra,
Compra_Indirecto, Cuenta_X_Pagar, Nota_Credito_Proveedor -- colapsadas a
grano documento en unificacion/layouts_lib.py) y pregunta cuánto de eso
tiene un CFDI Recibido tipo I/E detrás. Mide cuánto de lo que hay en mpro
no tiene nada ligado al SAT, que es donde queda el riesgo fiscal no visto.

Lógica de negocio (carga de los cinco layouts, clasificación contra el SAT,
agregaciones) vive en unificacion/layouts_lib.py -- este script solo la
envuelve en UI, no la duplica. El CLI hermano (unificacion/01_conciliacion_
inversa.py) importa las mismas funciones para su salida a terminal/CSV.

Corre standalone con:
  streamlit run pages/unificacion_conciliacion_inversa.py --server.port 8507
"""
import io
import os
import sys
from datetime import date

import pandas as pd
import streamlit as st

PAGES_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(PAGES_DIR))  # pages/ -> reportes_streamlit/ -> raiz del repo
sys.path.insert(0, os.path.join(REPO_ROOT, "unificacion"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))
sys.path.insert(0, os.path.join(REPO_ROOT, "layout_gastos_poliza"))

from layouts_lib import (  # noqa: E402
    cargar_documentos, cargar_sat, clasificar, cobertura_sat, tabla_por, contar_sin_layout,
    CONCILIADO, SIN_CFDI_POR_DEFINICION)

VERSION = "v1"

COLS_DETALLE = ["origen", "sub_origen", "folio", "fecha", "rfc", "razon_social", "referencia",
                "subtotal_neto", "iva", "total", "uuid", "tipo_comprobante_cfdi",
                "subtotal_sat", "total_sat", "estado"]

COLS_DISPLAY = {
    "origen": "Origen", "sub_origen": "Sub-origen", "folio": "Folio", "fecha": "Fecha",
    "rfc": "RFC", "razon_social": "Proveedor", "referencia": "Referencia",
    "subtotal_neto": "Subtotal (mpro)", "iva": "IVA (mpro)", "total": "Total (mpro)",
    "uuid": "UUID CFDI", "tipo_comprobante_cfdi": "Tipo CFDI",
    "subtotal_sat": "Subtotal (XML/SAT)", "total_sat": "Total (XML/SAT)",
    "estado": "Estado vs SAT",
}


@st.cache_data(ttl=3600, show_spinner="Consultando mpro (5 layouts) y el SAT...")
def cargar_reporte(fecha_ini: str, fecha_fin: str, empresa: str) -> pd.DataFrame:
    """Todo el universo mpro (sin excluir orígenes), ya clasificado contra el
    SAT. Se cachea SIN filtrar -- el toggle de 'excluir sin CFDI por
    definición' y los demás filtros se aplican después sobre este DataFrame,
    para no volver a consultar la base al cambiar un filtro."""
    mpro = cargar_documentos(fecha_ini, fecha_fin, empresa)
    sat = cargar_sat()
    return clasificar(mpro, sat)


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_hueco(fecha_ini: str, fecha_fin: str) -> pd.DataFrame:
    return contar_sin_layout(fecha_ini, fecha_fin)


def descarga_excel(df: pd.DataFrame, cols: list[str], nombre: str) -> bytes:
    buf = io.BytesIO()
    tabla = df[cols].rename(columns=COLS_DISPLAY)
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        tabla.to_excel(writer, index=False, sheet_name=nombre[:31])
    return buf.getvalue()


def render():
    st.title("Unificación · Conciliación inversa (mpro → SAT)")
    st.caption(f"Versión {VERSION} · Cinco layouts de mpro cruzados contra raw_sat.cfdi_recibidos")
    st.markdown(
        "Parte del documento de **mpro** (no del CFDI) y pregunta cuánto tiene un CFDI "
        "Recibido tipo I/E detrás -- el ejercicio contrario a **Recibido › Conciliación**. "
        "Mide el riesgo fiscal no visto: documentos de mpro sin nada ligado al SAT. "
        "Detalle completo en la pestaña **Documentación**."
    )

    with st.sidebar:
        st.subheader("Periodo")
        fecha_ini = st.date_input("Desde", value=date(2026, 2, 1), key="ci_ini")
        fecha_fin = st.date_input("Hasta", value=date(2026, 2, 28), key="ci_fin")
        empresa = st.text_input("Empresa", value="0001", key="ci_empresa")

    if fecha_ini > fecha_fin:
        st.error("La fecha 'Desde' debe ser anterior o igual a 'Hasta'.")
        return

    try:
        df = cargar_reporte(fecha_ini.strftime("%Y%m%d"), fecha_fin.strftime("%Y%m%d"), empresa)
    except Exception as exc:
        st.error(
            "No se pudo consultar la base de datos. Verifica las credenciales en .env "
            "(MSSQL_205_USER/PASSWORD, PG_USER/PG_PASSWORD -- ver .env.example) y que haya "
            "red hacia la LAN de Trivasa y hacia postgres_dw.\n\n"
            f"Error: {exc}"
        )
        return

    if df.empty:
        st.warning("Sin documentos de mpro para el periodo/empresa seleccionados.")
        return

    with st.sidebar:
        st.subheader("Filtros")
        filtrar_definicion = st.checkbox(
            "Excluir orígenes sin CFDI por definición", value=True, key="ci_filtrar",
            help="Quita NOMINA / CONSUMO_INTERNO / GASTO_RECLASIFICACION (Gasto_Registro) -- "
                 "dan 0.0% de conciliación porque no generan CFDI I/E, no porque falte algo.")
        origenes_todos = sorted(df["origen"].dropna().unique().tolist())
        origenes_sel = st.multiselect("Origen", origenes_todos, key="ci_origenes")
        busca = st.text_input("Buscar RFC, proveedor, folio o UUID", key="ci_busca")

    df_f = df.copy()
    if filtrar_definicion:
        excluido = df_f.set_index(["origen", "sub_origen"]).index.isin(SIN_CFDI_POR_DEFINICION)
        df_f = df_f[~excluido]
    if origenes_sel:
        df_f = df_f[df_f["origen"].isin(origenes_sel)]
    if busca:
        q = busca.strip().upper()
        df_f = df_f[
            df_f["rfc"].astype(str).str.upper().str.contains(q, na=False)
            | df_f["razon_social"].astype(str).str.upper().str.contains(q, na=False)
            | df_f["folio"].astype(str).str.upper().str.contains(q, na=False)
            | df_f["uuid"].astype(str).str.upper().str.contains(q, na=False)
        ]

    if df_f.empty:
        st.info("Ningún documento con los filtros actuales.")
        return

    conc_f = df_f[df_f["estado"] == CONCILIADO]
    total_docs = len(df_f)
    importe_total = df_f["total"].sum()
    importe_conc = conc_f["total"].sum()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Documentos (filtrado)", f"{total_docs:,}")
    k2.metric("Conciliados", f"{len(conc_f):,}",
              f"{len(conc_f)/total_docs*100:.1f}%" if total_docs else None)
    k3.metric("Importe mpro", f"${importe_total:,.0f}")
    k4.metric("Importe conciliado", f"${importe_conc:,.0f}",
              f"{importe_conc/importe_total*100:.1f}%" if importe_total else None)

    tab_detalle, tab_estado, tab_origen, tab_sub, tab_sat, tab_hueco, tab_docs = st.tabs(
        ["Detalle", "Estado", "Por origen", "Por sub-origen", "Cobertura SAT",
         "Sin layout (CHEQUE/ANTICIPO_CXP)", "Documentación"])

    with tab_detalle:
        st.caption(
            "Grano documento a documento (1 fila por documento de mpro -- Operacion_ID/Folio "
            "de cada layout), con su estado de conciliación contra el SAT en la columna "
            "**Estado vs SAT** (equivalente al 'tipo de movimiento' de la conciliación: "
            "CONCILIADO / UUID_NO_ES_I_NI_E / UUID_NO_EN_SAT / SIN_UUID_EN_MPRO -- ver "
            "Documentación). Incluye el importe de **ambos lados**: `total` (mpro, el layout "
            "unificado) y `total_sat` (el propio CFDI en `raw_sat.cfdi_recibidos`, solo llega "
            "para documentos con UUID -- vacío en `SIN_UUID_EN_MPRO`)."
        )

        uuids_conc = conc_f.drop_duplicates("uuid")
        s1, s2, s3 = st.columns(3)
        s1.metric("Σ Total mpro (todo lo filtrado)", f"${df_f['total'].sum():,.0f}",
                   help="Suma de `total` sobre TODOS los documentos filtrados (conciliados y no).")
        s2.metric("Σ Total XML/SAT (conciliados, por UUID único)", f"${uuids_conc['total_sat'].sum():,.0f}",
                   help="Suma de `total_sat` -- el propio CFDI, deduplicado por UUID -- para no "
                        "contar dos veces un mismo CFDI cuando varios documentos de mpro le "
                        "apuntan al mismo UUID.")
        s3.metric("UUID únicos conciliados", f"{uuids_conc['uuid'].nunique():,}",
                   help=f"{len(conc_f):,} documentos de mpro conciliados apuntan a estos UUID -- "
                        "la diferencia contra 'documentos conciliados' es cuántos comparten UUID "
                        "con otro documento (ej. una factura consolidada).")

        tabla_detalle = df_f[COLS_DETALLE].sort_values(["origen", "sub_origen", "folio"])
        st.dataframe(tabla_detalle.rename(columns=COLS_DISPLAY), width="stretch", height=560, hide_index=True)
        st.download_button(
            "Descargar Excel (detalle documento a documento, filtrado)",
            data=descarga_excel(df_f, COLS_DETALLE, "detalle"),
            file_name=f"conciliacion_inversa_{fecha_ini}_a_{fecha_fin}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_estado:
        estados = df_f.groupby("estado").agg(docs=("folio", "size"), importe=("total", "sum")).reset_index()
        estados["pct_docs"] = (estados["docs"] / total_docs * 100).round(1) if total_docs else 0.0
        st.dataframe(estados, width="stretch", hide_index=True)
        st.bar_chart(estados.set_index("estado")["docs"])

    with tab_origen:
        por_origen = tabla_por(df_f, ["origen"])
        st.dataframe(por_origen, width="stretch", hide_index=True)

    with tab_sub:
        por_sub = tabla_por(df_f, ["origen", "sub_origen"])
        st.dataframe(por_sub, width="stretch", height=520, hide_index=True)

    with tab_sat:
        periodos = [d.strftime("%Y-%m") for d in
                    pd.period_range(fecha_ini, fecha_fin, freq="M").to_timestamp()]
        try:
            cobertura = cobertura_sat(conc_f, periodos)
            st.dataframe(cobertura, width="stretch", hide_index=True)
            st.caption(
                "Cuánto del universo SAT del periodo (CFDI tipo I/E) alcanza a explicar este "
                "cruce -- comparable en importe (no en % de documentos) contra Recibido › "
                "Conciliación, que parte del CFDI en vez de mpro."
            )
        except Exception as exc:
            st.warning(f"No se pudo calcular la cobertura SAT: {exc}")

    with tab_hueco:
        hueco = cargar_hueco(fecha_ini.strftime("%Y%m%d"), fecha_fin.strftime("%Y%m%d"))
        if hueco.empty:
            st.info("Sin comprobantes de CHEQUE/ANTICIPO_CXP en el periodo.")
        else:
            st.dataframe(hueco, width="stretch", hide_index=True)
        st.caption(
            "CHEQUE y ANTICIPO_CXP no tienen layout todavía -- se cuentan aparte para que el % "
            "de conciliación de arriba se lea contra un universo honesto en vez de esconder el "
            "hueco."
        )

    with tab_docs:
        st.markdown(
            "**Los cinco layouts unificados** (`unificacion/layouts_lib.py`): "
            "`Gasto_Registro` (este repo), `Compra`, `Compra_Indirecto`, `Cuenta_X_Pagar`, "
            "`Nota_Credito_Proveedor` (los cuatro últimos reusan la lógica -- no el código -- "
            "de los reportes de auditoría `rptrv79_*` en `github.com/ehalso/reportes-mpro`, ya "
            "que esos devuelven importes formateados como texto y con fila de TOTAL, que no "
            "sirve para reconciliar).\n\n"
            "**Estados posibles**: `CONCILIADO` (UUID existe en el SAT como I/E), "
            "`UUID_NO_ES_I_NI_E` (el UUID sí está en el SAT pero es P/N/T), `UUID_NO_EN_SAT` "
            "(mpro tiene UUID que el SAT no conoce), `SIN_UUID_EN_MPRO` (documento sin "
            "comprobante digital ligado).\n\n"
            "**Por qué el filtro de orígenes por definición**: `GASTO_REGISTRO_NOMINA` (nómina "
            "timbra CFDI tipo N), `CONSUMO_INTERNO` (movimiento interno, sin proveedor que "
            "facture) y `GASTO_RECLASIFICACION` (reasienta gasto ya registrado, importe neto "
            "cero) dan 0.0% de conciliación sin excepción -- es evidencia de que no pertenecen "
            "al universo, no un hueco por resolver. Desactivar el checkbox para verlos de "
            "todas formas (línea base sin filtrar).\n\n"
            "**Huecos conocidos** (pestaña *Sin layout*): `CHEQUE` y `ANTICIPO_CXP` todavía no "
            "tienen layout hecho -- se miden aparte en vez de esconderse.\n\n"
            "Metodología completa y hallazgos de fidelidad de cada layout en el `README.md` de "
            "`github.com/ehalso/reportes-mpro`. CLI hermano: "
            "`unificacion/01_conciliacion_inversa.py` (misma lógica, salida a terminal/CSV)."
        )


st.set_page_config(page_title="Conciliación inversa (mpro → SAT)", layout="wide")
render()
