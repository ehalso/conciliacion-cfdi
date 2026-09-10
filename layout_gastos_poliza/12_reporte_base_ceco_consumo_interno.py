"""
Extiende 11_reporte_base_ceco.py (5 origenes "normales", 100%/99.95%,
Pd_Tipo real sin mascara) agregando CONSUMO_INTERNO como sexto origen.
GASTO_REGISTRO_NOMINA sigue excluido (fuera de alcance, nunca investigado
si tiene la misma estructura de doble poliza).

CONSUMO_INTERNO necesita una query de poliza DISTINTA a la de los otros 5
origenes -- genera DOS polizas paralelas por folio (memo de inventario
10500/10600 vs. gasto real, ver docs/schema/calidad-de-datos.md en
trivasa-context), asi que hay que filtrar la de gasto real explicito.

Filtro actualizado 2026-09-03 tras `trivasa-context/docs/proyectos/
poliza-explor/configuracion-polizas.md` -- ese documento explico la causa
raiz de la doble poliza (dos `Poliza_Configuracion` activas sobre la misma
`Pc_Tabla`, una marcada "(CUENTAS DE ORDEN)") y recomendo filtrar por ahi
en vez de `Pl_Comentario`, mas robusto porque es la fuente de la regla, no
un texto derivado. Se valido contra datos reales (enero-marzo 2026, 811
polizas) que el filtro viejo (`Pl_Comentario`) y el nuevo (`Poliza_
Configuracion.Pc_Descripcion`) dan el MISMO resultado exacto -- 0
discrepancias -- siempre que se usen las 4 variantes de abreviatura que
ya traia el filtro viejo (`CUENTAS DE ORDEN` / `CTS ORDEN` / `CTS DE
ORDEN` / `CUENTA ORDEN`; la 3ra no estaba y por poco se pierde en la
primera prueba -- configs `0296`/`0481` la usan):

    JOIN Poliza_Configuracion pc ON pc.Pc_Cve_Poliza_Configuracion = pl.Pl_Configuracion
    ...
    AND UPPER(ISNULL(pc.Pc_Descripcion,'')) NOT LIKE '%CUENTAS DE ORDEN%'
    AND UPPER(ISNULL(pc.Pc_Descripcion,'')) NOT LIKE '%CTS ORDEN%'
    AND UPPER(ISNULL(pc.Pc_Descripcion,'')) NOT LIKE '%CTS DE ORDEN%'
    AND UPPER(ISNULL(pc.Pc_Descripcion,'')) NOT LIKE '%CUENTA ORDEN%'

Diferencia con 09 -- 09 asumia CONSUMO_INTERNO=Cargo siempre (su query de
poliza solo traia `SUM(CASE WHEN Pd_Tipo=1...)`, ni siquiera miraba
Abono). Aqui, igual que en 11, se trae Pd_Tipo real (GROUP BY Pd_Tipo, sin
colapsar) -- no se asume nada, se deja que el dato diga si hay Abono.
Corrido y confirmado 2026-09-03: CONSUMO_INTERNO sale 100% CARGO en
enero 2026 (0 filas ABONO) -- confirma la sospecha inicial ("son cargos")
con evidencia, no con el supuesto de 09.

Cobertura: 6 origenes (los 5 de 11 + CONSUMO_INTERNO). Resultado CONSUMO_
INTERNO solo, enero 2026: coincide con el 99.12% ya documentado (3,044/
3,071) -- ver PROGRESS.md, las 27 filas que no cuadran son folios sin
ninguna poliza de gasto real (hueco de datos conocido, concentrado en
Tg_Cve_Tipo_Gasto 0182/0183), no un problema de esta query.

Pendiente igual que antes (ver PROGRESS.md "Pendiente"):
  - ~~Filtro de doble poliza fragil (LIKE sobre texto libre)~~ -- resuelto
    2026-09-03, ver arriba.
  - ~~Rama de capitalizacion (Grd_Comentario 'U-NNN' -> Pd_Referencia=NNN
    en cuentas 1210.xxx)~~ -- resuelto 2026-09-08, PERO no como se penso:
    no hay que parsear `Grd_Comentario`. `Pd_Referencia` de esas lineas es
    copia literal de `Gasto_Registro.Gr_Referencia` (columna real, ya
    viene con el codigo corto, ej. "445") -- confirmado leyendo
    `Poliza_Configuracion_Detalle` de las 2 configs que generan esta rama
    (`0295`/`0414`, ver `trivasa-context/docs/proyectos/poliza-explor/
    configuracion-polizas.md`). Ver `POLIZA_SQL_CI_ACTIVO_FIJO` +
    `GR_REFERENCIA_SQL` abajo y PROGRESS.md entrada 2026-09-08 para el
    detalle completo (incluye el problema de colision: `Gr_Referencia` NO
    es unico dentro de una poliza -- se resuelve con la misma tecnica de
    rank-pairing que el resto del proyecto). Resultado: CONSUMO_INTERNO
    sube de 99.37% a 99.84% (enero-marzo 2026), 45/47 folios de activo
    fijo recuperados -- quedan 2 residuales (folios que reparten el gasto
    en mas de 1 centro de costo, no cubiertos por el rank-pairing simple
    por `(Pl_Folio, Referencia)`, sin CECO en la llave).

Columnas de salida: identicas a 11 (FOLIO, ORIGEN, TIPO_GASTO,
TIPO_GASTO_DESCRIPCION, CECO, CECO_DESCRIPCION, CUENTA,
CUENTA_DESCRIPCION, TIPO_MOVIMIENTO, IMPORTE).

Uso:
    python3 12_reporte_base_ceco_consumo_interno.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
"""
import argparse
import sys

