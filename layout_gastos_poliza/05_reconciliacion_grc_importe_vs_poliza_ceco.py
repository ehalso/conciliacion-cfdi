"""
[3] Prueba directa: Grc_Importe (Gasto_Registro_Control) vs Cargo-Abono de
poliza, ambos agregados a FOLIO x CENTRO_COSTO. Adaptado de
layout-contabilidad/layout_gastos/paso18_validar_grc_importe_por_ceco.py.
Es la comparacion mas directa de "el importe que trae Grc_ID por centro de
costo, se parece al Cargo-Abono real de la poliza en ese mismo centro".

Fuente de Cargo/Abono: queries/v03_detalle_cuenta_centro_costo.sql
(Pd_Centro_Costo), agregada por FOLIO x CENTRO_COSTO -- ES una fuente
distinta de centro de costo a la de Grc_ID; ver v_impuestos_y_poliza_por_ceco.sql
(script 04) para la confirmacion de que ambas coinciden folio a folio.

Excluye CONSUMO_INTERNO / GASTO_REGISTRO_NOMINA (mismo universo que [1] y [2]).

Uso:
    python3 05_reconciliacion_grc_importe_vs_poliza_ceco.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
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


GRC_QUERY = """
SELECT
    gr.Gr_Folio AS FOLIO,
    grc.Cc_Cve_Centro_Costo AS CENTRO_COSTO,
    SUM(grc.Grc_Importe) AS IMPORTE_GRC
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
JOIN Gasto_Registro_Control grc ON grc.Gr_Folio = grd.Gr_Folio AND grc.Grd_ID = grd.Grd_ID
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, grc.Cc_Cve_Centro_Costo
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print("[bold]3/3 -- Grc_Importe vs poliza, FOLIO x CENTRO_COSTO[/bold]")

    grc_ceco = pd.read_sql(text(GRC_QUERY), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    grc_ceco["FOLIO"] = grc_ceco["FOLIO"].str.strip()

    poliza_detalle = pd.read_sql(text(leer_query("queries/v03_detalle_cuenta_centro_costo.sql", fi, ff)), engine)
    poliza_detalle["FOLIO"] = poliza_detalle["FOLIO"].str.strip()
    poliza_ceco = poliza_detalle.groupby(["FOLIO", "CENTRO_COSTO"], as_index=False).agg(
        CARGO=("CARGO", "sum"), ABONO=("ABONO", "sum")
    )
    poliza_ceco["IMPORTE_POLIZA"] = poliza_ceco["CARGO"] - poliza_ceco["ABONO"]

    comp = grc_ceco.merge(
        poliza_ceco[["FOLIO", "CENTRO_COSTO", "IMPORTE_POLIZA"]],
        on=["FOLIO", "CENTRO_COSTO"], how="outer", indicator=True
    )
    comp["IMPORTE_GRC"] = comp["IMPORTE_GRC"].fillna(0)
    comp["IMPORTE_POLIZA"] = comp["IMPORTE_POLIZA"].fillna(0)
    comp["DIFERENCIA"] = (comp["IMPORTE_GRC"] - comp["IMPORTE_POLIZA"]).abs()
    comp["CUADRA"] = comp["DIFERENCIA"] < 1

    n, c = len(comp), int(comp["CUADRA"].sum())
    resumen(combinaciones_folio_x_ceco=n, cuadran=c, pct=f"{100*c/n:.2f}%")

    match_dist = comp.groupby("_merge").agg(n=("FOLIO", "count"), cuadran=("CUADRA", "sum")).reset_index()
    mostrar_tabla(match_dist, "FOLIO x CENTRO_COSTO -- origen del match (left_only=solo GRC, right_only=solo Poliza)")

    no_cuadra = comp[~comp["CUADRA"]].sort_values("DIFERENCIA", ascending=False)
    console.print(f"\n[bold red]Combinaciones que NO cuadran:[/bold red] {len(no_cuadra)}")
    if len(no_cuadra):
        cols = ["FOLIO", "CENTRO_COSTO", "IMPORTE_GRC", "IMPORTE_POLIZA", "DIFERENCIA", "_merge"]
        mostrar_tabla(no_cuadra[cols], "Muestra -- combinaciones fuera de cuadre", max_filas=20)

    comp.to_csv(f"05_reconciliacion_grc_importe_vs_poliza_ceco_{fi}_{ff}.csv", index=False)
    console.print(f"\n[green]Guardado: 05_reconciliacion_grc_importe_vs_poliza_ceco_{fi}_{ff}.csv[/green]")


if __name__ == "__main__":
    main()
