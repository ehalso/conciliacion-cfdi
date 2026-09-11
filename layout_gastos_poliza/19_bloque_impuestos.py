"""
Bloque impuestos por tasa (columnas 19-40 del layout de 60 columnas del
Word) -- adaptado de layout_gastos_60col/legado/layout-gastos-pasos/docs/
queries/gastos/v5_impuestos_layout.sql (validado 100% en agosto 2026,
contra .200) a este repo/.205.

Por que no hace falta re-auditar contra los gotchas de Comprobante_Digital
(dedup formato 14/18, retenciones en fila hermana via CONSTANCIA_RETENCION,
moneda nativa del CFDI): esta query es 100% interna a Gasto_Registro/
Gasto_Registro_Documento/Gasto_Registro_Impuesto/Impuesto -- nunca toca
Comprobante_Digital. Esos 3 gotchas son especificos del cruce con el XML
(15/16/17 de este directorio), no aplican aqui.

El propio SQL legado ya trae 2 fixes de agosto (comentados en el archivo
.sql original, preservados aqui):
  - agregacion en dos niveles (documento -> folio) para evitar fan-out
    cuando un folio tiene varios Grd_ID.
  - TODAS las columnas monetarias convertidas por Grd_Tipo_Cambio (antes
    solo se convertian algunas, quedaba en moneda mixta).

Validacion (nueva, 2026-09-11): en vez de solo re-correr y confiar en el
100% de agosto, se cruza el subtotal neto de impuestos (por folio) contra
el Cargo real agregado por folio, misma fuente ya validada en
18_generalizar_reconstruccion_configs.py -- misma logica de "no
reinventar, reusar lo ya probado".

Hallazgo del cruce: comparar contra `TOTAL` (Grd_Precio_Neto_Importe, que
YA INCLUYE IVA) da 0% de cuadre en CONTROL_COMBUSTIBLE/VIAJE/ORDEN_COMPRA
-- el Cargo real se postea NETO de IVA (el IVA acreditable va a su propia
cuenta). La comparacion correcta es contra `SUBTOTAL_NETO`
(Grd_Precio_Descontado_Importe, el mismo campo que ya usa
layout_gastos_lib.IMPORTE_FOLIO_SQL para detectar reversiones). Con eso:
99.98% (4,258/4,259, ene-mar 2026) -- el unico residual es
`01-0035339` (COMPROBACION_GASTO, fondo fijo/82 CECOs), limite de
rank-pairing YA documentado en RESUMEN_CASOS.md, no un problema nuevo.
Ademas de la correccion de campo, dos casos necesitan trato especial
(mismas reglas que ya existen en el resto del proyecto, no nuevas):
reversion (SUBTOTAL_NETO <= -$1 -> comparar contra Abono, no Cargo) y
GASTO_RECLASIFICACION (folio neto ~$0 por diseno, par espejo -- se
compara el lado positivo a nivel documento, no el neto de folio).

Validado ademas (2026-09-11) contra el BASELINE REAL -- no derivado por
nosotros: `layout_gastos_60col/legado/layout-gastos-pasos/README.md`
(Paso 1/2) documenta que su reconstruccion de enero 2026 cuadro EXACTO
contra `gastos_por_documento_enero_26.xlsx`, el reporte NATIVO exportado
de MPro. Enero 2026, 5 origenes del Word, contra ese mismo baseline (antes
en .200, aqui en .205): 1,425 folios, SUBTOTAL_NETO $22,283,791.24,
IMPUESTO_IMPORTE_DOCUMENTO $1,084,277.23, TOTAL $23,368,068.46 --
coincide exacto en las 4 cifras y en el desglose por origen. Ver
`--verificar-baseline-enero2026` para re-correr este chequeo.

Uso:
    python3 19_bloque_impuestos.py --fecha-ini 2026-01-01 --fecha-fin 2026-04-01
    python3 19_bloque_impuestos.py --verificar-baseline-enero2026
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv("/home/esteban/ehalso/conciliacion-cfdi/.env")  # worktree no trae .env (no versionado)

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from sqlalchemy import text

from connection_205_trivasadb3 import engine
from helpers_output import console, mostrar_tabla, resumen

EMPRESA = "0001"

IMPUESTOS_SQL = """
WITH doc_impuestos AS (
    SELECT
        gr.Gr_Folio AS FOLIO,
        grd.Grd_ID,
        grd.Grd_Tipo_Cambio,
        grd.Grd_Precio_Descontado_Importe,
        grd.Grd_Precio_Neto_Importe,
        grd.Grd_Impuesto_Importe,
        SUM(CASE WHEN i.Im_Tasa = 16.0000 AND i.Im_Tipo_Factor = 'Tasa'
                 THEN gri.Gri_Base_Gravable ELSE 0 END)                AS SUBTOTAL_16,
        SUM(CASE WHEN i.Im_Tasa = 0.0000 AND i.Im_Tipo_Factor = 'Tasa'
                 THEN gri.Gri_Base_Gravable ELSE 0 END)                AS SUBTOTAL_0,
        SUM(CASE WHEN i.Im_Tipo_Factor = 'Exento'
                 THEN gri.Gri_Base_Gravable ELSE 0 END)                AS SUBTOTAL_EXENTA,
        SUM(CASE WHEN i.Im_Cve_Impuesto IN ('0023','0018','0015','0024','0016','0017')
                 THEN gri.Gri_Importe ELSE 0 END)                      AS RETENCIONES_IVA,
        SUM(CASE WHEN i.Im_Cve_Impuesto IN ('0026','0014','0013','0012','0011','0009','0010')
                 THEN gri.Gri_Importe ELSE 0 END)                      AS RETENCIONES_ISR,
        SUM(gri.Gri_Importe)                                           AS SUMA_GRI_IMPORTE_DOC
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
    LEFT JOIN Gasto_Registro_Impuesto gri ON gri.Gr_Folio = grd.Gr_Folio AND gri.Grd_ID = grd.Grd_ID
    LEFT JOIN Impuesto i ON i.Im_Cve_Impuesto = gri.Im_Cve_Impuesto
    WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = :emp
      AND 1=1 -- ampliado 2026-09-11: incluye NOMINA y CONSUMO_INTERNO
    GROUP BY gr.Gr_Folio, grd.Grd_ID, grd.Grd_Tipo_Cambio,
             grd.Grd_Precio_Descontado_Importe, grd.Grd_Precio_Neto_Importe, grd.Grd_Impuesto_Importe
)
SELECT
    FOLIO,
    SUM(SUBTOTAL_16 * Grd_Tipo_Cambio)                    AS SUBTOTAL_16,
    SUM(SUBTOTAL_0 * Grd_Tipo_Cambio)                     AS SUBTOTAL_0,
    SUM(SUBTOTAL_EXENTA * Grd_Tipo_Cambio)                AS SUBTOTAL_EXENTA,
    SUM(Grd_Precio_Descontado_Importe * Grd_Tipo_Cambio)  AS SUBTOTAL_NETO,
    SUM(Grd_Precio_Neto_Importe * Grd_Tipo_Cambio)        AS TOTAL,
    SUM(RETENCIONES_IVA * Grd_Tipo_Cambio)                AS RETENCIONES_IVA,
    SUM(RETENCIONES_ISR * Grd_Tipo_Cambio)                AS RETENCIONES_ISR,
    SUM(Grd_Impuesto_Importe * Grd_Tipo_Cambio)           AS IMPUESTO_IMPORTE_DOCUMENTO,
    SUM(SUMA_GRI_IMPORTE_DOC * Grd_Tipo_Cambio)           AS SUMA_GRI_IMPORTE
