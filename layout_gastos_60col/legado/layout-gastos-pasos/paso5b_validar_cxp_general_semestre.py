"""
v2.2 - Comprobacion CXP caso general, enero-junio 2026, contra .207.
Misma logica que validar_cxp_general_v2.py, ahora al semestre completo.
"""
import sys
sys.path.append("..")
from connection_207 import engine
import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()
FECHA_INI, FECHA_FIN = "2026-01-01", "2026-07-01"

with open("docs/queries/gastos/v_cxp_general.sql") as f:
    QUERY = f.read().replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")

base = pd.read_csv("v03_semestre_validacion.csv")[["FOLIO", "ORIGEN"]]
base["ORIGEN"] = base["ORIGEN"].fillna("GASTO_DIRECTO")

console.print("[bold]Corriendo (semestre completo, .207)...[/bold]")
df = pd.read_sql(QUERY, engine)
df["FOLIO"] = df["FOLIO"].str.strip()
df["CXP_MONEDA_ORIGINAL"] = df["CXP_MONEDA_ORIGINAL"].fillna(0)
df["DIFERENCIA"] = df.CXP_MONEDA_ORIGINAL - df.GASTO_MONEDA_ORIGINAL
df["CUADRA"] = df.DIFERENCIA.abs() < 1
df["ESPERADO_SIN_CXP"] = (df.CXP_MONEDA_ORIGINAL == 0) & (df.Gr_Genera_Cxp == "NO")
df["RESUELTO"] = df.CUADRA | df.ESPERADO_SIN_CXP

def motivo(row):
    if row.CUADRA: return "cuadra"
    if row.ESPERADO_SIN_CXP: return "sin_cxp_esperado"
    return "sin_explicacion"
df["MOTIVO"] = df.apply(motivo, axis=1)

rollup = df.groupby("FOLIO").agg(resuelto_folio=("RESUELTO", "all")).reset_index()
rollup = rollup.merge(base, on="FOLIO", how="left")

n, r = len(rollup), rollup.resuelto_folio.sum()
console.print(f"\n[bold]Folios (caso general, enero-junio 2026):[/bold] {n}")
console.print(f"[bold]Resueltos:[/bold] {r} ({100*r/n:.2f}%)\n")

t1 = Table(title="Resumen por ORIGEN")
t1.add_column("Origen")
t1.add_column("Folios", justify="right")
t1.add_column("Resueltos", justify="right")
t1.add_column("%", justify="right")
for origen, g in rollup.groupby("ORIGEN"):
    pct = 100*g.resuelto_folio.sum()/len(g)
    color = "green" if pct >= 99 else "yellow" if pct >= 95 else "red"
    t1.add_row(str(origen), str(len(g)), str(g.resuelto_folio.sum()), f"[{color}]{pct:.1f}%[/{color}]")
console.print(t1)

console.print("\n[bold]Por MOTIVO (a nivel documento):[/bold]")
console.print(df.MOTIVO.value_counts().to_string())

n_sin_exp = (df.MOTIVO == "sin_explicacion").sum()
console.print(f"\n[bold]Documentos sin explicación:[/bold] {n_sin_exp}")
if n_sin_exp:
    t4 = Table(title="Sin explicación (muestra)")
    for c in ["FOLIO", "Grd_ID", "Gr_Genera_Cxp", "GASTO_MONEDA_ORIGINAL", "CXP_MONEDA_ORIGINAL", "DIFERENCIA"]:
        t4.add_column(c, overflow="fold")
    for _, row in df[df.MOTIVO == "sin_explicacion"].sample(min(15, n_sin_exp), random_state=1).iterrows():
        t4.add_row(str(row.FOLIO), str(row.Grd_ID), str(row.Gr_Genera_Cxp),
                   f"{row.GASTO_MONEDA_ORIGINAL:,.2f}", f"{row.CXP_MONEDA_ORIGINAL:,.2f}", f"{row.DIFERENCIA:,.2f}")
    console.print(t4)

df.to_csv("v_cxp_general_semestre.csv", index=False)
console.print("\n[green]Guardado: v_cxp_general_semestre.csv[/green]")
