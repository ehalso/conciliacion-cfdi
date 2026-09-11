"""
Paso 12 - Columnas 53-56 (Fecha/Tipo/Numero/Concepto de poliza). Ultimo
bloque del layout 1-56 -- despues de esto solo queda Cargo/Abono (57-60,
aparte, ya resuelto en v8_detalle_cuenta_enero2026.csv).
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

maestro = pd.read_csv("v7_reporte_maestro_1_40_enero2026.csv")
maestro["FOLIO"] = maestro["FOLIO"].str.strip()
assert maestro["FOLIO"].is_unique

df = pd.read_sql(leer_query("docs/queries/gastos/poliza_descriptiva.sql"), engine)
df["FOLIO"] = df["FOLIO"].str.strip()
assert df["FOLIO"].is_unique, "fan-out en poliza_descriptiva"

cols_nuevas = ["FECHA_POLIZA", "TIPO_POLIZA", "NUMERO_POLIZA", "CONCEPTO_POLIZA"]
maestro = maestro.drop(columns=cols_nuevas).merge(df, on="FOLIO", how="left")
assert maestro["FOLIO"].is_unique

n = len(maestro)
n_varios = int((maestro.NUMERO_POLIZA == "VARIOS").sum())
cobertura = [(c, int(maestro[c].notna().sum()), n, round(100*maestro[c].notna().sum()/n, 1)) for c in cols_nuevas]

t = Table(title="Cobertura columnas 53-56")
t.add_column("Columna"); t.add_column("Poblados", justify="right"); t.add_column("%", justify="right")
for c, p, tot, pct in cobertura:
    t.add_row(c, str(p), f"{pct}%")
console_err.print(t)

resumen_err(folios_universo=n, folios_varios_poliza=n_varios)

maestro.to_csv("v7_reporte_maestro_1_40_enero2026.csv", index=False)
console_err.print("\n[green]Actualizado: v7_reporte_maestro_1_40_enero2026.csv (con 53-56)[/green]")

print("--- CSV_PARA_CLAUDE: cobertura_53_56 ---")
print(pd.DataFrame(cobertura, columns=["columna","poblados","universo","pct"]).to_csv(index=False))

print("--- CSV_PARA_CLAUDE: folios_con_varias_polizas ---")
print(maestro[maestro.NUMERO_POLIZA == "VARIOS"][["FOLIO","ORIGEN"]].to_csv(index=False))
