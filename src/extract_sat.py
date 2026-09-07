"""Extracción del lado SAT: Postgres raw_sat.cfdi_recibidos / cfdi_emitidos
vía el bridge.

Columnas reales confirmadas en vivo (information_schema, 2026-09-07) —
idénticas en ambas tablas: uuid, fecha_emision, rfc_emisor, nombre_emisor,
tipo_comprobante, subtotal, iva, total, uso_cfdi, metodo_pago, forma_pago,
periodo, archivo_origen, fecha_carga, rfc_receptor, direccion.

Nota: `iva` es un solo campo — validado empíricamente 2026-09-07 (periodo
2026-08, recibidos) que es TotalImpuestosTrasladados del XML tal cual, SIN
restar TotalImpuestosRetenidos. Ver extract_mpro.py. No revalidado para
emitidos, pero el mismo loader alimenta ambas tablas con el mismo criterio.
"""
from __future__ import annotations

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote

PAGE_SIZE = 2000

COLUMNS = [
    "uuid", "fecha_emision", "rfc_emisor", "nombre_emisor", "tipo_comprobante",
    "subtotal", "iva", "total", "periodo", "rfc_receptor",
]

TABLAS_VALIDAS = {"cfdi_recibidos", "cfdi_emitidos"}


def extract_sat_cfdi(tabla: str = "cfdi_recibidos", periodo=None, periodos=None) -> pd.DataFrame:
    """Trae todos los CFDI (recibidos o emitidos) de uno o varios periodos
    ('YYYY-MM'), de `raw_sat.<tabla>`.

    Pasa `periodo` para uno solo, o `periodos` (lista) para varios juntos
    (ej. un trimestre) — se combinan en un solo DataFrame con un `WHERE
    periodo IN (...)`.

    Cada tabla de `raw_sat` ya viene filtrada por dirección (recibido vs
    emitido) por diseño del ELT — no se filtra aquí por rfc_emisor/receptor.
    """
    if tabla not in TABLAS_VALIDAS:
        raise ValueError(f"tabla debe ser una de {TABLAS_VALIDAS}, se recibió {tabla!r}")
    if periodos is None:
        if periodo is None:
            raise ValueError("hay que pasar periodo o periodos")
        periodos = [periodo]

    where_periodos = ", ".join(sql_quote(p) for p in periodos)

    all_rows: list[dict] = []
    offset = 0
    cols_sql = ", ".join(COLUMNS)
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

    df = pd.DataFrame(all_rows, columns=COLUMNS)
    if df.empty:
        return df

    df["uuid"] = df["uuid"].str.upper()
    for f in ("subtotal", "iva", "total"):
        df[f] = pd.to_numeric(df[f], errors="coerce").fillna(0)
    df = df.rename(columns={"fecha_emision": "fecha"})
    return df


def extract_sat_recibidos(periodo=None, periodos=None) -> pd.DataFrame:
    """Compatibilidad hacia atrás: equivalente a
    extract_sat_cfdi('cfdi_recibidos', ...)."""
    return extract_sat_cfdi("cfdi_recibidos", periodo=periodo, periodos=periodos)


def extract_sat_emitidos(periodo=None, periodos=None) -> pd.DataFrame:
    """Equivalente a extract_sat_cfdi('cfdi_emitidos', ...)."""
    return extract_sat_cfdi("cfdi_emitidos", periodo=periodo, periodos=periodos)
