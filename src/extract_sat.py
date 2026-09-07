"""Extracción del lado SAT: Postgres raw_sat.cfdi_recibidos vía el bridge.

Columnas reales confirmadas en vivo (information_schema, 2026-09-07):
uuid, fecha_emision, rfc_emisor, nombre_emisor, tipo_comprobante, subtotal,
iva, total, uso_cfdi, metodo_pago, forma_pago, periodo, archivo_origen,
fecha_carga, rfc_receptor, direccion.

Nota: `iva` es un solo campo — validado empíricamente 2026-09-07 (periodo
2026-08) que es TotalImpuestosTrasladados del XML tal cual, SIN restar
TotalImpuestosRetenidos. Ver extract_mpro.py.
"""
from __future__ import annotations

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote

PAGE_SIZE = 2000

COLUMNS = [
    "uuid", "fecha_emision", "rfc_emisor", "nombre_emisor", "tipo_comprobante",
    "subtotal", "iva", "total", "periodo", "rfc_receptor",
]


def extract_sat_recibidos(periodo=None, periodos=None) -> pd.DataFrame:
    """Trae todos los CFDI recibidos de uno o varios periodos ('YYYY-MM').

    Pasa `periodo` para uno solo, o `periodos` (lista) para varios juntos
    (ej. un trimestre) — se combinan en un solo DataFrame con un `WHERE
    periodo IN (...)`.

    `raw_sat.cfdi_recibidos` ya es solo recibidos por diseño del ELT (loader
    dedicado a recibidos) — no se filtra por rfc_receptor aquí.
    """
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
            f"SELECT {cols_sql} FROM raw_sat.cfdi_recibidos "
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
