"""
Paso 10 - Columnas 44-46 (Concepto gasto, Clave/Descripcion Uso bien o
servicio). La clave (44-45) sale de SQL; la descripcion (46) se resuelve
en pandas contra el catalogo Uso_CFDI (tabla completa, 24 filas) -- el
JOIN a esa tabla dentro de un CTE anidado fallaba en pymssql/FreeTDS con
"invalid column name" para una columna confirmada existente (bug del
driver con CTEs profundos, no del schema).
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

df = pd.read_sql(leer_query("docs/queries/gastos/uso_cfdi_por_folio.sql"), engine)
df["FOLIO"] = df["FOLIO"].str.strip()
assert df["FOLIO"].is_unique, "fan-out en concepto/uso cfdi"

# --- Catalogo completo, tabla chica, join en pandas ---
catalogo = pd.read_sql("SELECT Uc_Cve_Uso_CFDI, Uc_Descripcion FROM Uso_CFDI", engine)
catalogo["Uc_Cve_Uso_CFDI"] = catalogo["Uc_Cve_Uso_CFDI"].str.strip()
catalogo["Uc_Descripcion"] = catalogo["Uc_Descripcion"].str.strip()

df = df.merge(catalogo, left_on="CLAVE_USO_BIEN_SERVICIO", right_on="Uc_Cve_Uso_CFDI", how="left")
df["DESCRIPCION_USO_BIEN_SERVICIO"] = df["Uc_Descripcion"]
df.loc[df["CLAVE_USO_BIEN_SERVICIO"] == "VARIOS", "DESCRIPCION_USO_BIEN_SERVICIO"] = "VARIOS"
df = df.drop(columns=["Uc_Cve_Uso_CFDI", "Uc_Descripcion"])

maestro = maestro.drop(columns=["CONCEPTO_GASTO", "CLAVE_USO_BIEN_SERVICIO", "DESCRIPCION_USO_BIEN_SERVICIO"])
maestro = maestro.merge(df, on="FOLIO", how="left")
assert maestro["FOLIO"].is_unique

n = len(maestro)
resumen_err(
    folios_universo=n,
    con_concepto=int(maestro.CONCEPTO_GASTO.notna().sum()),
    con_clave_uso=int(maestro.CLAVE_USO_BIEN_SERVICIO.notna().sum()),
    con_descripcion=int(maestro.DESCRIPCION_USO_BIEN_SERVICIO.notna().sum()),
    claves_sin_descripcion=int(maestro[maestro.CLAVE_USO_BIEN_SERVICIO.notna() & maestro.DESCRIPCION_USO_BIEN_SERVICIO.isna() & (maestro.CLAVE_USO_BIEN_SERVICIO != "VARIOS")].shape[0]),
)

maestro.to_csv("v7_reporte_maestro_1_40_enero2026.csv", index=False)
console_err.print("\n[green]Actualizado: v7_reporte_maestro_1_40_enero2026.csv (con 44-46)[/green]")

print("--- CSV_PARA_CLAUDE: cobertura_44_46 ---")
print(f"con_concepto,{int(maestro.CONCEPTO_GASTO.notna().sum())}")
print(f"con_clave_uso,{int(maestro.CLAVE_USO_BIEN_SERVICIO.notna().sum())}")
print(f"con_descripcion,{int(maestro.DESCRIPCION_USO_BIEN_SERVICIO.notna().sum())}")

print("--- CSV_PARA_CLAUDE: distribucion_claves ---")
print(maestro.CLAVE_USO_BIEN_SERVICIO.value_counts(dropna=False).reset_index().to_csv(index=False))
