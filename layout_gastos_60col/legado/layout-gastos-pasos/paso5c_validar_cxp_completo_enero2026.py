"""
Validacion CXP completa, enero 2026, universo = v01_baseline_enero2026_sin_nomina_consumo.csv.
Fix 2026-08-04: el total_gasto por referencia de CONTROL_COMBUSTIBLE debe sumar
TODOS los folios de esa (Grd_Referencia, Pv_Cve_Proveedor) sin restringir por
fecha ni por Gr_Tabla -- los folios tardios (Gr_Tabla vacio) suelen caer en el
mes siguiente (ver docs/control_combustible_hallazgo.md). Restringir a Gr_Fecha
de enero rompe el match para casi todas las referencias.
"""
import sys
sys.path.append("..")
from connection_200_trivasadb3 import engine
import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console(width=160)
FECHA_INI, FECHA_FIN = "2026-01-01", "2026-02-01"

base = pd.read_csv("v01_baseline_enero2026_sin_nomina_consumo.csv")
base["ORIGEN"] = base["ORIGEN"].fillna("GASTO_DIRECTO")
base["FOLIO"] = base["FOLIO"].str.strip()

# ============ CASO GENERAL (ya excluye CONTROL_COMBUSTIBLE) ============
with open("docs/queries/gastos/v_cxp_general.sql") as f:
    q_general = f.read().replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")

gen = pd.read_sql(q_general, engine)
gen["FOLIO"] = gen["FOLIO"].str.strip()
gen["CXP_MONEDA_ORIGINAL"] = gen["CXP_MONEDA_ORIGINAL"].fillna(0)
gen["DIFERENCIA"] = gen.CXP_MONEDA_ORIGINAL - gen.GASTO_MONEDA_ORIGINAL
gen["CUADRA"] = gen.DIFERENCIA.abs() < 1
gen["ESPERADO_SIN_CXP"] = (gen.CXP_MONEDA_ORIGINAL == 0) & (gen.Gr_Genera_Cxp == "NO")
gen["RESUELTO"] = gen.CUADRA | gen.ESPERADO_SIN_CXP

gen_folio = gen.groupby("FOLIO").agg(resuelto_folio=("RESUELTO", "all")).reset_index()
gen_folio["METODO"] = "general"

# ============ CASO CONTROL_COMBUSTIBLE ============
# Paso 1: folios de enero 2026 que pertenecen a nuestro universo (con su referencia+proveedor)
q_combustible_folios = f"""
SELECT
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
    grd.Grd_Referencia, grd.Pv_Cve_Proveedor
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = gr.Gr_Folio
WHERE gr.Gr_Tabla = 'CONTROL_COMBUSTIBLE'
  AND gr.Gr_Fecha >= '{FECHA_INI}' AND gr.Gr_Fecha < '{FECHA_FIN}'
  AND gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = '0001'
"""
comb_folios = pd.read_sql(q_combustible_folios, engine)
comb_folios["FOLIO"] = comb_folios["FOLIO"].str.strip()

# Paso 2: total_gasto por (referencia, proveedor) SIN restringir fecha ni Gr_Tabla
# -- solo restringido a las referencias que nos interesan (las del paso 1)
refs_unicas = comb_folios["Grd_Referencia"].unique().tolist()
proveedores_unicos = comb_folios["Pv_Cve_Proveedor"].unique().tolist()
assert len(proveedores_unicos) == 1, f"Se esperaba 1 solo proveedor, hay {proveedores_unicos}"
proveedor = proveedores_unicos[0]

placeholders = ",".join(["%s"] * len(refs_unicas))
q_totales_ref = f"""
SELECT grd.Grd_Referencia, grd.Pv_Cve_Proveedor,
       SUM(grd.Grd_Precio_Neto_Importe) AS total_gasto,
       COUNT(*) AS n_folios_totales
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = gr.Gr_Folio
WHERE gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = '0001'
  AND grd.Pv_Cve_Proveedor = %s
  AND grd.Grd_Referencia IN ({placeholders})
GROUP BY grd.Grd_Referencia, grd.Pv_Cve_Proveedor
"""
totales_ref = pd.read_sql(q_totales_ref, engine, params=tuple([proveedor] + refs_unicas))

