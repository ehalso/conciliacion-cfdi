"""
Bloque poliza (57-60 + Fecha/Tipo/Numero/Concepto de poliza) -- reemplaza a
18_generalizar_reconstruccion_configs.py como fuente del reporte final.

Hallazgo 2026-09-11 (conversacion): reconstruir_config() (14/15/
poliza_configuracion_lib.py) resuelve un problema que este entregable NO
necesita -- atribuir cada linea de poliza a su Tipo_Gasto de origen (algo
que si necesita CONT-1/CONT-2, pero el Word nunca pide Tipo_Gasto). Sin
esa necesidad, el JOIN DIRECTO a Poliza_Detalle por
`Pd_Referencia = Gr_Folio` (identico a layout_gastos_60col/legado/
layout-gastos-pasos/docs/queries/gastos/v03_detalle_cuenta_centro_costo.sql,
ya "100% reconciliado" segun RESUMEN_CASOS.md) da Cargo/Abono exactos, sin
ambiguedad, para los 5 origenes -- incluido GASTO_RECLASIFICACION, que
reconstruir_config() no podia cubrir completo (solo traia el lado Cargo
de la config 0371, nunca el lado Abono del par espejo).

Ademas elimina la regla de reversion que reconstruir_config() si necesitaba
(IMPORTE_FOLIO <= -$1 -> tratar como Abono): aqui no hace falta, `Pd_Tipo`
ya dice Cargo o Abono linea por linea, sin heuristica.

`Pd_Centro_Costo <> ''` es el filtro que importa: las lineas sin centro
(reclasificaciones de pasivo, Provision en reversion) no son parte del
gasto por CECO -- sin este filtro, un folio de reversion sumaria Cargo=
Abono=mismo monto y se cancelaria a 0 en vez de reflejar el monto negativo
real. Mismo filtro que ya usa layout_gastos_lib.POLIZA_SQL.

reconstruir_config() (script 18) NO se descarta -- queda como cross-check
independiente ya hecho (99.98% de coincidencia confirmada), no como fuente.

Uso:
    python3 24_bloque_poliza_directo.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # ruta relativa -- no asumir usuario/maquina

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from sqlalchemy import text

from connection_205_trivasadb3 import engine
from helpers_output import console, mostrar_tabla, resumen

EMPRESA = "0001"

POLIZA_DIRECTO_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    CASE WHEN ISNULL(gr.Gr_Tabla,'')='' THEN 'GASTO_DIRECTO' ELSE gr.Gr_Tabla END AS ORIGEN,
    pl.Pl_Folio AS POLIZA,
    pl.Pl_Fecha AS FECHA_POLIZA,
    pl.Pl_Tipo AS TIPO_POLIZA,
    pl.Pl_Numero AS NUMERO_POLIZA,
    pl.Pl_Comentario AS CONCEPTO_POLIZA,
    pd.Cc_Cve_Cuenta_Contable AS CUENTA_REGISTRO,
    cc.Cc_Descripcion AS NOMBRE_CUENTA_REGISTRO,
    pd.Pd_Centro_Costo AS CECO,
    cco.Cc_Descripcion AS CECO_DESCRIPCION,
    CASE WHEN pd.Pd_Tipo = 1 THEN pd.Pd_Importe ELSE 0 END AS CARGO,
    CASE WHEN pd.Pd_Tipo = 2 THEN pd.Pd_Importe ELSE 0 END AS ABONO
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc ON plc.Pc_Tabla = 'GASTO_REGISTRO' AND plc.Pc_Documento = gr.Gr_Folio AND plc.Es_Cve_Estado <> 'CA'
JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio AND pl.Es_Cve_Estado <> 'CA'
JOIN Poliza_Detalle pd ON pd.Pl_Folio = plc.Pl_Folio AND pd.Pd_Referencia = gr.Gr_Folio
LEFT JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable
LEFT JOIN Centro_Costo cco ON cco.Cc_Cve_Centro_Costo = pd.Pd_Centro_Costo
WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = :emp
  AND pd.Pd_Centro_Costo <> ''
  -- CONSUMO_INTERNO genera 2 polizas paralelas por folio (memo de
  -- inventario 10500/10600 vs. gasto real) -- se filtra la de memo por
  -- comentario. Probado 2026-09-11: filtrar por raiz de cuenta (6xxx) en
  -- vez de comentario excluye 1,319 de 2,970 folios legitimos (muchas
  -- cuentas de gasto real NO son 6xxx) -- descartado, el comentario es
  -- mas completo pese a su bug conocido (ver 05-0174748 en conversacion,
  -- una "Provision" que se escapa del filtro, 1 folio/$64.51 en todo el
  -- trimestre, no vale la pena arriesgar el otro camino para cerrarlo).
  AND (
        ISNULL(gr.Gr_Tabla, '') <> 'CONSUMO_INTERNO'
        OR (
            UPPER(ISNULL(pl.Pl_Comentario,'')) NOT LIKE '%CUENTAS DE ORDEN%'
        AND UPPER(ISNULL(pl.Pl_Comentario,'')) NOT LIKE '%CTS ORDEN%'
        AND UPPER(ISNULL(pl.Pl_Comentario,'')) NOT LIKE '%CUENTA ORDEN%'
        )
      )
"""

