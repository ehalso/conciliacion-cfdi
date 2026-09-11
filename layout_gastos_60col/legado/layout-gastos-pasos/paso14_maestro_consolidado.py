"""
Paso 14 - Reconstruye el maestro 1-56 con UN solo query para el bloque
1-18/41-45/47-56 (maestro_detalle_1_56.sql) + v5_impuestos_layout.sql
para 19-40 (estructura de agregacion distinta, se mantiene aparte).
DESCUENTO/DESCUENTO_GLOBAL como literal 0. Descripcion Uso CFDI (46)
resuelta en pandas contra el catalogo (evita el bug de JOIN anidado).

Reemplaza paso7 + paso9 + paso10 + paso11 + paso12 + paso13 (6 round
trips independientes) por 2 round trips.
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
assert base["FOLIO"].is_unique

detalle = pd.read_sql(leer_query("docs/queries/gastos/maestro_detalle_1_56.sql"), engine)
detalle["FOLIO"] = detalle["FOLIO"].str.strip()
assert detalle["FOLIO"].is_unique, "fan-out en maestro_detalle_1_56 -- revisar"

impuestos = pd.read_sql(leer_query("docs/queries/gastos/v5_impuestos_layout.sql"), engine)
impuestos["FOLIO"] = impuestos["FOLIO"].str.strip()
assert impuestos["FOLIO"].is_unique, "fan-out en impuestos -- revisar"

# --- Catalogo Uso_CFDI, resuelto en pandas (evita bug de JOIN anidado) ---
catalogo = pd.read_sql("SELECT Uc_Cve_Uso_CFDI, Uc_Descripcion FROM Uso_CFDI", engine)
catalogo["Uc_Cve_Uso_CFDI"] = catalogo["Uc_Cve_Uso_CFDI"].str.strip()
catalogo["Uc_Descripcion"] = catalogo["Uc_Descripcion"].str.strip()

maestro = (base[["FOLIO"]]
           .merge(detalle, on="FOLIO", how="left")
           .merge(impuestos, on="FOLIO", how="left", suffixes=("", "_imp")))
assert len(maestro) == len(base), "el merge cambio el numero de filas -- revisar fan-out"
assert maestro["FOLIO"].is_unique

maestro = maestro.merge(catalogo, left_on="CLAVE_USO_BIEN_SERVICIO", right_on="Uc_Cve_Uso_CFDI", how="left")
maestro["DESCRIPCION_USO_BIEN_SERVICIO"] = maestro["Uc_Descripcion"]
maestro.loc[maestro["CLAVE_USO_BIEN_SERVICIO"] == "VARIOS", "DESCRIPCION_USO_BIEN_SERVICIO"] = "VARIOS"
maestro = maestro.drop(columns=["Uc_Cve_Uso_CFDI", "Uc_Descripcion"])

maestro["DESCUENTO"] = 0.0
maestro["DESCUENTO_GLOBAL"] = 0.0

OUT = "v7_reporte_maestro_1_40_enero2026.csv"
maestro.to_csv(OUT, index=False)

n = len(maestro)
cobertura = []
for col in maestro.columns:
    if col == "FOLIO":
        continue
    poblados = int(maestro[col].notna().sum())
    cobertura.append((col, poblados, n, round(100*poblados/n, 1)))

t = Table(title=f"Cobertura -- maestro consolidado ({len(maestro.columns)-1} columnas, 2 round trips)")
t.add_column("Columna"); t.add_column("Poblados", justify="right"); t.add_column("%", justify="right")
for col, pob, tot, pct in cobertura:
    t.add_row(col, str(pob), f"{pct}%")
console_err.print(t)

resumen_err(folios_universo=n, columnas_totales=len(maestro.columns) - 1)
console_err.print(f"\n[green]Guardado: {OUT}[/green]")

print("--- CSV_PARA_CLAUDE: cobertura_maestro_consolidado ---")
print(pd.DataFrame(cobertura, columns=["columna","poblados","universo","pct"]).to_csv(index=False))