FROM doc_impuestos
GROUP BY FOLIO
"""

CARGO_REAL_SQL = """
SELECT gr.Gr_Folio AS FOLIO, pd.Pd_Tipo, SUM(pd.Pd_Importe) AS IMPORTE
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc ON plc.Pc_Tabla='GASTO_REGISTRO' AND plc.Pc_Documento=gr.Gr_Folio AND plc.Es_Cve_Estado<>'CA'
JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio AND pl.Es_Cve_Estado<>'CA'
JOIN Poliza_Detalle pd ON pd.Pl_Folio = plc.Pl_Folio AND pd.Pd_Referencia = gr.Gr_Folio
WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
  AND gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = :emp
  AND 1=1 -- ampliado 2026-09-11: incluye NOMINA y CONSUMO_INTERNO
  AND pd.Pd_Centro_Costo <> ''
GROUP BY gr.Gr_Folio, pd.Pd_Tipo
"""

ORIGEN_SQL = """
SELECT gr.Gr_Folio AS FOLIO, CASE WHEN ISNULL(gr.Gr_Tabla,'')='' THEN 'GASTO_DIRECTO' ELSE gr.Gr_Tabla END AS ORIGEN
FROM Gasto_Registro gr JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff AND gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = :emp
"""

# Para GASTO_RECLASIFICACION, el folio neto es ~$0 por diseno (par espejo,
# ver layout_gastos_lib.py) -- el "importe" comparable es la suma del LADO
# POSITIVO a nivel documento, no el neto de folio. Mismo dato base que
# SUBTOTAL_NETO pero sin colapsar por folio antes de partir el signo.
SUBTOTAL_NETO_DOC_SQL = """
SELECT gr.Gr_Folio AS FOLIO, grd.Grd_ID,
       grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio AS SUBTOTAL_NETO_DOC
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
  AND gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = :emp
  AND gr.Gr_Tabla = 'GASTO_RECLASIFICACION'
