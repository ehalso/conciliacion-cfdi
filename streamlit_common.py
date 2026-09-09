"""Componentes compartidos entre los reportes Streamlit de conciliación:

- `streamlit_app_conciliacion.py` (TEMP-1: el reporte original, solo
  conciliación — sin detalle de línea).
- `streamlit_app_conciliacion_detalle.py` (TEMP-2: Detalle como primera
  pestaña, Conciliación como segunda).

Carga de datos cacheada, helpers de filtro/descarga y los diccionarios de
columnas para mostrar. La lógica de negocio (`calcular` / `detalle_regla1`)
vive en `baseline_universal.py` — este módulo solo la envuelve para
Streamlit, no la duplica.
"""
import io
import os
import sys

import pandas as pd
import streamlit as st

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))

from baseline_universal import calcular, detalle_regla1  # noqa: E402

# Confirmado en src/config.py: mientras MPRO_TARGET sea mssql_205, el rango
# validado es enero-junio 2026 (ver PROGRESS.md).
PERIODOS_DISPONIBLES = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]

# Única vía con detalle de línea implementado por ahora (ver
# baseline_universal.detalle_regla1 y docs/hallazgos.md punto 27) — las
# otras diez vías jalan líneas de documentos que no son propios del CFDI
# (folios hermanos, póliza de banco, cheque agrupado) y quedan pendientes.
VIA_CON_DETALLE = "cargo = base CFDI"

COLS_DISPLAY = {
    "uuid": "UUID CFDI",
    "periodo": "Periodo",
    "fecha": "Fecha",
    "rfc_emisor": "RFC Emisor",
    "nombre_emisor": "Proveedor",
    "origenes": "Origen(es) en mpro",
    "subtotal": "Subtotal CFDI",
    "iva": "IVA CFDI",
    "total": "Total CFDI",
    "cargo_agregado": "Cargo agregado",
    "diferencia": "Diferencia vs Subtotal",
    "cuadra_via": "Via de cuadre",
    "motivo_pendiente": "Motivo pendiente",
}

DETALLE_COLS_DISPLAY = {
    "uuid": "UUID CFDI",
    "periodo": "Periodo",
    "rfc_emisor": "RFC Emisor",
    "nombre_emisor": "Proveedor",
    "origen": "Origen",
    "documento": "Documento mpro",
    "Pl_Folio": "Póliza",
    "tipo": "Cargo/Abono",
    "importe": "Importe línea",
    "cuenta": "Cuenta contable",
    "cuenta_descripcion": "Descripción cuenta",
    "concepto": "Concepto",
    "centro_costo": "Centro de costo",
    "subtotal": "Subtotal CFDI",
    "cargo_agregado": "Cargo agregado (CFDI)",
}

COLS_BASE = ["uuid", "periodo", "fecha", "rfc_emisor", "nombre_emisor", "origenes",
             "subtotal", "iva", "total", "cargo_agregado", "diferencia"]

# Igual que cols_base pero sin las columnas que no aplican a un CFDI que
# nunca se etiquetó en mpro (no tiene origen, ni cargo, ni diferencia).
COLS_NO_EN_MPRO = ["uuid", "periodo", "fecha", "rfc_emisor", "nombre_emisor", "subtotal", "iva", "total"]


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_periodo(periodo: str) -> pd.DataFrame:
    """Corre calcular() de baseline_universal.py para un solo periodo.
    Cacheado por periodo (no por la seleccion completa): cambiar de mes en
    el multiselect no vuelve a calcular los que ya estaban."""
    _, _, resumen = calcular(periodo)
    resumen = resumen.copy()
    resumen["periodo"] = periodo
    return resumen


def cargar_periodos(periodos: tuple[str, ...]) -> pd.DataFrame:
    partes = []
    progreso = st.progress(0.0)
    for i, p in enumerate(periodos, start=1):
        progreso.progress((i - 1) / len(periodos), text=f"Consultando la base (conexión directa): {p}...")
        partes.append(cargar_periodo(p))
    progreso.empty()
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_detalle_periodo(periodo: str) -> pd.DataFrame:
    """Detalle de línea (regla 1 únicamente) para TODAS las CFDI conciliadas
    por esa vía en el periodo — carga completa/eager. Reusa `cargar_periodo`
    (ya cacheado) para no volver a correr calcular(); solo dispara consultas
    nuevas para las líneas."""
    resumen = cargar_periodo(periodo)
    universo = resumen["monetario"] & resumen["en_mpro"]
    regla1 = resumen[universo & (resumen["cuadra_via"] == VIA_CON_DETALLE)]
    detalle = detalle_regla1(regla1["uuid"].tolist())
    detalle["periodo"] = periodo
    return detalle


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_detalle_uuid(uuid: str) -> pd.DataFrame:
    """Detalle de línea para un solo CFDI — drill-down perezoso, sin cargar
    el resto del periodo."""
    return detalle_regla1([uuid])


def descarga_excel(df: pd.DataFrame, cols: list[str], nombre: str, cols_display: dict = COLS_DISPLAY) -> bytes:
    buf = io.BytesIO()
    tabla = df[cols].rename(columns=cols_display)
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        tabla.to_excel(writer, index=False, sheet_name=nombre[:31])
    return buf.getvalue()


