#!/usr/bin/env python3
"""Cruce independiente contra el SAT para CFDI emitido (factura, nota de
crédito): compara `raw_sat.cfdi_emitidos` contra `Comprobante_Digital`
(cualquier módulo) -- detecta un CFDI que se timbró y el ERP nunca
registró, y el caso simétrico.

CAVEAT DE COBERTURA: `raw_sat.cfdi_emitidos` solo tiene backfill hasta
enero 2026 (ver docs/emitidos_retenciones.md). Para periodos posteriores,
el cruce va a mostrar casi todo como `SOLO_MPRO` -- eso es el backfill
pendiente, NO un hallazgo real de CFDI no registrados. Solo enero 2026 es
interpretable hoy; se deja el script correr sobre cualquier periodo a
propósito (para que sea inmediato en cuanto el backfill avance), pero el
resumen imprime la advertencia si detecta ese patrón.

Uso:
    python3 cruce_sat_emitidos.py --periodo 2026-01
    python3 cruce_sat_emitidos.py --periodos 2026-01,2026-02
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
    salida = salida or f"output/cruce_sat_emitidos_{label}.xlsx"
    Path(salida).parent.mkdir(parents=True, exist_ok=True)

    print(f"Calculando cruce SAT emitido, periodos={periodos} ...")
    detalle, resumen_df = calcular_periodos(periodos, "emitido")
    if detalle.empty:
        print("Sin datos para ese/esos periodo(s).")
        return None, None

    print(resumen_df.to_string(index=False))

    n_solo_mpro = int(resumen_df.loc[resumen_df["estatus"] == "SOLO_MPRO", "conteo"].sum())
    n_total = int(resumen_df["conteo"].sum())
    if n_total and n_solo_mpro / n_total > 0.5:
        print(
            "\nADVERTENCIA: más de la mitad del universo salió SOLO_MPRO -- típico de un "
            "periodo sin backfill de raw_sat.cfdi_emitidos (hoy solo cubre hasta enero 2026), "
            "no un hallazgo real de CFDI no registrados. Ver docs/emitidos_retenciones.md."
        )

    print(f"\nEscribiendo reporte en {salida} ...")
    write_report(detalle, resumen_df, salida)
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