# Rama de capitalizacion de activo fijo de CONSUMO_INTERNO (configs 0295/
# 0414) -- resuelta 2026-09-08 (PROGRESS.md) en
# 12_reporte_base_ceco_consumo_interno.py, nunca portada a layout_gastos_lib.py
# (CONT-1/CONT-2) ni usada hasta ahora en este trabajo. Estos folios NO
# aparecen en POLIZA_DIRECTO_SQL porque su Pd_Referencia es el codigo corto
# Gr_Referencia (ej. "445"), no Gr_Folio -- el join principal simplemente
# no los encuentra (no hay riesgo de doble conteo entre las dos consultas).
POLIZA_CI_ACTIVO_FIJO_SQL = """
SELECT
    pl.Pl_Folio AS POLIZA,
    pl.Pl_Fecha AS FECHA_POLIZA,
    pl.Pl_Tipo AS TIPO_POLIZA,
    pl.Pl_Numero AS NUMERO_POLIZA,
    pl.Pl_Comentario AS CONCEPTO_POLIZA,
    pd.Pd_Referencia AS REFERENCIA,
    pd.Cc_Cve_Cuenta_Contable AS CUENTA_REGISTRO,
    cc.Cc_Descripcion AS NOMBRE_CUENTA_REGISTRO,
    pd.Pd_Centro_Costo AS CECO,
    cco.Cc_Descripcion AS CECO_DESCRIPCION,
    pd.Pd_Importe AS IMPORTE_PD
FROM Poliza pl
JOIN Poliza_Detalle pd ON pd.Pl_Folio = pl.Pl_Folio
LEFT JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable
LEFT JOIN Centro_Costo cco ON cco.Cc_Cve_Centro_Costo = pd.Pd_Centro_Costo
WHERE pl.Es_Cve_Estado <> 'CA'
  AND pl.Pl_Configuracion IN ('0295', '0414')
  AND pl.Pl_Fecha >= :fi AND pl.Pl_Fecha < :ff
  AND pd.Pd_Tipo = 1
  AND pd.Pd_Centro_Costo <> ''
"""

# Gr_Referencia NO es unico dentro de una poliza -- se resuelve con
# rank-pairing por (POLIZA, REFERENCIA), misma tecnica ya validada en 12.
GR_REFERENCIA_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    gr.Gr_Referencia AS REFERENCIA,
    plc.Pl_Folio AS POLIZA,
    ABS(SUM(grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio)) AS VALOR_CMP
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = gr.Gr_Folio
JOIN Poliza_Control plc ON plc.Pc_Tabla = 'GASTO_REGISTRO' AND plc.Pc_Documento = gr.Gr_Folio AND plc.Es_Cve_Estado <> 'CA'
JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio AND pl.Es_Cve_Estado <> 'CA'
WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = :emp
  AND gr.Gr_Tabla = 'CONSUMO_INTERNO'
  AND pl.Pl_Configuracion IN ('0295', '0414')
  AND ISNULL(gr.Gr_Referencia, '') <> ''
