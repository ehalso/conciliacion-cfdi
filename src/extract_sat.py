"""Extracción del lado SAT: Postgres raw_sat.cfdi_recibidos / cfdi_emitidos
vía el bridge.

Columnas reales confirmadas en vivo (information_schema, 2026-09-07) —
idénticas en ambas tablas: uuid, fecha_emision, rfc_emisor, nombre_emisor,
tipo_comprobante, subtotal, iva, total, uso_cfdi, metodo_pago, forma_pago,
periodo, archivo_origen, fecha_carga, rfc_receptor, direccion.

Nota (corregida 2026-09-10, ver `docs/schema/calidad-de-datos.md` en
trivasa-context): `iva` es SOLO el IVA trasladado (código SAT `002`), no
`TotalImpuestosTrasladados` del CFDI -- esa lectura de 2026-09-07 se validó
contra una muestra sin CFDI de combustible, donde `ieps_trasladado` vale 0
y por eso la distinción no se notaba. Confirmado con CFDI que sí traen
IEPS: `iva + ieps_trasladado = total - subtotal`, siempre. No restar
`ieps_trasladado` de `iva` para obtener el IVA trasladado -- `iva` ya lo
es. Ver `conciliacion_xml_lib.py` (recibidos/nivel_documento) para el caso
real que expuso el error (restar daba negativo en CFDI de combustible).
"""
from __future__ import annotations

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote

PAGE_SIZE = 2000

COLUMNS = [
    "uuid", "fecha_emision", "rfc_emisor", "nombre_emisor", "tipo_comprobante",
    "subtotal", "iva", "total", "periodo", "rfc_receptor",
    # Agregados 2026-09-10: parseados ya en la ingesta (raw_sat_xml, ctunlinux)
    # a partir del mismo XML que antes había que volver a bajar y parsear de
    # Comprobante_Digital.Cd_XML en cada corrida de baseline_universal.py — ver
    # docstring de cfdi_parser.py para el detalle de cada campo.
    "descuento", "ieps_trasladado", "impuestos_locales_trasladados",
    "impuestos_locales_retenidos", "total_impuestos_retenidos",
]

# Columnas agregadas 2026-09-10 (segunda tanda), pedidas puntualmente para
# poder retirar `parsear_cfdi()` de `recibidos/nivel_documento/
# conciliacion_xml_lib.py` — ahí se explican los descuadres que SÍ requieren
# esta granularidad (complemento Pagos de un REP, ValesDeDespensa, IVA/ISR
# retenido por separado) y que `total_impuestos_retenidos` por sí solo no
# resuelve. No se agregan a `COLUMNS` para no exigirlas también del lado de
# `cfdi_emitidos` en los llamadores existentes que no las necesitan.
COLUMNS_XML_EXTRA = [
    "ret_iva", "ret_isr", "pagos_monto_total", "pagos_iva_total",
    "pagos_dr_uuids", "pagos_dr_pagado", "vales_despensa_total",
    "vales_despensa_n_trab", "complementos", "base_exenta",
]
_TEXT_COLS = {"uuid", "rfc_emisor", "nombre_emisor", "tipo_comprobante", "periodo",
              "rfc_receptor", "pagos_dr_uuids", "complementos"}

TABLAS_VALIDAS = {"cfdi_recibidos", "cfdi_emitidos"}


