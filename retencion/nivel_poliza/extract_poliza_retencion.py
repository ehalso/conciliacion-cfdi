"""Extracción SAT para el nivel 3 (granular, por CFDI) de retención de
intereses a prestamistas/inversionistas terceros (`cve_retenc=16`).

⚠️ Gotcha de esquema descubierto 2026-09-10: NO filtrar por
`raw_sat.cfdi_retencion.periodo` para agrupar por mes. Esa columna agrupa
por **fecha de timbrado**, no por el periodo fiscal que el CFDI declara
(`mes_periodo_ini`/`mes_periodo_fin`/`ejercicio_periodo`). Caso real que lo
confirmó: 13 de los 15 CFDI de la retención real de **noviembre 2025** se
re-timbraron en bloque el 22-ene-2026 (el SAT invalidó los UUID originales
de noviembre — ya no aparecen en `raw_sat`), y por eso `periodo='2026-01'`
trae 29 filas (15 de enero real + 14 de noviembre re-timbrado) en vez de
las 15 reales de enero. Por eso aquí se filtra por
`mes_periodo_ini`/`mes_periodo_fin`/`ejercicio_periodo`, no por `periodo`.

El resto del cruce (Comprobante_Digital -> Gasto_Registro -> cargo) reusa
tal cual los extractores genéricos de `src/` (`extract_origen.py`,
`extract_gasto_registro.py`) — no hace falta un extractor propio para eso,
ver `baseline_retencion.py`.
"""
from __future__ import annotations

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote

CVE_RETENC_INTERESES = "16"


def extract_sat_retencion_intereses(periodo: str) -> pd.DataFrame:
    """CFDI de retención de intereses (`cve_retenc=16`) de `raw_sat` cuyo
    PERIODO FISCAL DECLARADO (no la fecha de timbrado) es `periodo`
    ('YYYY-MM'). cve_retenc=16 es mensual en la práctica observada
    (`mes_periodo_ini == mes_periodo_fin` siempre) — se exige explícito por
    seguridad, para no sumar en silencio un periodo multi-mes distinto si
    algún día aparece uno."""
    anio, mes = periodo.split("-")
    sql = (
        "SELECT uuid, fecha_emision, rfc_receptor, nombre_receptor, monto_total_operacion "
        "FROM raw_sat.cfdi_retencion "
        f"WHERE cve_retenc={sql_quote(CVE_RETENC_INTERESES)} "
        f"AND ejercicio_periodo={sql_quote(anio)} "
        f"AND mes_periodo_ini={sql_quote(mes)} AND mes_periodo_fin={sql_quote(mes)} "
        "ORDER BY fecha_emision"
    )
    rows = rows_as_dicts(run_query("postgres_dw", sql))
    df = pd.DataFrame(rows, columns=["uuid", "fecha_emision", "rfc_receptor",
                                      "nombre_receptor", "monto_total_operacion"])
    if not df.empty:
        df["uuid"] = df["uuid"].str.upper()
        df["monto_total_operacion"] = pd.to_numeric(df["monto_total_operacion"], errors="coerce").fillna(0.0)
    return df
