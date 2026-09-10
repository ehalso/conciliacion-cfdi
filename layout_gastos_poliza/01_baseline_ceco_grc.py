"""
Baseline layout de gastos a nivel CECO (Gasto_Registro_Control / Grc_ID) --
un renglon por reparto de centro de costo, no por folio ni por documento.

Contexto: v01_gastos_por_folio.sql (nivel folio) da IMPORTE=39,469,269.50 /
TOTAL=40,553,546.72 para enero 2026, empresa 0001 -- validado 1:1 contra
gastos_por_documento_enero_26.xlsx. Se buscaba reproducir un numero de
referencia externo (8,393 filas / IMPORTE=39,469,269.89) y se encontro que
sumando Grc_Importe (en vez de Grd_Precio_Descontado_Importe*Tipo_Cambio) el
IMPORTE total SI cierra casi exacto (diff $0.04), confirmando que
Gasto_Registro_Control.Grc_Importe ya viene en moneda convertida. La cuenta
de filas NO se pudo reproducir exacta: la version cruda (join a nivel
Gr_Folio+Grd_ID) da 14,584 filas, no 8,393 -- pendiente encontrar la regla
de deduplicacion exacta del reporte de referencia. Grc_Factor NO sirve para
prorratear TOTAL/IMPUESTOS: 2,458 de 7,038 documentos (35%) tienen la suma
de Grc_Factor en 0 aunque Grc_Importe si trae valor -- columna no confiable
para ese calculo, se deja fuera de este baseline.

Uso:
    python3 01_baseline_ceco_grc.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
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

    out = f"baseline_ceco_grc_{args.fecha_ini}_{args.fecha_fin}.csv"
    df.to_csv(out, index=False)

    mostrar_tabla(df.head(25), f"Baseline CECO/Grc_ID {args.fecha_ini} a {args.fecha_fin} (muestra)")

    por_origen = df.groupby(df["ORIGEN"].fillna("GASTO_DIRECTO")).agg(
        folios=("FOLIO", "nunique"), filas=("GRC_ID", "count"), importe=("IMPORTE", "sum")
    ).sort_values("importe", ascending=False)
    mostrar_tabla(por_origen.reset_index(), "Composicion por ORIGEN (Gr_Tabla)")

    EXP_IMPORTE_FOLIO = 39469269.50  # ground truth nivel folio (v01_gastos_por_folio.sql)
    EXP_IMPORTE_REF = 39469269.89    # numero de referencia externo (fuente sin confirmar, ver docstring)

    resumen(
        filas=len(df),
        folios=df["FOLIO"].nunique(),
        importe=f"{df['IMPORTE'].sum():,.2f}",
        diff_vs_folio=f"{df['IMPORTE'].sum() - EXP_IMPORTE_FOLIO:,.2f}",
        diff_vs_referencia_externa=f"{df['IMPORTE'].sum() - EXP_IMPORTE_REF:,.2f}",
    )
    console.print(f"\n[green]Guardado: {out}[/green]")
    console.print(
        "[dim]Nota: filas = reparto por centro de costo (Grc_ID), no folios ni documentos. "
        "IMPORTE valida contra el baseline a nivel folio; TOTAL/IMPUESTOS prorrateados no se "
        "incluyen -- Grc_Factor no es confiable para eso (ver docstring).[/dim]"
    )


if __name__ == "__main__":
    main()
