#!/usr/bin/env python3
"""Cruce independiente contra el SAT para CFDI recibido: compara
`raw_sat.cfdi_recibidos` (el XML que el PAC deja en el share del SAT,
cargado a Postgres sin pasar por el ERP) contra `Comprobante_Digital`
(cualquier módulo) -- detecta un CFDI recibido que el ERP nunca registró
en ningún lado, y el caso simétrico: algo etiquetado en el ERP que no
aparece en la fuente independiente del SAT.

A diferencia de `recibidos/nivel_poliza/baseline_universal.py` (que
pregunta si el IMPORTE cuadra contra la póliza), esto es un chequeo de
EXISTENCIA -- más simple, y no requiere que el CFDI tenga valor monetario
para ser candidato.

Uso:
    python3 cruce_sat_recibidos.py --periodo 2026-02
    python3 cruce_sat_recibidos.py --periodos 2026-01,2026-02,2026-03 --salida output/cruce_recibidos_Q1.xlsx
"""
from __future__ import annotations

import argparse
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from cruce_sat import calcular_periodos  # noqa: E402
from report import write_report  # noqa: E402


def run(periodos: list[str], salida: str | None = None):
    label = "-".join(periodos)
    salida = salida or f"output/cruce_sat_recibidos_{label}.xlsx"
    Path(salida).parent.mkdir(parents=True, exist_ok=True)

    print(f"Calculando cruce SAT recibido, periodos={periodos} ...")
    detalle, resumen_df = calcular_periodos(periodos, "recibido")
    if detalle.empty:
        print("Sin datos para ese/esos periodo(s).")
        return None, None

    print(resumen_df.to_string(index=False))

    solo_sat_real = detalle[(detalle["estatus"] == "SOLO_SAT") & (detalle["subtotal"] > 1)]
    print(f"\nDe los SOLO_SAT, {len(solo_sat_real)} tienen valor monetario real "
          f"(subtotal > $1) -- los candidatos a hueco real de registro en el ERP.")

    print(f"\nEscribiendo reporte en {salida} ...")
    write_report(detalle.rename(columns={"estatus": "estatus"}), resumen_df, salida)
    print("Listo.")
    return detalle, resumen_df


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--periodo", help="Periodo único, formato YYYY-MM")
    g.add_argument("--periodos", help="Varios periodos separados por coma, ej. 2026-01,2026-02")
    ap.add_argument("--salida", default=None, help="Ruta del .xlsx de salida")
    args = ap.parse_args()

    periodos = [args.periodo] if args.periodo else [p.strip() for p in args.periodos.split(",")]
    run(periodos, salida=args.salida)


if __name__ == "__main__":
    main()
