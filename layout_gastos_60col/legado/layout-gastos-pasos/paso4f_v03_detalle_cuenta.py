"""
v0.3 - Detalle de Cargo/Abono por CUENTA CONTABLE + CENTRO DE COSTO.
Lee la query directo de docs/queries/gastos/v03_detalle_cuenta_centro_costo.sql
(la misma que se sirve en FlexMonster) -- para probar exactamente esa query,
no una copia que se puede desincronizar.

Validacion (solo aqui, en Python -- NO va en la query de produccion):
  - Folios normales (Importe > -$1): SUM(Cargo) sin filtrar == Importe.
  - Reversion (Importe <= -$1): SUM(Abono) sin filtrar == |Importe|.
  - GASTO_RECLASIFICACION (Importe siempre $0 neto): SUM(Cargo) == SUM(Abono).
"""
import sys
sys.path.append("..")
from connection_207 import engine

import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()

FECHA_INI, FECHA_FIN = "2026-01-01", "2026-02-01"

def leer_query(path):
    with open(path) as f:
        return f.read().replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")

QUERY_DETALLE = leer_query("docs/queries/gastos/v03_detalle_cuenta_centro_costo.sql")

console.print("[bold]Corriendo v0.3 (leyendo la query guardada, la misma de FlexMonster)...[/bold]")
detalle = pd.read_sql(QUERY_DETALLE, engine)
detalle["FOLIO"] = detalle["FOLIO"].str.strip()
console.print(f"  {len(detalle)} filas (folio x cuenta x centro de costo)")
console.print(f"  {detalle.FOLIO.nunique()} folios distintos")

detalle.to_csv("v03_detalle_cuenta_enero2026.csv", index=False)

# --- Muestra ---
t = Table(title="v0.3 - Muestra del detalle")
for col in ["FOLIO", "CUENTA", "CENTRO_COSTO", "CARGO", "ABONO"]:
    t.add_column(col, overflow="fold")
for _, r in detalle.sample(min(15, len(detalle)), random_state=1).iterrows():
    t.add_row(str(r.FOLIO), str(r.CUENTA), str(r.CENTRO_COSTO),
               f"{r.CARGO:,.2f}", f"{r.ABONO:,.2f}")
console.print(t)

# --- Validación: rollup a nivel folio, contra v01 ---
console.print("\n[bold]Validando contra v01_baseline_enero2026_sin_nomina_consumo.csv...[/bold]")
base = pd.read_csv("v01_baseline_enero2026_sin_nomina_consumo.csv")[["FOLIO", "ORIGEN", "IMPORTE"]]

rollup = detalle.groupby("FOLIO", as_index=False).agg(
    CARGO_TOTAL=("CARGO", "sum"), ABONO_TOTAL=("ABONO", "sum")
)

df = base.merge(rollup, on="FOLIO", how="left")
df[["CARGO_TOTAL", "ABONO_TOTAL"]] = df[["CARGO_TOTAL", "ABONO_TOTAL"]].fillna(0)

es_reversion = df.IMPORTE <= -1.0
es_reclasificacion = df.ORIGEN == "GASTO_RECLASIFICACION"

df["VALOR_VALIDACION"] = df.CARGO_TOTAL
df.loc[es_reversion, "VALOR_VALIDACION"] = df.loc[es_reversion, "ABONO_TOTAL"]

df["COMPARAR_CONTRA"] = df.IMPORTE.abs()
df.loc[es_reclasificacion, "COMPARAR_CONTRA"] = df.loc[es_reclasificacion, "ABONO_TOTAL"]

df["DIFERENCIA"] = df.VALOR_VALIDACION - df.COMPARAR_CONTRA
df["CUADRA"] = df.DIFERENCIA.abs() < 1

n, c = len(df), df.CUADRA.sum()
console.print(f"\n[bold]Reconciliación v0.3 (rollup a folio):[/bold] {c}/{n} ({100*c/n:.2f}%)\n")

resumen = df.groupby(df["ORIGEN"].fillna("GASTO_DIRECTO")).agg(
    n=("FOLIO", "count"), cuadran=("CUADRA", "sum")
).reset_index()
resumen["pct"] = (resumen.cuadran / resumen.n * 100).round(2)
t2 = Table(title="Reconciliación por ORIGEN")
t2.add_column("ORIGEN")
t2.add_column("n", justify="right")
t2.add_column("Cuadran", justify="right")
t2.add_column("%", justify="right")
for _, r in resumen.iterrows():
    t2.add_row(str(r.ORIGEN), str(r.n), str(r.cuadran), f"{r.pct}%")
console.print(t2)

mal = df[~df.CUADRA]
console.print(f"\n[bold red]Folios que NO cuadran:[/bold red] {len(mal)}")
if len(mal):
    t3 = Table()
    for col in ["FOLIO", "ORIGEN", "IMPORTE", "CARGO_TOTAL", "ABONO_TOTAL", "DIFERENCIA"]:
        t3.add_column(col, overflow="fold")
    for _, r in mal.sort_values("DIFERENCIA", key=abs, ascending=False).iterrows():
        t3.add_row(str(r.FOLIO), str(r.ORIGEN or "GASTO_DIRECTO"), f"{r.IMPORTE:,.2f}",
                    f"{r.CARGO_TOTAL:,.2f}", f"{r.ABONO_TOTAL:,.2f}", f"{r.DIFERENCIA:,.2f}")
    console.print(t3)

console.print(f"\n[green]Guardado: v03_detalle_cuenta_enero2026.csv[/green]")
