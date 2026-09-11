"""
Etapa 6 - Validacion del bloque de proveedor, cobro/pago y comprobante de
pago (columnas 1-18 del layout de 60 columnas). Corre contra .200/TRIVASADB3,
enero 2026, universo v01_baseline_enero2026_sin_nomina_consumo.csv.

Query: docs/queries/gastos/etapa6_columnas_1_18.sql (1 fila por FOLIO).

A diferencia de v3.0/v5.0 (que cuadran contra un total conocido), este
bloque no tiene una identidad numerica global que cuadrar -- son campos
descriptivos (proveedor, banco, cheque, comprobante). La validacion aqui es
de COBERTURA: cuantos folios del universo quedan con cada grupo de columnas
poblado, explicando los huecos por causa de negocio conocida (igual
metodologia que v2.2/v3.0 con Gr_Genera_Cxp y CONTROL_COMBUSTIBLE).
"""
import sys
sys.path.append("..")
from connection_200_trivasadb3 import engine
import pandas as pd
from rich.table import Table
from helpers_output import console_err, resumen_err

FECHA_INI, FECHA_FIN = "2026-01-01", "2026-02-01"

with open("docs/queries/gastos/etapa6_columnas_1_18.sql") as f:
    QUERY = f.read().replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")

df = pd.read_sql(QUERY, engine)
df["FOLIO"] = df["FOLIO"].str.strip()
assert df["FOLIO"].is_unique, "FOLIO no es unico en el resultado del SQL -- revisar fan-out"

base = pd.read_csv("v01_baseline_enero2026_sin_nomina_consumo.csv")
base["FOLIO"] = base["FOLIO"].str.strip()
base["ORIGEN"] = base["ORIGEN"].fillna("GASTO_DIRECTO")

full = base[["FOLIO", "ORIGEN"]].merge(df.drop(columns=["ORIGEN"]), on="FOLIO", how="left")
assert len(full) == len(base), "El merge con el baseline cambio el numero de filas -- revisar fan-out"

n = len(full)
resumen_err(folios_universo=n, folios_en_query=int(df["FOLIO"].notna().sum()))

# --- Cobertura por bloque de columnas ---
bloques = {
    "Proveedor (4-6)": "CLAVE_PROVEEDOR",
    "Cobro/pago (7-9,12-13)": "BANCO",
    "CFDI comprobante de pago (10)": "CFDI_COMPROBANTE_PAGO",
    "FACTURA_REF (11) -- gap conocido": "FACTURA_REF",
    "Fecha/No. cheque (14-15)": "NO_CHEQUE_TRANSF",
    "Monto Cobrado (16)": "MONTO_COBRADO",
    "Tipo comprobante (17)": "TIPO_COMPROBANTE",
    "Numero de factura (18)": "NUMERO_FACTURA",
}
t0 = Table(title="Cobertura por bloque de columnas (universo completo, enero 2026)")
t0.add_column("Bloque"); t0.add_column("Poblados", justify="right"); t0.add_column("%", justify="right")
resumen_bloques_rows = []
for nombre, col in bloques.items():
    poblados = int(full[col].notna().sum())
    pct = 100 * poblados / n
    t0.add_row(nombre, str(poblados), f"{pct:.1f}%")
    resumen_bloques_rows.append((nombre, poblados, n, round(pct, 1)))
console_err.print(t0)

# --- Explicacion de huecos en el bloque de pago (7-10,12-16), por ORIGEN ---
full["SIN_PAGO"] = full["MONTO_COBRADO"].isna()
t1 = Table(title="Bloque de pago (Monto Cobrado como proxy) -- cobertura por ORIGEN")
t1.add_column("Origen"); t1.add_column("Folios", justify="right")
t1.add_column("Con pago", justify="right"); t1.add_column("%", justify="right")
for origen, g in full.groupby("ORIGEN"):
    con_pago = (~g.SIN_PAGO).sum()
    t1.add_row(str(origen), str(len(g)), str(con_pago), f"{100*con_pago/len(g):.1f}%")
console_err.print(t1)

# --- Explicacion de huecos en XML (17-18), por ORIGEN ---
full["SIN_XML"] = full["NUMERO_FACTURA"].isna()
t2 = Table(title="Bloque XML (Tipo comprobante / Numero factura) -- cobertura por ORIGEN")
t2.add_column("Origen"); t2.add_column("Folios", justify="right")
t2.add_column("Con XML", justify="right"); t2.add_column("%", justify="right")
for origen, g in full.groupby("ORIGEN"):
    con_xml = (~g.SIN_XML).sum()
    t2.add_row(str(origen), str(len(g)), str(con_xml), f"{100*con_xml/len(g):.1f}%")
console_err.print(t2)

# --- Proveedor multiple / muestra ---
n_multi = (full["PROVEEDOR_MULTIPLE"] == "SI").sum()
resumen_err(folios_proveedor_multiple=int(n_multi))

# --- Muestra de folios "VARIOS" (2+ UUID de comprobante de pago o de XML) ---
varios_pago = (full["CFDI_COMPROBANTE_PAGO"] == "VARIOS").sum()
varios_xml = (full["NUMERO_FACTURA"] == "VARIOS").sum()
resumen_err(folios_varios_comprobante_pago=int(varios_pago), folios_varios_xml=int(varios_xml))

full.to_csv("v6_layout_1_18_enero2026.csv", index=False)
console_err.print("\n[green]Guardado: v6_layout_1_18_enero2026.csv[/green]")

# --- Salida para Claude (stdout, para | cb) ---
print("--- CSV_PARA_CLAUDE: cobertura_por_bloque ---")
print(pd.DataFrame(resumen_bloques_rows, columns=["bloque", "poblados", "universo", "pct"]).to_csv(index=False))

print("--- CSV_PARA_CLAUDE: pago_por_origen ---")
pago_origen = full.groupby("ORIGEN").agg(folios=("FOLIO", "count"), con_pago=("SIN_PAGO", lambda s: (~s).sum())).reset_index()
pago_origen["pct"] = (100 * pago_origen.con_pago / pago_origen.folios).round(1)
print(pago_origen.to_csv(index=False))

print("--- CSV_PARA_CLAUDE: xml_por_origen ---")
xml_origen = full.groupby("ORIGEN").agg(folios=("FOLIO", "count"), con_xml=("SIN_XML", lambda s: (~s).sum())).reset_index()
xml_origen["pct"] = (100 * xml_origen.con_xml / xml_origen.folios).round(1)
print(xml_origen.to_csv(index=False))
