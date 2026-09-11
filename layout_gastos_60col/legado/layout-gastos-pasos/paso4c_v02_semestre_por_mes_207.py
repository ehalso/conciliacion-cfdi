"""
Enfoque B (3 queries, el elegido por mantenibilidad) + desglose de
reconciliacion por mes. Enero-junio 2026.
"""
import sys
sys.path.append("..")
from connection_207 import engine
import pandas as pd
from rich.console import Console
from rich.table import Table

console = Console()
FECHA_INI, FECHA_FIN = "2026-01-01", "2026-07-01"

QUERY_V01 = f"""
SELECT
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + CONVERT(varchar, gr.Gr_Folio), 7) AS FOLIO,
    gr.Gr_Tabla AS ORIGEN,
    gr.Gr_Fecha AS FECHA,
    SUM(grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio) AS IMPORTE
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
WHERE gr.Gr_Fecha >= '{FECHA_INI}' AND gr.Gr_Fecha < '{FECHA_FIN}'
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, gr.Gr_Tabla, gr.Gr_Fecha
"""

def leer(nombre):
    with open(f"docs/queries/gastos/{nombre}") as f:
        return f.read().replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")

v01 = pd.read_sql(QUERY_V01, engine); v01["FOLIO"] = v01["FOLIO"].str.strip()
general = pd.read_sql(leer("v02_general.sql"), engine); general["FOLIO"] = general["FOLIO"].str.strip()
recla = pd.read_sql(leer("v02_reclasificacion.sql"), engine); recla["FOLIO"] = recla["FOLIO"].str.strip()

folios_reversion = v01[v01.IMPORTE <= -1.0].FOLIO.tolist()
if folios_reversion:
    folios_lista = "','".join(folios_reversion)
    q_rev = leer("v02_reversion.sql").replace(
        "WHERE gr.Gr_Fecha", f"WHERE gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + CONVERT(varchar, gr.Gr_Folio), 7) IN ('{folios_lista}') AND gr.Gr_Fecha"
    )
    reversion = pd.read_sql(q_rev, engine); reversion["FOLIO"] = reversion["FOLIO"].str.strip()
else:
    reversion = pd.DataFrame(columns=["FOLIO", "ABONO"])

df = v01.copy()
df["CARGO"] = 0.0
df["ABONO"] = 0.0
df = df.merge(general, on="FOLIO", how="left", suffixes=("", "_g"))
m = df["CARGO_g"].notna(); df.loc[m, "CARGO"] = df.loc[m, "CARGO_g"]; df.loc[m, "ABONO"] = df.loc[m, "ABONO_g"]
df = df.drop(columns=["CARGO_g", "ABONO_g"])
df = df.merge(recla, on="FOLIO", how="left", suffixes=("", "_r"))
m = df["CARGO_r"].notna(); df.loc[m, "CARGO"] = df.loc[m, "CARGO_r"]; df.loc[m, "ABONO"] = df.loc[m, "ABONO_r"]
df = df.drop(columns=["CARGO_r", "ABONO_r"])
df = df.merge(reversion, on="FOLIO", how="left", suffixes=("", "_v"))
m = df["ABONO_v"].notna(); df.loc[m, "CARGO"] = 0.0; df.loc[m, "ABONO"] = df.loc[m, "ABONO_v"]
df = df.drop(columns=["ABONO_v"])

df["DIFERENCIA"] = (df.CARGO - df.ABONO) - df.IMPORTE
df["CUADRA"] = df.DIFERENCIA.abs() < 1
df["MES"] = pd.to_datetime(df.FECHA).dt.strftime("%Y-%m")

console.print(f"[bold]Total folios:[/bold] {len(df)}   [bold]Cuadran:[/bold] {df.CUADRA.sum()} ({100*df.CUADRA.sum()/len(df):.2f}%)\n")

# --- Desglose por mes ---
resumen_mes = df.groupby("MES").agg(
    n=("FOLIO", "count"), cuadran=("CUADRA", "sum")
).reset_index()
resumen_mes["no_cuadran"] = resumen_mes.n - resumen_mes.cuadran
resumen_mes["pct"] = (resumen_mes.cuadran / resumen_mes.n * 100).round(2)

t = Table(title="Reconciliación por mes")
t.add_column("Mes")
t.add_column("Folios", justify="right")
t.add_column("Cuadran", justify="right")
t.add_column("No cuadran", justify="right")
t.add_column("%", justify="right")
for _, r in resumen_mes.iterrows():
    color = "green" if r.pct >= 99 else "yellow" if r.pct >= 95 else "red"
    t.add_row(str(r.MES), str(r.n), str(r.cuadran), str(r.no_cuadran), f"[{color}]{r.pct}%[/{color}]")
console.print(t)

# --- Desglose por mes x origen, para ver si el problema se concentra en algo ---
resumen_mo = df.groupby(["MES", df["ORIGEN"].fillna("GASTO_DIRECTO")]).agg(
    n=("FOLIO", "count"), cuadran=("CUADRA", "sum")
).reset_index()
resumen_mo["no_cuadran"] = resumen_mo.n - resumen_mo.cuadran
solo_con_fallos = resumen_mo[resumen_mo.no_cuadran > 0]
if len(solo_con_fallos):
    console.print("\n[bold]Desglose mes x origen (solo donde hay fallos):[/bold]")
    t2 = Table()
    t2.add_column("Mes")
    t2.add_column("Origen")
    t2.add_column("n", justify="right")
    t2.add_column("No cuadran", justify="right")
    for _, r in solo_con_fallos.iterrows():
        t2.add_row(str(r.MES), str(r.ORIGEN), str(r.n), str(r.no_cuadran))
    console.print(t2)

df.to_csv("v02_semestre_por_mes.csv", index=False)
console.print(f"\n[green]Guardado: v02_semestre_por_mes.csv[/green]")
