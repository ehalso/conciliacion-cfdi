"""
layout_gastos_lib.py -- logica de negocio para el reporte de gastos por CECO.

Reusa las queries validadas de 12_reporte_base_ceco_consumo_interno.py (6
origenes: CONTROL_COMBUSTIBLE, GASTO_DIRECTO, GASTO_RECLASIFICACION,
ORDEN_COMPRA, VIAJE, CONSUMO_INTERNO -- Pd_Tipo real, sin mascara de
reversion. Ver PROGRESS.md para el detalle completo de como se llego a
esta reconciliacion: 100% los 5 normales, 99.12% CONSUMO_INTERNO, 99.75%
total, enero 2026).

A diferencia de 12 (que exporta TIPO_MOVIMIENTO + IMPORTE, una sola columna
de valor), aqui se pivota a CARGO/ABONO como columnas separadas -- formato
mas natural para un reporte tabular.

Pivote seguro, confirmado 2026-09-03 contra datos reales (enero y
enero-marzo 2026): a nivel (FOLIO, CECO, TIPO_GASTO) nunca hay mas de un
TIPO_MOVIMIENTO en la misma fila -- incluido el folio residual conocido de
GASTO_RECLASIFICACION que mezcla Cargo y Abono en el mismo centro
(0005-0182622, centro 103): ahi caen en TIPO_GASTO distintos (uno real,
otro NaN por ser la linea de poliza sin match operativo), nunca compiten
por la misma fila.
"""
import sys

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, "/home/esteban/trivasa/connections")
from connection_205_trivasadb3 import engine  # default de exploracion


# --- Lado poliza real, 5 origenes normales (identica a 11/12) ---
POLIZA_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    pl.Pl_Folio AS POLIZA,
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
    gr.Sc_Cve_Sucursal, gr.Gr_Folio, pl.Pl_Folio,
    pd.Cc_Cve_Cuenta_Contable, cc.Cc_Descripcion,
    pd.Pd_Centro_Costo, cco.Cc_Descripcion,
    pd.Pd_Tipo
"""

# --- Lado poliza real, CONSUMO_INTERNO (filtra la poliza de gasto real,
# excluye la memo de inventario) ---
POLIZA_SQL_CI = """
SELECT
    gr.Gr_Folio AS FOLIO,
    pl.Pl_Folio AS POLIZA,
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
  AND gr.Gr_Tabla = 'CONSUMO_INTERNO'
  AND UPPER(ISNULL(pl.Pl_Comentario, '')) NOT LIKE '%CUENTAS DE ORDEN%'
  AND UPPER(ISNULL(pl.Pl_Comentario, '')) NOT LIKE '%CTS ORDEN%'
  AND UPPER(ISNULL(pl.Pl_Comentario, '')) NOT LIKE '%CUENTA ORDEN%'
  AND pd.Pd_Centro_Costo <> ''
GROUP BY
    gr.Sc_Cve_Sucursal, gr.Gr_Folio, pl.Pl_Folio,
    pd.Cc_Cve_Cuenta_Contable, cc.Cc_Descripcion,
    pd.Pd_Centro_Costo, cco.Cc_Descripcion,
    pd.Pd_Tipo
"""

# --- GASTO_REGISTRO_NOMINA -- lado operativo. No existe FK real
# Tipo_Gasto->Cuenta_Contable (Tg_Cuenta_Contable vacio en los 249 tipos de
# gasto) -- se trae CONCEPTO (Tg_Descripcion normalizado) para matchear del
# lado poliza por texto exacto. Es el UNICO metodo que dio 1:1 sin huerfanos
# (confirmado 2026-09-03: 6,591/6,591, ver 13_reconciliacion_nomina_ceco.py)
# -- por eso aqui NO se usa rank-pairing como los demas origenes, se hace
# join directo por (FOLIO, CECO, CONCEPTO).
GRC_SQL_NOMINA = """
SELECT
    gr.Gr_Folio AS FOLIO,
    grd.Tg_Cve_Tipo_Gasto AS TIPO_GASTO,
    tg.Tg_Descripcion AS TIPO_GASTO_DESCRIPCION,
    UPPER(LTRIM(RTRIM(tg.Tg_Descripcion))) AS CONCEPTO,
    grc.Cc_Cve_Centro_Costo AS CECO,
    SUM(grc.Grc_Importe) AS IMPORTE_GRC
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
JOIN Gasto_Registro_Control grc ON grc.Gr_Folio = grd.Gr_Folio AND grc.Grd_ID = grd.Grd_ID
JOIN Tipo_Gasto tg ON tg.Tg_Cve_Tipo_Gasto = grd.Tg_Cve_Tipo_Gasto
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND gr.Gr_Tabla = 'GASTO_REGISTRO_NOMINA'
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, grd.Tg_Cve_Tipo_Gasto, tg.Tg_Descripcion, grc.Cc_Cve_Centro_Costo
"""

# --- GASTO_REGISTRO_NOMINA -- lado poliza. Pd_Tipo real (insight de 12:
# no asumir Cargo como hacia 13) -- confirmado 2026-09-03 que igual sale
# 100% Cargo, 0% Abono con centro real. CONCEPTO normalizado (Cc_Descripcion)
# para el join de texto. Lineas SIN centro (reclasificaciones de pasivo:
# ISR, IMSS, sueldos por pagar...) se excluyen igual que en POLIZA_SQL.
POLIZA_SQL_NOMINA = """
SELECT
    gr.Gr_Folio AS FOLIO,
    pl.Pl_Folio AS POLIZA,
    pd.Cc_Cve_Cuenta_Contable AS CUENTA,
    cc.Cc_Descripcion AS CUENTA_DESCRIPCION,
    UPPER(LTRIM(RTRIM(cc.Cc_Descripcion))) AS CONCEPTO,
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
  AND gr.Gr_Tabla = 'GASTO_REGISTRO_NOMINA'
  AND pd.Pd_Centro_Costo <> ''
