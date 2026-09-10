"""
[1] Reconciliacion Cargo/Abono a nivel folio x cuenta x centro de costo.
Adaptado de layout-contabilidad/layout_gastos/v03_detalle_cuenta.py --
la query mas validada del proyecto historico (99.96%, 9,158/9,162,
enero-junio .207). Query vigente: queries/v03_detalle_cuenta_centro_costo.sql
(la misma que se sirve en FlexMonster), grano = Poliza_Detalle.Pd_Centro_Costo,
NO Grc_ID (ver 05_reconciliacion_grc_importe_vs_poliza_ceco.py para esa liga).

Excluye CONSUMO_INTERNO / GASTO_REGISTRO_NOMINA -- no generan poliza por
este camino (ver docstring de la query).

Validacion (solo aqui, en Python -- no en la query de produccion):
  - Folios normales (Importe > -$1): SUM(Cargo) == Importe.
  - Reversion (Importe <= -$1): SUM(Abono) == |Importe|.
  - GASTO_RECLASIFICACION (Importe siempre $0 neto): SUM(Cargo) == SUM(Abono).

Uso:
    python3 03_reconciliacion_cargo_abono_ceco.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
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


BASELINE_QUERY = """
SELECT
    gr.Gr_Folio AS FOLIO,
    gr.Gr_Tabla AS ORIGEN,
    SUM(grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio) AS IMPORTE
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, gr.Gr_Tabla
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print("[bold]1/3 -- Cargo/Abono a nivel folio x cuenta x centro de costo[/bold]")

    detalle = pd.read_sql(text(leer_query("queries/v03_detalle_cuenta_centro_costo.sql", fi, ff)), engine)
    detalle["FOLIO"] = detalle["FOLIO"].str.strip()
    detalle.to_csv(f"03_detalle_cargo_abono_ceco_{fi}_{ff}.csv", index=False)
    console.print(f"  {len(detalle)} filas (folio x cuenta x centro de costo), {detalle.FOLIO.nunique()} folios")

    base = pd.read_sql(text(BASELINE_QUERY), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    base["FOLIO"] = base["FOLIO"].str.strip()

    rollup = detalle.groupby("FOLIO", as_index=False).agg(
        CARGO_TOTAL=("CARGO", "sum"), ABONO_TOTAL=("ABONO", "sum")
    )
    df = base.merge(rollup, on="FOLIO", how="left")
    df[["CARGO_TOTAL", "ABONO_TOTAL"]] = df[["CARGO_TOTAL", "ABONO_TOTAL"]].fillna(0)

    es_reversion = df.IMPORTE <= -1.0
    es_reclasificacion = df.ORIGEN == "GASTO_RECLASIFICACION"

    df["VALOR_VALIDACION"] = df.CARGO_TOTAL
    df.loc[es_reversion, "VALOR_VALIDACION"] = df.loc[es_reversion, "ABONO_TOTAL"]
    df["COMPARAR_CONTRA"] = df.IMPORTE.abs()
    df.loc[es_reclasificacion, "COMPARAR_CONTRA"] = df.loc[es_reclasificacion, "ABONO_TOTAL"]

    df["DIFERENCIA"] = df.VALOR_VALIDACION - df.COMPARAR_CONTRA
    df["CUADRA"] = df.DIFERENCIA.abs() < 1

    n, c = len(df), int(df.CUADRA.sum())
    resumen(folios=n, cuadran=c, pct=f"{100*c/n:.2f}%")

    por_origen = df.groupby(df["ORIGEN"].fillna("GASTO_DIRECTO")).agg(
        n=("FOLIO", "count"), cuadran=("CUADRA", "sum")
    ).reset_index()
    por_origen["pct"] = (por_origen.cuadran / por_origen.n * 100).round(2)
    mostrar_tabla(por_origen, "Reconciliacion por ORIGEN")

    mal = df[~df.CUADRA]
    console.print(f"\n[bold red]Folios que NO cuadran:[/bold red] {len(mal)}")
    if len(mal):
        mostrar_tabla(mal.sort_values("DIFERENCIA", key=abs, ascending=False), "Folios fuera de cuadre", max_filas=15)

    console.print(f"\n[green]Guardado: 03_detalle_cargo_abono_ceco_{fi}_{ff}.csv[/green]")


if __name__ == "__main__":
    main()