q_cxp_ref = """
SELECT Cxp_Referencia AS Grd_Referencia, Pv_Cve_Proveedor,
       SUM(Cxp_Precio_Neto_Importe) AS total_cxp, COUNT(*) AS n_cxp_rows
FROM Cuenta_X_Pagar
WHERE Cxp_Tabla = 'Cuenta_X_Pagar'
GROUP BY Cxp_Referencia, Pv_Cve_Proveedor
"""
cxp_ref = pd.read_sql(q_cxp_ref, engine)

comb_ref = totales_ref.merge(cxp_ref, on=["Grd_Referencia", "Pv_Cve_Proveedor"], how="left")
comb_ref["total_cxp"] = comb_ref["total_cxp"].fillna(0)
comb_ref["DIFERENCIA"] = comb_ref.total_cxp - comb_ref.total_gasto
comb_ref["REF_CUADRA"] = comb_ref.DIFERENCIA.abs() < 1

comb_folios = comb_folios.merge(comb_ref[["Grd_Referencia", "Pv_Cve_Proveedor", "REF_CUADRA", "DIFERENCIA", "n_cxp_rows"]],
                                 on=["Grd_Referencia", "Pv_Cve_Proveedor"], how="left")
comb_folio = comb_folios.groupby("FOLIO").agg(resuelto_folio=("REF_CUADRA", "all")).reset_index()
comb_folio["METODO"] = "combustible"

# ============ COMBINAR Y CRUZAR CONTRA UNIVERSO COMPLETO ============
resultado = pd.concat([gen_folio, comb_folio], ignore_index=True)
full = base.merge(resultado, on="FOLIO", how="left")
full["resuelto_folio"] = full["resuelto_folio"].fillna(False)
full["METODO"] = full["METODO"].fillna("SIN_QUERY")

n, r = len(full), full.resuelto_folio.sum()
console.print(f"[bold]Universo completo (baseline, ene-2026):[/bold] {n} folios")
console.print(f"[bold]Resueltos:[/bold] {r} ({100*r/n:.1f}%)\n")

t1 = Table(title="Resumen por ORIGEN (universo completo)")
t1.add_column("Origen"); t1.add_column("Metodo"); t1.add_column("Folios", justify="right")
t1.add_column("Resueltos", justify="right"); t1.add_column("%", justify="right")
for (origen, metodo), g in full.groupby(["ORIGEN", "METODO"]):
    t1.add_row(str(origen), str(metodo), str(len(g)), str(g.resuelto_folio.sum()),
               f"{100*g.resuelto_folio.sum()/len(g):.1f}%")
console.print(t1)

console.print(f"\n[bold]Referencias de combustible -- {len(comb_ref)} totales, "
              f"{comb_ref.REF_CUADRA.sum()} cuadran ({100*comb_ref.REF_CUADRA.sum()/len(comb_ref):.1f}%)[/bold]")

no_resueltos = full[~full.resuelto_folio]
if len(no_resueltos):
    t2 = Table(title="Folios NO resueltos (revisar)")
    for c in ["FOLIO", "ORIGEN", "TOTAL", "METODO"]:
        t2.add_column(c, overflow="fold")
    for _, row in no_resueltos.head(20).iterrows():
        t2.add_row(str(row.FOLIO), str(row.ORIGEN), f"{row.TOTAL:,.2f}", str(row.METODO))
    console.print(t2)
else:
    console.print("\n[green]100% resuelto en el universo completo.[/green]")

full.to_csv("v_cxp_completo_enero2026.csv", index=False)
comb_ref.to_csv("v_cxp_combustible_referencias_enero2026.csv", index=False)
console.print("\n[green]Guardado: v_cxp_completo_enero2026.csv, v_cxp_combustible_referencias_enero2026.csv[/green]")
