"""Nivel 3 de retención: ubica la póliza REAL de intereses a prestamistas/
inversionistas terceros (`cve_retenc=16`) para un periodo, y suma su cargo.

Por qué no es un cruce CFDI-a-CFDI como `extract_retencion.py` (nivel 1):
`cve_retenc=16` nunca liga a `Comprobante_Digital` vía `CONSTANCIA_RETENCION`
(ver docs/schema/calidad-de-datos.md, sección "Retención"), y en algunos
meses (confirmado en vivo: 2026-02) ni siquiera deja el stub de siempre en
`GASTO_REGISTRO` — 0 UUIDs con cualquier fila en `Comprobante_Digital`. Un
cruce por UUID no es viable con esa cobertura.

Lo que SÍ es estable: la póliza de este concepto la genera una sola familia
de configuraciones conocida (`Poliza_Configuracion` 0139 "REGISTRO INTERESES
PREST TERCEROS 2018 A ABR 2026" y su sucesora 0521 "...MAYO 2026 ADEL",
confirmado en vivo 2026-09-10 contra `Poliza_Configuracion` filtrando por
descripción `%INTERES%PREST%`/`%PREST%TERCER%` — ver también
trivasa-context/docs/proyectos/poliza-explor/configuracion-polizas.md para
el mecanismo general de versionado por `Gr_Fecha`), consolidada en UNA sola
póliza por mes (todos los folios de intereses del mes en un solo
`Pl_Folio`, cargo cuenta `8200.001.007` "INTERESES DE INVERSIONISTAS").

Validado en vivo (2026-09-10):
    2025-11: SAT $254,305.39  ==  Poliza 0000465867 (config 0139) $254,305.39
    2026-01: SAT $254,305.39  ==  Poliza 0000472672 (config 0139) $254,305.39
    2026-02: SAT $254,305.39  ==  Poliza 0000477903 (config 0139) $254,305.39

En ambos meses existe además una póliza "hermana" bajo la config sucesora
(0521), que en los dos casos quedó CANCELADA (`Es_Cve_Estado='CA'`) — se
excluye del cuadre (`Es_Cve_Estado <> 'CA'`), pero es rara: 0521 dice regir
"MAYO 2026 EN ADELANTE" y no debería generar nada en ene/feb. Queda como
pendiente de investigar con Contabilidad, no afecta el cuadre porque está
cancelada.

⚠️ Gotcha de esquema descubierto 2026-09-10, corrige una versión anterior de
este módulo: NO filtrar por `raw_sat.cfdi_retencion.periodo` para agrupar por
mes. Esa columna agrupa por **fecha de timbrado**, no por el periodo fiscal
que el CFDI declara (`mes_periodo_ini`/`mes_periodo_fin`/`ejercicio_periodo`).
Caso real que lo confirmó: 13 de los 15 CFDI de la retención real de
**noviembre 2025** se re-timbraron en bloque el 22-ene-2026 (el SAT invalidó
los UUID originales de noviembre — ya no aparecen en `raw_sat`), y por eso
`periodo='2026-01'` trae 29 filas (15 de enero real + 14 de noviembre
re-timbrado) en vez de las 15 reales de enero. La plata de noviembre YA
estaba contabilizada desde entonces (Poliza 0000465867, 2025-11-05) — el
"duplicado" es solo un artefacto de agrupar por fecha de timbrado en vez de
por periodo fiscal declarado. Por eso aquí se filtra por
`mes_periodo_ini`/`mes_periodo_fin`/`ejercicio_periodo`, no por `periodo`.
"""
from __future__ import annotations

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET

CVE_RETENC_INTERESES = "16"
CONFIGS_INTERESES_TERCEROS = ["0139", "0521"]
CUENTA_CARGO_INTERESES = "8200.001.007"


def extract_sat_retencion_intereses(periodo: str) -> pd.DataFrame:
    """CFDI de retención de intereses (`cve_retenc=16`) de `raw_sat` cuyo
    PERIODO FISCAL DECLARADO (no la fecha de timbrado) es `periodo`
    ('YYYY-MM'). cve_retenc=16 es mensual en la práctica observada
    (`mes_periodo_ini == mes_periodo_fin` siempre) — se exige explícito por
    seguridad, para no sumar en silencio un periodo multi-mes distinto si
    algún día aparece uno.

    Deliberadamente NO se usa la columna `periodo` (agrupa por fecha de
    timbrado): un CFDI re-timbrado tarde por invalidación del SAT declara
    su periodo fiscal real en `mes_periodo_ini`/`mes_periodo_fin`/
    `ejercicio_periodo` sin importar cuándo se volvió a timbrar — ver
    docstring del módulo, caso real de noviembre 2025 re-timbrado en enero
    2026."""
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
        df["monto_total_operacion"] = pd.to_numeric(df["monto_total_operacion"], errors="coerce").fillna(0.0)
    return df


def poliza_real_mes(periodo: str) -> dict | None:
    """Ubica la póliza ACTIVA de la config de intereses a terceros para el
    mes de `periodo`. None si no hay ninguna activa (hueco real de
    contabilización, distinto del hueco de etiquetado fiscal ya conocido).
    Lanza si hay más de una activa — eso sería un caso nuevo, no el patrón
    ya visto, y hay que revisarlo a mano antes de sumarlas a ciegas."""
    anio, mes = periodo.split("-")
    ini = f"{anio}-{mes}-01"
    configs_in = ", ".join(sql_quote(c) for c in CONFIGS_INTERESES_TERCEROS)
    sql = (
        "SELECT Pl_Folio, Pl_Fecha, Pl_Configuracion FROM Poliza "
        f"WHERE Pl_Configuracion IN ({configs_in}) "
        f"AND Pl_Fecha >= '{ini}' AND Pl_Fecha < DATEADD(month, 1, '{ini}') "
        "AND Es_Cve_Estado <> 'CA'"
    )
    rows = rows_as_dicts(run_query(MPRO_TARGET, sql))
    if not rows:
        return None
    if len(rows) > 1:
        raise RuntimeError(
            f"Más de una póliza ACTIVA de intereses a terceros en {periodo}: {rows} "
            "— no es el patrón ya validado (una sola por mes), revisar a mano antes de sumar."
        )
    return rows[0]


def poliza_cargo_intereses(pl_folio: str) -> float:
    """Suma el cargo de la cuenta de intereses de inversionistas
    (`8200.001.007`) en la póliza `pl_folio`. Es el lado bruto (antes de
    ISR) — comparable 1:1 contra `monto_total_operacion` del SAT."""
    sql = (
        "SELECT SUM(Pd_Importe) AS cargo FROM Poliza_Detalle "
        f"WHERE Pl_Folio={sql_quote(pl_folio)} AND Pd_Tipo=1 "
        f"AND Cc_Cve_Cuenta_Contable={sql_quote(CUENTA_CARGO_INTERESES)}"
    )
    row = rows_as_dicts(run_query(MPRO_TARGET, sql))[0]
    return float(row["cargo"] or 0.0)
