"""
Helper de salida estandar para scripts de comprobacion/validacion (conteos,
reconciliaciones, checks de calidad de dato). Origen: trivasa-bi-dev/
exploracion/layout_gastos/, generalizado el 2026-08-10 para reusarse en
cualquier proyecto -- sin dependencias propias de ese directorio.

Formato elegido 2026-08-04: rich.Console() SIN ancho fijo (auto-detecta
el ancho real de la terminal del usuario, confirmado 138 columnas) --
mas legible que Console(width=160) fijo, que rompia tablas anchas en
bloques verticales ilegibles.

Uso:
    from helpers_output import console, mostrar_tabla, resumen
"""
from rich.console import Console
from rich.table import Table

console = Console()  # SIN width fijo -- auto-detecta terminal del usuario

def mostrar_tabla(df, titulo, max_filas=30):
    """Muestra un dataframe como tabla rich, formato estandar del proyecto."""
    t = Table(title=titulo)
    for c in df.columns:
        t.add_column(c, overflow="fold")
    for _, row in df.head(max_filas).iterrows():
        t.add_row(*[str(v) for v in row])
    console.print(t)
    if len(df) > max_filas:
        console.print(f"[dim](mostrando {max_filas} de {len(df)} filas totales)[/dim]")

def resumen(**kpis):
    """Linea de resumen compacta, formato key=value."""
    linea = " | ".join(f"{k}={v}" for k, v in kpis.items())
    console.print(f"\n[bold]{linea}[/bold]")

# ============================================================================
# Actualización 2026-08-05: variantes a stderr, para separar salida humana
# de los bloques CSV_PARA_CLAUDE que van a stdout (y por tanto a "| cb").
# Usar estas en scripts nuevos que se corran con pipe a cb.
# ============================================================================
console_err = Console(stderr=True)  # SIN width fijo, igual que console


def mostrar_tabla_err(df, titulo, max_filas=30):
    """Igual que mostrar_tabla(), pero a stderr -- no la captura '| cb'."""
    t = Table(title=titulo)
    for c in df.columns:
        t.add_column(c, overflow="fold")
    for _, row in df.head(max_filas).iterrows():
        t.add_row(*[str(v) for v in row])
    console_err.print(t)
    if len(df) > max_filas:
        console_err.print(f"[dim](mostrando {max_filas} de {len(df)} filas totales)[/dim]")


def resumen_err(**kpis):
    """Igual que resumen(), pero a stderr -- no la captura '| cb'."""
    linea = " | ".join(f"{k}={v}" for k, v in kpis.items())
    console_err.print(f"\n[bold]{linea}[/bold]")
