"""
Paso 7 - Reporte maestro, columnas 1-40 del layout (nivel folio, 1:1).
Une etapa6_columnas_1_18.sql (1-18) + v5_impuestos_layout.sql (19-40) --
ambas validadas al 100%/95.7%+ y confirmadas 1 fila/folio (assert en cada
script origen). Cargo/Abono (59-60) y Cuenta Registro (57-58) NO van aqui
-- viven en su propia tabla de detalle (paso7_detalle_cuenta.py), a
distinto grano, para consumirse como expandible en el reporte final.

Columnas 41-56 (UUID, XML, poliza descriptiva) quedan como placeholder --
no resueltas en esta carpeta todavia.
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

# --- Universo base ---
base = pd.read_csv("v01_baseline_enero2026_sin_nomina_consumo.csv")
base["FOLIO"] = base["FOLIO"].str.strip()
assert base["FOLIO"].is_unique

# --- Columnas 1-18 ---
df_1_18 = pd.read_sql(leer_query("docs/queries/gastos/etapa6_columnas_1_18.sql"), engine)
df_1_18["FOLIO"] = df_1_18["FOLIO"].str.strip()
assert df_1_18["FOLIO"].is_unique, "fan-out en columnas 1-18"

# --- Columnas 19-40 ---
df_19_40 = pd.read_sql(leer_query("docs/queries/gastos/v5_impuestos_layout.sql"), engine)
df_19_40["FOLIO"] = df_19_40["FOLIO"].str.strip()
assert df_19_40["FOLIO"].is_unique, "fan-out en columnas 19-40"

# --- Merge maestro (1-40) ---
maestro = (base[["FOLIO"]]
           .merge(df_1_18, on="FOLIO", how="left")
           .merge(df_19_40, on="FOLIO", how="left", suffixes=("", "_imp")))
assert len(maestro) == len(base), "el merge cambio el numero de filas -- revisar fan-out"
assert maestro["FOLIO"].is_unique

# --- Placeholders explícitos, columnas 41-56 (pendientes) ---
PENDIENTES_41_56 = [
    "UUID", "UUID_4", "FECHA_FACTURA", "CONCEPTO_GASTO",
    "CLAVE_USO_BIEN_SERVICIO", "DESCRIPCION_USO_BIEN_SERVICIO",
    "XML_RFC_EMISOR", "XML_MONTO", "XML_SERIE", "XML_FOLIO",
    "XML_METODO_PAGO", "XML_FORMA_PAGO",
    "FECHA_POLIZA", "TIPO_POLIZA", "NUMERO_POLIZA", "CONCEPTO_POLIZA",
]
for col in PENDIENTES_41_56:
    maestro[col] = pd.NA

OUT = "v7_reporte_maestro_1_40_enero2026.csv"
maestro.to_csv(OUT, index=False)

# --- Cobertura por columna ---
n = len(maestro)
cobertura = []
for col in maestro.columns:
    if col == "FOLIO":
        continue
    poblados = int(maestro[col].notna().sum())
    cobertura.append((col, poblados, n, round(100*poblados/n, 1)))

t = Table(title="Cobertura por columna -- reporte maestro (1-40, nivel folio)")
t.add_column("Columna"); t.add_column("Poblados", justify="right"); t.add_column("%", justify="right")
for col, pob, tot, pct in cobertura:
    marca = "" if pct == 0 else ""
    t.add_row(col, str(pob), f"{pct}%")
console_err.print(t)

resumen_err(
    folios_universo=n,
    columnas_1_40=len(maestro.columns) - 1,
    columnas_pobladas_100pct=sum(1 for _,_,_,p in cobertura if p == 100.0),
    columnas_placeholder=len(PENDIENTES_41_56),
)
console_err.print(f"\n[green]Guardado: {OUT}[/green]")

print("--- CSV_PARA_CLAUDE: cobertura_reporte_maestro ---")
print(pd.DataFrame(cobertura, columns=["columna","poblados","universo","pct"]).to_csv(index=False))
