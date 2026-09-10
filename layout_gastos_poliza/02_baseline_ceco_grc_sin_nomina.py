"""
Baseline CECO/Grc_ID (ver 01_baseline_ceco_grc.py) excluyendo GASTO_REGISTRO_NOMINA.

Uso:
    python3 02_baseline_ceco_grc_sin_nomina.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
"""
import argparse
import sys

sys.path.insert(0, "/home/esteban/trivasa/connections")
from connection_205_trivasadb3 import engine  # default de exploracion -- ver skill trivasa-sql-exploracion

import pandas as pd
from sqlalchemy import text
from helpers_output import console, mostrar_tabla, resumen

QUERY = """
SELECT
    gr.Gr_Folio AS FOLIO,
    gr.Gr_Fecha                          AS FECHA_R,
    gr.Gr_Tabla                          AS ORIGEN,
    grd.Grd_ID                           AS GRD_ID,
    grc.Grc_ID                           AS GRC_ID,
    grc.Cc_Cve_Centro_Costo              AS CENTRO_COSTO,
    grc.Grc_Factor                       AS GRC_FACTOR,
    grc.Grc_Importe                      AS IMPORTE
FROM Gasto_Registro gr
JOIN Sucursal s
    ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd
    ON gr.Gr_Folio = grd.Gr_Folio
JOIN Gasto_Registro_Control grc
    ON grc.Gr_Folio = grd.Gr_Folio AND grc.Grd_ID = grd.Grd_ID
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') <> 'GASTO_REGISTRO_NOMINA'
ORDER BY FOLIO, GRD_ID, GRC_ID
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    args = ap.parse_args()

    df = pd.read_sql(
        text(QUERY), engine,
        params={"fecha_ini": args.fecha_ini, "fecha_fin": args.fecha_fin},
    )

    out = f"baseline_ceco_grc_sin_nomina_{args.fecha_ini}_{args.fecha_fin}.csv"
    df.to_csv(out, index=False)

    por_origen = df.groupby(df["ORIGEN"].fillna("GASTO_DIRECTO")).agg(
        folios=("FOLIO", "nunique"), filas=("GRC_ID", "count"), importe=("IMPORTE", "sum")
    ).sort_values("importe", ascending=False)
    mostrar_tabla(por_origen.reset_index(), "Composicion por ORIGEN (sin GASTO_REGISTRO_NOMINA)")

    resumen(
        filas=len(df),
        folios=df["FOLIO"].nunique(),
        importe=f"{df['IMPORTE'].sum():,.2f}",
    )
    console.print(f"\n[green]Guardado: {out}[/green]")


if __name__ == "__main__":
    main()
