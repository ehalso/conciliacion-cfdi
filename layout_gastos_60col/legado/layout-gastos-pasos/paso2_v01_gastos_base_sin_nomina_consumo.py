"""
v0.1 (base filtrada) - Universo de folios que SÍ requieren atribución Cargo/Abono.
Excluye GASTO_REGISTRO_NOMINA y CONSUMO_INTERNO (no llevan póliza por diseño).
Fuente de verdad para v0.2+.
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
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, gr.Gr_Fecha, gr.Gr_Tabla
ORDER BY FOLIO
"""

df = pd.read_sql(QUERY, engine)

BASELINE_PATH = "v01_baseline_enero2026_sin_nomina_consumo.csv"
df.to_csv(BASELINE_PATH, index=False)

# --- Muestra ---
tabla = Table(title="Gastos por folio - enero 2026 - sin NOMINA/CONSUMO_INTERNO")
for col in ["FOLIO", "FECHA_R", "ORIGEN", "IMPORTE", "IMPUESTOS", "TOTAL"]:
    tabla.add_column(col, overflow="fold")
for _, r in df.sample(min(20, len(df)), random_state=1).sort_values("FOLIO").iterrows():
    tabla.add_row(
        str(r.FOLIO), str(r.FECHA_R)[:10], str(r.ORIGEN if pd.notna(r.ORIGEN) else "GASTO_DIRECTO"),
        f"{r.IMPORTE:,.2f}", f"{r.IMPUESTOS:,.2f}", f"{r.TOTAL:,.2f}"
    )
console.print(tabla)

# --- Composición por ORIGEN restante ---
por_origen = df.groupby(df["ORIGEN"].fillna("GASTO_DIRECTO")).agg(
    folios=("FOLIO", "count"), total=("TOTAL", "sum")
).sort_values("total", ascending=False)
tabla_origen = Table(title="Composición por ORIGEN (post-filtro)")
tabla_origen.add_column("ORIGEN")
tabla_origen.add_column("Folios", justify="right")
tabla_origen.add_column("Total", justify="right")
for origen, row in por_origen.iterrows():
    tabla_origen.add_row(str(origen), str(int(row.folios)), f"{row.total:,.2f}")
console.print(tabla_origen)

console.print(f"\n[bold]Folios (sin nómina/consumo interno):[/bold] {len(df)}")
console.print(f"[bold]IMPORTE:[/bold] {df.IMPORTE.sum():,.2f}")
console.print(f"[bold]IMPUESTOS:[/bold] {df.IMPUESTOS.sum():,.2f}")
console.print(f"[bold]TOTAL:[/bold] {df.TOTAL.sum():,.2f}")
console.print(f"\n[green]Baseline guardado en {BASELINE_PATH}[/green]")
