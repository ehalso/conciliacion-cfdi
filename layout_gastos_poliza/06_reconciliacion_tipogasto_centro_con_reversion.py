"""
Colapsa Gasto_Registro_Control a nivel (FOLIO, Tg_Cve_Tipo_Gasto, CENTRO) --
en vez de (Grd_ID, Centro) como en 04/05 -- y lo compara contra Cargo real
de Poliza_Detalle colapsado a (FOLIO, CUENTA, CENTRO). Incluye la misma
regla de reversion que 05 (folios con IMPORTE <= -$1: comparar contra
Abono, no Cargo -- rescatada de layout-gastos-pasos/docs/queries/gastos/
v02_reversion.sql).

Por que Tg_Cve_Tipo_Gasto y no Grd_ID: al momento de contabilizar, el
sistema NO postea un renglon por documento -- postea un renglon por
(tipo de gasto, centro de costo), sumando todos los documentos que
compartan ambos. Caso real documentado en la conversacion: folio
01-0034885 (TELEFONIA, 7 documentos/recibos) -- colapsado por Grd_ID da 53
filas, colapsado por Tipo_Gasto da 27, EXACTO el numero de lineas reales
de la poliza, y cada una cuadra al centavo. El mismo patron aplica a
CELEBRACIONES, MANTENIMIENTO PREVENTIVO, etc. -- cualquier tipo de gasto
que se repita en varios documentos del mismo folio.

Resultado (universo sin CONSUMO_INTERNO/GASTO_REGISTRO_NOMINA, enero 2026):
99.09% (7,621/7,691). Por ORIGEN:
    CONTROL_COMBUSTIBLE  100.00% (591/591)
    GASTO_DIRECTO        100.00% (6,531/6,531)  <- resuelto
    VIAJE                100.00% (346/346)      <- resuelto de regalo,
                                                    no hizo falta logica
                                                    especial de anticipos
    ORDEN_COMPRA         100.00% (80/80)
    GASTO_RECLASIFICACION 51.05% (73/143)        <- PENDIENTE, no resuelto
                                                    por este enfoque (el
                                                    27.36% de 04/05 sube a
                                                    51.05% como efecto
                                                    colateral, no porque
                                                    el patron aplique)

Pendiente conocido: GASTO_RECLASIFICACION usa reparto por signo (positivo/
negativo, ver v02_reclasificacion.sql en layout-gastos-pasos) y
CONSUMO_INTERNO sigue excluido del universo -- ambos quedan para scripts
futuros.

Uso:
    python3 06_reconciliacion_tipogasto_centro_con_reversion.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
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
    grd.Tg_Cve_Tipo_Gasto,
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
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, gr.Gr_Tabla, grd.Tg_Cve_Tipo_Gasto, grc.Cc_Cve_Centro_Costo
"""

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

    console.print("[bold](Tg_Cve_Tipo_Gasto, Centro) + regla de reversion (Abono para IMPORTE <= -$1)[/bold]")

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

    console.print(f"  GRC colapsado (folio,tipo_gasto,centro): {len(grc)} filas")
    console.print(f"  Poliza Cargo/Abono segun corresponda (folio,cuenta,centro): {len(pdc)} filas")

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

    mal = comp[~comp.CUADRA]
    console.print(f"\n[bold red]Filas que NO cuadran:[/bold red] {len(mal)} ({mal.FOLIO.nunique()} folios)")
    if len(mal):
        cols = ["FOLIO", "ORIGEN", "CENTRO", "IMPORTE_GRC_CMP", "IMPORTE_PD", "DIFERENCIA", "_merge"]
        mostrar_tabla(mal[cols].sort_values("DIFERENCIA", ascending=False), "Muestra fuera de cuadre", max_filas=20)

    comp.to_csv(f"06_reconciliacion_tipogasto_centro_con_reversion_{fi}_{ff}.csv", index=False)
    console.print(f"\n[green]Guardado: 06_reconciliacion_tipogasto_centro_con_reversion_{fi}_{ff}.csv[/green]")


if __name__ == "__main__":
    main()
