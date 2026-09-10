"""
Igual que 04_reconciliacion_grd_centro_vs_poliza.py (colapsa Grc_Importe a
(FOLIO, Grd_ID, CENTRO) vs Cargo de poliza a (FOLIO, CUENTA, CENTRO)), mas
la regla de REVERSION rescatada de layout-gastos-pasos/docs/queries/gastos/
v02_reversion.sql:

  Cuando el folio tiene IMPORTE <= -$1 (reversion), el Cargo cae en una
  cuenta de Provision/Pasivo -- no es el gasto real. El numero que sirve
  esta en el ABONO. Se compara |Grc_Importe| contra Abono en vez de Cargo
  para esos folios (Grc_Importe llega negativo, Abono en poliza siempre
  positivo).

Confirmado con los 4 folios de reversion del universo de enero 2026
(01-0034998, 01-0034999, 05-0177386, 05-0181359): las 47 filas
correspondientes cuadran 100% con esta regla (antes fallaban las 47).

Resultado (mismo universo, enero 2026): 94.05% (7,491/7,965) -- sube desde
93.35% de 04. Sigue sin resolver GASTO_RECLASIFICACION (la causa dominante
de lo que falta es que varios Grd_ID comparten Tg_Cve_Tipo_Gasto y la
poliza los consolida en una sola linea -- ver pendiente "colapsar por
Tg_Cve_Tipo_Gasto", que en pruebas sueltas ya con esta regla de reversion
dio 99.09%, pero todavia no se promueve a script).

Uso:
    python3 05_reconciliacion_grd_centro_con_reversion.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
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


GRC_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    gr.Gr_Tabla AS ORIGEN,
    grd.Grd_ID,
    grc.Cc_Cve_Centro_Costo AS CENTRO,
    SUM(grc.Grc_Importe) AS IMPORTE_GRC
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
JOIN Gasto_Registro_Control grc ON grc.Gr_Folio = grd.Gr_Folio AND grc.Grd_ID = grd.Grd_ID
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, gr.Gr_Tabla, grd.Grd_ID, grc.Cc_Cve_Centro_Costo
"""

# reusa el baseline de folio (v01_gastos_por_folio.sql en el root del proyecto original)
# para saber cuales folios son reversion -- inline aqui porque solo se necesita IMPORTE por folio
IMPORTE_FOLIO_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    SUM(grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio) AS IMPORTE
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print("[bold](Grd_ID, Centro) + regla de reversion (Abono para IMPORTE <= -$1)[/bold]")

    grc = pd.read_sql(text(GRC_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    grc["FOLIO"] = grc["FOLIO"].str.strip()

    imp = pd.read_sql(text(IMPORTE_FOLIO_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    imp["FOLIO"] = imp["FOLIO"].str.strip()
    folios_reversion = set(imp[imp.IMPORTE <= -1.0].FOLIO)
    console.print(f"  Folios de reversion en el universo: {len(folios_reversion)}")

    detalle = pd.read_sql(text(leer_query("queries/v03_detalle_cuenta_centro_costo.sql", fi, ff)), engine)
    detalle["FOLIO"] = detalle["FOLIO"].str.strip()
    detalle["VALOR"] = detalle["CARGO"]
    es_rev = detalle["FOLIO"].isin(folios_reversion)
    detalle.loc[es_rev, "VALOR"] = detalle.loc[es_rev, "ABONO"]

    pdc = detalle.groupby(["FOLIO", "CUENTA", "CENTRO_COSTO"], as_index=False).agg(IMPORTE_PD=("VALOR", "sum"))
    pdc = pdc.rename(columns={"CENTRO_COSTO": "CENTRO"})
    pdc = pdc[pdc.IMPORTE_PD != 0]

    grc["IMPORTE_GRC_CMP"] = grc["IMPORTE_GRC"]
    grc.loc[grc.FOLIO.isin(folios_reversion), "IMPORTE_GRC_CMP"] = grc.loc[
        grc.FOLIO.isin(folios_reversion), "IMPORTE_GRC"
    ].abs()

    grc_r = grc.sort_values(["FOLIO", "CENTRO", "IMPORTE_GRC_CMP"]).reset_index(drop=True)
    pdc_r = pdc.sort_values(["FOLIO", "CENTRO", "IMPORTE_PD"]).reset_index(drop=True)
    grc_r["rank"] = grc_r.groupby(["FOLIO", "CENTRO"]).cumcount()
    pdc_r["rank"] = pdc_r.groupby(["FOLIO", "CENTRO"]).cumcount()

    comp = grc_r.merge(pdc_r, on=["FOLIO", "CENTRO", "rank"], how="outer", indicator=True)
    origen_map = grc[["FOLIO", "ORIGEN"]].drop_duplicates().set_index("FOLIO")["ORIGEN"]
    comp["ORIGEN"] = comp["FOLIO"].map(origen_map).fillna("")
    comp["IMPORTE_GRC_CMP"] = comp["IMPORTE_GRC_CMP"].fillna(0)
    comp["IMPORTE_PD"] = comp["IMPORTE_PD"].fillna(0)
    comp["DIFERENCIA"] = (comp.IMPORTE_GRC_CMP - comp.IMPORTE_PD).abs()
    comp["CUADRA"] = comp.DIFERENCIA < 1

    n, c = len(comp), int(comp.CUADRA.sum())
    resumen(filas=n, cuadran=c, pct=f"{100*c/n:.2f}%")

    por_origen = comp.groupby(comp.ORIGEN.replace("", "GASTO_DIRECTO")).agg(
        filas=("FOLIO", "count"), cuadran=("CUADRA", "sum")
    )
    por_origen["pct"] = (por_origen.cuadran / por_origen.filas * 100).round(2)
    mostrar_tabla(por_origen.reset_index(), "Reconciliacion por ORIGEN")

    comp.to_csv(f"05_reconciliacion_grd_centro_con_reversion_{fi}_{ff}.csv", index=False)
    console.print(f"\n[green]Guardado: 05_reconciliacion_grd_centro_con_reversion_{fi}_{ff}.csv[/green]")


if __name__ == "__main__":
    main()
