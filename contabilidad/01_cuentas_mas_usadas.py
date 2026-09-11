#!/usr/bin/env python3
"""¿Qué cuentas contables usa la conciliación de CFDI recibidos?

Toma el universo de CFDI recibidos de un periodo (el mismo de
`baseline_universal.py`), los liga a sus documentos de mpro y rankea las
cuentas contables que tocan, en los DOS granos que importan:

  A) GRANO DOCUMENTO — solo las líneas atribuibles al CFDI
     (`Pd_Referencia` = folio del documento). Responde: *¿en qué cuenta
     aterriza el gasto/inventario de estos CFDI?* Es lo que suma
     `baseline_universal`, así que los totales son comparables con él.

  B) GRANO PÓLIZA — todas las líneas de las pólizas tocadas. Responde:
     *¿qué más se mueve alrededor?* Aquí aparecen el IVA acreditable, las
     retenciones y el abono a proveedores, que el grano A **no ve** porque
     esas líneas no llevan la referencia del documento (ver el punto 1 de
     `docs/hallazgos_cuentas.md`). Como la póliza consolida el día, estos
     importes NO son atribuibles a un CFDI individual.

Uso:
    python3 contabilidad/01_cuentas_mas_usadas.py --periodo 2026-02
    python3 contabilidad/01_cuentas_mas_usadas.py --periodos 2026-01 2026-02 ... --csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "contabilidad"))

import pandas as pd  # noqa: E402

import cuentas_lib as cl  # noqa: E402
import poliza_lineas_lib as pll  # noqa: E402
import universo_lib as ul  # noqa: E402
from helpers_output import mostrar_tabla_err, resumen_err, console_err  # noqa: E402


def recolectar(periodos: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    console_err.print(f"[bold]Universo CFDI recibidos:[/bold] {', '.join(periodos)}")
    sat, origenes = ul.universo(periodos=periodos)
    console_err.print(f"  {len(sat)} CFDI tipo I/E · "
                      f"{origenes['uuid'].nunique()} con etiqueta en mpro · "
                      f"{len(origenes)} etiquetas documento")

    lineas_doc, polizas = [], []
    for origen in ul.origenes_con_cargo(origenes):
        sub = origenes[origenes["origen"] == origen]
        # GASTO_REGISTRO liga por folio de 10; el Grd_ID solo distingue
        # renglones dentro del folio, y Poliza_Detalle no lo guarda.
        docs = sub["documento_real"].dropna().unique().tolist()
        if not docs:
            continue
        ld = pll.lineas_por_documento(origen, docs)
        pol = pll.polizas_de_documentos(origen, docs)
        if not ld.empty:
            # Re-liga cada línea a los CFDI de su documento (un documento
            # puede amparar más de un CFDI).
            mapa = sub[["uuid", "documento_real"]].rename(columns={"documento_real": "documento"})
            lineas_doc.append(ld.merge(mapa, on="documento", how="inner"))
        if not pol.empty:
            polizas.append(pol)
        console_err.print(f"  {origen}: {len(docs)} docs -> {len(ld)} líneas, "
                          f"{pol['poliza'].nunique() if not pol.empty else 0} pólizas")

    doc_df = pd.concat(lineas_doc, ignore_index=True) if lineas_doc else pd.DataFrame()
    pol_map = pd.concat(polizas, ignore_index=True) if polizas else pd.DataFrame()

    pol_df = pd.DataFrame()
    if not pol_map.empty:
        folios = pol_map["poliza"].dropna().unique().tolist()
        console_err.print(f"  grano póliza: {len(folios)} pólizas distintas…")
        pol_df = pll.lineas_de_polizas(folios)

    meta = {
        "n_cfdi": len(sat),
        "n_cfdi_en_mpro": origenes["uuid"].nunique(),
        "n_polizas": pol_map["poliza"].nunique() if not pol_map.empty else 0,
    }
    return doc_df, pol_df, meta


def rankear(df: pd.DataFrame, por_cfdi: bool) -> pd.DataFrame:
    """Una fila por (cuenta, tipo) con volumen y monto."""
    if df.empty:
        return pd.DataFrame()
    agg = {"lineas": ("importe", "size"), "monto": ("importe", "sum"),
           "documentos": ("documento", "nunique"), "polizas": ("poliza", "nunique")}
    if por_cfdi:
        agg["cfdi"] = ("uuid", "nunique")
    out = df.groupby(["cuenta", "cuenta_descripcion", "tipo"]).agg(**agg).reset_index()
    out = cl.enriquecer(out)
    out = out.sort_values("monto", ascending=False).reset_index(drop=True)
    total = out["monto"].sum()
    out["pct_monto"] = (out["monto"] / total * 100).round(2) if total else 0.0
    out["monto"] = out["monto"].round(2)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--periodo", help="un periodo YYYY-MM")
    ap.add_argument("--periodos", nargs="+", help="varios periodos YYYY-MM")
    ap.add_argument("--top", type=int, default=25, help="filas por tabla (default 25)")
    ap.add_argument("--csv", action="store_true", help="volcar CSV a stdout")
    args = ap.parse_args()

    periodos = args.periodos or ([args.periodo] if args.periodo else None)
    if not periodos:
        ap.error("hay que pasar --periodo o --periodos")

    doc_df, pol_df, meta = recolectar(periodos)
    if doc_df.empty:
        console_err.print("[red]Sin líneas de póliza para ese universo.[/red]")
        return

    rank_doc = rankear(doc_df, por_cfdi=True)
    rank_pol = rankear(pol_df, por_cfdi=False)

    resumen_err(periodos=",".join(periodos), cfdi=meta["n_cfdi"],
                cfdi_en_mpro=meta["n_cfdi_en_mpro"], polizas=meta["n_polizas"],
                lineas_grano_documento=len(doc_df), lineas_grano_poliza=len(pol_df))

    mostrar_tabla_err(
        rank_doc[["cuenta", "cuenta_descripcion", "familia", "tipo", "lineas",
                  "cfdi", "monto", "pct_monto"]],
        "A) GRANO DOCUMENTO — cuentas donde aterriza el importe atribuible a cada CFDI",
        max_filas=args.top)

    fam_doc = (doc_df.assign(familia=doc_df["cuenta"].map(cl.familia))
               .groupby(["familia", "tipo"])
               .agg(lineas=("importe", "size"), cfdi=("uuid", "nunique"),
                    monto=("importe", "sum")).reset_index()
               .sort_values("monto", ascending=False))
    fam_doc["monto"] = fam_doc["monto"].round(2)
    mostrar_tabla_err(fam_doc, "A.1) Grano documento, agrupado por familia de cuenta", max_filas=20)

    if not rank_pol.empty:
        mostrar_tabla_err(
            rank_pol[["cuenta", "cuenta_descripcion", "familia", "tipo", "lineas",
                      "polizas", "monto", "pct_monto"]],
            "B) GRANO PÓLIZA — todo lo que se mueve en las pólizas tocadas "
            "(incluye IVA, retenciones y proveedores; NO atribuible por CFDI)",
            max_filas=args.top)

        fam_pol = (pol_df.assign(familia=pol_df["cuenta"].map(cl.familia))
                   .groupby(["familia", "tipo"])
                   .agg(lineas=("importe", "size"), monto=("importe", "sum")).reset_index()
                   .sort_values("monto", ascending=False))
        fam_pol["monto"] = fam_pol["monto"].round(2)
        mostrar_tabla_err(fam_pol, "B.1) Grano póliza, agrupado por familia de cuenta", max_filas=25)

        # Cuadre de la partida doble a nivel del conjunto de pólizas: si el
        # motor de mpro no genera pólizas descuadradas, cargo == abono.
        cargo = pol_df.loc[pol_df["tipo"] == "Cargo", "importe"].sum()
        abono = pol_df.loc[pol_df["tipo"] == "Abono", "importe"].sum()
        resumen_err(cargo_polizas=f"${cargo:,.2f}", abono_polizas=f"${abono:,.2f}",
                    diferencia=f"${cargo - abono:,.2f}")

    por_origen = (doc_df.groupby(["origen", "tipo"])
                  .agg(lineas=("importe", "size"), cfdi=("uuid", "nunique"),
                       cuentas=("cuenta", "nunique"), monto=("importe", "sum")).reset_index()
                  .sort_values("monto", ascending=False))
    por_origen["monto"] = por_origen["monto"].round(2)
    mostrar_tabla_err(por_origen, "A.2) Grano documento, por origen de mpro", max_filas=25)

    if args.csv:
        print("--- CSV_PARA_CLAUDE: cuentas_grano_documento ---")
        print(rank_doc.to_csv(index=False))
        print("--- CSV_PARA_CLAUDE: cuentas_grano_poliza ---")
        print(rank_pol.to_csv(index=False))
        print("--- CSV_PARA_CLAUDE: familias_grano_documento ---")
        print(fam_doc.to_csv(index=False))


if __name__ == "__main__":
    main()