sys.path.insert(0, "/home/esteban/trivasa/connections")
from connection_205_trivasadb3 import engine  # default de exploracion

import pandas as pd
from sqlalchemy import text
from helpers_output import console, mostrar_tabla, resumen


# Lado poliza real -- 5 origenes normales, identica a 11 (ya excluye
# CONSUMO_INTERNO y NOMINA del universo).
POLIZA_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    pd.Cc_Cve_Cuenta_Contable AS CUENTA,
    cc.Cc_Descripcion AS CUENTA_DESCRIPCION,
    pd.Pd_Centro_Costo AS CECO,
    cco.Cc_Descripcion AS CECO_DESCRIPCION,
    CASE WHEN pd.Pd_Tipo = 1 THEN 'CARGO' ELSE 'ABONO' END AS TIPO_MOVIMIENTO,
    SUM(pd.Pd_Importe) AS IMPORTE
FROM Gasto_Registro gr
JOIN Sucursal s
    ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
   AND plc.Es_Cve_Estado <> 'CA'
JOIN Poliza pl
    ON pl.Pl_Folio = plc.Pl_Folio
JOIN Poliza_Detalle pd
    ON pd.Pl_Folio = plc.Pl_Folio
   AND pd.Pd_Referencia = gr.Gr_Folio
LEFT JOIN Cuenta_Contable cc
    ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable
LEFT JOIN Centro_Costo cco
    ON cco.Cc_Cve_Centro_Costo = pd.Pd_Centro_Costo
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND pl.Es_Cve_Estado <> 'CA'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
  AND pd.Pd_Centro_Costo <> ''
GROUP BY
    gr.Sc_Cve_Sucursal, gr.Gr_Folio,
    pd.Cc_Cve_Cuenta_Contable, cc.Cc_Descripcion,
    pd.Pd_Centro_Costo, cco.Cc_Descripcion,
    pd.Pd_Tipo