GROUP BY
    gr.Sc_Cve_Sucursal, gr.Gr_Folio, pl.Pl_Folio,
    pd.Cc_Cve_Cuenta_Contable, cc.Cc_Descripcion,
    pd.Pd_Centro_Costo, cco.Cc_Descripcion,
    pd.Pd_Tipo
"""

# --- Lado operativo, 6 origenes unificados (solo excluye NOMINA) ---
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

# --- Importe nativo de folio ("Importe reporte MPRO") -- NO es Cargo/Abono
# de poliza, es el importe operativo de Gasto_Registro_Documento, misma
# formula que 01_baseline_ceco_grc.py, validada 1:1 contra el export real
# de MPRO (v0.1 "reporte nativo" en trivasa-context: $39,469,269.50 vs
# $39,469,269.59, enero 2026). 1 valor por FOLIO, no por (FOLIO,CECO,
# TIPO_GASTO) -- hay que deduplicar por FOLIO antes de sumar, ver
# reporte_completo().
IMPORTE_FOLIO_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    SUM(grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio) AS IMPORTE_FOLIO
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') <> 'GASTO_REGISTRO_NOMINA'
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio
"""

IMPORTE_FOLIO_SQL_NOMINA = """
SELECT
    gr.Gr_Folio AS FOLIO,
    SUM(grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio) AS IMPORTE_FOLIO
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND gr.Gr_Tabla = 'GASTO_REGISTRO_NOMINA'
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio
"""


def _emparejar(g_r, p_r, llave):
    """Rank-pairing: ordena ambos lados por valor dentro de `llave`, asigna
    rank por posicion, empareja por (llave, rank). Ver PROGRESS.md -- no
    existe llave real Grc_ID <-> Poliza_Detalle."""
    g_r = g_r.sort_values(llave + ["VALOR_CMP"]).reset_index(drop=True)
    p_r = p_r.sort_values(llave + ["IMPORTE_PD"]).reset_index(drop=True)
    g_r["rank"] = g_r.groupby(llave).cumcount()
    p_r["rank"] = p_r.groupby(llave).cumcount()
    return g_r.merge(p_r, on=llave + ["rank"], how="outer")


