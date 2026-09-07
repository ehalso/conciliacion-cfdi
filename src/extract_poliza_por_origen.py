"""Reconciliación a nivel póliza, YA distinguida por origen de documento
(Comprobante_Digital.Cd_Tabla / Poliza_Control.Pc_Tabla) — no agregado como
en extract_poliza.py (el piloto de la sesión anterior).

Para cada (origen, documento) real — sacado de Comprobante_Digital, no
inventado — trae el Cargo/Abono posteado en Poliza_Detalle vía
Poliza_Control, en pólizas activas, EXCLUYENDO el lado "cuentas de orden"
cuando el origen tiene el patrón de doble póliza documentado en
poliza-explor/configuracion-polizas.md (Compra, Compra_Indirecto:
Pl_Configuracion → Poliza_Configuracion.Pc_Descripcion NOT LIKE '%CUENTAS
DE ORDEN%').

Nota de mapeo: `Poliza_Control.Pc_Tabla` usa 'Cheque' (title-case) para ese
origen específico y MAYÚSCULAS para el resto — confirmado en vivo
(DISTINCT Pc_Tabla, 2026-09-07). Se compara con UPPER() por seguridad.
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET

BATCH_SIZE = 150


def _fetch_batch(origen: str, documentos: list[str]) -> list[dict]:
    in_list = ", ".join(sql_quote(d) for d in documentos)
    # Clave del fix (confirmado en vivo 2026-09-07): un Pl_Folio consolida
    # VARIOS documentos del mismo origen (ej. varios Gr_Folio bajo una sola
    # póliza del día) — sumar por Poliza_Control sin más trae el cargo/abono
    # de TODOS esos documentos, no solo el que nos interesa. Filtrar
    # además por Poliza_Detalle.Pd_Referencia = documento aísla las líneas
    # correctas dentro de la póliza consolidada — mismo método ya validado
    # en layout-gastos para GASTO_REGISTRO, generalizado aquí a los demás
    # orígenes con Pd_Referencia confiable (todos salvo Cheque, ver
    # extract_poliza_cheque()).
    sql = (
        "SELECT pd.Pd_Referencia AS documento, pd.Pd_Tipo, SUM(pd.Pd_Importe) AS importe, "
        "COUNT(DISTINCT pc.Pl_Folio) AS n_polizas "
        "FROM Poliza_Control pc "
        "JOIN Poliza p ON p.Pl_Folio = pc.Pl_Folio "
        "JOIN Poliza_Detalle pd ON pd.Pl_Folio = pc.Pl_Folio AND pd.Pd_Referencia = pc.Pc_Documento "
        "LEFT JOIN Poliza_Configuracion pcf ON pcf.Pc_Cve_Poliza_Configuracion = p.Pl_Configuracion "
        f"WHERE UPPER(pc.Pc_Tabla) = UPPER({sql_quote(origen)}) "
        "AND p.Es_Cve_Estado <> 'CA' "
        "AND (pcf.Pc_Descripcion IS NULL OR UPPER(pcf.Pc_Descripcion) NOT LIKE '%CUENTAS DE ORDEN%') "
        f"AND pc.Pc_Documento IN ({in_list}) "
        "GROUP BY pd.Pd_Referencia, pd.Pd_Tipo"
    )
    result = run_query(MPRO_TARGET, sql)
    return rows_as_dicts(result)


def extract_poliza_por_origen(origen: str, documentos: list[str]) -> pd.DataFrame:
    """Devuelve una fila por `documento` con suma de cargo/abono (pólizas
    activas, sin cuentas de orden) para ese origen específico."""
    documentos = sorted(set(documentos))
    raw: list[dict] = []
    for i in range(0, len(documentos), BATCH_SIZE):
        raw.extend(_fetch_batch(origen, documentos[i : i + BATCH_SIZE]))

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for r in raw:
        by_doc[r["documento"]].append(r)

    out = []
    for doc, rows in by_doc.items():
        cargo = sum(float(r["importe"]) for r in rows if r["Pd_Tipo"] == 1)
        abono = sum(float(r["importe"]) for r in rows if r["Pd_Tipo"] == 2)
        n_polizas = max((r["n_polizas"] for r in rows), default=0)
        out.append({"documento": doc, "cargo": cargo, "abono": abono, "n_polizas": int(n_polizas)})
    return pd.DataFrame(out, columns=["documento", "cargo", "abono", "n_polizas"])


def extract_poliza_cheque(folios: list[str]) -> pd.DataFrame:
    """Método específico para Cheque, ya validado en poliza-explor:
    `Pd_Referencia` NO es confiable para este origen (72% de los casos trae
    `Ch_Referencia`, la referencia externa, en vez de `Ch_Folio`). Se aísla
    el Abono por MONTO en vez de por referencia: `ABS(Pd_Importe -
    Ch_Importe) <= 1`, dentro de las pólizas activas ligadas por
    `Poliza_Control`.
    """
    folios = sorted(set(folios))
    out = []
    for i in range(0, len(folios), BATCH_SIZE):
        batch = folios[i : i + BATCH_SIZE]
        in_list = ", ".join(sql_quote(f) for f in batch)
        sql = (
            "SELECT ch.Ch_Folio AS documento, ch.Ch_Importe AS importe_cheque, "
            "pd.Pd_Importe AS importe_poliza, pc.Pl_Folio "
            "FROM Cheque ch "
            "JOIN Poliza_Control pc ON pc.Pc_Documento = ch.Ch_Folio AND UPPER(pc.Pc_Tabla) = 'CHEQUE' "
            "JOIN Poliza p ON p.Pl_Folio = pc.Pl_Folio AND p.Es_Cve_Estado <> 'CA' "
            "JOIN Poliza_Detalle pd ON pd.Pl_Folio = pc.Pl_Folio AND pd.Pd_Tipo = 2 "
            f"WHERE ch.Ch_Folio IN ({in_list}) "
            "AND ABS(pd.Pd_Importe - ch.Ch_Importe) <= 1"
        )
        result = run_query(MPRO_TARGET, sql)
        out.extend(rows_as_dicts(result))

    df = pd.DataFrame(out, columns=["documento", "importe_cheque", "importe_poliza", "Pl_Folio"])
    if df.empty:
        return pd.DataFrame(columns=["documento", "cargo", "abono", "n_polizas"])
    df["importe_poliza"] = pd.to_numeric(df["importe_poliza"], errors="coerce")
    agg = df.groupby("documento").agg(
        abono=("importe_poliza", "sum"),
        n_polizas=("Pl_Folio", "nunique"),
    ).reset_index()
    agg["cargo"] = 0.0
    return agg[["documento", "cargo", "abono", "n_polizas"]]