"""

# Lado poliza real -- CONSUMO_INTERNO, misma forma que POLIZA_SQL pero
# filtrando la poliza de gasto real (excluye la memo de inventario) y
# solo este origen. Pd_Tipo real, sin asumir Cargo. Filtro de doble poliza
# via Poliza_Configuracion (no Pl_Comentario) -- ver docstring del modulo.
POLIZA_SQL_CI = """
SELECT
    gr.Gr_Folio AS FOLIO,
    pd.Cc_Cve_Cuenta_Contable AS CUENTA,
    cc.Cc_Descripcion AS CUENTA_DESCRIPCION,
    pd.Pd_Centro_Costo AS CECO,
    cco.Cc_Descripcion AS CECO_DESCRIPCION,
    CASE WHEN pd.Pd_Tipo = 1 THEN 'CARGO' ELSE 'ABONO' END AS TIPO_MOVIMIENTO,
    SUM(pd.Pd_Importe) AS IMPORTE
FROM Gasto_Registro gr
JOIN Sucursal s
    ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
   AND plc.Es_Cve_Estado <> 'CA'
JOIN Poliza pl
    ON pl.Pl_Folio = plc.Pl_Folio
JOIN Poliza_Detalle pd
    ON pd.Pl_Folio = plc.Pl_Folio
   AND pd.Pd_Referencia = gr.Gr_Folio
LEFT JOIN Cuenta_Contable cc
    ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable
LEFT JOIN Centro_Costo cco
    ON cco.Cc_Cve_Centro_Costo = pd.Pd_Centro_Costo
LEFT JOIN Poliza_Configuracion pc
    ON pc.Pc_Cve_Poliza_Configuracion = pl.Pl_Configuracion
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND pl.Es_Cve_Estado <> 'CA'
  AND gr.Gr_Tabla = 'CONSUMO_INTERNO'
  AND UPPER(ISNULL(pc.Pc_Descripcion, '')) NOT LIKE '%CUENTAS DE ORDEN%'
  AND UPPER(ISNULL(pc.Pc_Descripcion, '')) NOT LIKE '%CTS ORDEN%'
  AND UPPER(ISNULL(pc.Pc_Descripcion, '')) NOT LIKE '%CTS DE ORDEN%'
  AND UPPER(ISNULL(pc.Pc_Descripcion, '')) NOT LIKE '%CUENTA ORDEN%'
  AND pd.Pd_Centro_Costo <> ''
GROUP BY
    gr.Sc_Cve_Sucursal, gr.Gr_Folio,
    pd.Cc_Cve_Cuenta_Contable, cc.Cc_Descripcion,
    pd.Pd_Centro_Costo, cco.Cc_Descripcion,
    pd.Pd_Tipo
"""

# Rama de capitalizacion de activo fijo -- las 2 configuraciones de
# Gasto_Registro cuyo Pcd_Referencia (Poliza_Configuracion_Detalle) es
# `Gasto_Registro.Gr_Referencia`, no `Gr_Folio` (confirmado leyendo la
# tabla, ver PROGRESS.md 2026-09-08 y trivasa-context/docs/proyectos/
# poliza-explor/configuracion-polizas.md): `0295` (2018-ago 2021) y `0414`
# (sep 2021 en adelante). Solo Cargo (Pd_Tipo=1) -- el Abono de estas
# polizas usa Pd_Referencia='CONSUMO INTERNO' literal, consolidado, no
# atribuible por folio (mismo patron ya documentado para nomina/config
# 0450 en poliza_configuracion_lib.py).
POLIZA_SQL_CI_ACTIVO_FIJO = """
SELECT
    pl.Pl_Folio AS PL_FOLIO,
    pd.Pd_Referencia AS REFERENCIA,
    pd.Cc_Cve_Cuenta_Contable AS CUENTA,
    cc.Cc_Descripcion AS CUENTA_DESCRIPCION,
    pd.Pd_Centro_Costo AS CECO,
    cco.Cc_Descripcion AS CECO_DESCRIPCION,
    pd.Pd_Importe AS IMPORTE_PD