def reporte_completo(fecha_ini: str, fecha_fin: str, incluir_nomina: bool = False) -> pd.DataFrame:
    """Reporte base CECO, grano (FOLIO, CECO, TIPO_GASTO), con columnas
    CARGO/ABONO separadas (nunca ambas != 0 en la misma fila -- ver
    docstring del modulo). 6 origenes por default; con `incluir_nomina=True`
    agrega GASTO_REGISTRO_NOMINA como 7mo origen -- ahi el emparejamiento
    NO es rank-pairing (no aplica, no hay llave real ni siquiera posicional
    confiable) sino join directo por texto (FOLIO, CECO, CONCEPTO), el unico
    metodo que dio 1:1 exacto para nomina (ver GRC_SQL_NOMINA/POLIZA_SQL_
    NOMINA arriba)."""
    p = {"fecha_ini": fecha_ini, "fecha_fin": fecha_fin}

    grc = pd.read_sql(text(GRC_SQL), engine, params=p)
    grc["FOLIO"] = grc["FOLIO"].str.strip()

    COLS_DETALLE = ["FOLIO", "POLIZA", "CUENTA", "CUENTA_DESCRIPCION", "CECO", "CECO_DESCRIPCION", "TIPO_MOVIMIENTO"]

    detalle = pd.read_sql(text(POLIZA_SQL), engine, params=p)
    detalle["FOLIO"] = detalle["FOLIO"].str.strip()
    detalle = detalle.groupby(COLS_DETALLE, as_index=False).agg(IMPORTE=("IMPORTE", "sum"))

    detalle_ci = pd.read_sql(text(POLIZA_SQL_CI), engine, params=p)
    detalle_ci["FOLIO"] = detalle_ci["FOLIO"].str.strip()
    detalle_ci = detalle_ci.groupby(COLS_DETALLE, as_index=False).agg(IMPORTE=("IMPORTE", "sum"))

    es_reclasificacion = grc.ORIGEN == "GASTO_RECLASIFICACION"
    es_consumo_interno = grc.ORIGEN == "CONSUMO_INTERNO"

    # GASTO_RECLASIFICACION -- signo de Grc_Importe por linea decide Cargo/Abono
    recla = grc[es_reclasificacion].copy()
    recla["VALOR_CMP"] = recla["IMPORTE_GRC"].abs()
    recla["TIPO_MOVIMIENTO"] = recla["IMPORTE_GRC"].apply(lambda x: "CARGO" if x > 0 else "ABONO")
    pdc_recla = detalle[detalle.FOLIO.isin(recla.FOLIO.unique()) & (detalle.IMPORTE != 0)].rename(
        columns={"IMPORTE": "IMPORTE_PD"}
    )
    comp_recla = _emparejar(recla, pdc_recla, ["FOLIO", "CECO", "TIPO_MOVIMIENTO"])
    comp_recla["ORIGEN"] = "GASTO_RECLASIFICACION"

    # Los 4 origenes normales restantes -- abs siempre, Pd_Tipo real decide
    resto = grc[~es_reclasificacion & ~es_consumo_interno].copy()
    resto["VALOR_CMP"] = resto["IMPORTE_GRC"].abs()
    pdc_resto = detalle[(detalle.IMPORTE != 0) & (~detalle.FOLIO.isin(recla.FOLIO.unique()))].rename(
        columns={"IMPORTE": "IMPORTE_PD"}
    )
    comp_resto = _emparejar(resto, pdc_resto, ["FOLIO", "CECO"])
    origen_map = grc[["FOLIO", "ORIGEN"]].drop_duplicates().set_index("FOLIO")["ORIGEN"]
    comp_resto["ORIGEN"] = comp_resto["FOLIO"].map(origen_map)

    # CONSUMO_INTERNO -- su propia poliza (filtro de doble poliza)
    ci = grc[es_consumo_interno].copy()
    ci["VALOR_CMP"] = ci["IMPORTE_GRC"].abs()
    pdc_ci = detalle_ci[detalle_ci.IMPORTE != 0].rename(columns={"IMPORTE": "IMPORTE_PD"})
    comp_ci = _emparejar(ci, pdc_ci, ["FOLIO", "CECO"])
    comp_ci["ORIGEN"] = "CONSUMO_INTERNO"

    partes = [comp_recla, comp_resto, comp_ci]

    # GASTO_REGISTRO_NOMINA -- join directo por texto, no rank-pairing.
    if incluir_nomina:
        grc_nom = pd.read_sql(text(GRC_SQL_NOMINA), engine, params=p)
        grc_nom["FOLIO"] = grc_nom["FOLIO"].str.strip()

        pd_nom = pd.read_sql(text(POLIZA_SQL_NOMINA), engine, params=p)
        pd_nom["FOLIO"] = pd_nom["FOLIO"].str.strip()
        pd_nom = pd_nom.groupby(
            ["FOLIO", "POLIZA", "CUENTA", "CUENTA_DESCRIPCION", "CONCEPTO", "CECO", "CECO_DESCRIPCION", "TIPO_MOVIMIENTO"],
            as_index=False,
        ).agg(IMPORTE=("IMPORTE", "sum"))

        comp_nom = grc_nom.merge(pd_nom, on=["FOLIO", "CECO", "CONCEPTO"], how="outer")
        comp_nom["VALOR_CMP"] = comp_nom["IMPORTE_GRC"].fillna(0)
        comp_nom["IMPORTE_PD"] = comp_nom["IMPORTE"]
        comp_nom["ORIGEN"] = "GASTO_REGISTRO_NOMINA"
        partes.append(comp_nom)

    comp = pd.concat(partes, ignore_index=True)
    comp["DIFERENCIA"] = (comp.VALOR_CMP.fillna(0) - comp.IMPORTE_PD.fillna(0)).abs()
    comp["CUADRA"] = comp.DIFERENCIA < 1

    # --- pivote a CARGO/ABONO -- seguro, ver docstring del modulo ---
    comp["CARGO"] = comp.IMPORTE_PD.where(comp.TIPO_MOVIMIENTO == "CARGO", 0).fillna(0)
    comp["ABONO"] = comp.IMPORTE_PD.where(comp.TIPO_MOVIMIENTO == "ABONO", 0).fillna(0)

    reporte = comp[[
        "FOLIO", "POLIZA", "ORIGEN", "TIPO_GASTO", "TIPO_GASTO_DESCRIPCION",
        "CECO", "CECO_DESCRIPCION", "CUENTA", "CUENTA_DESCRIPCION",
        "CARGO", "ABONO", "CUADRA", "DIFERENCIA",
    ]].copy()

    # Residual conocido (<0.06% del universo, ver PROGRESS.md): filas sin
    # match de un lado u otro quedan con NaN -- se etiquetan explicito en
    # vez de dejarlas en blanco en la tabla.
    reporte["ORIGEN"] = reporte["ORIGEN"].fillna("SIN_MATCH")
    reporte["TIPO_GASTO"] = reporte["TIPO_GASTO"].fillna("(residual)")
    reporte["TIPO_GASTO_DESCRIPCION"] = reporte["TIPO_GASTO_DESCRIPCION"].fillna("Linea de poliza sin match operativo")
    reporte["CUENTA"] = reporte["CUENTA"].fillna("(residual)")
    reporte["CUENTA_DESCRIPCION"] = reporte["CUENTA_DESCRIPCION"].fillna("Linea operativa sin match en poliza")
    reporte["POLIZA"] = reporte["POLIZA"].fillna("(residual)")

    # Importe nativo de folio ("Importe reporte MPRO") -- 1 valor por
    # FOLIO, se pega repetido en cada una de sus N filas (una por CECO x
    # TIPO_GASTO); quien lo consuma debe deduplicar por FOLIO antes de
    # sumar (ver resumen_qa/reporte_ui.py -- nunca sumar esta columna tal
    # cual sobre el dataframe completo).
    imp = pd.read_sql(text(IMPORTE_FOLIO_SQL), engine, params=p)
    imp["FOLIO"] = imp["FOLIO"].str.strip()
    if incluir_nomina:
        imp_nom = pd.read_sql(text(IMPORTE_FOLIO_SQL_NOMINA), engine, params=p)
        imp_nom["FOLIO"] = imp_nom["FOLIO"].str.strip()
        imp = pd.concat([imp, imp_nom], ignore_index=True)
    reporte = reporte.merge(imp, on="FOLIO", how="left")

    return reporte.reset_index(drop=True)


