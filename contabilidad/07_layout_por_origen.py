#!/usr/bin/env python3
"""Layout de gastos/impuestos/póliza, generalizado a TODOS los orígenes de
CFDI recibidos — no solo GASTO_REGISTRO (`layout_gastos_poliza/`, el estado
del arte de columnas 57-60: Cuenta Registro, Nombre Cuenta Registro, Cargo,
Abono).

## Qué replica y qué no

El layout de 60 campos original (`Requerimiento_de_Reportes_de_Contabilidad_
auditoria_V2.docx`, ver `layout_gastos_poliza/`) tiene 6 bloques: identidad,
pago, proveedor, factura/CFDI, importes/impuestos, y póliza (columnas 53-60).
Ese proyecto solo llegó completo al bloque de póliza (57-60, 99.96%) y al de
importes base — el bloque de impuestos por tasa quedó "territorio nuevo, sin
explorar" y el de pago solo identificado, no construido.

Este reporte generaliza a TODOS los orígenes lo que YA está construido y
validado en otras partes del repo, en vez de repetir la exploración:

  - **Bloque documento**: CFDI (`raw_sat`) + `Comprobante_Digital`
    (universo_lib — ya genérico, cualquier origen).
  - **Bloque impuestos**: `impuestos_mpro()` de
    `recibidos/nivel_documento/conciliacion_xml_lib.py` — YA es genérico
    para los 6 módulos con tabla de impuestos propia (GASTO_REGISTRO,
    COMPRA, CUENTA_X_PAGAR, COMPRA_INDIRECTO, NOTA_CREDITO_PROVEEDOR,
    FACTURA), traducido a código SAT vía `Impuesto.Im_Codigo_SAT`.
  - **Bloque póliza (57-60)**: `poliza_lineas_lib.lineas_por_documento()` —
    YA es genérico (mismo query parametrizado por origen que usa
    `extract_poliza_por_origen`, con cuenta contable y centro de costo
    resueltos contra el catálogo).

Lo que NO se replica aquí (territorio que sigue sin resolver para ningún
origen, GASTO_REGISTRO incluido): el bloque de pago (banco/cheque/fecha —
ver en cambio `05_pagos_recibidos.py`, que sí lo resuelve pero a nivel CFDI,
no como columna de este layout) y 4 campos sin origen identificado
(`FACTURA_REF`, `Concepto gasto`, `Clave/Descripcion Uso bien o servicio`).

Por eso el grano de salida no es "1 fila por folio, N filas de detalle"
como el Excel original (que mezclaba dos granos en una hoja, causa de sus
propios bugs documentados — ver `layout-gastos-ctunlinux/docs/01_hallazgos_
excel_referencia.md`): aquí son DOS reportes separados por grano,
unidos por `uuid`+`documento`, que es más fácil de auditar y de pivotear
en Excel/Streamlit sin repetir el encabezado en cada línea de detalle.

Uso:
    python3 contabilidad/07_layout_por_origen.py --periodo 2026-02
    python3 contabilidad/07_layout_por_origen.py --periodo 2026-02 --origen COMPRA
    python3 contabilidad/07_layout_por_origen.py --periodo 2026-02 --csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "contabilidad"))
sys.path.insert(0, str(RAIZ / "recibidos" / "nivel_documento"))

import pandas as pd  # noqa: E402

import cuentas_lib as cl  # noqa: E402
import poliza_lineas_lib as pll  # noqa: E402
import universo_lib as ul  # noqa: E402
from helpers_output import mostrar_tabla_err, resumen_err, console_err  # noqa: E402
from conciliacion_xml_lib import impuestos_mpro  # noqa: E402

# Los 6 orígenes con tabla de impuestos propia en mpro (ver impuestos_mpro).
ORIGENES_CON_IMPUESTO = {"GASTO_REGISTRO", "COMPRA", "CUENTA_X_PAGAR",
                         "COMPRA_INDIRECTO", "NOTA_CREDITO_PROVEEDOR", "FACTURA"}


def maestro(sat: pd.DataFrame, origenes: pd.DataFrame, origen_filtro: str | None) -> pd.DataFrame:
    """Bloque documento — 1 fila por (uuid, origen, documento)."""
    o = origenes if origen_filtro is None else origenes[origenes["origen"].str.upper() == origen_filtro.upper()]
    m = o.merge(sat, on="uuid", how="inner")
    cols = ["uuid", "origen", "documento_real", "fecha", "rfc_emisor", "nombre_emisor",
            "tipo_comprobante", "subtotal", "iva", "total"]
    return m[[c for c in cols if c in m.columns]].rename(columns={"documento_real": "documento"})


def bloque_impuestos(origenes: pd.DataFrame, origen_filtro: str | None) -> pd.DataFrame:
    """Bloque impuestos — genérico vía impuestos_mpro(), 1 fila por documento."""
    o = origenes if origen_filtro is None else origenes[origenes["origen"].str.upper() == origen_filtro.upper()]
    o = o[o["origen_up"].isin(ORIGENES_CON_IMPUESTO)]
    folios_por_origen = {org: sub["documento_real"].dropna().unique().tolist()
                         for org, sub in o.groupby("origen")}
    if not folios_por_origen:
        return pd.DataFrame()
    piv, _ = impuestos_mpro(folios_por_origen=folios_por_origen)
    return piv.rename(columns={"ORIGEN": "origen", "FOLIO": "documento"})


def bloque_poliza(origenes: pd.DataFrame, origen_filtro: str | None) -> pd.DataFrame:
    """Bloque póliza (columnas 57-60) — genérico vía lineas_por_documento(),
    N filas por documento (una por línea de Poliza_Detalle)."""
    o = origenes if origen_filtro is None else origenes[origenes["origen"].str.upper() == origen_filtro.upper()]
    partes = []
    for origen, sub in o.groupby("origen"):
        docs = sub["documento_real"].dropna().unique().tolist()
        if not docs:
            continue
        ld = pll.lineas_por_documento(origen, docs)
        if not ld.empty:
            partes.append(ld)
    if not partes:
        return pd.DataFrame()
    df = pd.concat(partes, ignore_index=True)
    return cl.enriquecer(df)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--periodo", required=True)
    ap.add_argument("--origen", help="filtra a un solo origen (COMPRA, GASTO_REGISTRO, ...)")
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()

    sat, origenes = ul.universo(periodos=[args.periodo])
    console_err.print(f"[bold]Layout por origen — {args.periodo}[/bold]")
    console_err.print(f"  {len(sat)} CFDI I/E, {origenes['uuid'].nunique()} con etiqueta en mpro")

    censo = origenes["origen"].value_counts().reset_index()
    censo.columns = ["origen", "n_documentos"]
    mostrar_tabla_err(censo, "Orígenes presentes este periodo", max_filas=15)

    m = maestro(sat, origenes, args.origen)
    console_err.print(f"\n[bold]Bloque MAESTRO[/bold] — {len(m)} filas (1 por CFDI x documento)")
    mostrar_tabla_err(m.head(15), "Maestro (documento + CFDI) — muestra", max_filas=15)

    imp = bloque_impuestos(origenes, args.origen)
    if not imp.empty:
        console_err.print(f"\n[bold]Bloque IMPUESTOS[/bold] — {len(imp)} documentos con desglose fiscal")
        mostrar_tabla_err(imp.head(15), "Impuestos por documento — muestra", max_filas=15)
        por_origen_imp = imp.groupby("origen").agg(
            documentos=("documento", "nunique"),
            iva_trasladado=("MPRO_IVA_TRASLADADO", "sum"),
            ret_iva=("MPRO_RET_IVA", "sum"), ret_isr=("MPRO_RET_ISR", "sum")).reset_index()
        mostrar_tabla_err(por_origen_imp.round(2), "Impuestos — totales por origen", max_filas=10)
    else:
        console_err.print("[yellow]Sin documentos en orígenes con tabla de impuestos.[/yellow]")

    pol = bloque_poliza(origenes, args.origen)
    if not pol.empty:
        console_err.print(f"\n[bold]Bloque PÓLIZA (columnas 57-60)[/bold] — {len(pol)} líneas")
        mostrar_tabla_err(pol[["origen", "documento", "poliza", "tipo", "cuenta",
                                "cuenta_descripcion", "familia", "importe", "centro_costo"]].head(15),
                          "Póliza detalle — muestra", max_filas=15)
        por_origen_pol = (pol.groupby(["origen", "tipo"])
                          .agg(lineas=("importe", "size"), documentos=("documento", "nunique"),
                               monto=("importe", "sum")).reset_index())
        por_origen_pol["monto"] = por_origen_pol["monto"].round(2)
        mostrar_tabla_err(por_origen_pol.sort_values("monto", ascending=False),
                          "Póliza — totales por origen", max_filas=20)
    else:
        console_err.print("[yellow]Sin líneas de póliza encontradas.[/yellow]")

    # --- Cobertura del layout por origen: qué tan completo queda cada bloque ---
    cobertura = censo.copy()
    cobertura["en_maestro"] = cobertura["origen"].map(m.groupby("origen")["uuid"].nunique()).fillna(0).astype(int) \
        if not m.empty else 0
    cobertura["con_impuestos"] = cobertura["origen"].isin(ORIGENES_CON_IMPUESTO)
    cobertura["docs_con_poliza"] = cobertura["origen"].map(
        pol.groupby("origen")["documento"].nunique()) if not pol.empty else 0
    cobertura["docs_con_poliza"] = cobertura["docs_con_poliza"].fillna(0).astype(int)
    mostrar_tabla_err(cobertura, "Cobertura del layout por origen (1=universal en este reporte)",
                      max_filas=15)

    if args.csv:
        print("--- CSV_PARA_CLAUDE: layout_maestro ---")
        print(m.to_csv(index=False))
        print("--- CSV_PARA_CLAUDE: layout_impuestos ---")
        print(imp.to_csv(index=False))
        print("--- CSV_PARA_CLAUDE: layout_poliza ---")
        print(pol.to_csv(index=False))


if __name__ == "__main__":
    main()
