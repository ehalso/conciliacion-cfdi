"""
Extiende 07_reconciliacion_completa_ceco.py (5 origenes "normales", 100%/
99.95%) agregando CONSUMO_INTERNO como sexto origen. GASTO_REGISTRO_NOMINA
sigue excluido (fuera de alcance, nunca investigado si tiene la misma
estructura de doble poliza).

CONSUMO_INTERNO necesita una query de poliza DISTINTA a la de los otros 5
origenes -- no reusa queries/v03_detalle_cuenta_centro_costo.sql. Genera
DOS polizas paralelas por folio (memo de inventario 10500/10600 vs. gasto
real, ver docs/schema/calidad-de-datos.md en trivasa-context), asi que hay
que filtrar la de gasto real explicito:

    AND UPPER(ISNULL(pl.Pl_Comentario,'')) NOT LIKE '%CUENTAS DE ORDEN%'
    AND UPPER(ISNULL(pl.Pl_Comentario,'')) NOT LIKE '%CTS ORDEN%'
    AND UPPER(ISNULL(pl.Pl_Comentario,'')) NOT LIKE '%CUENTA ORDEN%'

Confirmado que el filtro es correcto: totales cuadran exacto con lo ya
documentado en trivasa-context (Importe $6,594,522.55, Cargo gasto real
$6,388,627.47, enero 2026).

Resultado CONSUMO_INTERNO a nivel CECO (Tipo_Gasto, Centro) vs Cargo real:
99.12% (3,044/3,071, enero 2026) -- coincide con el 99.1% ya documentado
en layout-gastos/index.md (calculado en otra sesion, nunca con script
guardado hasta ahora). Las 27 filas que no cuadran son folios sin ninguna
poliza de gasto real -- hueco de datos ya conocido (concentrado en
Tg_Cve_Tipo_Gasto 0182/0183), no un problema de la query.

IMPORTANTE -- simplificacion pendiente: a CONSUMO_INTERNO NO se le aplico
la regla de reversion ni ninguna otra de las de 07 (Cargo/Abono por signo,
etc.) -- solo comparacion plana contra Cargo. Si CONSUMO_INTERNO tiene sus
propios folios de reversion, el % podria subir. Ver PROGRESS.md para el
pendiente completo (incluye ademas la nota de "resolver el filtro de doble
poliza de forma mas elegante" -- Pl_Comentario es un LIKE sobre texto
libre, funciona pero es fragil).

Uso:
    python3 09_reconciliacion_completa_con_consumo_interno.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
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


# --- 5 origenes normales (identico a 07) ---
GRC_SQL_NORMAL = """
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

# --- CONSUMO_INTERNO -- query de poliza propia (filtro de doble poliza) ---
GRC_SQL_CI = """
SELECT
    gr.Gr_Folio AS FOLIO,
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
  AND gr.Gr_Tabla = 'CONSUMO_INTERNO'
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, grd.Tg_Cve_Tipo_Gasto, grc.Cc_Cve_Centro_Costo
"""

POLIZA_SQL_CI = """
SELECT
    gr.Gr_Folio AS FOLIO,
    pd.Pd_Centro_Costo AS CENTRO,
    SUM(CASE WHEN pd.Pd_Tipo = 1 THEN pd.Pd_Importe ELSE 0 END) AS CARGO
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc ON plc.Pc_Tabla = 'GASTO_REGISTRO' AND plc.Pc_Documento = gr.Gr_Folio AND plc.Es_Cve_Estado <> 'CA'
JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio AND pl.Es_Cve_Estado <> 'CA'
JOIN Poliza_Detalle pd ON pd.Pl_Folio = plc.Pl_Folio AND pd.Pd_Referencia = gr.Gr_Folio
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND gr.Gr_Tabla = 'CONSUMO_INTERNO'
  AND UPPER(ISNULL(pl.Pl_Comentario,'')) NOT LIKE '%CUENTAS DE ORDEN%'
  AND UPPER(ISNULL(pl.Pl_Comentario,'')) NOT LIKE '%CTS ORDEN%'
  AND UPPER(ISNULL(pl.Pl_Comentario,'')) NOT LIKE '%CUENTA ORDEN%'
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, pd.Pd_Centro_Costo
"""