def resumen_por_folio(df: pd.DataFrame) -> pd.DataFrame:
    """Reconciliacion a nivel FOLIO (no fila) -- compara Cargo-Abono del
    folio completo (sumado sobre todas sus filas de CECO x TIPO_GASTO)
    contra su importe nativo (IMPORTE_FOLIO, "Importe reporte MPRO").

    Mas simple y mas robusta que el CUADRA a nivel fila: ese depende del
    rank-pairing (llave posicional, ver PROGRESS.md) y hereda su residual
    conocido; esta solo pregunta "¿el folio completo cierra?", sin
    importar como se repartieron sus lineas entre centros/tipos de gasto.
    1 fila por folio."""
    por_folio = df.groupby(["FOLIO", "ORIGEN"], as_index=False).agg(
        CARGO=("CARGO", "sum"), ABONO=("ABONO", "sum")
    )
    imp = df.drop_duplicates("FOLIO")[["FOLIO", "IMPORTE_FOLIO"]]
    por_folio = por_folio.merge(imp, on="FOLIO", how="left")
    por_folio["DIFERENCIA"] = (por_folio.CARGO - por_folio.ABONO) - por_folio.IMPORTE_FOLIO
    por_folio["CUADRA"] = por_folio.DIFERENCIA.abs() < 1
    return por_folio


def resumen_qa(df: pd.DataFrame) -> pd.DataFrame:
    """Tabla de %cuadre por origen -- para la pestana de Reconciliacion.
    A nivel FOLIO (ver resumen_por_folio), no a nivel fila."""
    pf = resumen_por_folio(df)
    r = pf.groupby("ORIGEN").agg(
        folios=("FOLIO", "count"), cuadran=("CUADRA", "sum"),
        cargo=("CARGO", "sum"), abono=("ABONO", "sum"),
    )
    r["pct"] = (r.cuadran / r.folios * 100).round(2)
    return r.reset_index().sort_values("folios", ascending=False)
