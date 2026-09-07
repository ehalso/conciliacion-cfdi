"""Cruce por UUID entre SAT (raw_sat.cfdi_recibidos) y MPRO
(Comprobante_Digital, importes parseados de Cd_XML) y clasificación de
diferencias de importe (subtotal, iva, total).

Nota sobre `iva`: en SAT es el campo `iva` tal cual carga el ELT. En MPRO
se calcula como TotalImpuestosTrasladados - TotalImpuestosRetenidos del
XML parseado. Es una hipótesis de equivalencia razonable pero no 100%
verificada contra el criterio exacto del loader SAT — se valida
empíricamente comparando ambos lados en el detalle (ver notas del reporte).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pandas as pd

AMOUNT_FIELDS = ["subtotal", "iva", "total"]


def _dec(value) -> Decimal:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return Decimal("0")


def reconcile(sat_df: pd.DataFrame, mpro_df: pd.DataFrame, tolerancia: Decimal) -> pd.DataFrame:
    sat = sat_df.set_index("uuid", drop=False) if not sat_df.empty else sat_df
    mpro = mpro_df.set_index("uuid", drop=False) if not mpro_df.empty else mpro_df

    all_uuids = sorted(set(sat.index if not sat.empty else []) | set(mpro.index if not mpro.empty else []))

    rows = []
    for uuid in all_uuids:
        en_sat = uuid in sat.index if not sat.empty else False
        en_mpro = uuid in mpro.index if not mpro.empty else False

        row = {"uuid": uuid, "en_sat": en_sat, "en_mpro": en_mpro}
        row["tipo_comprobante"] = sat.loc[uuid, "tipo_comprobante"] if en_sat else None
        row["rfc_emisor"] = sat.loc[uuid, "rfc_emisor"] if en_sat else None
        row["n_modulos_mpro"] = mpro.loc[uuid, "n_modulos"] if en_mpro else None
        row["modulos_mpro"] = mpro.loc[uuid, "modulos_mpro"] if en_mpro else None
        xml_parseado = bool(mpro.loc[uuid, "xml_parseado"]) if en_mpro else None
        row["xml_parseado_mpro"] = xml_parseado
        row["retenciones_mpro"] = (
            mpro.loc[uuid, "retenciones_mpro"] if en_mpro and xml_parseado else None
        )

        if en_sat and en_mpro and xml_parseado:
            diffs = {}
            for field in AMOUNT_FIELDS:
                v_sat = _dec(sat.loc[uuid, field])
                v_mpro = _dec(mpro.loc[uuid, field])
                diff = v_sat - v_mpro
                row[f"{field}_sat"] = v_sat
                row[f"{field}_mpro"] = v_mpro
                row[f"{field}_diff"] = diff
                diffs[field] = diff
            row["estatus"] = "OK" if all(abs(d) <= tolerancia for d in diffs.values()) else "DIFERENCIA_IMPORTE"
            row["fecha_sat"] = sat.loc[uuid, "fecha"]
            row["fecha_mpro"] = mpro.loc[uuid, "fecha"]
        elif en_sat and en_mpro and not xml_parseado:
            for field in AMOUNT_FIELDS:
                row[f"{field}_sat"] = _dec(sat.loc[uuid, field])
                row[f"{field}_mpro"] = None
                row[f"{field}_diff"] = None
            row["estatus"] = "MPRO_SIN_XML"
            row["fecha_sat"] = sat.loc[uuid, "fecha"]
            row["fecha_mpro"] = None
        elif en_sat:
            for field in AMOUNT_FIELDS:
                row[f"{field}_sat"] = _dec(sat.loc[uuid, field])
                row[f"{field}_mpro"] = None
                row[f"{field}_diff"] = None
            row["estatus"] = "SOLO_SAT"
            row["fecha_sat"] = sat.loc[uuid, "fecha"]
            row["fecha_mpro"] = None
        else:
            for field in AMOUNT_FIELDS:
                row[f"{field}_sat"] = None
                row[f"{field}_mpro"] = _dec(mpro.loc[uuid, field]) if xml_parseado else None
                row[f"{field}_diff"] = None
            row["estatus"] = "SOLO_MPRO" if xml_parseado else "SOLO_MPRO_SIN_XML"
            row["fecha_sat"] = None
            row["fecha_mpro"] = mpro.loc[uuid, "fecha"] if en_mpro else None

        rows.append(row)

    return pd.DataFrame(rows)


def resumen(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["estatus", "conteo", "total_sat", "total_mpro"])

    out = (
        df.groupby("estatus")
        .agg(
            conteo=("uuid", "count"),
            total_sat=("total_sat", lambda s: sum(v for v in s if v is not None)),
            total_mpro=("total_mpro", lambda s: sum(v for v in s if v is not None)),
        )
        .reset_index()
    )
    return out
