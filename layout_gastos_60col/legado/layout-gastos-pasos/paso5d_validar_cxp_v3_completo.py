"""
v3.0 - Comprobacion CXP completa (general + CONTROL_COMBUSTIBLE), enero 2026.
Usa GRANULARIDAD_CXP para decidir la comparacion: 'documento' compara
GASTO_MONEDA_ORIGINAL vs CXP_MONEDA_ORIGINAL directo; 'referencia_consolidada'
compara GASTO_REFERENCIA_TOTAL vs CXP_MONEDA_ORIGINAL (ambos ya calculados
a nivel referencia en el SQL, sin necesidad de reagrupar en Python).
"""
import sys
sys.path.append("..")
from connection_200_trivasadb3 import engine
import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console(width=160)
FECHA_INI, FECHA_FIN = "2026-01-01", "2026-02-01"

with open("docs/queries/gastos/v3_cxp_completo.sql") as f:
    QUERY = f.read().replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")

df = pd.read_sql(QUERY, engine)
df["FOLIO"] = df["FOLIO"].str.strip()
df["CXP_MONEDA_ORIGINAL"] = df["CXP_MONEDA_ORIGINAL"].fillna(0)

es_ref = df["GRANULARIDAD_CXP"] == "referencia_consolidada"
df["GASTO_COMPARABLE"] = df["GASTO_MONEDA_ORIGINAL"]
df.loc[es_ref, "GASTO_COMPARABLE"] = df.loc[es_ref, "GASTO_REFERENCIA_TOTAL"]

df["DIFERENCIA"] = df.CXP_MONEDA_ORIGINAL - df.GASTO_COMPARABLE
df["CUADRA"] = df.DIFERENCIA.abs() < 1
df["ESPERADO_SIN_CXP"] = (df.CXP_MONEDA_ORIGINAL == 0) & (df.Gr_Genera_Cxp == "NO") & (~es_ref)
df["RESUELTO"] = df.CUADRA | df.ESPERADO_SIN_CXP

def motivo(row):
    if row.CUADRA and row.GRANULARIDAD_CXP == "referencia_consolidada":
        return "cuadra_combustible"
    if row.CUADRA:
        return "cuadra"
    if row.ESPERADO_SIN_CXP:
        return "sin_cxp_esperado"
    return "sin_explicacion"
df["MOTIVO"] = df.apply(motivo, axis=1)

rollup = df.groupby("FOLIO").agg(
    resuelto_folio=("RESUELTO", "all"),
    origen=("ORIGEN", "first"),
    granularidad=("GRANULARIDAD_CXP", "first"),
    gasto_total=("GASTO_MONEDA_ORIGINAL", "sum"),
).reset_index()

n, r = len(rollup), rollup.resuelto_folio.sum()
console.print(f"[bold]Folios (universo completo, enero 2026):[/bold] {n}")
console.print(f"[bold]Resueltos:[/bold] {r} ({100*r/n:.1f}%)\n")

t1 = Table(title="Resumen por ORIGEN")
t1.add_column("Origen")
t1.add_column("Granularidad CXP")
t1.add_column("Folios", justify="right")
t1.add_column("Resueltos", justify="right")
t1.add_column("%", justify="right")
for (origen, gran), g in rollup.groupby(["origen", "granularidad"]):
    origen = origen if pd.notna(origen) else "GASTO_DIRECTO"
    t1.add_row(str(origen), str(gran), str(len(g)), str(g.resuelto_folio.sum()),
               f"{100*g.resuelto_folio.sum()/len(g):.1f}%")
console.print(t1)

console.print("\n[bold]Por MOTIVO (a nivel documento):[/bold]")
console.print(df.MOTIVO.value_counts().to_string())

no_resueltos = rollup[~rollup.resuelto_folio]
if len(no_resueltos):
    t2 = Table(title="Folios NO resueltos (revisar)")
    for c in ["FOLIO", "origen", "granularidad", "gasto_total"]:
        t2.add_column(c, overflow="fold")
    for _, row in no_resueltos.head(20).iterrows():
        t2.add_row(str(row.FOLIO), str(row.origen), str(row.granularidad), f"{row.gasto_total:,.2f}")
    console.print(t2)
else:
    console.print("\n[green]100% resuelto -- sin folios pendientes de revisar.[/green]")

df.to_csv("v3_cxp_completo_enero2026.csv", index=False)
console.print("\n[green]Guardado: v3_cxp_completo_enero2026.csv[/green]")
