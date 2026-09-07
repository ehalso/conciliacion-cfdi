#!/usr/bin/env python3
"""Conciliación CFDI (recibidos o emitidos): SAT (raw_sat.cfdi_recibidos /
cfdi_emitidos) vs MPRO (Comprobante_Digital), ambos vía el bridge de solo
lectura en ctunlinux.

Uso:
    python3 main.py --periodo 2026-08 --salida output/conciliacion_2026-08.xlsx
    python3 main.py --periodos 2026-01,2026-02,2026-03 --salida output/conciliacion_2026-Q1.xlsx
    python3 main.py --tipo emitido --periodo 2026-01 --salida output/conciliacion_emitido_2026-01.xlsx
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from extract_sat import extract_sat_cfdi  # noqa: E402
from extract_mpro import extract_mpro_por_uuids  # noqa: E402
from reconcile import reconcile, resumen  # noqa: E402
from report import write_report  # noqa: E402

TABLA_POR_TIPO = {"recibido": "cfdi_recibidos", "emitido": "cfdi_emitidos"}


def run(periodos: list[str], tipo: str = "recibido", tolerancia: str = "1.00", salida: str | None = None, label: str | None = None):
    tabla = TABLA_POR_TIPO[tipo]
    label = label or f"{tipo}_" + "-".join(periodos) if tipo != "recibido" else "-".join(periodos)
    salida = salida or f"output/conciliacion_{label}.xlsx"
    Path(salida).parent.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] Extrayendo SAT {tipo} periodos={periodos} (raw_sat.{tabla}) ...")
    sat_df = extract_sat_cfdi(tabla, periodos=periodos)
    print(f"      {len(sat_df)} filas de raw_sat.{tabla}")

    if sat_df.empty:
        print("Sin datos SAT para ese/esos periodo(s), nada que conciliar.")
        return None, None

    print(f"[2/4] Buscando {sat_df['uuid'].nunique()} UUIDs en Comprobante_Digital (MPRO) ...")
    mpro_df = extract_mpro_por_uuids(sat_df["uuid"].tolist())
    n_parsed = int(mpro_df["xml_parseado"].sum()) if not mpro_df.empty else 0
    print(f"      {len(mpro_df)} UUIDs encontrados en MPRO ({n_parsed} con XML parseado)")

    print("[3/4] Conciliando ...")
    detalle = reconcile(sat_df, mpro_df, Decimal(tolerancia))
    resumen_df = resumen(detalle)
    print(resumen_df.to_string(index=False))

    print(f"[4/4] Escribiendo reporte en {salida} ...")
    write_report(detalle, resumen_df, salida)
    print("Listo.")
    return detalle, resumen_df


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--periodo", help="Periodo único, formato YYYY-MM")
    g.add_argument("--periodos", help="Varios periodos separados por coma, ej. 2026-01,2026-02,2026-03")
    ap.add_argument("--tipo", choices=["recibido", "emitido"], default="recibido", help="Dirección del CFDI")
    ap.add_argument("--tolerancia", type=str, default="1.00", help="Tolerancia en pesos por campo")
    ap.add_argument("--salida", default=None, help="Ruta del .xlsx de salida")
    ap.add_argument("--label", default=None, help="Etiqueta para nombrar el archivo si no se da --salida")
    args = ap.parse_args()

    periodos = [args.periodo] if args.periodo else [p.strip() for p in args.periodos.split(",")]
    run(periodos, tipo=args.tipo, tolerancia=args.tolerancia, salida=args.salida, label=args.label)


if __name__ == "__main__":
    main()
