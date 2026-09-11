"""
v0.1 + v0.2 dividido en 3 queries independientes (general/reclasificacion/
reversion), cada folio usa exactamente una. Enero 2026.
"""
import sys
sys.path.append("..")
from connection_200_trivasadb3 import engine

import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()

FECHA_INI = "2026-01-01"
FECHA_FIN = "2026-02-01"

QUERY_V01 = f"""
SELECT
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + CONVERT(varchar, gr.Gr_Folio), 7) AS FOLIO,
    gr.Gr_Tabla AS ORIGEN,
    SUM(grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio) AS IMPORTE
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
WHERE gr.Gr_Fecha >= '{FECHA_INI}' AND gr.Gr_Fecha < '{FECHA_FIN}'
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, gr.Gr_Tabla
"""

def leer_query(nombre):
    with open(f"docs/queries/gastos/{nombre}") as f:
        return f.read()

QUERY_GENERAL = leer_query("v02_general.sql").replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")
QUERY_RECLASIFICACION = leer_query("v02_reclasificacion.sql").replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")
QUERY_REVERSION_BASE = leer_query("v02_reversion.sql").replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")

console.print(f"[bold]Corriendo v0.1...[/bold]")
v01 = pd.read_sql(QUERY_V01, engine)
v01["FOLIO"] = v01["FOLIO"].str.strip()
console.print(f"  {len(v01)} folios")

console.print(f"[bold]Corriendo v0.2 general...[/bold]")
general = pd.read_sql(QUERY_GENERAL, engine)
general["FOLIO"] = general["FOLIO"].str.strip()
console.print(f"  {len(general)} folios")

console.print(f"[bold]Corriendo v0.2 reclasificación...[/bold]")
recla = pd.read_sql(QUERY_RECLASIFICACION, engine)
recla["FOLIO"] = recla["FOLIO"].str.strip()
console.print(f"  {len(recla)} folios")

folios_reversion = v01[v01.IMPORTE <= -1.0].FOLIO.tolist()
console.print(f"[bold]Folios de reversión detectados (Importe<=-$1):[/bold] {len(folios_reversion)}")

if folios_reversion:
    folios_lista = "','".join(folios_reversion)
    QUERY_REVERSION = QUERY_REVERSION_BASE.replace(
        "WHERE gr.Gr_Fecha", f"WHERE gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + CONVERT(varchar, gr.Gr_Folio), 7) IN ('{folios_lista}') AND gr.Gr_Fecha"
    )
    reversion = pd.read_sql(QUERY_REVERSION, engine)
    reversion["FOLIO"] = reversion["FOLIO"].str.strip()
else:
    reversion = pd.DataFrame(columns=["FOLIO", "ABONO"])
console.print(f"  {len(reversion)} folios")

# --- Combinar: cada folio usa exactamente una fuente de Cargo/Abono ---
df = v01.copy()
df["CARGO"] = 0.0
df["ABONO"] = 0.0

df = df.merge(general, on="FOLIO", how="left", suffixes=("", "_gen"))
mask_gen = df["CARGO_gen"].notna()
df.loc[mask_gen, "CARGO"] = df.loc[mask_gen, "CARGO_gen"]
df.loc[mask_gen, "ABONO"] = df.loc[mask_gen, "ABONO_gen"]
df = df.drop(columns=["CARGO_gen", "ABONO_gen"])

df = df.merge(recla, on="FOLIO", how="left", suffixes=("", "_recla"))
mask_recla = df["CARGO_recla"].notna()
df.loc[mask_recla, "CARGO"] = df.loc[mask_recla, "CARGO_recla"]
df.loc[mask_recla, "ABONO"] = df.loc[mask_recla, "ABONO_recla"]
df = df.drop(columns=["CARGO_recla", "ABONO_recla"])

df = df.merge(reversion, on="FOLIO", how="left", suffixes=("", "_rev"))
mask_rev = df["ABONO_rev"].notna()
df.loc[mask_rev, "CARGO"] = 0.0
df.loc[mask_rev, "ABONO"] = df.loc[mask_rev, "ABONO_rev"]
df = df.drop(columns=["ABONO_rev"])

df["DIFERENCIA"] = (df.CARGO - df.ABONO) - df.IMPORTE
df["CUADRA"] = df.DIFERENCIA.abs() < 1

n, c = len(df), df.CUADRA.sum()
console.print(f"\n[bold]Reconciliación enero 2026:[/bold] {c}/{n} ({100*c/n:.2f}%)\n")

resumen = df.groupby(df["ORIGEN"].fillna("GASTO_DIRECTO")).agg(
    n=("FOLIO", "count"), cuadran=("CUADRA", "sum")
).reset_index()
resumen["pct"] = (resumen.cuadran / resumen.n * 100).round(2)
t_resumen = Table(title="Reconciliación por ORIGEN")
t_resumen.add_column("ORIGEN")
t_resumen.add_column("n", justify="right")
t_resumen.add_column("Cuadran", justify="right")
t_resumen.add_column("%", justify="right")
for _, r in resumen.iterrows():
    t_resumen.add_row(str(r.ORIGEN), str(r.n), str(r.cuadran), f"{r.pct}%")
console.print(t_resumen)

mal = df[~df.CUADRA].sort_values("DIFERENCIA", key=abs, ascending=False)
console.print(f"\n[bold red]Folios que NO cuadran:[/bold red] {len(mal)}")
if len(mal):
    t_mal = Table()
    for col in ["FOLIO", "ORIGEN", "IMPORTE", "CARGO", "ABONO", "DIFERENCIA"]:
        t_mal.add_column(col, overflow="fold")
    for _, r in mal.iterrows():
        t_mal.add_row(str(r.FOLIO), str(r.ORIGEN or "GASTO_DIRECTO"),
                       f"{r.IMPORTE:,.2f}", f"{r.CARGO:,.2f}", f"{r.ABONO:,.2f}", f"{r.DIFERENCIA:,.2f}")
    console.print(t_mal)

df.to_csv("v02_baseline_enero2026_v3.csv", index=False)
console.print(f"\n[green]Guardado: v02_baseline_enero2026_v3.csv[/green]")
