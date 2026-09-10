#!/usr/bin/env python3
"""Conciliación de CFDI de retención: SAT (raw_sat.cfdi_retencion) vs MPRO
(Comprobante_Digital, Cd_Tabla='CONSTANCIA_RETENCION'), vía el bridge de
solo lectura en ctunlinux.

Nivel 1: existencia + cuadre de `monto_total_operacion` (SAT) contra
`Cd_Monto` (mpro, columna nativa — no requiere parsear el XML, ver
docstring de `src/extract_retencion.py` para por qué). No traza hasta
Poliza_Control/cargo-abono todavía (nivel 3, pendiente).

Uso:
    python3 retencion_reconciliation.py --periodo 2026-01
    python3 retencion_reconciliation.py --periodos 2026-01,2026-02 --salida output/retencion_Q1.xlsx
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from extract_retencion import (  # noqa: E402
    extract_sat_retencion,
    extract_mpro_retencion,
    reconcile_retencion,
    resumen,
)
from report import write_report  # noqa: E402


def calcular(periodos: list[str], tolerancia: str = "1.00") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extrae y concilia, sin tocar el filesystem -- lo que reusa tanto
    `run()` (CLI, escribe .xlsx) como el reporte Streamlit (solo necesita
    los DataFrames en memoria, cacheados)."""
    sat_df = extract_sat_retencion(periodos=periodos)
    if sat_df.empty:
        return sat_df, pd.DataFrame(columns=["estatus", "conteo", "monto_total_operacion"])

    mpro_df = extract_mpro_retencion(sat_df["uuid"].tolist())
    detalle = reconcile_retencion(sat_df, mpro_df, Decimal(tolerancia))
    return detalle, resumen(detalle)


def run(periodos: list[str], tolerancia: str = "1.00", salida: str | None = None):
    label = "-".join(periodos)
    salida = salida or f"output/retencion_{label}.xlsx"
    Path(salida).parent.mkdir(parents=True, exist_ok=True)

    print(f"[1/3] Extrayendo y conciliando periodos={periodos} (raw_sat.cfdi_retencion vs MPRO) ...")
    detalle, resumen_df = calcular(periodos, tolerancia)

    if detalle.empty:
        print("Sin datos SAT para ese/esos periodo(s), nada que conciliar.")
        return None, None

    print(f"      {len(detalle)} CFDI de retención conciliados")
    print("[2/3] Resumen:")
    print(resumen_df.to_string(index=False))

    print(f"[3/3] Escribiendo reporte en {salida} ...")
    write_report(detalle, resumen_df, salida)
    print("Listo.")
    return detalle, resumen_df


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--periodo", help="Periodo único, formato YYYY-MM")
    g.add_argument("--periodos", help="Varios periodos separados por coma, ej. 2026-01,2026-02,2026-03")
    ap.add_argument("--tolerancia", type=str, default="1.00", help="Tolerancia en pesos")
    ap.add_argument("--salida", default=None, help="Ruta del .xlsx de salida")
    args = ap.parse_args()

    periodos = [args.periodo] if args.periodo else [p.strip() for p in args.periodos.split(",")]
    run(periodos, tolerancia=args.tolerancia, salida=args.salida)


if __name__ == "__main__":
    main()
