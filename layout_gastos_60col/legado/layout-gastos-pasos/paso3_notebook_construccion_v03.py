"""
Notebook de análisis: cómo se construye la query ganadora (V3) paso a paso.
Cada celda muestra el SQL (con comentarios, como un bloque de código de Colab)
y luego el resultado de correrlo -- para ver qué agrega cada pieza antes de
juntarlo todo en la query final.
"""
import sys
sys.path.append("..")
from connection_200_trivasadb3 import engine

import pandas as pd
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

console = Console()

def celda(numero, titulo, sql, muestra_cols=None, mostrar_filas=5):
    console.rule(f"[bold cyan]Celda {numero} — {titulo}[/bold cyan]")
    console.print(Syntax(sql.strip(), "sql", theme="monokai", line_numbers=False, word_wrap=True))
    df = pd.read_sql(sql, engine)
    console.print(f"\n[bold]# Output: {len(df)} filas[/bold]")
    cols = muestra_cols or list(df.columns)
    t = Table()
    for c in cols: t.add_column(c, overflow="fold")
    for _, r in df.head(mostrar_filas).iterrows():
        t.add_row(*[f"{r[c]:,.2f}" if isinstance(r[c], float) else str(r[c]) for c in cols])
    console.print(t)
    console.print()
    return df


# ============================================================
# Celda 1 — el folio base, sin nada más
# ============================================================
celda(1, "Gasto_Registro solo", """
-- Arrancamos del folio: fecha, sucursal, origen.
-- Todavía sin dinero (eso vive en Gasto_Registro_Documento),
-- sin póliza (eso viene en las celdas siguientes).
SELECT TOP 5
    gr.Gr_Folio,
    gr.Sc_Cve_Sucursal,
    gr.Gr_Fecha,
    gr.Gr_Tabla            -- origen: VIAJE, ORDEN_COMPRA, (vacío), etc.
FROM Gasto_Registro gr
WHERE gr.Gr_Fecha >= '2026-01-01' AND gr.Gr_Fecha < '2026-02-01'
  AND gr.Es_Cve_Estado <> 'CA'   -- 'CA' = cancelado; NO usar 'ACTI' aquí, esta
                                  -- tabla no sigue esa convención
ORDER BY gr.Gr_Folio
""")

# ============================================================
# Celda 2 — filtro de empresa vía Sucursal
# ============================================================
celda(2, "+ JOIN Sucursal (filtro de empresa)", """
-- Gasto_Registro NO trae empresa directo. Sin este join se cuelan
-- sucursales de otras empresas (0071->0003, 0076->0004) mezcladas
-- con la 0001 que nos interesa.
SELECT TOP 5
    gr.Gr_Folio,
    gr.Sc_Cve_Sucursal,
    s.Em_Cve_Empresa
FROM Gasto_Registro gr
JOIN Sucursal s
    ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
WHERE gr.Gr_Fecha >= '2026-01-01' AND gr.Gr_Fecha < '2026-02-01'
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
ORDER BY gr.Gr_Folio
""")

# ============================================================
# Celda 3 — llegar a Poliza_Control, fila por fila
# ============================================================
celda(3, "+ JOIN Poliza_Control (Pc_Documento = Gr_Folio)", """
-- Resolvemos QUÉ póliza corresponde a este folio específico.
-- IMPORTANTE: se hace fila por fila desde gr (ya acotado por fecha)
-- porque Pd_Referencia/Pc_Documento son solo el número de folio, sin
-- año -- el mismo número se reutiliza en años distintos (3,179
-- colisiones confirmadas en toda la tabla). Sin este orden de joins
-- se mezclan folios de otros años.
SELECT TOP 5
    gr.Gr_Folio,
    plc.Pl_Folio,
    plc.Pc_Tabla,
    plc.Pc_Documento
FROM Gasto_Registro gr
JOIN Sucursal s
    ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
WHERE gr.Gr_Fecha >= '2026-01-01' AND gr.Gr_Fecha < '2026-02-01'
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
ORDER BY gr.Gr_Folio
""")

# ============================================================
# Celda 4 — llegar a Poliza_Detalle, doblemente acotado
# ============================================================
celda(4, "+ JOIN Poliza_Detalle (Pl_Folio + Pd_Referencia)", """
-- Las líneas reales de Cargo/Abono. Doble condición a propósito:
--   1. pd.Pl_Folio = plc.Pl_Folio  -> la póliza ya resuelta en Celda 3
--   2. pd.Pd_Referencia = gr.Gr_Folio -> por si esa póliza trae
--      líneas de OTROS folios batcheados en el mismo asiento
SELECT TOP 5
    gr.Gr_Folio,
    pd.Pd_ID,
    pd.Pd_Tipo,             -- 1 = Cargo, 2 = Abono
    pd.Pd_Importe,
    pd.Cc_Cve_Cuenta_Contable
FROM Gasto_Registro gr
JOIN Sucursal s
    ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
JOIN Poliza pl
    ON pl.Pl_Folio = plc.Pl_Folio
JOIN Poliza_Detalle pd
    ON pd.Pl_Folio = plc.Pl_Folio
   AND pd.Pd_Referencia = gr.Gr_Folio
WHERE gr.Gr_Fecha >= '2026-01-01' AND gr.Gr_Fecha < '2026-02-01'
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND pl.Es_Cve_Estado <> 'CA'
ORDER BY gr.Gr_Folio, pd.Pd_ID
""")