FROM Poliza pl
JOIN Poliza_Detalle pd ON pd.Pl_Folio = pl.Pl_Folio
LEFT JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable
LEFT JOIN Centro_Costo cco ON cco.Cc_Cve_Centro_Costo = pd.Pd_Centro_Costo
WHERE pl.Es_Cve_Estado <> 'CA'
  AND pl.Pl_Configuracion IN ('0295', '0414')
  AND pl.Pl_Fecha >= :fecha_ini AND pl.Pl_Fecha < :fecha_fin
  AND pd.Pd_Tipo = 1
  AND pd.Pd_Centro_Costo <> ''
"""

# Folios de CONSUMO_INTERNO cuya poliza es una de las 2 de arriba, con su
# Gr_Referencia real -- la llave para emparejar contra POLIZA_SQL_CI_ACTIVO_FIJO.
# Gr_Referencia NO es unico dentro de una poliza (un mismo codigo de activo
# puede recibir varios folios de gasto) -- eso se resuelve en Python via
# `emparejar()` (rank-pairing por (PL_FOLIO, REFERENCIA), igual tecnica que
# el resto del proyecto para llaves sin unicidad garantizada).
GR_REFERENCIA_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    gr.Gr_Referencia AS REFERENCIA,
    plc.Pl_Folio AS PL_FOLIO
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
   AND plc.Es_Cve_Estado <> 'CA'
JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio AND pl.Es_Cve_Estado <> 'CA'
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND gr.Gr_Tabla = 'CONSUMO_INTERNO'
  AND pl.Pl_Configuracion IN ('0295', '0414')
  AND ISNULL(gr.Gr_Referencia, '') <> ''
"""