def aplica_filtros(df: pd.DataFrame, origenes_sel: list[str], busca: str) -> pd.DataFrame:
    d = df.copy()
    if origenes_sel:
        d = d[d["origenes"].fillna("").apply(lambda s: any(o in s for o in origenes_sel))]
    if busca:
        q = busca.strip().upper()
        d = d[
            d["rfc_emisor"].astype(str).str.upper().str.contains(q, na=False)
            | d["nombre_emisor"].astype(str).str.upper().str.contains(q, na=False)
            | d["uuid"].astype(str).str.upper().str.contains(q, na=False)
        ]
    return d


def calcular_universo(resumen: pd.DataFrame) -> pd.DataFrame:
    """CFDI con valor monetario real Y con al menos una etiqueta en mpro —
    el universo que compara `baseline_universal.calcular()` (conciliados +
    pendientes)."""
    return resumen[resumen["monetario"] & resumen["en_mpro"]].copy()


def calcular_no_en_mpro(resumen: pd.DataFrame) -> pd.DataFrame:
    """CFDI con valor monetario real que NUNCA aparecen etiquetados en
    `Comprobante_Digital` — quedan fuera del universo de conciliados/
    pendientes, no porque no cuadren sino porque no hay nada contra qué
    compararlos."""
    return resumen[resumen["monetario"] & ~resumen["en_mpro"]].copy()


def render_kpis(universo: pd.DataFrame, universo_f: pd.DataFrame,
                 conciliados_f: pd.DataFrame, pendientes_f: pd.DataFrame,
                 no_en_mpro: pd.DataFrame) -> None:
    """Fila de métricas: universo completo (sin filtrar) -> universo
    filtrado -> conciliados -> pendientes, y montos conciliado/pendiente.

    "Universo completo" incluye TODAS las CFDI con valor monetario del/los
    periodo(s) cargado(s), estén o no en mpro — `universo` (en_mpro) +
    `no_en_mpro`. "Universo filtrado" y de ahí para abajo (conciliados/
    pendientes) siguen siendo solo sobre las que sí están en mpro, que es
    el universo que compara `calcular()`."""
    total_completo = len(universo) + len(no_en_mpro)
    total_f = len(universo_f)
    n_conc = len(conciliados_f)
    n_pend = len(pendientes_f)
    monto_conc = conciliados_f["subtotal_ajustado"].sum() if "subtotal_ajustado" in conciliados_f else 0.0
    monto_pend = pendientes_f["subtotal_ajustado"].sum() if "subtotal_ajustado" in pendientes_f else 0.0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Universo completo (sin filtrar)", f"{total_completo:,}",
               help="Todas las CFDI con valor monetario del/los periodo(s) cargado(s) — estén o no "
                    "etiquetadas en mpro (ver pestaña 'No encontrados en mpro') — antes de aplicar "
                    "los filtros de la barra lateral.")
    k2.metric("Universo filtrado (en mpro)", f"{total_f:,}",
               f"{total_f/total_completo*100:.1f}% del completo" if total_completo else None)
    k3.metric("Conciliados", f"{n_conc:,}", f"{n_conc/total_f*100:.1f}%" if total_f else None)
    k4.metric("Pendientes", f"{n_pend:,}", f"-{n_pend/total_f*100:.1f}%" if total_f else None,
               delta_color="inverse")

    m1, m2 = st.columns(2)
    m1.metric("Monto conciliado (base MXN)", f"${monto_conc:,.0f}",
               help="Suma de la base fiscal ajustada de los CFDI conciliados (filtrado).")
    m2.metric("Monto pendiente (base MXN)", f"${monto_pend:,.0f}",
               help="Suma de la base fiscal ajustada de los CFDI pendientes (filtrado).")


def render_tab_no_en_mpro(no_en_mpro_f: pd.DataFrame, periodos_sel: list[str]) -> None:
    """Pestaña 'No encontrados en mpro': CFDI con valor monetario que jamás
    se etiquetaron en Comprobante_Digital — no llegan ni a conciliados ni a
    pendientes porque no hay nada de mpro contra qué compararlos."""
    st.caption(
        f"{len(no_en_mpro_f):,} CFDI con valor monetario real que no tienen ninguna etiqueta en "
        "`Comprobante_Digital` — no se pudieron comparar contra mpro en absoluto (distinto de "
        "'Pendientes', que sí están en mpro pero no cuadran)."
    )
    if no_en_mpro_f.empty:
        st.info("Ninguno con los filtros actuales.")
        return
    st.dataframe(no_en_mpro_f[COLS_NO_EN_MPRO].rename(columns=COLS_DISPLAY),
                 width="stretch", height=520, hide_index=True)
    st.download_button(
        "Descargar Excel (no encontrados en mpro, filtrado)",
        data=descarga_excel(no_en_mpro_f, COLS_NO_EN_MPRO, "no_en_mpro"),
        file_name=f"no_en_mpro_{'-'.join(periodos_sel)}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
