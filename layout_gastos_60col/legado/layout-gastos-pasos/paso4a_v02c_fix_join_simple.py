"""
Re-intento de v0.2 solo para los folios que NO conciliaron antes, con el
join simple confirmado (Gr_Folio YA es el string completo 'SS-FFFFFFF',
igual que Pc_Documento -- sin CONVERT/reconstruccion en el join, solo
comparacion de texto directa).
"""
import sys
sys.path.append("..")
from connection_200_trivasadb3 import engine
import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()

pendientes = pd.read_csv("v02_folios_sin_conciliar_enero2026.csv")
pendientes = pendientes[["FOLIO", "ORIGEN", "IMPORTE"]]  # descartar CARGO/ABONO/DIFERENCIA/CUADRA viejos
folios_lista = "','".join(pendientes.FOLIO.tolist())

QUERY = f"""
SELECT
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + CONVERT(varchar, gr.Gr_Folio), 7) AS FOLIO_DISPLAY,
    SUM(CASE WHEN pd.Pd_Tipo = 1 THEN pd.Pd_Importe ELSE 0 END) AS CARGO,
    SUM(CASE WHEN pd.Pd_Tipo = 2 THEN pd.Pd_Importe ELSE 0 END) AS ABONO
FROM Gasto_Registro gr
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio          -- simple, sin CONVERT
   AND plc.Es_Cve_Estado <> 'CA'
JOIN Poliza pl
    ON pl.Pl_Folio = plc.Pl_Folio
JOIN Poliza_Detalle pd
    ON pd.Pl_Folio = plc.Pl_Folio
   AND pd.Pd_Referencia = gr.Gr_Folio           -- simple, sin CONVERT
WHERE pl.Es_Cve_Estado <> 'CA'
  AND gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + CONVERT(varchar, gr.Gr_Folio), 7) IN ('{folios_lista}')
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio
"""

poliza = pd.read_sql(QUERY, engine)
poliza = poliza.rename(columns={"FOLIO_DISPLAY": "FOLIO"})
poliza["FOLIO"] = poliza["FOLIO"].str.strip()
pendientes["FOLIO"] = pendientes["FOLIO"].str.strip()
console.print(f"[bold]Filas devueltas:[/bold] {len(poliza)}")
if len(poliza):
    console.print(poliza.to_string(index=False))

df = pendientes.merge(poliza, on="FOLIO", how="left", indicator=True)
console.print(df[["FOLIO","_merge"]])
if "CARGO" not in df.columns: df["CARGO"] = 0.0
if "ABONO" not in df.columns: df["ABONO"] = 0.0
df[["CARGO", "ABONO"]] = df[["CARGO", "ABONO"]].fillna(0)
df["DIFERENCIA"] = (df.CARGO - df.ABONO) - df.IMPORTE
df["CUADRA"] = df.DIFERENCIA.abs() < 1

n, c = len(df), df.CUADRA.sum()
console.print(f"\n[bold]Reconciliación (solo pendientes):[/bold] {c}/{n} ({100*c/n:.1f}%)\n")

t = Table()
for col in ["FOLIO", "ORIGEN", "IMPORTE", "CARGO", "ABONO", "DIFERENCIA", "CUADRA"]:
    t.add_column(col, overflow="fold")
for _, r in df.iterrows():
    t.add_row(str(r.FOLIO), str(r.ORIGEN if pd.notna(r.ORIGEN) else "GASTO_DIRECTO"),
               f"{r.IMPORTE:,.2f}", f"{r.CARGO:,.2f}", f"{r.ABONO:,.2f}", f"{r.DIFERENCIA:,.2f}", str(r.CUADRA))
console.print(t)
