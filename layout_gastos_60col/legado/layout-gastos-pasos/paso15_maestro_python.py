"""
Paso 15 - Maestro 1-56, version "SQL tonto + Python con reglas nombradas".
5 queries crudas (solo joins, sin CASE/ROW_NUMBER) + reglas_negocio.py
(cada decision de negocio como funcion documentada y testeable aparte).

Mismo resultado que paso14_maestro_consolidado.py -- se corre y se compara
contra ese antes de reemplazarlo.
"""
import sys
sys.path.append("..")
from connection_200_trivasadb3 import engine
import pandas as pd
from rich.table import Table
from helpers_output import console_err, resumen_err
import reglas_negocio as reglas

FECHA_INI, FECHA_FIN = "2026-01-01", "2026-02-01"

def leer(nombre):
    with open(f"docs/queries/gastos/{nombre}.sql") as f:
        sql = f.read().replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")
    df = pd.read_sql(sql, engine)
    df["FOLIO"] = df["FOLIO"].str.strip()
    return df

base = pd.read_csv("v01_baseline_enero2026_sin_nomina_consumo.csv")
base["FOLIO"] = base["FOLIO"].str.strip()
assert base["FOLIO"].is_unique

console_err.print("[bold]Trayendo tablas crudas...[/bold]")
documentos = leer("raw_documentos")
pagos = leer("raw_pagos")
comprobantes = leer("raw_comprobante_pago")
xml = leer("raw_xml")
polizas = leer("raw_poliza")

cheques_folios = pagos[pagos.Pc_Tabla == "Cheque"]["Pc_Documento"].dropna().unique().tolist()
if cheques_folios:
    lista = "','".join(cheques_folios)
    cheques = pd.read_sql(f"SELECT Ch_Folio, Ch_Fecha FROM Cheque WHERE Ch_Folio IN ('{lista}')", engine)
else:
    cheques = pd.DataFrame(columns=["Ch_Folio", "Ch_Fecha"])

console_err.print("[bold]Aplicando reglas de negocio...[/bold]")

# Datos de folio (ORIGEN, FECHA, CONCEPTO_GASTO) -- unica pieza que no
# viene de raw_documentos (esta a nivel Gasto_Registro, no documento).
folios_meta = pd.read_sql(f"""
    SELECT
        gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
        gr.Gr_Tabla AS ORIGEN, gr.Gr_Fecha AS FECHA, gr.Gr_Comentario AS CONCEPTO_GASTO
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    WHERE gr.Gr_Fecha >= '{FECHA_INI}' AND gr.Gr_Fecha < '{FECHA_FIN}'
      AND gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = '0001'
      AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
""", engine)
folios_meta["FOLIO"] = folios_meta["FOLIO"].str.strip()

proveedor = reglas.resolver_proveedor(documentos)
referencia = reglas.resolver_referencia(documentos)
pago = reglas.resolver_pago(pagos)
cheque = reglas.resolver_cheque(pago, cheques)
cobrado = reglas.resolver_cobrado_efectivo_cheque(pago)
comprobante_pago = reglas.resolver_comprobante_pago(comprobantes)
xml_resuelto = reglas.resolver_xml(xml)
poliza = reglas.resolver_poliza(polizas)

console_err.print("[bold]Trayendo impuestos (19-40) y catalogo Uso_CFDI...[/bold]")
impuestos = leer("v5_impuestos_layout")
catalogo = pd.read_sql("SELECT Uc_Cve_Uso_CFDI, Uc_Descripcion FROM Uso_CFDI", engine)
catalogo["Uc_Cve_Uso_CFDI"] = catalogo["Uc_Cve_Uso_CFDI"].str.strip()
catalogo["Uc_Descripcion"] = catalogo["Uc_Descripcion"].str.strip()

console_err.print("[bold]Ensamblando maestro...[/bold]")
maestro = base[["FOLIO"]].copy()
for pieza in [folios_meta, proveedor, referencia, pago.drop(columns=["Pc_Documento", "Pc_Tabla"]),
              cheque, cobrado, comprobante_pago, xml_resuelto, poliza, impuestos]:
    maestro = maestro.merge(pieza, on="FOLIO", how="left")
    assert maestro["FOLIO"].is_unique, "fan-out al ensamblar -- revisar la ultima pieza mergeada"

maestro = maestro.merge(catalogo, left_on="CLAVE_USO_BIEN_SERVICIO", right_on="Uc_Cve_Uso_CFDI", how="left")
maestro["DESCRIPCION_USO_BIEN_SERVICIO"] = maestro["Uc_Descripcion"]
maestro.loc[maestro["CLAVE_USO_BIEN_SERVICIO"] == "VARIOS", "DESCRIPCION_USO_BIEN_SERVICIO"] = "VARIOS"
maestro = maestro.drop(columns=["Uc_Cve_Uso_CFDI", "Uc_Descripcion"])

maestro["DESCUENTO"] = 0.0
maestro["DESCUENTO_GLOBAL"] = 0.0

# Rellenar Proveedor/RFC/Nombre via join a Proveedor
prov_cat = pd.read_sql("SELECT Pv_Cve_Proveedor, Pv_R_F_C, Pv_Descripcion FROM Proveedor", engine)
maestro = maestro.rename(columns={"Pv_Cve_Proveedor": "CLAVE_PROVEEDOR", "Mn_Cve_Moneda": "MONEDA"})
maestro = maestro.merge(prov_cat, left_on="CLAVE_PROVEEDOR", right_on="Pv_Cve_Proveedor", how="left")
maestro = maestro.rename(columns={"Pv_R_F_C": "RFC_PROVEEDOR", "Pv_Descripcion": "NOMBRE_PROVEEDOR"})
maestro = maestro.drop(columns=["Pv_Cve_Proveedor"])
maestro = maestro.rename(columns={"Pc_Banco": "BANCO", "Pc_Cuenta_Bancaria": "CUENTA_BANCARIA",
                                   "Ch_Fecha": "FECHA_CHEQUE", "Ch_Folio": "NO_CHEQUE_TRANSF"})

assert len(maestro) == len(base)
assert maestro["FOLIO"].is_unique

maestro = maestro.drop(columns=["Fp_Cve_Forma_Pago"])
OUT = "v7_reporte_maestro_1_40_enero2026.csv"
maestro.to_csv(OUT, index=False)
console_err.print(f"\n[green]Guardado: {OUT}[/green]")

print("--- CSV_PARA_CLAUDE: cobertura_v9 ---")
n = len(maestro)
cobertura = [(c, int(maestro[c].notna().sum()), n, round(100*maestro[c].notna().sum()/n, 1))
             for c in maestro.columns if c != "FOLIO"]
print(pd.DataFrame(cobertura, columns=["columna","poblados","universo","pct"]).to_csv(index=False))
