"""Conciliacion inversa: mpro -> SAT.

El reporte que ya existe (localhost:8509/recibido_conciliacion) parte de
`raw_sat.cfdi_recibidos` tipo I/E y busca su documento en mpro. Este hace el
ejercicio contrario: parte del layout unificado de mpro (ver layouts_lib) y
pregunta cuanto de eso tiene un CFDI Recibido I/E detras.

Esta es la version SIN FILTRAR de origenes: entra todo lo que producen los
cinco layouts, incluidos los origenes que por definicion no llevan CFDI
(consumo interno, reclasificacion de gasto, nomina). El porcentaje global va a
salir bajo a proposito — sirve de linea base para decidir, viendo los numeros,
que origenes sacar.

El cruce contra el SAT se hace contra TODO `cfdi_recibidos`, no solo el
periodo: un documento de mpro puede colgar de un CFDI timbrado el mes anterior
y ese cruce es valido.

    python3 unificacion/01_conciliacion_inversa.py --fecha-ini 20260201 --fecha-fin 20260228
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parent / "src"))
sys.path.insert(0, str(AQUI.parent / "layout_gastos_poliza"))

from bridge_client import run_query  # noqa: E402
from helpers_output import console_err, mostrar_tabla_err, resumen_err  # noqa: E402
from layouts_lib import cargar_documentos, contar_sin_layout  # noqa: E402

# Estados del documento de mpro frente al SAT.
CONCILIADO = "CONCILIADO"                # UUID existe en raw_sat como I/E
UUID_FUERA_IE = "UUID_NO_ES_I_NI_E"      # UUID existe en el SAT pero es P/N/T
UUID_NO_EN_SAT = "UUID_NO_EN_SAT"        # mpro tiene UUID que el SAT no conoce
SIN_UUID = "SIN_UUID_EN_MPRO"            # documento sin comprobante digital

# Sub-origenes que por definicion no generan un CFDI Recibido I/E. Salen del
# universo con --filtrar; medidos en la corrida sin filtrar de feb-2026, los
# tres dan 0.0% de conciliacion sobre 5,230 documentos, que es la evidencia de
# que no pertenecen al universo y no un hueco por resolver:
#   GASTO_REGISTRO_NOMINA  — la nomina timbra CFDI tipo N, no I/E
#   CONSUMO_INTERNO        — movimiento interno, no hay proveedor que facture
#   GASTO_RECLASIFICACION  — reasienta gasto ya registrado, importe neto cero
SIN_CFDI_POR_DEFINICION = {
    ("GASTO_REGISTRO", "GASTO_REGISTRO_NOMINA"),
    ("GASTO_REGISTRO", "CONSUMO_INTERNO"),
    ("GASTO_REGISTRO", "GASTO_RECLASIFICACION"),
}


def cargar_sat() -> pd.DataFrame:
    sql = """
SELECT upper(trim(uuid)) AS uuid, tipo_comprobante, periodo, total AS total_sat,
       subtotal AS subtotal_sat, rfc_emisor
FROM raw_sat.cfdi_recibidos
"""
    res = run_query("postgres_dw", sql)
    sat = pd.DataFrame(res["rows"], columns=res["columns"])
    sat["total_sat"] = pd.to_numeric(sat["total_sat"], errors="coerce").fillna(0.0)
    sat["subtotal_sat"] = pd.to_numeric(sat["subtotal_sat"], errors="coerce").fillna(0.0)
    return sat.drop_duplicates(subset="uuid")


def clasificar(mpro: pd.DataFrame, sat: pd.DataFrame) -> pd.DataFrame:
    df = mpro.merge(sat, on="uuid", how="left", suffixes=("", "_sat"))
    tiene_uuid = df["uuid"] != ""
    en_sat = df["tipo_comprobante"].notna()
    es_ie = df["tipo_comprobante"].isin(["I", "E"])

    df["estado"] = SIN_UUID
    df.loc[tiene_uuid & ~en_sat, "estado"] = UUID_NO_EN_SAT
    df.loc[tiene_uuid & en_sat & ~es_ie, "estado"] = UUID_FUERA_IE
    df.loc[tiene_uuid & en_sat & es_ie, "estado"] = CONCILIADO
    return df


def cobertura_sat(conc: pd.DataFrame, periodos: list[str]) -> pd.DataFrame:
    """Cuanto del universo SAT del periodo alcanza a explicar este cruce.

    Es el puente con el reporte SAT -> mpro (localhost:8509): alli el universo
    es el CFDI y aqui el documento de mpro, asi que los porcentajes no son
    comparables, pero el importe alcanzado si deberia parecerse.
    """
    lista = ", ".join(f"'{p}'" for p in periodos)
    sql = f"""
