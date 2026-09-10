"""
Notebook-hito: marca el cierre de la reconciliacion Gasto_Registro_Control
(Grc_Importe) vs Poliza_Detalle a nivel CECO (99.95%-100%, ver
07_reconciliacion_completa_ceco.py y PROGRESS.md). Muestra, celda por
celda, cada pieza SQL que se necesita y por que -- para poder retomar el
razonamiento sin releer toda la conversacion que lo construyo.

No repite los intentos descartados (colapsar por Grd_ID en vez de
Tg_Cve_Tipo_Gasto, ver 04/05) -- esos quedan documentados en PROGRESS.md,
aqui solo va el camino que SI llego a la solucion.

Uso:
    python3 08_notebook_hito_ceco.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
"""
import argparse
import sys

sys.path.insert(0, "/home/esteban/trivasa/connections")
from connection_205_trivasadb3 import engine  # default de exploracion

import pandas as pd
from sqlalchemy import text
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

console = Console()


def celda(numero, titulo, explicacion, sql, params=None, mostrar_filas=8):
    console.rule(f"[bold cyan]Celda {numero} — {titulo}[/bold cyan]")
    console.print(Panel(explicacion.strip(), border_style="dim"))
    console.print(Syntax(sql.strip(), "sql", theme="monokai", line_numbers=False, word_wrap=True))
    df = pd.read_sql(text(sql), engine, params=params or {})
    if "FOLIO" in df.columns:
        df["FOLIO"] = df["FOLIO"].str.strip()
    console.print(f"\n[bold]# Output: {len(df)} filas[/bold]")
    t = Table()
    for c in df.columns:
        t.add_column(c, overflow="fold")
    for _, r in df.head(mostrar_filas).iterrows():
        t.add_row(*[f"{v:,.4f}" if isinstance(v, float) else str(v) for v in r])
    console.print(t)
    console.print()
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin
    p = {"fecha_ini": fi, "fecha_fin": ff}

    console.print(Panel(
        f"[bold]HITO — Reconciliacion Grc_Importe vs Poliza_Detalle a nivel CECO[/bold]\n"
        f"Periodo: {fi} a {ff}  |  Empresa 0001  |  Conexion .205/TRIVASADB3\n\n"
        "Pregunta que responde: ¿el reparto por centro de costo que trae "
        "Gasto_Registro_Control (lado operativo) coincide con lo que "
        "realmente quedo contabilizado en Poliza_Detalle? -- diagnostico "
        "de calidad de dato, no la fuente del layout final (esa ya cuadra "
        "100% via Poliza_Detalle sola, ver ref/reconciliacion_cargo_abono_ceco.py).",
        border_style="green"
    ))

    # ========================================================================
    # Celda 1 — universo base
    # ========================================================================
    universo = celda(1, "Universo base (folio, origen, importe)", """
    El punto de partida. Un folio, su origen (Gr_Tabla), y su IMPORTE real
    (subtotal SIN IVA -- Poliza_Detalle nunca incluye impuestos). Convertido
    a MXN via Grd_Tipo_Cambio. Excluye GASTO_REGISTRO_NOMINA/CONSUMO_INTERNO
    -- ambos tienen su propia estructura de poliza, fuera de alcance aqui.
    """, """
    SELECT
        gr.Gr_Folio AS FOLIO,
        gr.Gr_Tabla AS ORIGEN,
        SUM(grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio) AS IMPORTE
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
    WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = '0001'
      AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
    GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, gr.Gr_Tabla
    """, params=p)
    folios_reversion = set(universo[universo.IMPORTE <= -1.0].FOLIO)

    # ========================================================================
    # Celda 2 — Grc_Importe colapsado por (Tipo_Gasto, Centro)
    # ========================================================================
    grc = celda(2, "Gasto_Registro_Control, colapsado por (Tg_Cve_Tipo_Gasto, Centro)", """
    LA LLAVE GANADORA. Se probo primero colapsar por (Grd_ID, Centro) --
    dio solo 93.35%, porque el sistema NO postea un renglon de poliza por
    documento: postea uno por (tipo de gasto, centro de costo), sumando
    TODOS los documentos que compartan ambos. Caso real que lo confirmo:
    folio 01-0034885 (TELEFONIA, 7 recibos/documentos) -- colapsado por
    documento da 53 filas, colapsado por tipo de gasto da 27, EXACTO el
    numero de lineas reales de la poliza, cuadrando al centavo cada una.
    """, """
    SELECT
        gr.Gr_Folio AS FOLIO,
        gr.Gr_Tabla AS ORIGEN,
        grd.Tg_Cve_Tipo_Gasto,
        grc.Cc_Cve_Centro_Costo AS CENTRO,
        SUM(grc.Grc_Importe) AS IMPORTE_GRC
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
    JOIN Gasto_Registro_Control grc ON grc.Gr_Folio = grd.Gr_Folio AND grc.Grd_ID = grd.Grd_ID
    WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = '0001'
      AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
    GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, gr.Gr_Tabla, grd.Tg_Cve_Tipo_Gasto, grc.Cc_Cve_Centro_Costo
    """, params=p)

    # ========================================================================
    # Celda 3 — Poliza real por (Cuenta, Centro)
    # ========================================================================
    with open("queries/v03_detalle_cuenta_centro_costo.sql") as f:
        sql_poliza = f.read().replace(":fecha_ini", f"'{fi}'").replace(":fecha_fin", f"'{ff}'")
    poliza = celda(3, "Poliza_Detalle real, por (Cuenta, Centro)", """
    La fuente de verdad -- Cc_Cve_Cuenta_Contable y Pd_Centro_Costo son
    campos REALES de Poliza_Detalle, grabados por el contador. Es la misma
    query que se sirve en FlexMonster (ver ref/reconciliacion_cargo_abono_ceco.py,
    100% de reconciliacion a nivel folio). Aqui se colapsa por (Cuenta,
    Centro) para compararla contra la celda 2.
    """, sql_poliza)
    poliza_ceco = poliza.groupby(["FOLIO", "CUENTA", "CENTRO_COSTO"], as_index=False).agg(
        CARGO=("CARGO", "sum"), ABONO=("ABONO", "sum")
    ).rename(columns={"CENTRO_COSTO": "CENTRO"})

    # ========================================================================
    # Celda 4 — regla de reversion
    # ========================================================================
    console.rule("[bold cyan]Celda 4 — Regla de reversion (Python, no SQL)[/bold cyan]")
    console.print(Panel(f"""
    Folios con IMPORTE (celda 1) <= -$1: el Cargo cae en una cuenta de
    Provision/Pasivo, no es el gasto real -- el numero que sirve esta en
    el ABONO. Regla rescatada de layout-gastos-pasos/docs/queries/gastos/
    v02_reversion.sql (proyecto historico, resuelta ahi solo a nivel
    folio -- aqui se aplica a nivel CECO). Confirmado con folio real
    0005-0177386: IMPORTE=-92,046.66, Grc_Importe=-92,046.66 en centro
    000291, y la poliza tiene ese mismo monto en Pd_Tipo=2 (Abono) del
    centro 000291, NO en Cargo.

    Folios de reversion en este periodo: {len(folios_reversion)}
    {sorted(folios_reversion) if folios_reversion else '(ninguno en este rango)'}
    """.strip(), border_style="dim"))

    # ========================================================================
    # Celda 5 — regla de signo para GASTO_RECLASIFICACION
    # ========================================================================
    console.rule("[bold cyan]Celda 5 — Regla de signo por linea (GASTO_RECLASIFICACION)[/bold cyan]")
    console.print(Panel("""
    GASTO_RECLASIFICACION es un par espejo Cargo=Abono dentro de la misma
    poliza (v02_reclasificacion.sql confirma esto a nivel folio, pero ese
    proyecto nunca lo bajo a CECO -- su propio README dice "sin dividir su
    detalle todavia"). Hallazgo nuevo de esta exploracion: el SIGNO de
    Grc_Importe POR LINEA (no si el folio completo es negativo) dice si
    esa linea es Cargo (positivo) o Abono (negativo). Confirmado con folio
    real 01-0037389: centro 000028 (positivo) = Cargo: TELEFONIA CELULAR
    403.97, DEPREC. EDIFICIO 1.60, ... ; centro 000497 (negativo, el
    espejo) = Abono: mismos conceptos, mismos montos, signo invertido.
    """.strip(), border_style="dim"))

    # ========================================================================
    # Celda 6 — resultado consolidado
    # ========================================================================
    console.rule("[bold cyan]Celda 6 — Resultado consolidado (aplicando celdas 4 y 5)[/bold cyan]")

    es_reclasificacion = grc.ORIGEN == "GASTO_RECLASIFICACION"
    es_reversion = grc.FOLIO.isin(folios_reversion) & ~es_reclasificacion

    recla = grc[es_reclasificacion].copy()
    recla["VALOR_CMP"] = recla["IMPORTE_GRC"].abs()
    recla["TIPO_ESPERADO"] = recla["IMPORTE_GRC"].apply(lambda x: "CARGO" if x > 0 else "ABONO")
    pdc_recla = poliza_ceco[poliza_ceco.FOLIO.isin(recla.FOLIO.unique())]
    pdc_cargo = pdc_recla[pdc_recla.CARGO != 0][["FOLIO", "CENTRO", "CARGO"]].rename(columns={"CARGO": "IMPORTE_PD"})
    pdc_cargo["TIPO_ESPERADO"] = "CARGO"
    pdc_abono = pdc_recla[pdc_recla.ABONO != 0][["FOLIO", "CENTRO", "ABONO"]].rename(columns={"ABONO": "IMPORTE_PD"})
    pdc_abono["TIPO_ESPERADO"] = "ABONO"
    pdc_split = pd.concat([pdc_cargo, pdc_abono])
    r_r = recla.sort_values(["FOLIO", "CENTRO", "TIPO_ESPERADO", "VALOR_CMP"]).reset_index(drop=True)
    p_r = pdc_split.sort_values(["FOLIO", "CENTRO", "TIPO_ESPERADO", "IMPORTE_PD"]).reset_index(drop=True)
    r_r["rank"] = r_r.groupby(["FOLIO", "CENTRO", "TIPO_ESPERADO"]).cumcount()
    p_r["rank"] = p_r.groupby(["FOLIO", "CENTRO", "TIPO_ESPERADO"]).cumcount()
    comp_recla = r_r.merge(p_r, on=["FOLIO", "CENTRO", "TIPO_ESPERADO", "rank"], how="outer")
    comp_recla["VALOR_CMP"] = comp_recla["VALOR_CMP"].fillna(0)
    comp_recla["IMPORTE_PD"] = comp_recla["IMPORTE_PD"].fillna(0)
    comp_recla["ORIGEN"] = "GASTO_RECLASIFICACION"

    resto = grc[~es_reclasificacion].copy()
    poliza["VALOR"] = poliza["CARGO"]
    m = poliza.FOLIO.isin(folios_reversion) & ~poliza.FOLIO.isin(recla.FOLIO.unique())
    poliza.loc[m, "VALOR"] = poliza.loc[m, "ABONO"]
    pdc_resto = poliza.groupby(["FOLIO", "CUENTA", "CENTRO_COSTO"], as_index=False).agg(IMPORTE_PD=("VALOR", "sum"))
    pdc_resto = pdc_resto.rename(columns={"CENTRO_COSTO": "CENTRO"})
    pdc_resto = pdc_resto[(pdc_resto.IMPORTE_PD != 0) & (~pdc_resto.FOLIO.isin(recla.FOLIO.unique()))]
    resto["VALOR_CMP"] = resto["IMPORTE_GRC"]
    resto.loc[resto.FOLIO.isin(folios_reversion), "VALOR_CMP"] = resto.loc[resto.FOLIO.isin(folios_reversion), "IMPORTE_GRC"].abs()
    g_r = resto.sort_values(["FOLIO", "CENTRO", "VALOR_CMP"]).reset_index(drop=True)
    p_r2 = pdc_resto.sort_values(["FOLIO", "CENTRO", "IMPORTE_PD"]).reset_index(drop=True)
    g_r["rank"] = g_r.groupby(["FOLIO", "CENTRO"]).cumcount()
    p_r2["rank"] = p_r2.groupby(["FOLIO", "CENTRO"]).cumcount()
    comp_resto = g_r.merge(p_r2, on=["FOLIO", "CENTRO", "rank"], how="outer")
    comp_resto["VALOR_CMP"] = comp_resto["VALOR_CMP"].fillna(0)
    comp_resto["IMPORTE_PD"] = comp_resto["IMPORTE_PD"].fillna(0)
    origen_map = grc[["FOLIO", "ORIGEN"]].drop_duplicates().set_index("FOLIO")["ORIGEN"]
    comp_resto["ORIGEN"] = comp_resto["FOLIO"].map(origen_map).fillna("")

    cols = ["FOLIO", "ORIGEN", "CENTRO", "VALOR_CMP", "IMPORTE_PD"]
    comp = pd.concat([comp_recla[cols], comp_resto[cols]], ignore_index=True)
    comp["DIFERENCIA"] = (comp.VALOR_CMP - comp.IMPORTE_PD).abs()
    comp["CUADRA"] = comp.DIFERENCIA < 1

    n, c = len(comp), int(comp.CUADRA.sum())
    por_origen = comp.groupby(comp.ORIGEN.replace("", "GASTO_DIRECTO")).agg(
        filas=("FOLIO", "count"), cuadran=("CUADRA", "sum")
    )
    por_origen["pct"] = (por_origen.cuadran / por_origen.filas * 100).round(2)

    t = Table(title=f"HITO -- {fi} a {ff}  |  Total: {c}/{n} ({100*c/n:.2f}%)")
    t.add_column("ORIGEN"); t.add_column("filas", justify="right")
    t.add_column("cuadran", justify="right"); t.add_column("%", justify="right")
    for origen, row in por_origen.iterrows():
        t.add_row(str(origen), str(int(row.filas)), str(int(row.cuadran)), f"{row.pct}%")
    console.print(t)

    console.print(Panel(
        "[bold green]HITO CERRADO[/bold green] -- 5 origenes normales reconciliados a nivel CECO.\n"
        "Siguiente pendiente: CONSUMO_INTERNO (fuera de este universo, estructura de doble poliza aparte).\n"
        "Detalle completo del residual y la nota de arquitectura en PROGRESS.md.",
        border_style="green"
    ))


if __name__ == "__main__":
    main()