GROUP BY gr.Gr_Folio, gr.Gr_Referencia, plc.Pl_Folio
"""


def _emparejar_activo_fijo(gr_ref, poliza_af):
    """Rank-pairing por (POLIZA, REFERENCIA) -- Gr_Referencia no es unico
    dentro de una poliza (misma tecnica ya validada en 12, 2026-09-08)."""
    g = gr_ref.sort_values(["POLIZA", "REFERENCIA", "VALOR_CMP"]).reset_index(drop=True)
    p = poliza_af.sort_values(["POLIZA", "REFERENCIA", "IMPORTE_PD"]).reset_index(drop=True)
    g["rank"] = g.groupby(["POLIZA", "REFERENCIA"]).cumcount()
    p["rank"] = p.groupby(["POLIZA", "REFERENCIA"]).cumcount()
    m = g.merge(p, on=["POLIZA", "REFERENCIA", "rank"], how="inner")
    m["ORIGEN"] = "CONSUMO_INTERNO"
    m["CARGO"] = m["IMPORTE_PD"]
    m["ABONO"] = 0.0
    return m[["FOLIO", "ORIGEN", "POLIZA", "FECHA_POLIZA", "TIPO_POLIZA", "NUMERO_POLIZA",
              "CONCEPTO_POLIZA", "CUENTA_REGISTRO", "NOMBRE_CUENTA_REGISTRO", "CECO",
              "CECO_DESCRIPCION", "CARGO", "ABONO"]]


def cargar(fi, ff):
    df = pd.read_sql(text(POLIZA_DIRECTO_SQL), engine, params={"fi": fi, "ff": ff, "emp": EMPRESA})
    df["FOLIO"] = df.FOLIO.str.strip()

    poliza_af = pd.read_sql(text(POLIZA_CI_ACTIVO_FIJO_SQL), engine, params={"fi": fi, "ff": ff})
    poliza_af["REFERENCIA"] = poliza_af.REFERENCIA.str.strip()

    gr_ref = pd.read_sql(text(GR_REFERENCIA_SQL), engine, params={"fi": fi, "ff": ff, "emp": EMPRESA})
    gr_ref["FOLIO"] = gr_ref.FOLIO.str.strip()
    gr_ref["REFERENCIA"] = gr_ref.REFERENCIA.str.strip()

    activo_fijo = _emparejar_activo_fijo(gr_ref, poliza_af)
    return pd.concat([df, activo_fijo], ignore_index=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", default="2026-01-01")
    ap.add_argument("--fecha-fin", default="2026-02-01")
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print(f"[bold]Bloque poliza, join directo -- {fi} a {ff}[/bold]\n")

    df = cargar(fi, ff)
    console.print(f"Filas: {len(df)}  |  Folios: {df.FOLIO.nunique()}\n")

    por_origen = df.groupby("ORIGEN").agg(
        folios=("FOLIO", "nunique"), cargo=("CARGO", "sum"), abono=("ABONO", "sum")
    )
    por_origen["cargo_menos_abono"] = por_origen.cargo - por_origen.abono
    mostrar_tabla(por_origen.reset_index(), "Por origen", max_filas=10)

    total_cargo = df.CARGO.sum()
    total_abono = df.ABONO.sum()
    neto = total_cargo - total_abono

    resumen(
        folios=df.FOLIO.nunique(),
        CARGO=f"{total_cargo:,.2f}",
        ABONO=f"{total_abono:,.2f}",
        CARGO_MENOS_ABONO=f"{neto:,.2f}",
    )

    out = Path(__file__).resolve().parent.parent / "layout_gastos_60col" / f"poliza_directo_{fi}_{ff}.csv"
    out.parent.mkdir(exist_ok=True)
    df.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]")
    return df


if __name__ == "__main__":
    main()
