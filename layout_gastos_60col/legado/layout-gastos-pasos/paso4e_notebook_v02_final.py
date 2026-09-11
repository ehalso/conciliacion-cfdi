"""
Notebook: cómo queda la consulta completa de v0.1 + v0.2 (4 queries), con
comentarios explicando el porqué de cada una, mostrando output real de una
muestra (enero 2026, contra .207).
"""
import sys
sys.path.append("..")
from connection_207 import engine

import pandas as pd
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from rich.panel import Panel

console = Console()

def celda(numero, titulo, explicacion, sql, mostrar_filas=8):
    console.rule(f"[bold cyan]Celda {numero} — {titulo}[/bold cyan]")
    console.print(Panel(explicacion, border_style="dim"))
    console.print(Syntax(sql.strip(), "sql", theme="monokai", line_numbers=False, word_wrap=True))
    df = pd.read_sql(sql, engine)
    df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
    if "FOLIO" in df.columns:
        df["FOLIO"] = df["FOLIO"].str.strip()
    console.print(f"\n[bold]# Output: {len(df)} filas[/bold]")
    t = Table()
    for c in df.columns: t.add_column(c, overflow="fold")
    for _, r in df.head(mostrar_filas).iterrows():
        t.add_row(*[f"{v:,.2f}" if isinstance(v, float) else str(v) for v in r])
    console.print(t)
    console.print()
    return df

FECHA_INI, FECHA_FIN = "2026-01-01", "2026-02-01"

# ============================================================
# Celda 1 — v0.1: universo base (folio, origen, importe)
# ============================================================
v01 = celda(1, "v0.1 — universo base", """
El punto de partida de TODO lo demás. Un folio, su origen (Gr_Tabla), y su
IMPORTE real (subtotal SIN IVA -- Poliza_Detalle nunca incluye impuestos,
por eso comparamos contra el subtotal y no contra el total con IVA).
Convertido a MXN via Grd_Tipo_Cambio.
Excluye GASTO_REGISTRO_NOMINA/CONSUMO_INTERNO: no llevan poliza por diseño.
""", f"""
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
""")

# ============================================================
# Celda 2 — v0.2 caso GENERAL
# ============================================================
general = celda(2, "v0.2 — caso GENERAL (todo excepto GASTO_RECLASIFICACION)", """
Cargo: TODO Pd_Tipo=1, sin filtro (siempre gasto real).
Abono: SOLO Pd_Tipo=2 en cuentas '6xxx' (familia de Gastos) -- sin este
filtro, folios con doble partida legitima (ej. depreciacion: Abono va a
"Depreciacion Acumulada", cuenta de ACTIVO, no de gasto) rompen todo,
porque Cargo≈Abono es NORMAL contablemente ahi, no un error.
Join: Gr_Folio YA es el string 'SS-FFFFFFF' completo -- comparacion de
texto directa contra Pc_Documento/Pd_Referencia, sin CONVERT.
Poliza_Control.Es_Cve_Estado <> 'CA': confirmado en POLIZA_REDIRDOC.asp
real de MPRO, no solo se filtra en Poliza.
""", f"""
SELECT
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + CONVERT(varchar, gr.Gr_Folio), 7) AS FOLIO,
    SUM(CASE WHEN pd.Pd_Tipo = 1 THEN pd.Pd_Importe ELSE 0 END) AS CARGO,
    SUM(CASE WHEN pd.Pd_Tipo = 2 AND LEFT(pd.Cc_Cve_Cuenta_Contable, 1) = '6'
             THEN pd.Pd_Importe ELSE 0 END) AS ABONO
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
   AND plc.Es_Cve_Estado <> 'CA'
JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio
JOIN Poliza_Detalle pd
    ON pd.Pl_Folio = plc.Pl_Folio
   AND pd.Pd_Referencia = gr.Gr_Folio
WHERE gr.Gr_Fecha >= '{FECHA_INI}' AND gr.Gr_Fecha < '{FECHA_FIN}'
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND pl.Es_Cve_Estado <> 'CA'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO', 'GASTO_RECLASIFICACION')
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio
""")

