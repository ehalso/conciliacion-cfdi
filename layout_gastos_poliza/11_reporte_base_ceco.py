"""
Esqueleto del REPORTE (no de la validacion) de gastos por CECO.

Construido desde cero sobre la llave que 06/07 ya validaron
(Tg_Cve_Tipo_Gasto + Centro, con reglas de reversion y reclasificacion) --
a proposito NO reusa 10_detalle_layout_cuenta_centro.py, que es la query
vieja de FlexMonster heredada tal cual del proyecto historico (grano
Cuenta x Centro, sin las dimensiones operativas Origen/Tipo_Gasto que
son justo lo que este proyecto peleo por conectar).

Diferencia con 07 (validacion): 07 produce columnas de diagnostico
(VALOR_CMP, DIFERENCIA, CUADRA) para medir el % de cuadre. Este script usa
la misma tecnica de rank-pairing para el match, pero el output son campos
de reporte reales -- CUENTA y TIPO_MOVIMIENTO viajaban ya en el lado
poliza del merge de 07, solo se descartaban antes de guardar (ver 07:135-
138 y 07:177). Aqui se conservan.

Segunda diferencia, mas importante -- CARGO/ABONO ya NO se adivina con una
regla de reversion de folio (la de 05/06/07: "si IMPORTE del folio <= -$1,
usar Abono"). Esa regla existia porque queries/v03_detalle_cuenta_centro_
costo.sql (heredada de FlexMonster) colapsa Pd_Tipo (el dato REAL: 1=Cargo,
2=Abono) en dos columnas sumadas -- una vez colapsado, ya no se sabe cual
de las dos es la real para esa fila, y habia que reconstruirlo con una
senal indirecta (el total del folio del lado OPERATIVO, ni siquiera del
lado poliza). Aqui la query de poliza agrupa por Pd_Tipo en vez de
colapsarlo -- TIPO_MOVIMIENTO sale directo del dato real, cero inferencia,
cero mascara. Efecto secundario: ya no hace falta ninguna query de
"folios de reversion" -- se elimino por completo.

Grano: 1 fila por (FOLIO, TIPO_GASTO, CECO), con la linea real de
poliza que le toco por rank dentro de (FOLIO, CECO) -- no existe llave
real Grc_ID <-> Poliza_Detalle, ver PROGRESS.md para la discusion
completa de por que rank-pairing es la tecnica y sus limites conocidos
(residual <0.06% en el trimestre).

Cobertura: los 5 origenes "normales" de 07 (CONTROL_COMBUSTIBLE,
GASTO_DIRECTO, VIAJE, ORDEN_COMPRA, GASTO_RECLASIFICACION), ya validados
99.95%-100%. CONSUMO_INTERNO y GASTO_REGISTRO_NOMINA quedan fuera --
mismo alcance que 07, ver PROGRESS.md "Pendiente" para el plan de
incorporar CONSUMO_INTERNO aparte (estructura de doble poliza distinta).

Columnas de salida:
    FOLIO, ORIGEN, TIPO_GASTO, TIPO_GASTO_DESCRIPCION,
    CECO, CECO_DESCRIPCION, CUENTA, CUENTA_DESCRIPCION,
    TIPO_MOVIMIENTO, IMPORTE

Corrido y validado contra .205/TRIVASADB3 (2026-09-03): Tipo_Gasto.
Tg_Descripcion existe y resuelve. Enero 2026: 100.00% (7,691/7,691).
Enero-Marzo 2026: 99.95% (17,935/17,944), mismos 3 folios residuales de
07/PROGRESS.md.

Uso:
    python3 11_reporte_base_ceco.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
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


# Lado poliza real -- a diferencia de queries/v03_detalle_cuenta_centro_
# costo.sql (heredada de FlexMonster), NO colapsa Pd_Tipo en columnas
# Cargo/Abono -- lo deja como dimension (GROUP BY Pd_Tipo), asi
# TIPO_MOVIMIENTO sale directo del dato real, no de una regla de reversion
# inferida del lado operativo.
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
  -- Contrapartida contable normal de la poliza (Abono a Proveedores/
  -- Provision de costo estandar/Prestamos a Terceros, etc.) -- son
  -- cuentas de balance, nunca traen centro de costo real, y no les
  -- corresponde uno. Confirmado 2026-09-03: 210 filas asi en enero 2026,
  -- ninguna pertenece a un reporte "por CECO". Antes se excluian por
  -- accidente (ver docstring); ahora es explicito.
  AND pd.Pd_Centro_Costo <> ''
GROUP BY
    gr.Sc_Cve_Sucursal, gr.Gr_Folio,
    pd.Cc_Cve_Cuenta_Contable, cc.Cc_Descripcion,
    pd.Pd_Centro_Costo, cco.Cc_Descripcion,
    pd.Pd_Tipo
"""

