"""
Drill-down completo de los folios que NO cuadran contra .207 (produccion).
Primero recalcula v0.2 (enfoque 3 queries) para identificar cuales son,
despues trae el detalle completo de Poliza_Detalle de cada uno.
"""
import sys
sys.path.append("..")
from connection_207 import engine, q
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()
FECHA_INI, FECHA_FIN = "2026-01-01", "2026-07-01"

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

mal = df[~df.CUADRA]
console.print(f"[bold]Folios que NO cuadran contra .207:[/bold] {len(mal)}\n")
console.print(mal[["FOLIO","ORIGEN","IMPORTE","CARGO","ABONO","DIFERENCIA"]].to_string(index=False))

# --- Drill-down de cada uno ---
for _, fila in mal.iterrows():
    folio = fila.FOLIO
    # Pc_Documento/Gr_Folio reales usan sucursal de 2 digitos, no los 4 que
    # usamos nosotros para mostrar -- reconstruir antes de buscar.
    sucursal_4, num_folio = folio.split("-")
    folio_raw = sucursal_4[-2:] + "-" + num_folio
    console.print(Panel(
        f"[bold]{folio}[/bold]  Origen: {fila.ORIGEN or 'GASTO_DIRECTO'}  "
        f"Importe: {fila.IMPORTE:,.2f}  Cargo: {fila.CARGO:,.2f}  Abono: {fila.ABONO:,.2f}",
        border_style="cyan"
    ))

    detalle = q(f"""
        SELECT pd.Pd_ID, pd.Pd_Tipo, pd.Pd_Importe, pd.Cc_Cve_Cuenta_Contable, cc.Cc_Descripcion
        FROM Poliza_Control plc
        JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio
        JOIN Poliza_Detalle pd ON pd.Pl_Folio = plc.Pl_Folio AND pd.Pd_Referencia = '{folio_raw}'
        LEFT JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable
        WHERE plc.Pc_Tabla = 'GASTO_REGISTRO' AND plc.Pc_Documento = '{folio_raw}'
          AND plc.Es_Cve_Estado <> 'CA' AND pl.Es_Cve_Estado <> 'CA'
        ORDER BY pd.Pd_ID
    """)

    if detalle.empty:
        console.print("[red]Sin líneas de Poliza_Detalle encontradas -- probablemente sin póliza posteada.[/red]\n")
        continue

    t = Table()
    for c in detalle.columns: t.add_column(c, overflow="fold")
    for _, r in detalle.iterrows():
        t.add_row(*[f"{v:,.2f}" if isinstance(v, float) else str(v) for v in r])
    console.print(t)
    console.print()
