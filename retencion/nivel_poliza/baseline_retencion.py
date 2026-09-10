#!/usr/bin/env python3
"""Nivel 3 de conciliación de retención: CFDI de intereses a prestamistas/
inversionistas terceros (`cve_retenc=16`) vs. póliza real en mpro.

Mismo espíritu que `recibidos/nivel_poliza/baseline_universal.py`: la base
contra la que se compara es la SUMA de importe del `raw_sat`, no un cruce
CFDI-por-CFDI. Aquí es la única forma viable, no solo la más simple: nivel 1
(`retencion/cruce_sat/retencion_reconciliation.py`) exige un link 1:1 por
UUID en `Comprobante_Digital`, y `cve_retenc=16` no lo tiene de forma
confiable (nunca `CONSTANCIA_RETENCION`, y en meses como 2026-02 ni el stub
de `GASTO_REGISTRO` de siempre). En cambio, la póliza real de este concepto
sí es estable: la genera una sola configuración conocida (`Poliza_Configuracion`
0139/0521, "REGISTRO INTERESES PREST TERCEROS..."), consolidada en una sola
póliza por mes. Se ubica esa póliza por periodo y se suma su cargo (cuenta
`8200.001.007`) contra la suma de `monto_total_operacion` del SAT del mismo
periodo — el periodo FISCAL declarado por el CFDI (`mes_periodo_ini`/
`mes_periodo_fin`/`ejercicio_periodo`), no la fecha de timbrado: un CFDI
puede volver a timbrarse meses después si el SAT invalida el original (caso
real: noviembre 2025 re-timbrado en enero 2026), y agrupar por fecha de
timbrado infla el periodo equivocado con dinero que ya estaba contabilizado
en el periodo correcto. Detalle del mecanismo y validación en vivo en
`extract_poliza_retencion.py`.

Uso:
    python3 baseline_retencion.py --periodo 2026-02
    python3 baseline_retencion.py --periodos 2026-01,2026-02,2026-03,2026-04,2026-05,2026-06
    python3 baseline_retencion.py --periodo 2026-02 --salida output/retencion_poliza_2026-02.xlsx
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pandas as pd  # noqa: E402

from extract_poliza_retencion import (  # noqa: E402
    extract_sat_retencion_intereses,
    poliza_real_mes,
    poliza_cargo_intereses,
)
from report import write_report  # noqa: E402

TOL = 1.00


def calcular_periodo(periodo: str) -> dict:
    sat_df = extract_sat_retencion_intereses(periodo)
    sat_total = float(sat_df["monto_total_operacion"].sum()) if not sat_df.empty else 0.0

    pol = poliza_real_mes(periodo)
    if pol is None:
        return {
            "periodo": periodo,
            "n_cfdi_sat": len(sat_df),
            "sat_total": sat_total,
            "pl_folio": None,
            "pl_fecha": None,
            "pl_configuracion": None,
            "poliza_cargo": 0.0,
            "diferencia": round(sat_total, 2),
            "estatus": "SIN_POLIZA" if sat_total > TOL else "SIN_SAT_NI_POLIZA",
        }

    cargo = poliza_cargo_intereses(pol["Pl_Folio"])
    diff = round(sat_total - cargo, 2)
    return {
        "periodo": periodo,
        "n_cfdi_sat": len(sat_df),
        "sat_total": sat_total,
        "pl_folio": pol["Pl_Folio"],
        "pl_fecha": pol["Pl_Fecha"],
        "pl_configuracion": pol["Pl_Configuracion"],
        "poliza_cargo": cargo,
        "diferencia": diff,
        "estatus": "CONCILIADO" if abs(diff) <= TOL else "DIFERENCIA_IMPORTE",
    }


def run(periodos: list[str], salida: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    print(f"Conciliando retención de intereses (cve_retenc=16) a nivel póliza: {periodos}")
    detalle = pd.DataFrame([calcular_periodo(p) for p in periodos])
    print(detalle.to_string(index=False))

    n_ok = int((detalle["estatus"] == "CONCILIADO").sum())
    print(f"\n{n_ok}/{len(detalle)} periodos conciliados (tolerancia ${TOL:.2f}).")

    resumen = (
        detalle.groupby("estatus")
        .agg(conteo=("periodo", "count"), sat_total=("sat_total", "sum"), poliza_cargo=("poliza_cargo", "sum"))
        .reset_index()
    )

    if salida:
        Path(salida).parent.mkdir(parents=True, exist_ok=True)
        write_report(detalle, resumen, salida)
        print(f"\nReporte: {salida}")

    return detalle, resumen


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--periodo", help="Periodo único, formato YYYY-MM")
    g.add_argument("--periodos", help="Varios periodos separados por coma, ej. 2026-01,2026-02")
    ap.add_argument("--salida", default=None, help="Ruta .xlsx opcional para el reporte")
    args = ap.parse_args()

    periodos = args.periodos.split(",") if args.periodos else [args.periodo]
    run(periodos, args.salida)


if __name__ == "__main__":
    main()
