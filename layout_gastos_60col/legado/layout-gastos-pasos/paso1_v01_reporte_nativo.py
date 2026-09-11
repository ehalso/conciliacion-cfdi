"""
v0.1 - Réplica del reporte nativo MPRO, a nivel Gasto_Registro (folio), con origen.
Ground truth (gastos_por_documento_enero_26.xlsx, agregado por FOLIO): empresa 0001
IMPORTE=39,469,269.50  IMPUESTOS=1,084,277.23  TOTAL=40,553,546.72
"""
import sys
sys.path.append("..")
from connection_200_trivasadb3 import engine

import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()

QUERY = """
SELECT
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + CONVERT(varchar, gr.Gr_Folio), 7) AS FOLIO,
    gr.Gr_Fecha                                                     AS FECHA_R,
    gr.Gr_Tabla                                                     AS ORIGEN,
    SUM(grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio)    AS IMPORTE,
    SUM(grd.Grd_Impuesto_Importe * grd.Grd_Tipo_Cambio)             AS IMPUESTOS,
    SUM(grd.Grd_Precio_Neto_Importe * grd.Grd_Tipo_Cambio)          AS TOTAL
FROM Gasto_Registro gr
JOIN Sucursal s
    ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd
    ON gr.Gr_Folio = grd.Gr_Folio
WHERE gr.Gr_Fecha >= '2026-01-01' AND gr.Gr_Fecha < '2026-02-01'
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, gr.Gr_Fecha, gr.Gr_Tabla
ORDER BY FOLIO
"""

df = pd.read_sql(QUERY, engine)

BASELINE_PATH = "v01_baseline_enero2026.csv"
df.to_csv(BASELINE_PATH, index=False)

# --- Muestra ---
tabla = Table(title="Gastos por folio - enero 2026 - empresa 0001 (v0.1)")
for col in ["FOLIO", "FECHA_R", "ORIGEN", "IMPORTE", "IMPUESTOS", "TOTAL"]:
    tabla.add_column(col, overflow="fold")
for _, r in df.head(25).iterrows():
    tabla.add_row(
        str(r.FOLIO), str(r.FECHA_R)[:10], str(r.ORIGEN or "GASTO_DIRECTO"),
        f"{r.IMPORTE:,.2f}", f"{r.IMPUESTOS:,.2f}", f"{r.TOTAL:,.2f}"
    )
console.print(tabla)

# --- Desglose por ORIGEN (para ir conociendo la composición antes de v0.2+) ---
por_origen = df.groupby(df["ORIGEN"].fillna("GASTO_DIRECTO")).agg(
    folios=("FOLIO", "count"), total=("TOTAL", "sum")
).sort_values("total", ascending=False)
tabla_origen = Table(title="Composición por ORIGEN (Gr_Tabla)")
tabla_origen.add_column("ORIGEN")
tabla_origen.add_column("Folios", justify="right")
tabla_origen.add_column("Total", justify="right")
for origen, row in por_origen.iterrows():
    tabla_origen.add_row(str(origen), str(int(row.folios)), f"{row.total:,.2f}")
console.print(tabla_origen)

# --- Totales vs ground truth ---
EXP_IMP, EXP_IVA, EXP_TOT = 39469269.50, 1084277.23, 40553546.72

importe = df.IMPORTE.sum()
iva = df.IMPUESTOS.sum()
total = df.TOTAL.sum()

console.print("\n[bold]TOTALES (nivel folio)[/bold]")
console.print(f"  Folios     : {len(df)}")
console.print(f"  IMPORTE    : {importe:>15,.2f}   (esperado {EXP_IMP:,.2f})")
console.print(f"  IMPUESTOS  : {iva:>15,.2f}   (esperado {EXP_IVA:,.2f})")
console.print(f"  TOTAL      : {total:>15,.2f}   (esperado {EXP_TOT:,.2f})")

ok = (abs(importe - EXP_IMP) < 1 and abs(iva - EXP_IVA) < 1 and abs(total - EXP_TOT) < 1)
console.print(f"\n[bold {'green' if ok else 'red'}]{'✅ v0.1 CUADRA con el reporte nativo' if ok else '❌ v0.1 NO cuadra'}[/bold {'green' if ok else 'red'}]  -> baseline guardado en {BASELINE_PATH}")
