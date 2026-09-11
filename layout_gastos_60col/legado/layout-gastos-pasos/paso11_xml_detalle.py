"""
Paso 11 - Columnas 43, 47-52 (Fecha Factura, XML RFC/Monto/Serie/Folio/
MetodoPago/FormaPago). Mismo grano y dedup que UUID/etapa6.
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

df = pd.read_sql(leer_query("docs/queries/gastos/xml_detalle.sql"), engine)
df["FOLIO"] = df["FOLIO"].str.strip()
assert df["FOLIO"].is_unique, "fan-out en xml_detalle"

cols_nuevas = ["FECHA_FACTURA", "XML_RFC_EMISOR", "XML_MONTO", "XML_SERIE",
               "XML_FOLIO", "XML_METODO_PAGO", "XML_FORMA_PAGO"]
maestro = maestro.drop(columns=cols_nuevas).merge(df, on="FOLIO", how="left")
assert maestro["FOLIO"].is_unique

n = len(maestro)
cobertura = [(c, int(maestro[c].notna().sum()), n, round(100*maestro[c].notna().sum()/n, 1)) for c in cols_nuevas]

t = Table(title="Cobertura columnas 43, 47-52")
t.add_column("Columna"); t.add_column("Poblados", justify="right"); t.add_column("%", justify="right")
for c, p, tot, pct in cobertura:
    t.add_row(c, str(p), f"{pct}%")
console_err.print(t)

maestro.to_csv("v7_reporte_maestro_1_40_enero2026.csv", index=False)
console_err.print("\n[green]Actualizado: v7_reporte_maestro_1_40_enero2026.csv (con 43, 47-52)[/green]")

print("--- CSV_PARA_CLAUDE: cobertura_43_47_52 ---")
print(pd.DataFrame(cobertura, columns=["columna","poblados","universo","pct"]).to_csv(index=False))