# ============================================================
# Celda 3 — v0.2 caso GASTO_RECLASIFICACION
# ============================================================
recla = celda(3, "v0.2 — caso GASTO_RECLASIFICACION", """
Cargo=Abono simetrico por diseño: cada folio es un par espejo (mismo monto,
Cargo positivo + Abono negativo en Gasto_Registro_Documento) que MPRO
resuelve con una poliza real. El Abono puede caer en CUALQUIER cuenta
(confirmado con drill-down: activo, gastos, costo estandar...) -- por eso
aqui NO se filtra por cuenta, a diferencia del caso general.
""", f"""
SELECT
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + CONVERT(varchar, gr.Gr_Folio), 7) AS FOLIO,
    SUM(CASE WHEN pd.Pd_Tipo = 1 THEN pd.Pd_Importe ELSE 0 END) AS CARGO,
    SUM(CASE WHEN pd.Pd_Tipo = 2 THEN pd.Pd_Importe ELSE 0 END) AS ABONO
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
   AND plc.Es_Cve_Estado <> 'CA'
JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio
JOIN Poliza_Detalle pd
    ON pd.Pl_Folio = plc.Pl_Folio
   AND pd.Pd_Referencia = gr.Gr_Folio
WHERE gr.Gr_Fecha >= '{FECHA_INI}' AND gr.Gr_Fecha < '{FECHA_FIN}'
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND pl.Es_Cve_Estado <> 'CA'
  AND gr.Gr_Tabla = 'GASTO_RECLASIFICACION'
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio
""")

# ============================================================
# Celda 4 — v0.2 caso REVERSIÓN (folios con Importe negativo)
# ============================================================
folios_reversion = v01[v01.IMPORTE <= -1.0].FOLIO.tolist()
console.rule("[bold cyan]Celda 4 — v0.2 caso REVERSIÓN[/bold cyan]")
console.print(Panel(
    "Folios donde IMPORTE (de v0.1, Celda 1) <= -$1 -- son reversiones/saldos "
    "de una operación previa. La póliza trae Cargo Y Abono a la vez, pero el "
    "Cargo cae en una cuenta de Provisión/Pasivo (contrapartida de la "
    "reversión, no gasto real) -- solo se usa el Abono. Necesita la lista de "
    "folios como parámetro porque depende de IMPORTE (calculado en Celda 1), "
    "no se puede resolver dentro de esta misma query.",
    border_style="dim"))
console.print(f"[bold]Folios de reversión detectados este periodo:[/bold] {len(folios_reversion)}")
if folios_reversion:
    console.print(folios_reversion)

    folios_lista = "','".join(folios_reversion)
    sql_reversion = f"""
SELECT
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + CONVERT(varchar, gr.Gr_Folio), 7) AS FOLIO,
    SUM(CASE WHEN pd.Pd_Tipo = 2 THEN pd.Pd_Importe ELSE 0 END) AS ABONO
    -- (CARGO no se selecciona -- se descarta siempre en Python para estos folios)
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
   AND plc.Es_Cve_Estado <> 'CA'
JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio
JOIN Poliza_Detalle pd
    ON pd.Pl_Folio = plc.Pl_Folio
   AND pd.Pd_Referencia = gr.Gr_Folio
WHERE gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + CONVERT(varchar, gr.Gr_Folio), 7) IN ('{folios_lista}')
  AND gr.Gr_Fecha >= '{FECHA_INI}' AND gr.Gr_Fecha < '{FECHA_FIN}'
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND pl.Es_Cve_Estado <> 'CA'
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio
"""
    console.print(Syntax(sql_reversion.strip(), "sql", theme="monokai", line_numbers=False, word_wrap=True))
    reversion = pd.read_sql(sql_reversion, engine)
    reversion["FOLIO"] = reversion["FOLIO"].str.strip()
    console.print(f"\n[bold]# Output: {len(reversion)} filas[/bold]")
    console.print(reversion.to_string(index=False))
else:
    reversion = pd.DataFrame(columns=["FOLIO", "ABONO"])
    console.print("[dim]Sin folios de reversión este periodo, celda no ejecuta query.[/dim]")

# ============================================================
# Celda 5 — combinar las 4 en el resultado final
# ============================================================
console.rule("[bold green]Celda 5 — Combinar y validar[/bold green]")
console.print(Panel(
    "Cada folio usa EXACTAMENTE una fuente de Cargo/Abono, en este orden de "
    "prioridad: reversión > reclasificación > general. Después: "
    "DIFERENCIA = (Cargo - Abono) - Importe; CUADRA = |DIFERENCIA| < $1.",
    border_style="dim"))

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

n, c = len(df), df.CUADRA.sum()
console.print(f"\n[bold]Reconciliación final:[/bold] {c}/{n} ({100*c/n:.2f}%)")