# Lado operativo: Gasto_Registro_Control colapsado por (Tipo_Gasto, Centro)
# -- unificado para los 6 origenes (antes CONSUMO_INTERNO se excluia aqui;
# ahora solo se excluye NOMINA). El split entre "5 normales" / "CONSUMO_
# INTERNO" / "GASTO_RECLASIFICACION" pasa en Python, no en el SQL.
GRC_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    CASE WHEN ISNULL(gr.Gr_Tabla, '') = '' THEN 'GASTO_DIRECTO' ELSE gr.Gr_Tabla END AS ORIGEN,
    grd.Tg_Cve_Tipo_Gasto AS TIPO_GASTO,
    tg.Tg_Descripcion AS TIPO_GASTO_DESCRIPCION,
    grc.Cc_Cve_Centro_Costo AS CECO,
    SUM(grc.Grc_Importe) AS IMPORTE_GRC
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
JOIN Gasto_Registro_Control grc ON grc.Gr_Folio = grd.Gr_Folio AND grc.Grd_ID = grd.Grd_ID
LEFT JOIN Tipo_Gasto tg ON tg.Tg_Cve_Tipo_Gasto = grd.Tg_Cve_Tipo_Gasto
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') <> 'GASTO_REGISTRO_NOMINA'
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, gr.Gr_Tabla, grd.Tg_Cve_Tipo_Gasto, tg.Tg_Descripcion, grc.Cc_Cve_Centro_Costo
"""


def emparejar(g_r, p_r, llave):
    """Rank-pairing generico: ordena ambos lados por valor dentro de
    `llave`, asigna rank por posicion, y empareja por (llave, rank).
    Misma tecnica de 07/08/11 -- ver PROGRESS.md para el porque (no
    existe llave real Grc_ID <-> Poliza_Detalle)."""
    g_r = g_r.sort_values(llave + ["VALOR_CMP"]).reset_index(drop=True)
    p_r = p_r.sort_values(llave + ["IMPORTE_PD"]).reset_index(drop=True)
    g_r["rank"] = g_r.groupby(llave).cumcount()
    p_r["rank"] = p_r.groupby(llave).cumcount()
    return g_r.merge(p_r, on=llave + ["rank"], how="outer")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print("[bold]12 -- Reporte base CECO, 6 origenes (incluye CONSUMO_INTERNO)[/bold]")

    grc = pd.read_sql(text(GRC_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    grc["FOLIO"] = grc["FOLIO"].str.strip()

    detalle = pd.read_sql(text(POLIZA_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    detalle["FOLIO"] = detalle["FOLIO"].str.strip()
    detalle = detalle.groupby(
        ["FOLIO", "CUENTA", "CUENTA_DESCRIPCION", "CECO", "CECO_DESCRIPCION", "TIPO_MOVIMIENTO"], as_index=False
    ).agg(IMPORTE=("IMPORTE", "sum"))

    detalle_ci = pd.read_sql(text(POLIZA_SQL_CI), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    detalle_ci["FOLIO"] = detalle_ci["FOLIO"].str.strip()

    # ------------------------------------------------------------------
    # Rama de capitalizacion de activo fijo (config 0295/0414) -- estos
    # folios no traen NINGUNA fila en POLIZA_SQL_CI (su Pd_Referencia no es
    # Gr_Folio) y por eso aparecian como "no concilia, Cargo=Abono=0" pese
    # a tener poliza real. Ver PROGRESS.md 2026-09-08.
    # ------------------------------------------------------------------
    poliza_af = pd.read_sql(text(POLIZA_SQL_CI_ACTIVO_FIJO), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    poliza_af["REFERENCIA"] = poliza_af["REFERENCIA"].str.strip()

    gr_ref = pd.read_sql(text(GR_REFERENCIA_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    gr_ref["FOLIO"] = gr_ref["FOLIO"].str.strip()
    gr_ref["REFERENCIA"] = gr_ref["REFERENCIA"].str.strip()
    # Importe de referencia para el rank-pairing: total del folio completo
    # (no por centro -- la llave de emparejamiento aqui es (Pl_Folio,
    # Referencia), sin CECO; 45/47 folios de este universo caen en un solo
    # centro, ver PROGRESS.md para el residual de los otros 2).
    grc_folio_total = grc.groupby("FOLIO", as_index=False)["IMPORTE_GRC"].sum()
    gr_ref = gr_ref.merge(grc_folio_total, on="FOLIO", how="left")
    gr_ref["VALOR_CMP"] = gr_ref["IMPORTE_GRC"].abs()

    comp_af = emparejar(gr_ref, poliza_af, ["PL_FOLIO", "REFERENCIA"])
    detalle_af = comp_af.dropna(subset=["FOLIO", "IMPORTE_PD"])[
        ["FOLIO", "CUENTA", "CUENTA_DESCRIPCION", "CECO", "CECO_DESCRIPCION", "IMPORTE_PD"]
    ].rename(columns={"IMPORTE_PD": "IMPORTE"})
    detalle_af["TIPO_MOVIMIENTO"] = "CARGO"

    detalle_ci = pd.concat([detalle_ci, detalle_af], ignore_index=True)
    detalle_ci = detalle_ci.groupby(
        ["FOLIO", "CUENTA", "CUENTA_DESCRIPCION", "CECO", "CECO_DESCRIPCION", "TIPO_MOVIMIENTO"], as_index=False
    ).agg(IMPORTE=("IMPORTE", "sum"))

    es_reclasificacion = grc.ORIGEN == "GASTO_RECLASIFICACION"
    es_consumo_interno = grc.ORIGEN == "CONSUMO_INTERNO"

    # ------------------------------------------------------------------
    # GASTO_RECLASIFICACION -- identico a 11.
    # ------------------------------------------------------------------
    recla = grc[es_reclasificacion].copy()
    recla["VALOR_CMP"] = recla["IMPORTE_GRC"].abs()
    recla["TIPO_MOVIMIENTO"] = recla["IMPORTE_GRC"].apply(lambda x: "CARGO" if x > 0 else "ABONO")
    pdc_recla = detalle[detalle.FOLIO.isin(recla.FOLIO.unique()) & (detalle.IMPORTE != 0)].rename(
        columns={"IMPORTE": "IMPORTE_PD"}
    )
    comp_recla = emparejar(recla, pdc_recla, ["FOLIO", "CECO", "TIPO_MOVIMIENTO"])
    comp_recla["ORIGEN"] = "GASTO_RECLASIFICACION"

    # ------------------------------------------------------------------
    # Los 4 origenes normales restantes -- identico a 11 (abs siempre,
    # Pd_Tipo real decide Cargo/Abono, sin regla de reversion).
    # ------------------------------------------------------------------
    resto = grc[~es_reclasificacion & ~es_consumo_interno].copy()
    resto["VALOR_CMP"] = resto["IMPORTE_GRC"].abs()
    pdc_resto = detalle[(detalle.IMPORTE != 0) & (~detalle.FOLIO.isin(recla.FOLIO.unique()))].rename(
        columns={"IMPORTE": "IMPORTE_PD"}
    )
    comp_resto = emparejar(resto, pdc_resto, ["FOLIO", "CECO"])
    origen_map = grc[["FOLIO", "ORIGEN"]].drop_duplicates().set_index("FOLIO")["ORIGEN"]
    comp_resto["ORIGEN"] = comp_resto["FOLIO"].map(origen_map)

    # ------------------------------------------------------------------
    # CONSUMO_INTERNO -- nuevo. Mismo patron que "resto", pero con su
    # propia query de poliza (filtro de doble poliza) y sin distincion de
    # reclasificacion/reversion -- no le aplican (ver docstring).
    # ------------------------------------------------------------------
    ci = grc[es_consumo_interno].copy()
    ci["VALOR_CMP"] = ci["IMPORTE_GRC"].abs()
    pdc_ci = detalle_ci[detalle_ci.IMPORTE != 0].rename(columns={"IMPORTE": "IMPORTE_PD"})
    comp_ci = emparejar(ci, pdc_ci, ["FOLIO", "CECO"])
    comp_ci["ORIGEN"] = "CONSUMO_INTERNO"

    # ------------------------------------------------------------------
    # Union, QA rapido (consola), y CSV del reporte (disco).
    # ------------------------------------------------------------------
    comp = pd.concat([comp_recla, comp_resto, comp_ci], ignore_index=True)
    comp["DIFERENCIA"] = (comp.VALOR_CMP.fillna(0) - comp.IMPORTE_PD.fillna(0)).abs()
    comp["CUADRA"] = comp.DIFERENCIA < 1

    n, c = len(comp), int(comp.CUADRA.sum())
    resumen(filas=n, cuadran=c, pct=f"{100*c/n:.2f}%")
    por_origen = comp.groupby(comp.ORIGEN.fillna("SIN_MATCH")).agg(
        filas=("FOLIO", "count"), cuadran=("CUADRA", "sum")
    )
    por_origen["pct"] = (por_origen.cuadran / por_origen.filas * 100).round(2)
    mostrar_tabla(por_origen.reset_index(), "QA -- por origen (5 normales deben verse igual que 11)")

    # Chequeo especifico que pidio la revision: CONSUMO_INTERNO, ?que tan
    # cierto es que "son cargos"?
    ci_mov = comp_ci.TIPO_MOVIMIENTO.value_counts(dropna=False)
    console.print(f"\n[bold]CONSUMO_INTERNO -- TIPO_MOVIMIENTO real (Pd_Tipo, sin asumir):[/bold] {ci_mov.to_dict()}")

    mal = comp[~comp.CUADRA]
    console.print(f"\n[bold red]QA -- filas que no cuadran:[/bold red] {len(mal)} ({mal.FOLIO.nunique()} folios)")

    reporte = comp[[
        "FOLIO", "ORIGEN", "TIPO_GASTO", "TIPO_GASTO_DESCRIPCION",
        "CECO", "CECO_DESCRIPCION", "CUENTA", "CUENTA_DESCRIPCION",
        "TIPO_MOVIMIENTO", "IMPORTE_PD",
    ]].rename(columns={"IMPORTE_PD": "IMPORTE"})

    mostrar_tabla(reporte.head(20), "Reporte base CECO, 6 origenes (muestra)")

    out = f"12_reporte_base_ceco_consumo_interno_{fi}_{ff}.csv"
    reporte.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]")


if __name__ == "__main__":
    main()
