"""
Paso 13 - Columna 11 (FACTURA_REF), antes gap conocido. Fuente:
Grd_Referencia, mismo patron 'VARIOS' si multiples documentos con
referencia distinta.
"""
import sys
sys.path.append("..")
from connection_200_trivasadb3 import engine
import pandas as pd
from helpers_output import console_err, resumen_err

FECHA_INI, FECHA_FIN = "2026-01-01", "2026-02-01"

def leer_query(path):
    with open(path) as f:
        return f.read().replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")

maestro = pd.read_csv("v7_reporte_maestro_1_40_enero2026.csv")
maestro["FOLIO"] = maestro["FOLIO"].str.strip()
assert maestro["FOLIO"].is_unique

df = pd.read_sql(leer_query("docs/queries/gastos/factura_ref.sql"), engine)
df["FOLIO"] = df["FOLIO"].str.strip()
assert df["FOLIO"].is_unique, "fan-out en factura_ref"

maestro = maestro.drop(columns=["FACTURA_REF"]).merge(df, on="FOLIO", how="left")
assert maestro["FOLIO"].is_unique

n = len(maestro)
poblados = int(maestro.FACTURA_REF.notna().sum())
varios = int((maestro.FACTURA_REF == "VARIOS").sum())

resumen_err(
    folios_universo=n,
    con_factura_ref=poblados, pct=round(100*poblados/n, 1),
    folios_varios=varios,
)

maestro.to_csv("v7_reporte_maestro_1_40_enero2026.csv", index=False)
console_err.print("\n[green]Actualizado: v7_reporte_maestro_1_40_enero2026.csv (con FACTURA_REF, columna 11)[/green]")

print("--- CSV_PARA_CLAUDE: cobertura_factura_ref ---")
print(f"poblados,{poblados}\nvarios,{varios}\npct,{round(100*poblados/n,1)}")
