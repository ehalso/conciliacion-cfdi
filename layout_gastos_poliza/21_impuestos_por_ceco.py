"""
Baja el bloque de impuestos (19_bloque_impuestos.py, grano FOLIO) al grano
de DETALLE de la poliza (FOLIO x CECO) -- para poder sumar los totales de
impuestos a cualquier nivel de agregacion sin duplicar, igual que ya se
hace con Cargo/Abono. Repetir el total de folio en cada linea de CECO
(lo que haciamos en 18/19/20) es incorrecto para sumar: si un folio tiene
N lineas de CECO, sumar la columna de impuesto sobre esas N lineas da
N veces el valor real.

Pregunta de origen (conversacion 2026-09-11): "sigue siendo a nivel
detalle de la poliza?" -- confirmado que SI debe serlo, verificado contra
datos reales:
  - Gasto_Registro_Impuesto liga a (Gr_Folio, Grd_ID) -- por DOCUMENTO,
    no por folio completo. El folio-level de 19 ya suma de mas.
  - Gasto_Registro_Control liga (Grd_ID) a Centro_Costo -- normalmente
    1 documento = 1 centro, pero NO siempre: 19.345% de los documentos
    (1,033 de 5,340, ene-mar 2026) caen en MAS DE UN centro (hasta 79-81
    en casos extremos) -- hace falta prorratear, no asumir 1:1.

Metodo: `Gasto_Registro_Control.Grc_Factor` -- campo NATIVO de peso,
confirmado 2026-09-11 que suma exacto 1.0 dentro de cada Grd_ID (tanto en
el caso trivial, 1 centro, factor=1.0, como en el caso repartido, ej. 79
centros con factores fraccionarios que suman ~1.0) -- es el peso que el
propio motor de MPro usa para repartir el documento, mas confiable que
derivarlo de Grc_Importe/SUM(Grc_Importe) (que en teoria coincide, pero
depende de que el importe ya venga redondeado por linea; Grc_Factor es la
fuente, no una reconstruccion).

Validacion: la suma por CECO, re-agregada a FOLIO, debe reproducir
EXACTO el total ya validado en 19_bloque_impuestos.py (99.98%) -- es la
misma cifra solo redistribuida, no un calculo nuevo.

Uso:
    python3 21_impuestos_por_ceco.py --fecha-ini 2026-01-01 --fecha-fin 2026-04-01
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

# Impuestos por DOCUMENTO (Grd_ID), sin colapsar a folio -- mismo calculo
# que la CTE doc_impuestos de 19_bloque_impuestos.py, expuesto a este grano.
IMPUESTOS_POR_DOC_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    grd.Grd_ID,
    grd.Grd_Tipo_Cambio,
    SUM(CASE WHEN i.Im_Tasa = 16.0000 AND i.Im_Tipo_Factor = 'Tasa'
             THEN gri.Gri_Base_Gravable ELSE 0 END) * grd.Grd_Tipo_Cambio AS SUBTOTAL_16_DOC,
    SUM(CASE WHEN i.Im_Tasa = 0.0000 AND i.Im_Tipo_Factor = 'Tasa'
             THEN gri.Gri_Base_Gravable ELSE 0 END) * grd.Grd_Tipo_Cambio AS SUBTOTAL_0_DOC,
    SUM(CASE WHEN i.Im_Tipo_Factor = 'Exento'
             THEN gri.Gri_Base_Gravable ELSE 0 END) * grd.Grd_Tipo_Cambio AS SUBTOTAL_EXENTA_DOC,
    SUM(CASE WHEN i.Im_Cve_Impuesto IN ('0023','0018','0015','0024','0016','0017')
             THEN gri.Gri_Importe ELSE 0 END) * grd.Grd_Tipo_Cambio          AS RETENCIONES_IVA_DOC,
    SUM(CASE WHEN i.Im_Cve_Impuesto IN ('0026','0014','0013','0012','0011','0009','0010')
             THEN gri.Gri_Importe ELSE 0 END) * grd.Grd_Tipo_Cambio          AS RETENCIONES_ISR_DOC,
    SUM(CASE WHEN i.Im_Cve_Impuesto IN ('0001','0002','0003')
             THEN gri.Gri_Importe ELSE 0 END) * grd.Grd_Tipo_Cambio          AS IVA_ACREDITABLE_DOC,
    grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio                  AS SUBTOTAL_NETO_DOC
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
LEFT JOIN Gasto_Registro_Impuesto gri ON gri.Gr_Folio = grd.Gr_Folio AND gri.Grd_ID = grd.Grd_ID
LEFT JOIN Impuesto i ON i.Im_Cve_Impuesto = gri.Im_Cve_Impuesto
WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = :emp
GROUP BY gr.Gr_Folio, grd.Grd_ID, grd.Grd_Tipo_Cambio, grd.Grd_Precio_Descontado_Importe
"""