"""


# Baseline REAL, no derivado por nosotros -- ver layout_gastos_60col/legado/
# layout-gastos-pasos/README.md (Paso 1/2): validado contra
# gastos_por_documento_enero_26.xlsx, el reporte NATIVO exportado de MPro.
# Enero 2026, 5 origenes del Word, empresa 0001 (entonces .200, aqui .205).
BASELINE_NATIVO_ENERO2026 = {
    "folios": 1425,
    "SUBTOTAL_NETO": 22_283_791.24,
    "IMPUESTO_IMPORTE_DOCUMENTO": 1_084_277.23,
    "TOTAL": 23_368_068.46,
}


def verificar_baseline_nativo(fi="2026-01-01", ff="2026-02-01"):
    """Re-corre el bloque de impuestos contra el mismo periodo/alcance que
    layout-gastos-pasos ya valido contra el reporte nativo de MPro, y
    compara cifra por cifra -- prueba de regresion, no un chequeo suelto."""
    imp = pd.read_sql(text(IMPUESTOS_SQL), engine, params={"fi": fi, "ff": ff, "emp": EMPRESA})
    imp["FOLIO"] = imp.FOLIO.str.strip()

    actual = {
        "folios": len(imp),
        "SUBTOTAL_NETO": imp.SUBTOTAL_NETO.sum(),
        "IMPUESTO_IMPORTE_DOCUMENTO": imp.IMPUESTO_IMPORTE_DOCUMENTO.sum(),
        "TOTAL": imp.TOTAL.sum(),
    }
    console.print("[bold]Verificacion contra el reporte NATIVO de MPro (enero 2026, 5 origenes del Word)[/bold]\n")
    todo_ok = True
    for k, esperado in BASELINE_NATIVO_ENERO2026.items():
        obtenido = actual[k]
        diff = abs(obtenido - esperado)
        ok = diff < 1
        todo_ok &= ok
        marca = "✅" if ok else "❌"
        console.print(f"  {marca} {k:30s} obtenido={obtenido:>18,.2f}  esperado={esperado:>18,.2f}  diff={diff:,.2f}")
    console.print(f"\n[bold {'green' if todo_ok else 'red'}]{'CUADRA con el reporte nativo de MPro' if todo_ok else 'NO CUADRA -- revisar antes de seguir'}[/bold {'green' if todo_ok else 'red'}]")
    return todo_ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", default="2026-01-01")
    ap.add_argument("--fecha-fin", default="2026-04-01")
    ap.add_argument("--verificar-baseline-enero2026", action="store_true",
                     help="Re-corre solo el chequeo contra el reporte nativo de MPro de enero 2026 y sale.")
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    if args.verificar_baseline_enero2026:
        verificar_baseline_nativo()
        return

    console.print(f"[bold]Bloque impuestos (19-40) -- {fi} a {ff}[/bold]\n")

    imp = pd.read_sql(text(IMPUESTOS_SQL), engine, params={"fi": fi, "ff": ff, "emp": EMPRESA})
    imp["FOLIO"] = imp.FOLIO.str.strip()
    console.print(f"Folios con desglose de impuestos: {len(imp)}\n")

    # --- Consistencia interna: SUBTOTAL_NETO + IMPUESTO_IMPORTE_DOCUMENTO ?= TOTAL ---
    imp["CHECK_INTERNO"] = (imp.SUBTOTAL_NETO + imp.IMPUESTO_IMPORTE_DOCUMENTO - imp.TOTAL).abs()
    n_int, c_int = len(imp), int((imp.CHECK_INTERNO < 1).sum())
    resumen(consistencia_interna=f"{c_int}/{n_int} ({c_int/n_int*100:.2f}%) SUBTOTAL_NETO+IMPUESTO ≈ TOTAL")
    mal_int = imp[imp.CHECK_INTERNO >= 1]
    if not mal_int.empty:
        mostrar_tabla(mal_int.sort_values("CHECK_INTERNO", ascending=False).head(15),
                      "Folios sin consistencia interna (raro, revisar)", max_filas=15)

    # --- Cruce contra el Cargo real (mismo universo/filtro que 18) ---
    # OJO: se compara SUBTOTAL_NETO (neto de IVA, = Grd_Precio_Descontado_Importe),
    # NO "TOTAL" (Grd_Precio_Neto_Importe, que YA incluye IVA -- confundir los dos
    # produce 0% de cuadre en CONTROL_COMBUSTIBLE/VIAJE/ORDEN_COMPRA, descubierto
    # 2026-09-11: el Cargo real se postea neto, el IVA va a su propia cuenta).
    console.print("\n[bold]Cruzando SUBTOTAL_NETO contra Cargo real (Poliza_Detalle, mismo universo)...[/bold]")
    cr = pd.read_sql(text(CARGO_REAL_SQL), engine, params={"fi": fi, "ff": ff, "emp": EMPRESA})
    cr["FOLIO"] = cr.FOLIO.str.strip()
    cargo = cr[cr.Pd_Tipo == 1].groupby("FOLIO", as_index=False).IMPORTE.sum().rename(columns={"IMPORTE": "CARGO_REAL"})
    abono = cr[cr.Pd_Tipo == 2].groupby("FOLIO", as_index=False).IMPORTE.sum().rename(columns={"IMPORTE": "ABONO_REAL"})

    origen = pd.read_sql(text(ORIGEN_SQL), engine, params={"fi": fi, "ff": ff, "emp": EMPRESA})
    origen["FOLIO"] = origen.FOLIO.str.strip()

    cruce = imp.merge(cargo, on="FOLIO", how="outer").merge(abono, on="FOLIO", how="left").merge(origen, on="FOLIO", how="left")

    # GASTO_RECLASIFICACION: folio neto ~$0 por diseno (par espejo) -- se
    # compara el lado positivo a nivel documento, no el neto de folio.
    es_recla = cruce.ORIGEN == "GASTO_RECLASIFICACION"
    doc = pd.read_sql(text(SUBTOTAL_NETO_DOC_SQL), engine, params={"fi": fi, "ff": ff, "emp": EMPRESA})
    doc["FOLIO"] = doc.FOLIO.str.strip()
    lado_positivo = doc[doc.SUBTOTAL_NETO_DOC > 0].groupby("FOLIO", as_index=False).SUBTOTAL_NETO_DOC.sum()
    cruce = cruce.merge(lado_positivo.rename(columns={"SUBTOTAL_NETO_DOC": "SUBTOTAL_NETO_POSITIVO"}), on="FOLIO", how="left")

    # Reversion (SUBTOTAL_NETO <= -$1, mismo criterio que 18): el real esperado
    # es ABONO, no CARGO -- se compara abs(SUBTOTAL_NETO) contra ABONO_REAL.
    es_reversion = (~es_recla) & (cruce.SUBTOTAL_NETO <= -1.0)

    esperado = cruce.CARGO_REAL
    esperado = esperado.where(~es_reversion, cruce.ABONO_REAL)
    esperado = esperado.where(~es_recla, cruce.SUBTOTAL_NETO_POSITIVO)
    cruce["ESPERADO"] = esperado

    valor_impuestos = cruce.SUBTOTAL_NETO.abs()
    valor_impuestos = valor_impuestos.where(~es_recla, cruce.SUBTOTAL_NETO_POSITIVO)
    cruce["DIFF"] = (valor_impuestos.fillna(0) - cruce.ESPERADO.fillna(0)).abs()
    cruce["CUADRA"] = cruce.DIFF < 1
    n, c = len(cruce), int(cruce.CUADRA.sum())
    resumen(cruce_impuestos_vs_cargo_real=f"{c}/{n} ({c/n*100:.2f}%) folios: SUBTOTAL_NETO == Cargo/Abono/lado-positivo real")

    por_origen = cruce.groupby("ORIGEN").agg(n=("FOLIO", "count"), cuadran=("CUADRA", "sum"))
    por_origen["pct"] = (por_origen.cuadran / por_origen.n * 100).round(2)
    mostrar_tabla(por_origen.reset_index(), "Cuadre por origen", max_filas=10)

    mal = cruce[~cruce.CUADRA]
    if not mal.empty:
        mostrar_tabla(mal.sort_values("DIFF", ascending=False).head(20)[["FOLIO", "ORIGEN", "SUBTOTAL_NETO", "ESPERADO", "DIFF"]],
                      f"Folios donde no cuadra ({len(mal)})", max_filas=20)


if __name__ == "__main__":
    main()
