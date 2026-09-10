"""
[2] Reconciliacion Impuesto + Cargo/Abono de poliza, a nivel CECO usando
el centro de costo de Gasto_Registro_Control (Grc_ID), no Pd_Centro_Costo.
Adaptado de layout-contabilidad/layout_gastos/validar_impuestos_y_poliza_ceco.py.
Query vigente: queries/v_impuestos_y_poliza_por_ceco.sql (v2.4) --
prorratea Cargo/Abono de poliza (a nivel folio completo, Pd_Referencia no
baja a Grd_ID) usando el peso de Grc_Importe por folio.

Excluye CONSUMO_INTERNO / GASTO_REGISTRO_NOMINA (mismo universo que [1]).

Uso:
    python3 04_reconciliacion_impuestos_poliza_ceco.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
"""
import argparse
import sys

sys.path.insert(0, "/home/esteban/trivasa/connections")
from connection_205_trivasadb3 import engine  # default de exploracion

import pandas as pd
from sqlalchemy import text
from helpers_output import console, mostrar_tabla, resumen


def leer_query(path, fecha_ini, fecha_fin):
    with open(path) as f:
        return f.read().replace(":fecha_ini", f"'{fecha_ini}'").replace(":fecha_fin", f"'{fecha_fin}'")


ESPERADO_QUERY = """
SELECT
    gr.Gr_Folio AS FOLIO,
    gr.Gr_Tabla AS ORIGEN,
    SUM(grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio) AS IMPORTE,
    SUM(grd.Grd_Impuesto_Importe) AS IMPUESTO_ESPERADO
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
GROUP BY gr.Gr_Folio, gr.Gr_Tabla
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print("[bold]2/3 -- Impuesto + Cargo/Abono a nivel CECO (Gasto_Registro_Control)[/bold]")

    detalle = pd.read_sql(text(leer_query("queries/v_impuestos_y_poliza_por_ceco.sql", fi, ff)), engine)
    console.print(f"  {len(detalle)} filas (folio x centro de costo), {detalle.FOLIO.nunique()} folios")
    detalle.to_csv(f"04_detalle_impuestos_poliza_ceco_{fi}_{ff}.csv", index=False)

    esperado = pd.read_sql(text(ESPERADO_QUERY), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    esperado["ORIGEN"] = esperado["ORIGEN"].fillna("GASTO_DIRECTO")

    rollup = detalle.groupby("FOLIO", as_index=False).agg(
        CARGO_TOTAL=("CARGO_CECO", "sum"),
        ABONO_TOTAL=("ABONO_CECO", "sum"),
        IMPUESTO_TOTAL=("IMPUESTO_CECO", "sum"),
    )

    df = esperado.merge(rollup, on="FOLIO", how="left")
    for c in ["CARGO_TOTAL", "ABONO_TOTAL", "IMPUESTO_TOTAL"]:
        df[c] = df[c].fillna(0)

    es_reversion = df.IMPORTE <= -1.0
    es_reclasificacion = df.ORIGEN == "GASTO_RECLASIFICACION"

    df["VALOR_CARGO_VALIDACION"] = df.CARGO_TOTAL
    df.loc[es_reversion, "VALOR_CARGO_VALIDACION"] = df.loc[es_reversion, "ABONO_TOTAL"]
    df["COMPARAR_CARGO_CONTRA"] = df.IMPORTE.abs()
    df.loc[es_reclasificacion, "COMPARAR_CARGO_CONTRA"] = df.loc[es_reclasificacion, "ABONO_TOTAL"]

    df["DIF_CARGO"] = df.VALOR_CARGO_VALIDACION - df.COMPARAR_CARGO_CONTRA
    df["DIF_IMPUESTO"] = df.IMPUESTO_TOTAL - df.IMPUESTO_ESPERADO
    df["CUADRA_CARGO"] = df.DIF_CARGO.abs() < 1
    df["CUADRA_IMPUESTO"] = df.DIF_IMPUESTO.abs() < 1
    df["CUADRA"] = df.CUADRA_CARGO & df.CUADRA_IMPUESTO

    n, c = len(df), int(df.CUADRA.sum())
    resumen(
        folios=n,
        cuadran_cargo_y_impuesto=c,
        pct=f"{100*c/n:.2f}%",
        solo_cargo=int(df.CUADRA_CARGO.sum()),
        solo_impuesto=int(df.CUADRA_IMPUESTO.sum()),
    )

    por_origen = df.groupby("ORIGEN").agg(n=("FOLIO", "count"), cuadran=("CUADRA", "sum")).reset_index()
    mostrar_tabla(por_origen, "Reconciliacion por ORIGEN")

    mal = df[~df.CUADRA]
    console.print(f"\n[bold red]Folios que NO cuadran:[/bold red] {len(mal)}")
    if len(mal):
        cols = ["FOLIO", "ORIGEN", "IMPORTE", "CARGO_TOTAL", "DIF_CARGO", "IMPUESTO_ESPERADO", "IMPUESTO_TOTAL", "DIF_IMPUESTO"]
        mostrar_tabla(mal[cols].sort_values("DIF_CARGO", key=abs, ascending=False), "Folios fuera de cuadre", max_filas=15)

    df.to_csv(f"04_reconciliacion_impuestos_poliza_ceco_{fi}_{ff}.csv", index=False)
    console.print(f"\n[green]Guardado: 04_reconciliacion_impuestos_poliza_ceco_{fi}_{ff}.csv[/green]")


if __name__ == "__main__":
    main()
