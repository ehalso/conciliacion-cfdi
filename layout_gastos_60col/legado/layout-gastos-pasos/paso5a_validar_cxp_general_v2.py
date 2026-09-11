"""
v2.2 - Comprobacion CXP caso general, con tablas rich (resumen + muestras).
Lee v_cxp_general.sql, compara en moneda original, explica los "sin CXP"
via Gr_Genera_Cxp en vez de tratarlos como falla.
"""
import sys
sys.path.append("..")
from connection_207 import engine
import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()
FECHA_INI, FECHA_FIN = "2026-01-01", "2026-02-01"

with open("docs/queries/gastos/v_cxp_general.sql") as f:
    QUERY = f.read().replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")

base = pd.read_csv("v01_baseline_enero2026_sin_nomina_consumo.csv")[["FOLIO", "ORIGEN"]]
base["ORIGEN"] = base["ORIGEN"].fillna("GASTO_DIRECTO")

df = pd.read_sql(QUERY, engine)
df["FOLIO"] = df["FOLIO"].str.strip()
df["CXP_MONEDA_ORIGINAL"] = df["CXP_MONEDA_ORIGINAL"].fillna(0)
df["DIFERENCIA"] = df.CXP_MONEDA_ORIGINAL - df.GASTO_MONEDA_ORIGINAL
df["CUADRA"] = df.DIFERENCIA.abs() < 1
df["ESPERADO_SIN_CXP"] = (df.CXP_MONEDA_ORIGINAL == 0) & (df.Gr_Genera_Cxp == "NO")
df["RESUELTO"] = df.CUADRA | df.ESPERADO_SIN_CXP

def motivo(row):
    if row.CUADRA:
        return "cuadra"
    if row.ESPERADO_SIN_CXP:
        return "sin_cxp_esperado"
    return "sin_explicacion"
df["MOTIVO"] = df.apply(motivo, axis=1)

rollup = df.groupby("FOLIO").agg(
    resuelto_folio=("RESUELTO", "all"),
    gasto_total=("GASTO_MONEDA_ORIGINAL", "sum"),
    cxp_total=("CXP_MONEDA_ORIGINAL", "sum"),
    n_docs=("Grd_ID", "count"),
).reset_index().merge(base, on="FOLIO", how="left")

n, r = len(rollup), rollup.resuelto_folio.sum()
console.print(f"[bold]Folios (caso general, enero 2026):[/bold] {n}")
console.print(f"[bold]Resueltos:[/bold] {r} ({100*r/n:.1f}%)\n")

# --- Resumen por origen ---
t1 = Table(title="Resumen por ORIGEN")
t1.add_column("Origen")
t1.add_column("Folios", justify="right")
t1.add_column("Resueltos", justify="right")
t1.add_column("%", justify="right")
for origen, g in rollup.groupby("ORIGEN"):
    t1.add_row(str(origen), str(len(g)), str(g.resuelto_folio.sum()), f"{100*g.resuelto_folio.sum()/len(g):.1f}%")
console.print(t1)

# --- Resumen por motivo (a nivel documento, no folio) ---
console.print("\n[bold]Por MOTIVO (a nivel documento):[/bold]")
console.print(df.MOTIVO.value_counts().to_string())

# --- Muestra: cuadran por match directo ---
console.print("\n")
t2 = Table(title="Muestra -- cuadran (CXP encontrada, monto exacto)")
for c in ["FOLIO", "Grd_ID", "GASTO_MONEDA_ORIGINAL", "CXP_MONEDA_ORIGINAL", "Mn_Cve_Moneda"]:
    t2.add_column(c, overflow="fold")
muestra_cuadra = df[df.MOTIVO == "cuadra"].sample(min(8, (df.MOTIVO=="cuadra").sum()), random_state=1)
for _, row in muestra_cuadra.iterrows():
    t2.add_row(str(row.FOLIO), str(row.Grd_ID), f"{row.GASTO_MONEDA_ORIGINAL:,.2f}",
               f"{row.CXP_MONEDA_ORIGINAL:,.2f}", str(row.Mn_Cve_Moneda))
console.print(t2)

# --- Muestra: sin CXP esperado (Gr_Genera_Cxp='NO') ---
t3 = Table(title="Muestra -- sin CXP, esperado (Gr_Genera_Cxp='NO')")
for c in ["FOLIO", "Grd_ID", "GASTO_MONEDA_ORIGINAL", "Gr_Genera_Cxp"]:
    t3.add_column(c, overflow="fold")
muestra_sin_cxp = df[df.MOTIVO == "sin_cxp_esperado"].sample(min(8, (df.MOTIVO=="sin_cxp_esperado").sum()), random_state=1)
for _, row in muestra_sin_cxp.iterrows():
    t3.add_row(str(row.FOLIO), str(row.Grd_ID), f"{row.GASTO_MONEDA_ORIGINAL:,.2f}", str(row.Gr_Genera_Cxp))
console.print(t3)

# --- Muestra: sin explicación (si las hay) ---
n_sin_exp = (df.MOTIVO == "sin_explicacion").sum()
if n_sin_exp:
    t4 = Table(title="Muestra -- SIN EXPLICACIÓN (revisar)")
    for c in ["FOLIO", "Grd_ID", "Gr_Genera_Cxp", "GASTO_MONEDA_ORIGINAL", "CXP_MONEDA_ORIGINAL", "DIFERENCIA"]:
        t4.add_column(c, overflow="fold")
    for _, row in df[df.MOTIVO == "sin_explicacion"].head(15).iterrows():
        t4.add_row(str(row.FOLIO), str(row.Grd_ID), str(row.Gr_Genera_Cxp),
                   f"{row.GASTO_MONEDA_ORIGINAL:,.2f}", f"{row.CXP_MONEDA_ORIGINAL:,.2f}", f"{row.DIFERENCIA:,.2f}")
    console.print(t4)
else:
    console.print("\n[green]Sin folios sin explicación.[/green]")

df.to_csv("v_cxp_general_enero2026.csv", index=False)
console.print("\n[green]Guardado: v_cxp_general_enero2026.csv[/green]")
