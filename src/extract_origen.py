"""Para una lista de UUIDs de CFDI, trae TODAS las filas de
Comprobante_Digital que los referencian (un UUID puede aparecer en más de
un Cd_Tabla — no se colapsa a una sola, a diferencia de extract_mpro.py que
solo necesitaba parsear un XML representativo).

Objetivo: censar el origen real (Cd_Tabla = módulo del ERP, Cd_Documento =
folio del documento en ese módulo) para poder trazar cada CFDI hasta su
documento de mpro y de ahí hasta Poliza_Control/Poliza/Poliza_Detalle.
"""
from __future__ import annotations

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET

BATCH_SIZE = 200

COLUMNS = ["Cd_Timbre_UUID", "Cd_Tabla", "Cd_Documento", "Cd_Tipo_Comprobante_CFDI", "Cd_Monto"]


def extract_origenes_por_uuids(uuids: list[str]) -> pd.DataFrame:
    uuids = [u.upper() for u in uuids]
    rows = []
    cols_sql = ", ".join(COLUMNS)
    for i in range(0, len(uuids), BATCH_SIZE):
        batch = uuids[i : i + BATCH_SIZE]
        in_list = ", ".join(sql_quote(u) for u in batch)
        sql = f"SELECT {cols_sql} FROM Comprobante_Digital WHERE Cd_Timbre_UUID IN ({in_list})"
        result = run_query(MPRO_TARGET, sql)
        rows.extend(rows_as_dicts(result))

    df = pd.DataFrame(rows, columns=COLUMNS)
    if df.empty:
        return df
    df = df.rename(columns={
        "Cd_Timbre_UUID": "uuid",
        "Cd_Tabla": "origen",
        "Cd_Documento": "documento",
        "Cd_Tipo_Comprobante_CFDI": "tipo_comprobante_mpro",
        "Cd_Monto": "cd_monto",
    })
    df["uuid"] = df["uuid"].str.upper()
    return df
