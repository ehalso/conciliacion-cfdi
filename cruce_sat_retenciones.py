"""Cruce independiente: CFDI de retención timbrados ante el SAT
(raw_sat.cfdi_retencion, cargados directo del share del SAT, sin pasar por
el ERP) contra lo que Comprobante_Digital tiene registrado.

A diferencia de reconciliacion_emitidos.py (que compara el ERP consigo
mismo: el Cd_XML que guarda contra el documento que lo originó), este
cruce puede detectar un comprobante que se timbró pero el ERP nunca
registró en ninguna tabla — el hallazgo mayor de la investigación de
referencia (14 constancias de enero 2026 por $282,291.65 que el SAT tiene
y el ERP no, ver docs/emitidos_retenciones.md).

raw_sat.cfdi_retencion tiene cobertura histórica completa (2016-2026, sin
backfill pendiente) — a diferencia de cfdi_emitidos, que solo llega hasta
enero 2026. Por eso este cruce se puede correr sobre todo H1 2026 de una
vez.

Uso:
    python3 cruce_sat_retenciones.py --periodo 2026-01
    python3 cruce_sat_retenciones.py --periodos 2026-01,2026-02,2026-03,2026-04,2026-05,2026-06
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

sys.path.insert(0, "src")

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET

RFC_TRIVASA = "TRI970922TL2"


def extract_sat_retenciones(periodos: list[str]) -> pd.DataFrame:
    where_periodos = ", ".join(sql_quote(p) for p in periodos)
    sql = (
        "SELECT uuid, rfc_emisor, rfc_receptor, nombre_receptor, cve_retenc, "
        "monto_total_operacion, monto_total_retenido, fecha_emision, periodo "
        "FROM raw_sat.cfdi_retencion "
        f"WHERE rfc_emisor = {sql_quote(RFC_TRIVASA)} AND periodo IN ({where_periodos}) "
        "ORDER BY fecha_emision"
    )
    result = run_query("postgres_dw", sql)
    df = pd.DataFrame(rows_as_dicts(result))
    if df.empty:
        return df
    df["uuid"] = df["uuid"].str.upper()
    return df


def extract_mpro_uuids_retencion(fecha_ini: str, fecha_fin: str) -> set[str]:
    """UUIDs que el ERP tiene registrados como retención (en cualquiera de
    los dos módulos), SIN filtro de fecha de timbre -- para no dar un falso
    'no está' cuando en realidad se registró en otra fecha. Se trae un
    rango amplio (histórico completo) para máxima seguridad."""
    sql = (
        "SELECT DISTINCT Cd_Timbre_UUID AS uuid "
        "FROM Comprobante_Digital "
        f"WHERE Cd_RFC_Emisor = {sql_quote(RFC_TRIVASA)} "
        "AND Cd_Tabla IN ('CONSTANCIA_RETENCION', 'GASTO_REGISTRO')"
    )
    result = run_query(MPRO_TARGET, sql)
    df = pd.DataFrame(rows_as_dicts(result))
    if df.empty:
        return set()
    return set(df["uuid"].str.upper())


def cruzar(periodos: list[str]) -> pd.DataFrame:
    print(f"[1/2] Retenciones timbradas ante el SAT ({periodos})...")
    sat_df = extract_sat_retenciones(periodos)
    print(f"      {len(sat_df)} CFDI de retención en raw_sat.cfdi_retencion")

    print("[2/2] UUIDs de retención que el ERP tiene registrados (histórico completo)...")
    mpro_uuids = extract_mpro_uuids_retencion("", "")
    print(f"      {len(mpro_uuids)} UUIDs distintos en Comprobante_Digital")

    if sat_df.empty:
        return sat_df

    sat_df["en_erp"] = sat_df["uuid"].isin(mpro_uuids)
    return sat_df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--periodo", help="YYYY-MM")
    ap.add_argument("--periodos", help="YYYY-MM,YYYY-MM,...")
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()

    if args.periodos:
        periodos = args.periodos.split(",")
    elif args.periodo:
        periodos = [args.periodo]
    else:
        raise SystemExit("Pasa --periodo o --periodos")

    df = cruzar(periodos)
    if df.empty:
        print("Sin resultados.")
        return

    print()
    print("=" * 70)
    print(f"RESULTADO — retenciones SAT vs ERP, periodos {periodos}")
    print("=" * 70)

    n_total = len(df)
    n_en_erp = df["en_erp"].sum()
    n_faltantes = n_total - n_en_erp
    monto_faltante = df.loc[~df["en_erp"], "monto_total_operacion"].astype(float).sum()
    isr_faltante = df.loc[~df["en_erp"], "monto_total_retenido"].astype(float).sum()

    print(f"\nCFDI de retención timbrados: {n_total}")
    print(f"En el ERP: {n_en_erp} ({100*n_en_erp/n_total:.2f}%)")
    print(f"NO en el ERP: {n_faltantes} ({100*n_faltantes/n_total:.2f}%)")
    if n_faltantes:
        print(f"Monto de operación faltante: ${monto_faltante:,.2f}")
        print(f"ISR/retención faltante: ${isr_faltante:,.2f}")
        print("\nDetalle de los faltantes:")
        faltantes = df[~df["en_erp"]][["uuid", "rfc_receptor", "nombre_receptor", "cve_retenc",
                                          "monto_total_operacion", "monto_total_retenido",
                                          "fecha_emision", "periodo"]]
        print(faltantes.to_string(index=False))

    salida = args.salida or f"output/cruce_sat_retenciones_{'_'.join(periodos)}.csv"
    df.to_csv(salida, index=False)
    print(f"\nGuardado: {salida}")


if __name__ == "__main__":
    main()