def _coerce(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    df["uuid"] = df["uuid"].str.upper()
    for f in cols:
        if f in ("uuid", "fecha_emision") or f in _TEXT_COLS:
            continue
        df[f] = pd.to_numeric(df[f], errors="coerce").fillna(0)
    for f in _TEXT_COLS & set(cols) - {"uuid"}:
        df[f] = df[f].astype("string").fillna("")
    return df.rename(columns={"fecha_emision": "fecha"})


def extract_sat_cfdi(tabla: str = "cfdi_recibidos", periodo=None, periodos=None,
                      extra_columns: list[str] | None = None) -> pd.DataFrame:
    """Trae todos los CFDI (recibidos o emitidos) de uno o varios periodos
    ('YYYY-MM'), de `raw_sat.<tabla>`.

    Pasa `periodo` para uno solo, o `periodos` (lista) para varios juntos
    (ej. un trimestre) — se combinan en un solo DataFrame con un `WHERE
    periodo IN (...)`. `extra_columns` agrega columnas de `raw_sat` por
    encima de las base (ej. `COLUMNS_XML_EXTRA`), sin afectar a los
    llamadores que no las piden.

    Cada tabla de `raw_sat` ya viene filtrada por dirección (recibido vs
    emitido) por diseño del ELT — no se filtra aquí por rfc_emisor/receptor.
    """
    if tabla not in TABLAS_VALIDAS:
        raise ValueError(f"tabla debe ser una de {TABLAS_VALIDAS}, se recibió {tabla!r}")
    if periodos is None:
        if periodo is None:
            raise ValueError("hay que pasar periodo o periodos")
        periodos = [periodo]

    cols = COLUMNS + list(extra_columns or [])
    where_periodos = ", ".join(sql_quote(p) for p in periodos)

    all_rows: list[dict] = []
    offset = 0
    cols_sql = ", ".join(cols)
    while True:
        sql = (
            f"SELECT {cols_sql} FROM raw_sat.{tabla} "
            f"WHERE periodo IN ({where_periodos}) "
            f"ORDER BY uuid LIMIT {PAGE_SIZE} OFFSET {offset}"
        )
        result = run_query("postgres_dw", sql)
        page = rows_as_dicts(result)
        all_rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    df = pd.DataFrame(all_rows, columns=cols)
    if df.empty:
        return df
    return _coerce(df, cols)


def extract_sat_por_uuid(tabla: str, uuids: list[str],
                          extra_columns: list[str] | None = None) -> pd.DataFrame:
    """Trae `raw_sat.<tabla>` para una lista puntual de UUID, sin acotar por
    periodo — para cuando el universo no viene delimitado por mes (ej. una
    componente conexa de conciliación que arrastra CFDI de otros periodos,
    ver `cerrar_universo()` en conciliacion_xml_lib.py). Se pagina en lotes
    de 500 UUID por consulta, como ya hacían los extractores de mpro."""
    if tabla not in TABLAS_VALIDAS:
        raise ValueError(f"tabla debe ser una de {TABLAS_VALIDAS}, se recibió {tabla!r}")
    cols = COLUMNS + list(extra_columns or [])
    cols_sql = ", ".join(cols)
    vals = sorted({u.strip().upper() for u in uuids if u and str(u).strip()})
    if not vals:
        return pd.DataFrame(columns=cols)

    all_rows: list[dict] = []
    for i in range(0, len(vals), 500):
        lote = ", ".join(sql_quote(u) for u in vals[i:i + 500])
        sql = f"SELECT {cols_sql} FROM raw_sat.{tabla} WHERE UPPER(uuid) IN ({lote})"
        all_rows.extend(rows_as_dicts(run_query("postgres_dw", sql)))

    df = pd.DataFrame(all_rows, columns=cols)
    if df.empty:
        return df
    df = _coerce(df, cols)
    return df.drop_duplicates(subset=["uuid"])


def extract_sat_recibidos(periodo=None, periodos=None) -> pd.DataFrame:
    """Compatibilidad hacia atrás: equivalente a
    extract_sat_cfdi('cfdi_recibidos', ...)."""
    return extract_sat_cfdi("cfdi_recibidos", periodo=periodo, periodos=periodos)


def extract_sat_emitidos(periodo=None, periodos=None) -> pd.DataFrame:
    """Equivalente a extract_sat_cfdi('cfdi_emitidos', ...)."""
    return extract_sat_cfdi("cfdi_emitidos", periodo=periodo, periodos=periodos)
