"""
Etapa 6 -- extension: cobertura de pago (Banco/Cheque/Fecha) para
CONTROL_COMBUSTIBLE, usando el link por referencia consolidada en vez del
link por documento (que no aplica a combustible, ver v3_cxp_completo.sql).
Compara contra la cobertura original de etapa6_columnas_1_18.sql (0%).
"""
import sys
sys.path.append("..")
from connection_200_trivasadb3 import engine
import pandas as pd
from rich.table import Table
from helpers_output import console_err

FECHA_INI, FECHA_FIN = "2026-01-01", "2026-02-01"

with open("docs/queries/gastos/etapa6_cxp_con_pago.sql") as f:
    QUERY = f.read().replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")

df = pd.read_sql(QUERY, engine)
console_err.print(f"[bold]Filas crudas (antes de dedup):[/bold] {len(df)}")

# Mismo criterio de prioridad que pago_repr en etapa6_columnas_1_18.sql:
# forma de pago con instrumento bancario real primero, luego mayor importe
# absoluto como desempate.
INSTRUMENTO_REAL = ["0001", "0002", "0003"]
df["prioridad"] = (~df["Fp_Cve_Forma_Pago"].isin(INSTRUMENTO_REAL)).astype(int)
df["importe_abs"] = df["Pc_Importe"].abs()
df = df.sort_values(["FOLIO", "prioridad", "importe_abs"], ascending=[True, True, False])
repr_pago = df.groupby("FOLIO", as_index=False).first()

assert repr_pago["FOLIO"].is_unique, "FOLIO no es unico tras dedup -- revisar criterio"

# Universo base: los 384 folios de combustible de enero 2026
base = pd.read_csv("v01_baseline_enero2026_sin_nomina_consumo.csv")
base["FOLIO"] = base["FOLIO"].str.strip()
combustible = base[base["ORIGEN"] == "CONTROL_COMBUSTIBLE"][["FOLIO"]]

full = combustible.merge(repr_pago, on="FOLIO", how="left")
n, con_pago = len(full), full["Pc_ID"].notna().sum()

console_err.print(f"\n[bold]Cobertura CONTROL_COMBUSTIBLE (extension referencia_consolidada):[/bold]")
console_err.print(f"  Antes (etapa6_columnas_1_18.sql, link por documento): 0/{n} (0.0%)")
console_err.print(f"  Despues (link por referencia_consolidada): {con_pago}/{n} ({100*con_pago/n:.1f}%)")

t = Table(title="Muestra de pagos resueltos (combustible)")
for c in ["FOLIO", "Fp_Cve_Forma_Pago", "Pc_Banco", "Pc_Cuenta_Bancaria", "Pc_Fecha", "Pc_Importe"]:
    t.add_column(c, overflow="fold")
for _, row in full[full["Pc_ID"].notna()].head(10).iterrows():
    t.add_row(*[str(row[c]) for c in ["FOLIO", "Fp_Cve_Forma_Pago", "Pc_Banco", "Pc_Cuenta_Bancaria", "Pc_Fecha", "Pc_Importe"]])
console_err.print(t)

sin_pago = full[full["Pc_ID"].isna()]
if len(sin_pago):
    console_err.print(f"\n[yellow]Folios combustible sin pago encontrado ({len(sin_pago)}):[/yellow]")
    console_err.print(sin_pago["FOLIO"].to_string(index=False))

print("--- CSV_PARA_CLAUDE: cobertura_combustible_extension ---")
print(f"folios,{n}\ncon_pago,{con_pago}\npct,{100*con_pago/n:.1f}")
