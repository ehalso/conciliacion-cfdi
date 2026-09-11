"""
Comprobacion final: el reporte maestro (v7_reporte_maestro_1_40_enero2026.csv,
bloque 1-56, via reglas_negocio.py) contra el universo baseline
(v01_baseline_enero2026_sin_nomina_consumo.csv). Cuadre esperado: 100% --
si algo no cuadra aqui, hay fan-out o perdida de folios en el pipeline
nuevo, no es una diferencia de negocio como en las comprobaciones de CXP.
"""
import sys
sys.path.append("..")
import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console(width=200)

base = pd.read_csv("v01_baseline_enero2026_sin_nomina_consumo.csv")
base["FOLIO"] = base["FOLIO"].str.strip()
base["ORIGEN"] = base["ORIGEN"].fillna("GASTO_DIRECTO")

maestro = pd.read_csv("v7_reporte_maestro_1_40_enero2026.csv")
maestro["FOLIO"] = maestro["FOLIO"].str.strip()

df = base[["FOLIO", "ORIGEN", "TOTAL"]].merge(
    maestro[["FOLIO", "TOTAL"]], on="FOLIO", how="left", suffixes=("_baseline", "_maestro")
)
df["DIFERENCIA"] = df["TOTAL_maestro"] - df["TOTAL_baseline"]
df["CUADRA"] = df["DIFERENCIA"].abs() < 1

n, c = len(df), df.CUADRA.sum()
console.print(f"Total folios (universo): {n}    Cuadran: {c} ({100*c/n:.1f}%)\n")

# --- Por ORIGEN ---
console.print("Por ORIGEN:\n")
por_origen = df.groupby("ORIGEN").agg(
    sum_baseline=("TOTAL_baseline", "sum"),
    sum_maestro=("TOTAL_maestro", "sum"),
    folios=("FOLIO", "count"),
    cuadran=("CUADRA", "sum"),
)
console.print(por_origen.to_string())
console.print()

# --- Muestra -- sí cuadran ---
console.print("[bold]Muestra -- Sí cuadran[/bold]")
t1 = Table()
for col in ["FOLIO", "ORIGEN", "TOTAL_baseline", "TOTAL_maestro"]:
    t1.add_column(col, overflow="fold")
si_cuadran = df[df.CUADRA].sample(min(12, df.CUADRA.sum()), random_state=1).sort_values("FOLIO")
for _, r in si_cuadran.iterrows():
    t1.add_row(r.FOLIO, r.ORIGEN, f"{r.TOTAL_baseline:,.2f}", f"{r.TOTAL_maestro:,.2f}")
console.print(t1)
console.print()

# --- Muestra -- NO cuadran ---
no_cuadran = df[~df.CUADRA]
console.print(f"[bold red]Muestra -- NO cuadran ({len(no_cuadran)} folios)[/bold red]")
if len(no_cuadran):
    t2 = Table()
    for col in ["FOLIO", "ORIGEN", "TOTAL_baseline", "TOTAL_maestro", "DIFERENCIA"]:
        t2.add_column(col, overflow="fold")
    for _, r in no_cuadran.sort_values("DIFERENCIA", key=abs, ascending=False).iterrows():
        t2.add_row(r.FOLIO, r.ORIGEN, f"{r.TOTAL_baseline:,.2f}",
                   f"{r.TOTAL_maestro:,.2f}" if pd.notna(r.TOTAL_maestro) else "NULL",
                   f"{r.DIFERENCIA:,.2f}" if pd.notna(r.DIFERENCIA) else "N/A")
    console.print(t2)
else:
    console.print("[green]Ninguno -- 100% cuadrado.[/green]")

console.print(f"\n[bold]Columnas totales en el maestro:[/bold] {len(maestro.columns) - 1}")
console.print(f"[bold]Folios en el maestro:[/bold] {len(maestro)}")

# --- Salida para Claude ---
print("\n--- CSV_PARA_CLAUDE: resumen_comprobacion ---")
print(f"folios_universo,{n}")
print(f"cuadran,{int(c)}")
print(f"pct,{round(100*c/n,2)}")
print(f"columnas_maestro,{len(maestro.columns)-1}")

print("--- CSV_PARA_CLAUDE: por_origen ---")
print(por_origen.reset_index().to_csv(index=False))

print("--- CSV_PARA_CLAUDE: folios_no_cuadran ---")
print(no_cuadran[["FOLIO","ORIGEN","TOTAL_baseline","TOTAL_maestro","DIFERENCIA"]].to_csv(index=False))
