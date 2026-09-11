"""
Paso 7a - Reconciliar los dos niveles de agregacion antes de armar el maestro.
v2: distribucion agrupada en rangos (mas legible) + folios outlier explicados.
"""
import sys
sys.path.append("..")
from connection_200_trivasadb3 import engine
import pandas as pd
from rich.table import Table
from helpers_output import console_err, resumen_err

FECHA_INI, FECHA_FIN = "2026-01-01", "2026-02-01"

def leer_query(path):
    with open(path) as f:
        return f.read().replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")

base = pd.read_csv("v01_baseline_enero2026_sin_nomina_consumo.csv")
base["FOLIO"] = base["FOLIO"].str.strip()
base["ORIGEN"] = base["ORIGEN"].fillna("GASTO_DIRECTO")
assert base["FOLIO"].is_unique

cargo_abono = pd.read_sql(leer_query("docs/queries/gastos/v03_detalle_cuenta_centro_costo.sql"), engine)
cargo_abono["FOLIO"] = cargo_abono["FOLIO"].str.strip()
cargo_abono.to_csv("v03_detalle_cuenta_enero2026.csv", index=False)

n_lineas = cargo_abono.groupby("FOLIO").size().rename("N_LINEAS").reset_index()
n_lineas = n_lineas.merge(base[["FOLIO", "ORIGEN"]], on="FOLIO", how="left")

# --- Distribución en rangos, legible ---
bins = [0, 1, 2, 5, 10, 20, 50, 100, 10000]
labels = ["1", "2", "3-5", "6-10", "11-20", "21-50", "51-100", "100+"]
n_lineas["RANGO"] = pd.cut(n_lineas["N_LINEAS"], bins=bins, labels=labels)

dist = n_lineas.groupby("RANGO", observed=True).agg(
    N_FOLIOS=("FOLIO", "count"), TOTAL_LINEAS=("N_LINEAS", "sum")
).reindex(labels).fillna(0).astype(int)
dist["PCT_FOLIOS"] = (100 * dist.N_FOLIOS / len(n_lineas)).round(1)
dist["PCT_ACUM"] = dist["PCT_FOLIOS"].cumsum().round(1)

t1 = Table(title=f"Distribución de líneas contables por folio ({len(n_lineas)} folios, {len(cargo_abono)} líneas totales)")
t1.add_column("Líneas/folio"); t1.add_column("Folios", justify="right")
t1.add_column("% folios", justify="right"); t1.add_column("% acum.", justify="right")
t1.add_column("Total líneas", justify="right")
for rango, row in dist.iterrows():
    t1.add_row(rango, str(row.N_FOLIOS), f"{row.PCT_FOLIOS}%", f"{row.PCT_ACUM}%", str(row.TOTAL_LINEAS))
console_err.print(t1)

# --- Top 15 outliers, con ORIGEN, para entender que son ---
top = n_lineas.sort_values("N_LINEAS", ascending=False).head(15)
t2 = Table(title="Top 15 folios con más líneas contables")
t2.add_column("FOLIO"); t2.add_column("ORIGEN"); t2.add_column("N_LINEAS", justify="right")
for _, r in top.iterrows():
    t2.add_row(r.FOLIO, r.ORIGEN, str(r.N_LINEAS))
console_err.print(t2)

resumen_err(
    folios_universo=len(n_lineas),
    folios_1_linea=int((n_lineas.N_LINEAS == 1).sum()),
    folios_2plus=int((n_lineas.N_LINEAS >= 2).sum()),
    max_lineas=int(n_lineas.N_LINEAS.max()),
    total_lineas=len(cargo_abono),
)

print("--- CSV_PARA_CLAUDE: distribucion_rangos ---")
print(dist.reset_index().to_csv(index=False))

print("--- CSV_PARA_CLAUDE: top_outliers ---")
print(top.to_csv(index=False))
