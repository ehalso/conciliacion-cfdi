"""
v4.0c - Correccion 2026-08-04: la validacion correcta NO es
'Subtotal_0+16+Exenta = IMPORTE' (asumia que toda base gravable debe cubrir
el 100% del subtotal, falso para intereses financieros con exclusion de
componente inflacionario -- ver folio 0001-0034764).

La validacion correcta: SUM(Gri_Importe) por documento debe cuadrar contra
Grd_Impuesto_Importe -- eso confirma que los renglones de Gasto_Registro_Impuesto
(que es de donde sale cada columna del layout via Im_Cve_Impuesto) reconstruyen
el total de impuesto ya validado contra la baseline, sin exigir nada sobre
la base gravable.
"""
import sys
sys.path.append("..")
from connection_200_trivasadb3 import engine
import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console(width=160)
FECHA_INI, FECHA_FIN = "2026-01-01", "2026-02-01"

q = f"""
SELECT
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
    grd.Grd_ID,
    grd.Grd_Impuesto_Importe,
    SUM(gri.Gri_Importe) AS SUMA_GRI_IMPORTE,
    COUNT(gri.Im_Cve_Impuesto) AS n_renglones_impuesto
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
LEFT JOIN Gasto_Registro_Impuesto gri ON gri.Gr_Folio = grd.Gr_Folio AND gri.Grd_ID = grd.Grd_ID
WHERE gr.Gr_Fecha >= '{FECHA_INI}' AND gr.Gr_Fecha < '{FECHA_FIN}'
  AND gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, grd.Grd_ID, grd.Grd_Impuesto_Importe
"""
df = pd.read_sql(q, engine)
df["FOLIO"] = df["FOLIO"].str.strip()
df["SUMA_GRI_IMPORTE"] = df["SUMA_GRI_IMPORTE"].fillna(0)
df["DIFERENCIA"] = df.SUMA_GRI_IMPORTE - df.Grd_Impuesto_Importe
df["CUADRA"] = df.DIFERENCIA.abs() < 1

# Rollup a nivel folio (un folio puede tener varios Grd_ID)
rollup = df.groupby("FOLIO").agg(
    resuelto_folio=("CUADRA", "all"),
    n_documentos=("Grd_ID", "count"),
    impuesto_total=("Grd_Impuesto_Importe", "sum"),
).reset_index()

base = pd.read_csv("v01_baseline_enero2026_sin_nomina_consumo.csv")
base["FOLIO"] = base["FOLIO"].str.strip()
base["ORIGEN"] = base["ORIGEN"].fillna("GASTO_DIRECTO")
rollup = base.merge(rollup, on="FOLIO", how="left")
rollup["resuelto_folio"] = rollup["resuelto_folio"].fillna(False)

n, r = len(rollup), rollup.resuelto_folio.sum()
console.print(f"[bold]Folios (baseline enero 2026):[/bold] {n}")
console.print(f"[bold]SUM(Gri_Importe) cuadra contra Grd_Impuesto_Importe:[/bold] {r} ({100*r/n:.1f}%)\n")

t1 = Table(title="Resumen por ORIGEN")
t1.add_column("Origen"); t1.add_column("Folios", justify="right")
t1.add_column("Resuelto", justify="right"); t1.add_column("%", justify="right")
for origen, g in rollup.groupby("ORIGEN"):
    t1.add_row(str(origen), str(len(g)), str(g.resuelto_folio.sum()), f"{100*g.resuelto_folio.sum()/len(g):.1f}%")
console.print(t1)

no_resueltos = rollup[~rollup.resuelto_folio]
if len(no_resueltos):
    t2 = Table(title="Folios NO resueltos (SUM(Gri_Importe) != Grd_Impuesto_Importe)")
    for c in ["FOLIO", "ORIGEN", "IMPUESTOS"]:
        t2.add_column(c, overflow="fold")
    for _, row in no_resueltos.head(25).iterrows():
        t2.add_row(str(row.FOLIO), str(row.ORIGEN), f"{row.IMPUESTOS:,.2f}")
    console.print(t2)
else:
    console.print("\n[green]100% resuelto.[/green]")

df.to_csv("v4c_impuestos_detalle_enero2026.csv", index=False)
console.print("\n[green]Guardado: v4c_impuestos_detalle_enero2026.csv[/green]")