# Lado operativo: Gasto_Registro_Control colapsado por (Tipo_Gasto, Centro)
# -- la llave ganadora de 06/07. Suma el catalogo Tipo_Gasto para su
# descripcion, dimension nueva que 07 nunca necesito exponer.
GRC_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    -- Gr_Tabla viene '' (no NULL) para GASTO_DIRECTO -- confirmado en BD
    -- (610 folios/6,531 filas CECO enero 2026, coincide con RESUMEN_CASOS.md
    -- "GASTO_DIRECTO (vacio)"). Se normaliza aqui, en la fuente, en vez de
    -- adivinarlo despues en pandas.
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
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, gr.Gr_Tabla, grd.Tg_Cve_Tipo_Gasto, tg.Tg_Descripcion, grc.Cc_Cve_Centro_Costo
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print("[bold]11 -- Reporte base CECO (Tipo_Gasto+Centro, con Cuenta y Tipo_Movimiento reales)[/bold]")

    grc = pd.read_sql(text(GRC_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    grc["FOLIO"] = grc["FOLIO"].str.strip()

    detalle = pd.read_sql(text(POLIZA_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    detalle["FOLIO"] = detalle["FOLIO"].str.strip()
    # Re-agrupar por si el .str.strip() de FOLIO fusiona filas que la SQL
    # traia distintas por relleno de CHAR (mismo resguardo que 07:121-123).
    detalle = detalle.groupby(
        ["FOLIO", "CUENTA", "CUENTA_DESCRIPCION", "CECO", "CECO_DESCRIPCION", "TIPO_MOVIMIENTO"], as_index=False
    ).agg(IMPORTE=("IMPORTE", "sum"))

    es_reclasificacion = grc.ORIGEN == "GASTO_RECLASIFICACION"

    # ------------------------------------------------------------------
    # GASTO_RECLASIFICACION -- par espejo, el signo de Grc_Importe por
    # linea decide si esa linea es Cargo (positivo) o Abono (negativo)
    # del lado OPERATIVO. Del lado poliza no hace falta decidir nada --
    # TIPO_MOVIMIENTO ya viene de Pd_Tipo.
    # ------------------------------------------------------------------
    recla = grc[es_reclasificacion].copy()
    recla["VALOR_CMP"] = recla["IMPORTE_GRC"].abs()
    recla["TIPO_MOVIMIENTO"] = recla["IMPORTE_GRC"].apply(lambda x: "CARGO" if x > 0 else "ABONO")

    pdc_recla = detalle[detalle.FOLIO.isin(recla.FOLIO.unique()) & (detalle.IMPORTE != 0)].rename(
        columns={"IMPORTE": "IMPORTE_PD"}
    )

    r_r = recla.sort_values(["FOLIO", "CECO", "TIPO_MOVIMIENTO", "VALOR_CMP"]).reset_index(drop=True)
    p_r = pdc_recla.sort_values(["FOLIO", "CECO", "TIPO_MOVIMIENTO", "IMPORTE_PD"]).reset_index(drop=True)
    r_r["rank"] = r_r.groupby(["FOLIO", "CECO", "TIPO_MOVIMIENTO"]).cumcount()
    p_r["rank"] = p_r.groupby(["FOLIO", "CECO", "TIPO_MOVIMIENTO"]).cumcount()
    comp_recla = r_r.merge(p_r, on=["FOLIO", "CECO", "TIPO_MOVIMIENTO", "rank"], how="outer")
    comp_recla["ORIGEN"] = "GASTO_RECLASIFICACION"

    # ------------------------------------------------------------------
    # Los demas 4 origenes -- normal + reversion de folio completo, ya SIN
    # distincion: Pd_Importe siempre es magnitud positiva (el signo real
    # vive en Pd_Tipo, no en el numero), asi que comparar contra abs(
    # IMPORTE_GRC) es correcto siempre -- para folios normales es un
    # abs() que no cambia nada (ya son positivos), para folios de
    # reversion es lo que antes decidia la mascara. Cero regla de
    # reversion, cero query de folios_reversion.
    # ------------------------------------------------------------------
    resto = grc[~es_reclasificacion].copy()
    resto["VALOR_CMP"] = resto["IMPORTE_GRC"].abs()

    pdc_resto = detalle[(detalle.IMPORTE != 0) & (~detalle.FOLIO.isin(recla.FOLIO.unique()))].rename(
        columns={"IMPORTE": "IMPORTE_PD"}
    )

    g_r = resto.sort_values(["FOLIO", "CECO", "VALOR_CMP"]).reset_index(drop=True)
    p_r2 = pdc_resto.sort_values(["FOLIO", "CECO", "IMPORTE_PD"]).reset_index(drop=True)
    g_r["rank"] = g_r.groupby(["FOLIO", "CECO"]).cumcount()
    p_r2["rank"] = p_r2.groupby(["FOLIO", "CECO"]).cumcount()
    comp_resto = g_r.merge(p_r2, on=["FOLIO", "CECO", "rank"], how="outer")
    # Sin fallback a GASTO_DIRECTO (07 si lo hacia) -- si un FOLIO del lado
    # poliza no aparece en grc, se queda en NaN y sale a la luz en vez de
    # mal-etiquetarse en silencio.
    origen_map = grc[["FOLIO", "ORIGEN"]].drop_duplicates().set_index("FOLIO")["ORIGEN"]
    comp_resto["ORIGEN"] = comp_resto["FOLIO"].map(origen_map)

    # ------------------------------------------------------------------
    # Union, QA rapido (consola), y CSV del reporte (disco).
    # ------------------------------------------------------------------
    comp = pd.concat([comp_recla, comp_resto], ignore_index=True)
    comp["DIFERENCIA"] = (comp.VALOR_CMP.fillna(0) - comp.IMPORTE_PD.fillna(0)).abs()
    comp["CUADRA"] = comp.DIFERENCIA < 1

    n, c = len(comp), int(comp.CUADRA.sum())
    resumen(filas=n, cuadran=c, pct=f"{100*c/n:.2f}%")
    por_origen = comp.groupby(comp.ORIGEN.fillna("SIN_MATCH")).agg(
        filas=("FOLIO", "count"), cuadran=("CUADRA", "sum")
    )
    por_origen["pct"] = (por_origen.cuadran / por_origen.filas * 100).round(2)
    mostrar_tabla(por_origen.reset_index(), "QA -- debe verse igual que 07 (validacion, no es el reporte)")

    mal = comp[~comp.CUADRA]
    console.print(f"\n[bold red]QA -- filas que no cuadran:[/bold red] {len(mal)} ({mal.FOLIO.nunique()} folios)")

    reporte = comp[[
        "FOLIO", "ORIGEN", "TIPO_GASTO", "TIPO_GASTO_DESCRIPCION",
        "CECO", "CECO_DESCRIPCION", "CUENTA", "CUENTA_DESCRIPCION",
        "TIPO_MOVIMIENTO", "IMPORTE_PD",
    ]].rename(columns={"IMPORTE_PD": "IMPORTE"})

    mostrar_tabla(reporte.head(20), "Reporte base CECO (muestra)")

    out = f"11_reporte_base_ceco_{fi}_{ff}.csv"
    reporte.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]")
    console.print(
        "[dim]Columnas: FOLIO, ORIGEN, TIPO_GASTO, TIPO_GASTO_DESCRIPCION, CECO, "
        "CECO_DESCRIPCION, CUENTA, CUENTA_DESCRIPCION, TIPO_MOVIMIENTO, IMPORTE.[/dim]"
    )


if __name__ == "__main__":
    main()
