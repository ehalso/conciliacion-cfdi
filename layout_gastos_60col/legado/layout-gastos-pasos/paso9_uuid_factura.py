"""
Paso 9 - Columnas 41-42 (UUID, UUID_4), agregar al maestro 1-40 ya cerrado.
Misma logica de dedup que etapa6_columnas_1_18.sql (COUNT DISTINCT, no
COUNT(*) crudo -- ver check_uuid_por_folio.py, folios con UUID repetido
en 2 filas que NO son "Varios" real).
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

uuid_df = pd.read_sql(leer_query("docs/queries/gastos/uuid_factura.sql"), engine)
uuid_df["FOLIO"] = uuid_df["FOLIO"].str.strip()
assert uuid_df["FOLIO"].is_unique, "fan-out en UUID -- revisar dedup"

maestro = maestro.drop(columns=["UUID", "UUID_4"]).merge(uuid_df, on="FOLIO", how="left")
assert maestro["FOLIO"].is_unique

n = len(maestro)
n_uuid = int((maestro.UUID.notna() & (maestro.UUID != "VARIOS")).sum())
n_varios = int((maestro.UUID == "VARIOS").sum())
n_sin = int(maestro.UUID.isna().sum())

resumen_err(
    folios_universo=n,
    con_1_uuid=n_uuid, pct_1_uuid=round(100*n_uuid/n, 1),
    varios=n_varios, pct_varios=round(100*n_varios/n, 1),
    sin_xml=n_sin, pct_sin_xml=round(100*n_sin/n, 1),
)

maestro.to_csv("v7_reporte_maestro_1_40_enero2026.csv", index=False)
console_err.print("\n[green]Actualizado: v7_reporte_maestro_1_40_enero2026.csv (con UUID/UUID_4)[/green]")

print("--- CSV_PARA_CLAUDE: cobertura_uuid ---")
print(f"con_1_uuid,{n_uuid},{round(100*n_uuid/n,1)}")
print(f"varios,{n_varios},{round(100*n_varios/n,1)}")
print(f"sin_xml,{n_sin},{round(100*n_sin/n,1)}")

print("--- CSV_PARA_CLAUDE: muestra_varios ---")
print(maestro[maestro.UUID == "VARIOS"][["FOLIO","ORIGEN"]].head(10).to_csv(index=False))
