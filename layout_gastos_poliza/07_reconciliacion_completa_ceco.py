"""
Reconciliacion completa Grc_Importe (Gasto_Registro_Control) vs Poliza_Detalle
a nivel (FOLIO, Tg_Cve_Tipo_Gasto, CENTRO), combinando las 3 reglas
encontradas en esta exploracion + la rescatada de layout-gastos-pasos:

1. Caso normal (VIAJE, CONTROL_COMBUSTIBLE, ORDEN_COMPRA, GASTO_DIRECTO):
   comparar Grc_Importe agregado por (Tipo_Gasto, Centro) contra Cargo real
   de Poliza_Detalle agregado por (Cuenta, Centro) -- ver 06.

2. Reversion (folios con IMPORTE de Gasto_Registro_Documento <= -$1, fuera
   de GASTO_RECLASIFICACION): el Cargo cae en cuenta de Provision/Pasivo,
   no es el gasto real -- comparar contra Abono. Regla rescatada de
   layout-gastos-pasos/docs/queries/gastos/v02_reversion.sql. Ver 05.

3. GASTO_RECLASIFICACION: par espejo Cargo=Abono dentro de la misma poliza
   (layout-gastos-pasos/docs/queries/gastos/v02_reclasificacion.sql,
   confirmado ahi que es simetrico y sin filtro de cuenta -- pero ese
   proyecto nunca lo bajo a nivel centro de costo, "sin dividir su detalle
   todavia" segun su propio README). Aqui se resuelve a nivel CECO con una
   regla nueva, no documentada en ningun lado anterior: el SIGNO de
   Grc_Importe por linea (no si el folio completo es negativo) dice si esa
   linea corresponde a Cargo (positivo) o Abono (negativo) de la poliza --
   confirmado con folio real 01-0037389 (centro 000028 positivo = Cargo,
   centro 000497 negativo = Abono, mismos montos espejo).

Resultado (universo sin CONSUMO_INTERNO/GASTO_REGISTRO_NOMINA):
  Enero 2026:        100.00% (7,691/7,691) -- los 5 origenes normales en 100%.
  Enero-Marzo 2026:    99.95% (17,935/17,944) -- 3 folios residuales, ver abajo.
CONSUMO_INTERNO sigue excluido -- pendiente para un script aparte, tiene su
propia estructura de doble poliza (ver docs/schema/calidad-de-datos.md en
trivasa-context).

## Residual conocido (enero-marzo, 9 filas / 3 folios) -- documentado, no resuelto

Los 3 casos son limite de la tecnica de rank-pairing (emparejar por
posicion ordenando por importe dentro de FOLIO+CENTRO -- no hay llave real
entre Grc_ID y Poliza_Detalle, ver discusion en la conversacion de origen).
Cuando el conteo de lineas no coincide exacto entre los dos lados en un
folio puntual, el orden se desalinea en cascada. No es un patron sistemico
nuevo -- son folios aislados, <0.06% del universo del trimestre.

- `0005-0182622` (GASTO_RECLASIFICACION, centro 103): desajuste de $3,894 --
  mas de una linea en ese centro con signos mezclados distinto a como los
  separo la poliza.
- `0001-0035339` (`COMPROBACION_GASTO` -- origen nuevo, no investigado
  todavia, aparece solo en el rango ampliado): $4.95 sin contraparte.
- `0023-0007297` (GASTO_DIRECTO): 4 filas con patron de "corrimiento"
  (cada valor calza con el siguiente de la poliza) -- conteo de grupos no
  coincidio exacto, rank-pairing se desalineo en cascada.

Uso:
    python3 07_reconciliacion_completa_ceco.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
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

    console.print("[bold]Reconciliacion completa: Tipo_Gasto+Centro, reversion, y signo por linea (reclasificacion)[/bold]")

    grc = pd.read_sql(text(GRC_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    grc["FOLIO"] = grc["FOLIO"].str.strip()

    imp = pd.read_sql(text(IMPORTE_FOLIO_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    imp["FOLIO"] = imp["FOLIO"].str.strip()
    folios_reversion = set(imp[imp.IMPORTE <= -1.0].FOLIO)

    detalle = pd.read_sql(text(leer_query("queries/v03_detalle_cuenta_centro_costo.sql", fi, ff)), engine)
    detalle["FOLIO"] = detalle["FOLIO"].str.strip()
    pdc = detalle.groupby(["FOLIO", "CUENTA", "CENTRO_COSTO"], as_index=False).agg(
        CARGO=("CARGO", "sum"), ABONO=("ABONO", "sum")
    )
    pdc = pdc.rename(columns={"CENTRO_COSTO": "CENTRO"})

    es_reclasificacion = grc.ORIGEN == "GASTO_RECLASIFICACION"
    es_reversion = grc.FOLIO.isin(folios_reversion) & ~es_reclasificacion

    # --- Regla 3: GASTO_RECLASIFICACION -- signo por linea decide Cargo/Abono ---
    recla = grc[es_reclasificacion].copy()
    recla["VALOR_CMP"] = recla["IMPORTE_GRC"].abs()
    recla["TIPO_ESPERADO"] = recla["IMPORTE_GRC"].apply(lambda x: "CARGO" if x > 0 else "ABONO")

    pdc_recla = pdc[pdc.FOLIO.isin(recla.FOLIO.unique())]
    pdc_cargo = pdc_recla[pdc_recla.CARGO != 0][["FOLIO", "CENTRO", "CARGO"]].rename(columns={"CARGO": "IMPORTE_PD"})
    pdc_cargo["TIPO_ESPERADO"] = "CARGO"
    pdc_abono = pdc_recla[pdc_recla.ABONO != 0][["FOLIO", "CENTRO", "ABONO"]].rename(columns={"ABONO": "IMPORTE_PD"})
    pdc_abono["TIPO_ESPERADO"] = "ABONO"
    pdc_split = pd.concat([pdc_cargo, pdc_abono])

    r_r = recla.sort_values(["FOLIO", "CENTRO", "TIPO_ESPERADO", "VALOR_CMP"]).reset_index(drop=True)
    p_r = pdc_split.sort_values(["FOLIO", "CENTRO", "TIPO_ESPERADO", "IMPORTE_PD"]).reset_index(drop=True)
    r_r["rank"] = r_r.groupby(["FOLIO", "CENTRO", "TIPO_ESPERADO"]).cumcount()
    p_r["rank"] = p_r.groupby(["FOLIO", "CENTRO", "TIPO_ESPERADO"]).cumcount()
    comp_recla = r_r.merge(p_r, on=["FOLIO", "CENTRO", "TIPO_ESPERADO", "rank"], how="outer", indicator=True)
    comp_recla["VALOR_CMP"] = comp_recla["VALOR_CMP"].fillna(0)
    comp_recla["IMPORTE_PD"] = comp_recla["IMPORTE_PD"].fillna(0)

    # --- Reglas 1+2: todo lo demas (normal + reversion de folio) ---
    resto = grc[~es_reclasificacion].copy()
    detalle["VALOR"] = detalle["CARGO"]
    detalle.loc[detalle.FOLIO.isin(folios_reversion) & (~detalle.FOLIO.isin(recla.FOLIO.unique())), "VALOR"] = (
        detalle.loc[detalle.FOLIO.isin(folios_reversion) & (~detalle.FOLIO.isin(recla.FOLIO.unique())), "ABONO"]
    )
    pdc_resto = detalle.groupby(["FOLIO", "CUENTA", "CENTRO_COSTO"], as_index=False).agg(IMPORTE_PD=("VALOR", "sum"))
    pdc_resto = pdc_resto.rename(columns={"CENTRO_COSTO": "CENTRO"})
    pdc_resto = pdc_resto[(pdc_resto.IMPORTE_PD != 0) & (~pdc_resto.FOLIO.isin(recla.FOLIO.unique()))]

    resto["VALOR_CMP"] = resto["IMPORTE_GRC"]
    resto.loc[resto.FOLIO.isin(folios_reversion), "VALOR_CMP"] = resto.loc[
        resto.FOLIO.isin(folios_reversion), "IMPORTE_GRC"
    ].abs()

    g_r = resto.sort_values(["FOLIO", "CENTRO", "VALOR_CMP"]).reset_index(drop=True)
    p_r2 = pdc_resto.sort_values(["FOLIO", "CENTRO", "IMPORTE_PD"]).reset_index(drop=True)
    g_r["rank"] = g_r.groupby(["FOLIO", "CENTRO"]).cumcount()
    p_r2["rank"] = p_r2.groupby(["FOLIO", "CENTRO"]).cumcount()
    comp_resto = g_r.merge(p_r2, on=["FOLIO", "CENTRO", "rank"], how="outer", indicator=True)
    comp_resto["VALOR_CMP"] = comp_resto["VALOR_CMP"].fillna(0)
    comp_resto["IMPORTE_PD"] = comp_resto["IMPORTE_PD"].fillna(0)

    # --- Unir los dos bloques ---
    origen_map = grc[["FOLIO", "ORIGEN"]].drop_duplicates().set_index("FOLIO")["ORIGEN"]
    comp_recla["ORIGEN"] = "GASTO_RECLASIFICACION"
    comp_resto["ORIGEN"] = comp_resto["FOLIO"].map(origen_map).fillna("")

    cols = ["FOLIO", "ORIGEN", "CENTRO", "VALOR_CMP", "IMPORTE_PD", "_merge"]
    comp = pd.concat([comp_recla[cols], comp_resto[cols]], ignore_index=True)
    comp["DIFERENCIA"] = (comp.VALOR_CMP - comp.IMPORTE_PD).abs()
    comp["CUADRA"] = comp.DIFERENCIA < 1

    n, c = len(comp), int(comp.CUADRA.sum())
    resumen(filas=n, cuadran=c, pct=f"{100*c/n:.2f}%")

    por_origen = comp.groupby(comp.ORIGEN.replace("", "GASTO_DIRECTO")).agg(
        filas=("FOLIO", "count"), cuadran=("CUADRA", "sum")
    )
    por_origen["pct"] = (por_origen.cuadran / por_origen.filas * 100).round(2)
    mostrar_tabla(por_origen.reset_index(), "Reconciliacion por ORIGEN -- 07 (completa)")

    mal = comp[~comp.CUADRA]
    console.print(f"\n[bold red]Filas que NO cuadran:[/bold red] {len(mal)} ({mal.FOLIO.nunique()} folios)")
    if len(mal):
        mostrar_tabla(mal.sort_values("DIFERENCIA", ascending=False), "Muestra fuera de cuadre", max_filas=20)

    comp.to_csv(f"07_reconciliacion_completa_ceco_{fi}_{ff}.csv", index=False)
    console.print(f"\n[green]Guardado: 07_reconciliacion_completa_ceco_{fi}_{ff}.csv[/green]")


if __name__ == "__main__":
    main()