# Documento -> (centro, peso dentro del documento). GASTO_RECLASIFICACION
# excluido aqui a proposito -- su Grc_Importe es par espejo (+/-), el peso
# proporcional no aplica igual, se trata aparte (ver 19_bloque_impuestos.py).
GRC_POR_DOC_SQL = """
SELECT gr.Gr_Folio AS FOLIO, grc.Grd_ID, grc.Cc_Cve_Centro_Costo AS CECO, grc.Grc_Importe, grc.Grc_Factor
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Control grc ON grc.Gr_Folio = gr.Gr_Folio
WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
  AND gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = :emp
  AND ISNULL(gr.Gr_Tabla, '') <> 'GASTO_RECLASIFICACION'
"""


def construir(fi, ff):
    doc = pd.read_sql(text(IMPUESTOS_POR_DOC_SQL), engine, params={"fi": fi, "ff": ff, "emp": EMPRESA})
    doc["FOLIO"] = doc.FOLIO.str.strip()

    grc = pd.read_sql(text(GRC_POR_DOC_SQL), engine, params={"fi": fi, "ff": ff, "emp": EMPRESA})
    grc["FOLIO"] = grc.FOLIO.str.strip()

    # peso nativo de cada linea (FOLIO,GRD_ID,CECO) dentro de su documento --
    # Grc_Factor, no derivado. Fallback a reparto por Grc_Importe solo si
    # Grc_Factor viene nulo/0 en TODAS las lineas de un documento (no visto
    # en los datos probados, defensivo).
    grc["ABS_IMPORTE"] = grc.Grc_Importe.abs()
    grc["PESO"] = grc.Grc_Factor.fillna(0)
    suma_factor_doc = grc.groupby(["FOLIO", "Grd_ID"])["PESO"].transform("sum")
    total_importe_doc = grc.groupby(["FOLIO", "Grd_ID"])["ABS_IMPORTE"].transform("sum")
    sin_factor = suma_factor_doc < 0.01
    grc.loc[sin_factor, "PESO"] = (grc.ABS_IMPORTE / total_importe_doc)[sin_factor]
    grc["PESO"] = grc.PESO.fillna(0)

    cols_impuesto = ["SUBTOTAL_16_DOC", "SUBTOTAL_0_DOC", "SUBTOTAL_EXENTA_DOC",
                      "RETENCIONES_IVA_DOC", "RETENCIONES_ISR_DOC", "IVA_ACREDITABLE_DOC",
                      "SUBTOTAL_NETO_DOC"]
    m = grc.merge(doc[["FOLIO", "Grd_ID"] + cols_impuesto], on=["FOLIO", "Grd_ID"], how="left")
    for c in cols_impuesto:
        m[c.replace("_DOC", "")] = m[c] * m.PESO

    por_ceco = m.groupby(["FOLIO", "CECO"], as_index=False)[
        [c.replace("_DOC", "") for c in cols_impuesto]
    ].sum()
    return por_ceco, doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", default="2026-01-01")
    ap.add_argument("--fecha-fin", default="2026-04-01")
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print(f"[bold]Impuestos a grano de detalle (FOLIO x CECO) -- {fi} a {ff}[/bold]\n")

    por_ceco, doc = construir(fi, ff)
    console.print(f"Filas (FOLIO,CECO) con impuesto atribuido: {len(por_ceco)}\n")

    # --- Validacion: re-agregado a FOLIO, ¿reproduce el total de 19? ---
    reagregado = por_ceco.groupby("FOLIO", as_index=False).SUBTOTAL_NETO.sum()
    original = doc.groupby("FOLIO", as_index=False).SUBTOTAL_NETO_DOC.sum().rename(columns={"SUBTOTAL_NETO_DOC": "SUBTOTAL_NETO_FOLIO"})
    cmp = reagregado.merge(original, on="FOLIO", how="outer")
    cmp["DIFF"] = (cmp.SUBTOTAL_NETO.fillna(0) - cmp.SUBTOTAL_NETO_FOLIO.fillna(0)).abs()
    n, c = len(cmp), int((cmp.DIFF < 0.01).sum())
    resumen(reagregado_vs_folio_original=f"{c}/{n} ({c/n*100:.2f}%) -- debe ser ~100%, es la misma cifra redistribuida")
    mal = cmp[cmp.DIFF >= 0.01]
    if not mal.empty:
        mostrar_tabla(mal.sort_values("DIFF", ascending=False).head(10), "Folios donde la redistribucion no cuadra (revisar)", max_filas=10)

    # --- Muestra: el folio de 3 documentos/3 centros que se vio en conversacion ---
    ejemplo = por_ceco[por_ceco.FOLIO == "01-0034740"]
    if not ejemplo.empty:
        mostrar_tabla(ejemplo, "Ejemplo 01-0034740 -- impuesto YA atribuido por CECO (no repetido)", max_filas=10)

    out = Path(__file__).resolve().parent.parent / "layout_gastos_60col" / f"impuestos_por_ceco_{fi}_{ff}.csv"
    out.parent.mkdir(exist_ok=True)
    por_ceco.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]")


if __name__ == "__main__":
    main()
