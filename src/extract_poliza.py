"""Nivel de detalle adicional: trazabilidad de cada CFDI recibido hasta la
póliza contable y la cuenta contable exacta que lo registró en mpro.

Basado en la investigación ya documentada en trivasa-context
(docs/proyectos/poliza-explor/) — no se reinventa el mapeo, se reutiliza:

- `Poliza_Detalle_Comprobante` (anexo SAT, 2.9M filas, CONFIRMADO en vivo en
  producción .207 2026-09-07) liga cada línea de póliza (`Pl_Folio`,
  `Pd_ID`) con el UUID del CFDI que la originó — es el enlace directo
  CFDI → póliza, sin pasar por `Comprobante_Digital`.
- Se une con `Poliza_Detalle` (cuenta contable, cargo/abono, importe) y
  `Poliza` (para filtrar pólizas canceladas, `Es_Cve_Estado <> 'CA'`).

Decisión de alcance (ver notas en el reporte): NO se fuerza una regla de
"cargo debe cuadrar con abono" por UUID. Confirmado con datos reales
(2026-09-07) que el anexo SAT no necesariamente etiqueta ambos lados de la
partida doble con el mismo UUID — en la muestra probada, un CFDI de
`Compra` trajo únicamente renglones de Cargo etiquetados, ningún Abono.
Forzar ese balance daría falsos negativos. En su lugar se reporta lo que
hay: pólizas activas involucradas, cuentas contables tocadas, y las sumas
de cargo/abono tal cual, dejando el juicio de "cuadra o no" al detalle
visible en vez de un veredicto binario que no está garantizado por el
esquema.
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET

BATCH_SIZE = 150


def _fetch_batch(uuids: list[str]) -> list[dict]:
    in_list = ", ".join(sql_quote(u) for u in uuids)
    sql = (
        "SELECT UPPER(pdc.Pdc_UUID) AS uuid, pd.Pd_Tipo, pd.Cc_Cve_Cuenta_Contable AS cuenta, "
        "SUM(pd.Pd_Importe) AS importe, COUNT(DISTINCT pdc.Pl_Folio) AS n_polizas "
        "FROM Poliza_Detalle_Comprobante pdc "
        "JOIN Poliza_Detalle pd ON pd.Pl_Folio = pdc.Pl_Folio AND pd.Pd_ID = pdc.Pd_ID "
        "JOIN Poliza p ON p.Pl_Folio = pdc.Pl_Folio "
        f"WHERE p.Es_Cve_Estado <> 'CA' AND UPPER(pdc.Pdc_UUID) IN ({in_list}) "
        "GROUP BY UPPER(pdc.Pdc_UUID), pd.Pd_Tipo, pd.Cc_Cve_Cuenta_Contable"
    )
    result = run_query(MPRO_TARGET, sql)
    return rows_as_dicts(result)


def extract_poliza_por_uuids(uuids: list[str]) -> pd.DataFrame:
    """Para cada UUID, agrega su huella contable: pólizas activas que lo
    referencian, cuentas contables tocadas, y suma de cargo/abono.

    Devuelve una fila por UUID (los que tienen al menos una póliza activa
    con anexo SAT). Los que no aparecen aquí no tienen huella en
    `Poliza_Detalle_Comprobante` (activa) — ver `con_poliza` en quien
    consuma esto.
    """
    uuids = [u.upper() for u in uuids]
    raw_rows: list[dict] = []
    for i in range(0, len(uuids), BATCH_SIZE):
        batch = uuids[i : i + BATCH_SIZE]
        raw_rows.extend(_fetch_batch(batch))

    by_uuid: dict[str, list[dict]] = defaultdict(list)
    for r in raw_rows:
        by_uuid[r["uuid"]].append(r)

    out = []
    for uuid, rows in by_uuid.items():
        cargo = sum(float(r["importe"]) for r in rows if r["Pd_Tipo"] == 1)
        abono = sum(float(r["importe"]) for r in rows if r["Pd_Tipo"] == 2)
        cuentas_cargo = sorted({r["cuenta"] for r in rows if r["Pd_Tipo"] == 1})
        cuentas_abono = sorted({r["cuenta"] for r in rows if r["Pd_Tipo"] == 2})
        n_polizas = max((r["n_polizas"] for r in rows), default=0)
        out.append({
            "uuid": uuid,
            "con_poliza": True,
            "n_polizas_activas": int(n_polizas),
            "suma_cargo": cargo,
            "suma_abono": abono,
            "cuentas_cargo": ", ".join(cuentas_cargo),
            "cuentas_abono": ", ".join(cuentas_abono),
            "n_cuentas_distintas": len(set(cuentas_cargo) | set(cuentas_abono)),
        })
    return pd.DataFrame(out)