# ============================================================
# Celda 5 — Cargo vs Abono crudo (sin filtrar cuenta todavía)
# ============================================================
celda(5, "Pd_Tipo = 2: el Abono crudo, sin filtrar", """
-- Cargo (Pd_Tipo=1) siempre es gasto real, no necesita filtro.
-- Abono (Pd_Tipo=2) es AMBIGUO: la mayoría es la otra mitad normal
-- del asiento (banco, proveedores), no una reducción de gasto real.
-- Por eso no se puede sumar Abono tal cual -- hay que filtrar por cuenta.
SELECT TOP 5
    gr.Gr_Folio,
    pd.Pd_Importe,
    pd.Cc_Cve_Cuenta_Contable
FROM Gasto_Registro gr
JOIN Sucursal s
    ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
JOIN Poliza pl
    ON pl.Pl_Folio = plc.Pl_Folio
JOIN Poliza_Detalle pd
    ON pd.Pl_Folio = plc.Pl_Folio
   AND pd.Pd_Referencia = gr.Gr_Folio
WHERE gr.Gr_Fecha >= '2026-01-01' AND gr.Gr_Fecha < '2026-02-01'
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND pl.Es_Cve_Estado <> 'CA'
  AND pd.Pd_Tipo = 2
ORDER BY gr.Gr_Folio, pd.Pd_ID
""")

# ============================================================
# Celda 6 — el filtro ganador de V3: cuenta '6xxx'
# ============================================================
celda(6, "V3: Abono solo si la cuenta empieza con '6'", """
-- Hallazgo de la iteración de simplificación: las cuentas de Gastos
-- en el catálogo de Trivasa empiezan con '6' (6xxx). Filtrar por eso
-- -- sin joins extra a Cuenta_Contable ni árbol recursivo de
-- Grupo_Cuenta_Contable -- recupera 99.6% de reconciliación (vs 99.7%
-- del método completo con CTE), al costo de solo 2 folios adicionales
-- sin cuadrar. Ver docs/v03_simplificacion_resultados.md.
SELECT TOP 5
    gr.Gr_Folio,
    pd.Cc_Cve_Cuenta_Contable,
    pd.Pd_Importe
FROM Gasto_Registro gr
JOIN Sucursal s
    ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
JOIN Poliza pl
    ON pl.Pl_Folio = plc.Pl_Folio
JOIN Poliza_Detalle pd
    ON pd.Pl_Folio = plc.Pl_Folio
   AND pd.Pd_Referencia = gr.Gr_Folio
WHERE gr.Gr_Fecha >= '2026-01-01' AND gr.Gr_Fecha < '2026-02-01'
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND pl.Es_Cve_Estado <> 'CA'
  AND pd.Pd_Tipo = 2
  AND LEFT(pd.Cc_Cve_Cuenta_Contable, 1) = '6'
ORDER BY gr.Gr_Folio, pd.Pd_ID
""")

# ============================================================
# Celda 7 — todo junto: query final agregada por folio
# ============================================================
console.rule("[bold green]Celda 7 — Query final V3 (agregada por folio)[/bold green]")

FINAL_SQL = """
-- Todo lo de las celdas 1-6 junto, agregado a nivel folio.
-- CARGO = suma de Pd_Tipo=1 (sin filtro, siempre gasto real).
-- ABONO = suma de Pd_Tipo=2 SOLO en cuentas '6xxx' (Celda 6).
-- Excluye CONSUMO_INTERNO/GASTO_REGISTRO_NOMINA: esos orígenes no
-- llevan póliza por diseño (Cargo/Abono vacíos a propósito).
SELECT
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + CONVERT(varchar, gr.Gr_Folio), 7) AS FOLIO,
    SUM(CASE WHEN pd.Pd_Tipo = 1 THEN pd.Pd_Importe ELSE 0 END) AS CARGO,
    SUM(CASE WHEN pd.Pd_Tipo = 2 AND LEFT(pd.Cc_Cve_Cuenta_Contable, 1) = '6'
             THEN pd.Pd_Importe ELSE 0 END) AS ABONO
FROM Gasto_Registro gr
JOIN Sucursal s
    ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
JOIN Poliza pl
    ON pl.Pl_Folio = plc.Pl_Folio
JOIN Poliza_Detalle pd
    ON pd.Pl_Folio = plc.Pl_Folio
   AND pd.Pd_Referencia = gr.Gr_Folio
WHERE gr.Gr_Fecha >= '2026-01-01' AND gr.Gr_Fecha < '2026-02-01'
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND pl.Es_Cve_Estado <> 'CA'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio
"""
console.print(Syntax(FINAL_SQL.strip(), "sql", theme="monokai", line_numbers=False, word_wrap=True))

poliza = pd.read_sql(FINAL_SQL, engine)
base = pd.read_csv("v01_baseline_enero2026_sin_nomina_consumo.csv")
df = base.merge(poliza, on="FOLIO", how="left")
df[["CARGO", "ABONO"]] = df[["CARGO", "ABONO"]].fillna(0)
df["CUADRA"] = ((df.CARGO - df.ABONO) - df.IMPORTE).abs() < 1

n, c = len(df), df.CUADRA.sum()
console.print(f"\n[bold]# Output:[/bold] [bold green]Reconciliación final: {c}/{n} ({100*c/n:.1f}%)[/bold green]")