SELECT periodo, tipo_comprobante, COUNT(*) AS cfdi, SUM(total) AS total_sat
FROM raw_sat.cfdi_recibidos
WHERE tipo_comprobante IN ('I','E') AND periodo IN ({lista})
GROUP BY periodo, tipo_comprobante
"""
    res = run_query("postgres_dw", sql)
    universo = pd.DataFrame(res["rows"], columns=res["columns"])
    universo["total_sat"] = pd.to_numeric(universo["total_sat"], errors="coerce").fillna(0.0)

    alcanzado = (conc.drop_duplicates("uuid")
                 .groupby(["periodo", "tipo_comprobante"])
                 .agg(cfdi_alcanzados=("uuid", "size"), total_alcanzado=("total_sat", "sum"))
                 .reset_index())
    out = universo.merge(alcanzado, on=["periodo", "tipo_comprobante"], how="left").fillna(0)
    out["pct_cfdi"] = (out["cfdi_alcanzados"] / out["cfdi"] * 100).round(1)
    out["pct_importe"] = (out["total_alcanzado"] / out["total_sat"] * 100).round(1)
    return out


def tabla_por(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    """Documentos e importe mpro por corte, con su % conciliado."""
    g = df.groupby(columnas, dropna=False)
    out = g.agg(
        docs=("folio", "size"),
        importe_mpro=("total", "sum"),
        docs_conc=("estado", lambda s: (s == CONCILIADO).sum()),
    ).reset_index()
    conc = df[df["estado"] == CONCILIADO].groupby(columnas, dropna=False)["total"].sum()
    out = out.merge(conc.rename("importe_conc").reset_index(), on=columnas, how="left")
    out["importe_conc"] = out["importe_conc"].fillna(0.0)
    out["pct_docs"] = (out["docs_conc"] / out["docs"] * 100).round(1)
    out["pct_importe"] = (out["importe_conc"] / out["importe_mpro"].replace(0, float("nan")) * 100).round(1)
    return out.sort_values("importe_mpro", ascending=False)


def formatear(df: pd.DataFrame, cols_money: tuple[str, ...]) -> pd.DataFrame:
    out = df.copy()
    for c in cols_money:
        out[c] = out[c].map(lambda v: f"{v:,.0f}")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fecha-ini", required=True, help="YYYYMMDD")
    p.add_argument("--fecha-fin", required=True, help="YYYYMMDD")
    p.add_argument("--empresa", default="0001")
    p.add_argument("--filtrar", action="store_true",
                   help="excluye los sub-origenes que no generan CFDI I/E")
    p.add_argument("--csv", help="ruta para volcar el detalle documento a documento")
    args = p.parse_args()

    modo = "filtrado" if args.filtrar else "sin filtrar origenes"
    console_err.print(f"[bold]Conciliacion inversa mpro -> SAT[/bold]  "
                      f"{args.fecha_ini} a {args.fecha_fin}  ({modo})")

    mpro = cargar_documentos(args.fecha_ini, args.fecha_fin, args.empresa)
    sat = cargar_sat()
    df = clasificar(mpro, sat)

    if args.filtrar:
        excluido = df.set_index(["origen", "sub_origen"]).index.isin(SIN_CFDI_POR_DEFINICION)
        fuera = df[excluido]
        df = df[~excluido].copy()
        console_err.print(
            f"[dim]excluidos {len(fuera):,} documentos "
            f"({fuera['total'].sum():,.0f}) por no generar CFDI I/E[/dim]")

    total_docs = len(df)
    conc = df[df["estado"] == CONCILIADO]
    importe_total = df["total"].sum()
    importe_conc = conc["total"].sum()

    resumen_err(
        documentos=f"{total_docs:,}",
        conciliados=f"{len(conc):,} ({len(conc)/total_docs*100:.1f}%)",
        importe_mpro=f"{importe_total:,.0f}",
        importe_conciliado=f"{importe_conc:,.0f} ({importe_conc/importe_total*100:.1f}%)",
        uuids_unicos=f"{conc['uuid'].nunique():,}",
        importe_sat=f"{conc.drop_duplicates('uuid')['total_sat'].sum():,.0f}",
    )

    estados = df.groupby("estado").agg(docs=("folio", "size"), importe=("total", "sum")).reset_index()
    estados["pct_docs"] = (estados["docs"] / total_docs * 100).round(1)
    mostrar_tabla_err(formatear(estados, ("importe",)), "Estado de los documentos de mpro")

    por_origen = tabla_por(df, ["origen"])
    mostrar_tabla_err(
        formatear(por_origen, ("importe_mpro", "importe_conc")),
        "Conciliacion por origen",
    )

    por_sub = tabla_por(df, ["origen", "sub_origen"])
    mostrar_tabla_err(
        formatear(por_sub, ("importe_mpro", "importe_conc")),
        "Conciliacion por sub-origen — aqui se ve que vale la pena filtrar",
        max_filas=40,
    )

    periodos = [d.strftime("%Y-%m") for d in
                pd.period_range(args.fecha_ini, args.fecha_fin, freq="M").to_timestamp()]
    mostrar_tabla_err(
        formatear(cobertura_sat(conc, periodos), ("total_sat", "total_alcanzado")),
        "Cuanto del universo SAT del periodo alcanza este cruce",
    )

    hueco = contar_sin_layout(args.fecha_ini, args.fecha_fin)
    if not hueco.empty:
        mostrar_tabla_err(hueco, "Sin layout todavia (no entran al universo de arriba)")

    if args.csv:
        df.to_csv(args.csv, index=False)
        console_err.print(f"[dim]detalle -> {args.csv}[/dim]")

    print("CSV_PARA_CLAUDE_por_sub_origen")
    print(por_sub.to_csv(index=False))


if __name__ == "__main__":
    main()