def reconciliar_normales(fi, ff):
    grc = pd.read_sql(text(GRC_SQL_NORMAL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    grc["FOLIO"] = grc["FOLIO"].str.strip()

    imp = pd.read_sql(text(IMPORTE_FOLIO_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    imp["FOLIO"] = imp["FOLIO"].str.strip()
    folios_reversion = set(imp[imp.IMPORTE <= -1.0].FOLIO)

    detalle = pd.read_sql(text(leer_query("queries/v03_detalle_cuenta_centro_costo.sql", fi, ff)), engine)
    detalle["FOLIO"] = detalle["FOLIO"].str.strip()

    es_reclasificacion = grc.ORIGEN == "GASTO_RECLASIFICACION"

    recla = grc[es_reclasificacion].copy()
    recla["VALOR_CMP"] = recla["IMPORTE_GRC"].abs()
    recla["TIPO_ESPERADO"] = recla["IMPORTE_GRC"].apply(lambda x: "CARGO" if x > 0 else "ABONO")
    poliza_ceco = detalle.groupby(["FOLIO", "CUENTA", "CENTRO_COSTO"], as_index=False).agg(
        CARGO=("CARGO", "sum"), ABONO=("ABONO", "sum")
    ).rename(columns={"CENTRO_COSTO": "CENTRO"})
    pdc_recla = poliza_ceco[poliza_ceco.FOLIO.isin(recla.FOLIO.unique())]
    pdc_cargo = pdc_recla[pdc_recla.CARGO != 0][["FOLIO", "CENTRO", "CARGO"]].rename(columns={"CARGO": "IMPORTE_PD"})
    pdc_cargo["TIPO_ESPERADO"] = "CARGO"
    pdc_abono = pdc_recla[pdc_recla.ABONO != 0][["FOLIO", "CENTRO", "ABONO"]].rename(columns={"ABONO": "IMPORTE_PD"})
    pdc_abono["TIPO_ESPERADO"] = "ABONO"
    pdc_split = pd.concat([pdc_cargo, pdc_abono])
    r_r = recla.sort_values(["FOLIO", "CENTRO", "TIPO_ESPERADO", "VALOR_CMP"]).reset_index(drop=True)
    p_r = pdc_split.sort_values(["FOLIO", "CENTRO", "TIPO_ESPERADO", "IMPORTE_PD"]).reset_index(drop=True)
    r_r["rank"] = r_r.groupby(["FOLIO", "CENTRO", "TIPO_ESPERADO"]).cumcount()
    p_r["rank"] = p_r.groupby(["FOLIO", "CENTRO", "TIPO_ESPERADO"]).cumcount()
    comp_recla = r_r.merge(p_r, on=["FOLIO", "CENTRO", "TIPO_ESPERADO", "rank"], how="outer")
    comp_recla["VALOR_CMP"] = comp_recla["VALOR_CMP"].fillna(0)
    comp_recla["IMPORTE_PD"] = comp_recla["IMPORTE_PD"].fillna(0)
    comp_recla["ORIGEN"] = "GASTO_RECLASIFICACION"

    resto = grc[~es_reclasificacion].copy()
    detalle["VALOR"] = detalle["CARGO"]
    m = detalle.FOLIO.isin(folios_reversion) & ~detalle.FOLIO.isin(recla.FOLIO.unique())
    detalle.loc[m, "VALOR"] = detalle.loc[m, "ABONO"]
    pdc_resto = detalle.groupby(["FOLIO", "CUENTA", "CENTRO_COSTO"], as_index=False).agg(IMPORTE_PD=("VALOR", "sum"))
    pdc_resto = pdc_resto.rename(columns={"CENTRO_COSTO": "CENTRO"})
    pdc_resto = pdc_resto[(pdc_resto.IMPORTE_PD != 0) & (~pdc_resto.FOLIO.isin(recla.FOLIO.unique()))]
    resto["VALOR_CMP"] = resto["IMPORTE_GRC"]
    resto.loc[resto.FOLIO.isin(folios_reversion), "VALOR_CMP"] = resto.loc[resto.FOLIO.isin(folios_reversion), "IMPORTE_GRC"].abs()
    g_r = resto.sort_values(["FOLIO", "CENTRO", "VALOR_CMP"]).reset_index(drop=True)
    p_r2 = pdc_resto.sort_values(["FOLIO", "CENTRO", "IMPORTE_PD"]).reset_index(drop=True)
    g_r["rank"] = g_r.groupby(["FOLIO", "CENTRO"]).cumcount()
    p_r2["rank"] = p_r2.groupby(["FOLIO", "CENTRO"]).cumcount()
    comp_resto = g_r.merge(p_r2, on=["FOLIO", "CENTRO", "rank"], how="outer")
    comp_resto["VALOR_CMP"] = comp_resto["VALOR_CMP"].fillna(0)
    comp_resto["IMPORTE_PD"] = comp_resto["IMPORTE_PD"].fillna(0)
    origen_map = grc[["FOLIO", "ORIGEN"]].drop_duplicates().set_index("FOLIO")["ORIGEN"]
    comp_resto["ORIGEN"] = comp_resto["FOLIO"].map(origen_map).fillna("")

    cols = ["FOLIO", "ORIGEN", "CENTRO", "VALOR_CMP", "IMPORTE_PD"]
    return pd.concat([comp_recla[cols], comp_resto[cols]], ignore_index=True)


def reconciliar_consumo_interno(fi, ff):
    grc = pd.read_sql(text(GRC_SQL_CI), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    grc["FOLIO"] = grc["FOLIO"].str.strip()

    pdz = pd.read_sql(text(POLIZA_SQL_CI), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    pdz["FOLIO"] = pdz["FOLIO"].str.strip()
    pdc = pdz.groupby(["FOLIO", "CENTRO"], as_index=False).agg(IMPORTE_PD=("CARGO", "sum"))
    pdc = pdc[pdc.IMPORTE_PD != 0]

    g_r = grc.sort_values(["FOLIO", "CENTRO", "IMPORTE_GRC"]).reset_index(drop=True)
    p_r = pdc.sort_values(["FOLIO", "CENTRO", "IMPORTE_PD"]).reset_index(drop=True)
    g_r["rank"] = g_r.groupby(["FOLIO", "CENTRO"]).cumcount()
    p_r["rank"] = p_r.groupby(["FOLIO", "CENTRO"]).cumcount()
    comp = g_r.merge(p_r, on=["FOLIO", "CENTRO", "rank"], how="outer")
    comp["VALOR_CMP"] = comp["IMPORTE_GRC"].fillna(0)
    comp["IMPORTE_PD"] = comp["IMPORTE_PD"].fillna(0)
    comp["ORIGEN"] = "CONSUMO_INTERNO"

    return comp[["FOLIO", "ORIGEN", "CENTRO", "VALOR_CMP", "IMPORTE_PD"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print("[bold]Reconciliacion completa CECO -- 6 origenes (incluye CONSUMO_INTERNO)[/bold]")

    normales = reconciliar_normales(fi, ff)
    consumo = reconciliar_consumo_interno(fi, ff)
    comp = pd.concat([normales, consumo], ignore_index=True)
    comp["DIFERENCIA"] = (comp.VALOR_CMP - comp.IMPORTE_PD).abs()
    comp["CUADRA"] = comp.DIFERENCIA < 1

    n, c = len(comp), int(comp.CUADRA.sum())
    resumen(filas=n, cuadran=c, pct=f"{100*c/n:.2f}%")

    por_origen = comp.groupby(comp.ORIGEN.replace("", "GASTO_DIRECTO")).agg(
        filas=("FOLIO", "count"), cuadran=("CUADRA", "sum")
    )
    por_origen["pct"] = (por_origen.cuadran / por_origen.filas * 100).round(2)
    mostrar_tabla(por_origen.reset_index(), "Reconciliacion por ORIGEN -- 09 (6 origenes)")

    mal = comp[~comp.CUADRA]
    console.print(f"\n[bold red]Filas que NO cuadran:[/bold red] {len(mal)} ({mal.FOLIO.nunique()} folios)")
    if len(mal):
        mostrar_tabla(mal.sort_values("DIFERENCIA", ascending=False), "Muestra fuera de cuadre", max_filas=20)

    comp.to_csv(f"09_reconciliacion_completa_con_consumo_interno_{fi}_{ff}.csv", index=False)
    console.print(f"\n[green]Guardado: 09_reconciliacion_completa_con_consumo_interno_{fi}_{ff}.csv[/green]")


if __name__ == "__main__":
    main()
