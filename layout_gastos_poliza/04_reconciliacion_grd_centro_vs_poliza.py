"""
Colapsa Gasto_Registro_Control a nivel (FOLIO, Grd_ID, CENTRO) -- en vez del
Grc_ID crudo -- y lo compara contra Cargo real de Poliza_Detalle colapsado a
(FOLIO, CUENTA, CENTRO). El emparejamiento es por posicion (rank) dentro de
cada (FOLIO, CENTRO), ordenando por importe -- no hay una llave real entre
Grd_ID y Cuenta contable, se prueba si coinciden en cantidad y magnitud.

Origen: nace de investigar por que el join directo Grc_ID<->Poliza_Detalle
(ver 03_reconciliacion_grc_importe_vs_poliza_ceco.py) tiene fan-out --
Poliza_Detalle no tiene Grd_ID, asi que un folio con multiples documentos
que comparten centro de costo hace que cada Grc_ID matchee contra TODAS las
lineas de poliza de ese centro (ver caso real folio 01-0035004, documentado
en la conversacion). Colapsar antes de comparar evita ese fan-out.

Resultado (universo sin CONSUMO_INTERNO/GASTO_REGISTRO_NOMINA, 1,425 folios
enero 2026): 93.35% (7,444/7,974). Por ORIGEN:
  CONTROL_COMBUSTIBLE 100.00%, ORDEN_COMPRA 100.00%, GASTO_DIRECTO 95.76%,
  VIAJE 76.53%, GASTO_RECLASIFICACION 27.36%.

Diagnostico (ver 05 para la version con regla de reversion, que ya resuelve
parte de GASTO_DIRECTO): la causa dominante de las fallas NO es Grd_ID en si,
es que varios Grd_ID con el MISMO Tg_Cve_Tipo_Gasto se consolidan en una
sola linea de poliza -- agrupar por Grd_ID los deja separados. Ver pendiente
"colapsar por Tg_Cve_Tipo_Gasto en vez de Grd_ID" (todavia sin resolver /
promover a script, dio 98.36% en pruebas sueltas).

Uso:
    python3 04_reconciliacion_grd_centro_vs_poliza.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print("[bold]Grc colapsado a (Grd_ID, Centro) vs Cargo de poliza (Cuenta, Centro)[/bold]")

    grc = pd.read_sql(text(GRC_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    grc["FOLIO"] = grc["FOLIO"].str.strip()

    detalle = pd.read_sql(text(leer_query("queries/v03_detalle_cuenta_centro_costo.sql", fi, ff)), engine)
    detalle["FOLIO"] = detalle["FOLIO"].str.strip()
    pdc = detalle.groupby(["FOLIO", "CUENTA", "CENTRO_COSTO"], as_index=False).agg(IMPORTE_PD=("CARGO", "sum"))
    pdc = pdc.rename(columns={"CENTRO_COSTO": "CENTRO"})
    pdc = pdc[pdc.IMPORTE_PD != 0]

    console.print(f"  GRC colapsado (folio,grd,centro): {len(grc)} filas")
    console.print(f"  Poliza Cargo (folio,cuenta,centro): {len(pdc)} filas")

    grc_r = grc.sort_values(["FOLIO", "CENTRO", "IMPORTE_GRC"]).reset_index(drop=True)
    pdc_r = pdc.sort_values(["FOLIO", "CENTRO", "IMPORTE_PD"]).reset_index(drop=True)
    grc_r["rank"] = grc_r.groupby(["FOLIO", "CENTRO"]).cumcount()
    pdc_r["rank"] = pdc_r.groupby(["FOLIO", "CENTRO"]).cumcount()

    comp = grc_r.merge(pdc_r, on=["FOLIO", "CENTRO", "rank"], how="outer", indicator=True)
    origen_map = grc[["FOLIO", "ORIGEN"]].drop_duplicates().set_index("FOLIO")["ORIGEN"]
    comp["ORIGEN"] = comp["FOLIO"].map(origen_map).fillna("")
    comp["IMPORTE_GRC"] = comp["IMPORTE_GRC"].fillna(0)
    comp["IMPORTE_PD"] = comp["IMPORTE_PD"].fillna(0)
    comp["DIFERENCIA"] = (comp.IMPORTE_GRC - comp.IMPORTE_PD).abs()
    comp["CUADRA"] = comp.DIFERENCIA < 1

    n, c = len(comp), int(comp.CUADRA.sum())
    resumen(filas=n, cuadran=c, pct=f"{100*c/n:.2f}%")

    por_origen = comp.groupby(comp.ORIGEN.replace("", "GASTO_DIRECTO")).agg(
        filas=("FOLIO", "count"), cuadran=("CUADRA", "sum")
    )
    por_origen["pct"] = (por_origen.cuadran / por_origen.filas * 100).round(2)
    mostrar_tabla(por_origen.reset_index(), "Reconciliacion por ORIGEN")

    comp.to_csv(f"04_reconciliacion_grd_centro_{fi}_{ff}.csv", index=False)
    console.print(f"\n[green]Guardado: 04_reconciliacion_grd_centro_{fi}_{ff}.csv[/green]")


if __name__ == "__main__":
    main()
