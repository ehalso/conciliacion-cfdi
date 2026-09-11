#!/usr/bin/env python3
"""Conciliación del PAGO de CFDI recibidos — la cadena documento -> provisión
-> pago, y qué % del universo se explica.

Toda la conciliación existente en este repo (baseline_universal.py y todo
`recibidos/`) es de un SOLO LADO: valida el CARGO (reconocimiento de
gasto/inventario) contra la base fiscal. Nadie había armado el lado del
ABONO/pago para el universo completo — solo existe un intento parcial
(`baseline_conciliacion.py`, solo COMPRA, 81.8%, aislando el abono por
Serie+Folio del CFDI dentro de la misma póliza).

## La cadena real (confirmada en vivo 2026-09-11)

    UUID del CFDI
      -> Pago_Cxp_Comprobante.Pcc_Timbre_UUID   (liga fina: qué pago cubre
         este CFDI, por Pcc_Monto)
      -> (Cxp_Folio, Pc_ID) -> Pago_CXP          (el INSTRUMENTO: Pc_Tabla/
         Pc_Documento = 'Cheque'+folio, 'ANTICIPO_CXP'+folio,
         'NOTA_CREDITO_PROVEEDOR'+folio — y el monto de ESA aplicación,
         Pc_Importe, que puede cubrir más de un UUID)
      -> Cxp_Folio -> Cuenta_X_Pagar             (la obligación: importe
         total provisionado, pagado y saldo — `Cxp_Precio_Neto_Importe`/
         `_Pago`/`_Saldo`)

Es la MISMA arquitectura que el lado del cargo: un documento (aquí, un
`Cxp_Folio`) puede tener varias aplicaciones de pago (varios `Pc_ID`), y un
mismo pago puede cubrir varios CFDI (varios `Pcc_Id` bajo el mismo
`Cxp_Folio`+`Pc_ID`).

## Gotcha de datos encontrado en vivo

`Cuenta_X_Pagar.Cxp_Tabla` NO es una columna categórica limpia: para la
mayoría de las filas de GASTO_REGISTRO trae literalmente el texto
`"Gasto_Registro:<folio>"` (un valor DISTINTO por cada folio, cientos de
ellos), mientras que otros orígenes sí traen un valor limpio (`Compra`,
`Cuenta_X_Pagar`, `Recibo_Pago`, `Anticipo_Cxp`, `Compra_Indirecto`,
`GASTO_REGISTRO_NOMINA`). No filtrar por `Cxp_Tabla = 'GASTO_REGISTRO'`
(deja fuera casi todo) — filtrar por `LIKE 'Gasto_Registro%'` o, mejor,
ignorar `Cxp_Tabla` y llegar a `Cuenta_X_Pagar` siempre por `Cxp_Folio`.

## Cascada de vías (mismo patrón que baseline_universal.py)

  1. `pago_directo_comprobante` — el UUID aparece en `Pago_Cxp_Comprobante`.
     Fuerte: es un link explícito CFDI->pago hecho por mpro mismo.
  2. `pago_directo_cheque` — el CFDI está etiquetado con origen CHEQUE en
     `Comprobante_Digital` y el abono de esa póliza iguala el total del CFDI
     (mismo mecanismo que la vía 5 de `baseline_universal.py`).
  3. Sin vía encontrada -> `SIN_PAGO_ENCONTRADO` (no implica que no se haya
     pagado: puede que el link viva en una tabla que este reporte no cubre).

`Cuenta_X_Pagar.Cxp_Precio_Neto_Saldo` da el estatus real de saldo
(PAGADO_TOTAL si saldo ~0, PARCIAL si 0<saldo<importe).

Uso:
    python3 contabilidad/05_pagos_recibidos.py --periodo 2026-02
    python3 contabilidad/05_pagos_recibidos.py --periodo 2026-02 --uuid <UUID>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "contabilidad"))

import pandas as pd  # noqa: E402

from bridge_client import run_query, rows_as_dicts, sql_quote  # noqa: E402
from config import MPRO_TARGET  # noqa: E402
import universo_lib as ul  # noqa: E402
from helpers_output import mostrar_tabla_err, resumen_err, console_err  # noqa: E402

TOL = 1.00
BATCH = 300


def pago_comprobante_por_uuid(uuids: list[str]) -> pd.DataFrame:
    """Vía 1: UUID -> (Cxp_Folio, Pc_ID) -> Pc_Importe/Pc_Tabla -> saldo de
    Cuenta_X_Pagar. Una fila por UUID+Cxp_Folio+Pc_ID (puede haber varias
    aplicaciones para el mismo CFDI)."""
    uuids = sorted({u.upper() for u in uuids if u})
    out = []
    for i in range(0, len(uuids), BATCH):
        chunk = uuids[i:i + BATCH]
        in_list = ", ".join(sql_quote(u) for u in chunk)
        sql = (
            "SELECT DISTINCT pcc.Pcc_Timbre_UUID AS uuid, pcc.Cxp_Folio AS cxp_folio, "
            "pcc.Pc_ID AS pc_id, pcc.Pcc_Monto AS pcc_monto "
            f"FROM Pago_Cxp_Comprobante pcc WHERE pcc.Pcc_Timbre_UUID IN ({in_list})"
        )
        out.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    df = pd.DataFrame(out, columns=["uuid", "cxp_folio", "pc_id", "pcc_monto"])
    if df.empty:
        return df
    df["uuid"] = df["uuid"].str.upper()
    df["pcc_monto"] = pd.to_numeric(df["pcc_monto"], errors="coerce").fillna(0.0)
    return df


def detalle_pago_cxp(pares: pd.DataFrame) -> pd.DataFrame:
    """(cxp_folio, pc_id) -> instrumento de pago (Pago_CXP) + saldo de la
    obligación (Cuenta_X_Pagar)."""
    if pares.empty:
        return pd.DataFrame()
    folios = sorted(pares["cxp_folio"].dropna().unique().tolist())
    pago_rows, cxp_rows = [], []
    for i in range(0, len(folios), BATCH):
        chunk = folios[i:i + BATCH]
        in_list = ", ".join(sql_quote(f) for f in chunk)
        pago_rows.extend(rows_as_dicts(run_query(MPRO_TARGET,
            "SELECT Cxp_Folio AS cxp_folio, Pc_ID AS pc_id, Pc_Tabla AS instrumento, "
            "Pc_Documento AS instrumento_doc, Pc_Importe AS pc_importe, Pc_Fecha AS pc_fecha, "
            "Es_Cve_Estado AS estado "
            f"FROM Pago_CXP WHERE Cxp_Folio IN ({in_list})")))
        cxp_rows.extend(rows_as_dicts(run_query(MPRO_TARGET,
            "SELECT Cxp_Folio AS cxp_folio, Cxp_Precio_Neto_Importe AS cxp_importe, "
            "Cxp_Precio_Neto_Pago AS cxp_pago, Cxp_Precio_Neto_Saldo AS cxp_saldo, "
            "Es_Cve_Estado AS cxp_estado "
            f"FROM Cuenta_X_Pagar WHERE Cxp_Folio IN ({in_list})")))
    pago = pd.DataFrame(pago_rows)
    cxp = pd.DataFrame(cxp_rows)
    if not pago.empty:
        for c in ("pc_importe",):
            pago[c] = pd.to_numeric(pago[c], errors="coerce").fillna(0.0)
    if not cxp.empty:
        for c in ("cxp_importe", "cxp_pago", "cxp_saldo"):
            cxp[c] = pd.to_numeric(cxp[c], errors="coerce").fillna(0.0)
        cxp = cxp.drop_duplicates(subset=["cxp_folio"])
    out = pares.merge(pago, on=["cxp_folio", "pc_id"], how="left")
    if not cxp.empty:
        out = out.merge(cxp, on="cxp_folio", how="left")
    return out


def pago_directo_cheque(uuids: list[str]) -> pd.DataFrame:
    """Vía 2: mismo mecanismo que baseline_universal.py vía 5 — CFDI
    etiquetado como CHEQUE, abono aislado por monto (no por referencia,
    72% de los casos trae la referencia externa del banco)."""
    uuids = sorted({u.upper() for u in uuids if u})
    out = []
    for i in range(0, len(uuids), BATCH):
        chunk = uuids[i:i + BATCH]
        in_list = ", ".join(sql_quote(u) for u in chunk)
        sql = (
            "SELECT cd.Cd_Timbre_UUID AS uuid, ch.Ch_Folio AS cheque_folio, "
            "ch.Ch_Importe AS ch_importe, ch.Ch_Fecha AS ch_fecha "
            "FROM Comprobante_Digital cd "
            "JOIN Cheque ch ON ch.Ch_Folio = LEFT(cd.Cd_Documento, 10) "
            f"WHERE cd.Cd_Timbre_UUID IN ({in_list}) AND UPPER(cd.Cd_Tabla) = 'CHEQUE' "
            "AND ch.Es_Cve_Estado <> 'CA'"
        )
        out.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    df = pd.DataFrame(out, columns=["uuid", "cheque_folio", "ch_importe", "ch_fecha"])
    if not df.empty:
        df["uuid"] = df["uuid"].str.upper()
        df["ch_importe"] = pd.to_numeric(df["ch_importe"], errors="coerce").fillna(0.0)
    return df


def estatus_saldo(row) -> str:
    saldo = row.get("cxp_saldo")
    importe = row.get("cxp_importe")
    if pd.isna(saldo) or pd.isna(importe) or importe == 0:
        return "SIN_INFO_SALDO"
    if abs(saldo) <= TOL:
        return "PAGADO_TOTAL"
    if abs(saldo - importe) <= TOL:
        return "SIN_PAGO_APLICADO"
    return "PAGADO_PARCIAL"


def conciliar(periodos: list[str]) -> pd.DataFrame:
    sat, origenes = ul.universo(periodos=periodos)
    console_err.print(f"[bold]Universo: {len(sat)} CFDI I/E[/bold]")
    uuids = sat["uuid"].tolist()

    console_err.print("  vía 1 · Pago_Cxp_Comprobante…")
    v1 = pago_comprobante_por_uuid(uuids)
    console_err.print(f"    {v1['uuid'].nunique() if not v1.empty else 0} CFDI con al menos 1 aplicación")
    det1 = detalle_pago_cxp(v1) if not v1.empty else pd.DataFrame()
    if not det1.empty:
        det1["estatus_saldo"] = det1.apply(estatus_saldo, axis=1)

    console_err.print("  vía 2 · Cheque (match por monto)…")
    v2 = pago_directo_cheque(uuids)
    console_err.print(f"    {v2['uuid'].nunique() if not v2.empty else 0} CFDI etiquetados a un Cheque")

    # --- Consolidar por CFDI ---
    resumen = sat[["uuid", "fecha", "rfc_emisor", "nombre_emisor", "total"]].copy()
    if not det1.empty:
        agg1 = det1.groupby("uuid").agg(
            monto_via1=("pcc_monto", "sum"),
            instrumentos=("instrumento", lambda s: ", ".join(sorted({str(x) for x in s if pd.notna(x)}))),
            estatus_peor=("estatus_saldo", lambda s: sorted(s, key=lambda x: (
                x != "SIN_PAGO_APLICADO", x != "PAGADO_PARCIAL"))[0] if len(s) else ""),
        ).reset_index()
        resumen = resumen.merge(agg1, on="uuid", how="left")
    else:
        resumen["monto_via1"] = 0.0
        resumen["instrumentos"] = ""
        resumen["estatus_peor"] = ""

    if not v2.empty:
        agg2 = v2.groupby("uuid")["ch_importe"].sum().rename("monto_via2").reset_index()
        resumen = resumen.merge(agg2, on="uuid", how="left")
    else:
        resumen["monto_via2"] = 0.0
    resumen["monto_via1"] = resumen["monto_via1"].fillna(0.0)
    resumen["monto_via2"] = resumen["monto_via2"].fillna(0.0)

    def via(row):
        if row["monto_via1"] > TOL:
            cuadra = abs(row["monto_via1"] - row["total"]) <= max(TOL, row["total"] * 0.005)
            return "pago_directo_comprobante" + ("" if cuadra else " (monto no cuadra)")
        if row["monto_via2"] > TOL:
            cuadra = abs(row["monto_via2"] - row["total"]) <= max(TOL, row["total"] * 0.005)
            return "pago_directo_cheque" + ("" if cuadra else " (monto no cuadra)")
        return "SIN_PAGO_ENCONTRADO"

    resumen["via_pago"] = resumen.apply(via, axis=1)
    resumen["estatus"] = resumen.apply(
        lambda r: r["estatus_peor"] if r["monto_via1"] > TOL and r["estatus_peor"]
        else ("PAGADO_TOTAL" if r["monto_via2"] > TOL else "SIN_PAGO_ENCONTRADO"), axis=1)
    return resumen, det1, v2


def drill_down(uuid: str) -> None:
    console_err.print(f"\n[bold]Drill-down de pago — {uuid}[/bold]")
    v1 = pago_comprobante_por_uuid([uuid])
    if not v1.empty:
        mostrar_tabla_err(v1, "Pago_Cxp_Comprobante", max_filas=10)
        det = detalle_pago_cxp(v1)
        det["estatus_saldo"] = det.apply(estatus_saldo, axis=1)
        mostrar_tabla_err(det, "Instrumento de pago + saldo de Cuenta_X_Pagar", max_filas=10)
    else:
        console_err.print("[yellow]Sin registro en Pago_Cxp_Comprobante.[/yellow]")
    v2 = pago_directo_cheque([uuid])
    if not v2.empty:
        mostrar_tabla_err(v2, "Cheque directo (vía 2)", max_filas=10)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--periodo", required=True)
    ap.add_argument("--uuid", help="drill-down de un CFDI concreto")
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()
    periodos = [args.periodo]

    if args.uuid:
        drill_down(args.uuid)
        return

    resumen, det1, v2 = conciliar(periodos)
    cobertura = resumen["via_pago"].value_counts(normalize=False)
    console_err.print()
    resumen_err(cfdi_total=len(resumen),
                con_via1=int((resumen["monto_via1"] > TOL).sum()),
                con_via2=int((resumen["monto_via2"] > TOL).sum()),
                sin_pago_encontrado=int((resumen["via_pago"] == "SIN_PAGO_ENCONTRADO").sum()))
    mostrar_tabla_err(cobertura.reset_index().rename(columns={"index": "vía", "via_pago": "n_cfdi"}),
                      "Cobertura por vía", max_filas=15)

    mostrar_tabla_err(resumen["estatus"].value_counts().reset_index()
                      .rename(columns={"index": "estatus", "estatus": "n_cfdi"}),
                      "Estatus de saldo (solo vía 1, la única con Cuenta_X_Pagar)", max_filas=10)

    pendientes = resumen[resumen["via_pago"] == "SIN_PAGO_ENCONTRADO"]
    if not pendientes.empty:
        mostrar_tabla_err(pendientes[["uuid", "fecha", "rfc_emisor", "nombre_emisor", "total"]].head(20),
                          f"CFDI sin pago encontrado por ninguna vía ({len(pendientes)} total, "
                          "muestra 20)", max_filas=20)

    console_err.print(
        "\n[dim]Nota: Pago_Cxp_Comprobante es el link explícito que hace mpro entre CFDI y pago; "
        "no cubrir a un CFDI aquí no prueba que no se haya pagado -- puede vivir en un mecanismo "
        "no cubierto (Pago_CXC visto desde cobranza, aplicación manual, etc.). SIN_PAGO_ENCONTRADO "
        "es 'no lo hallamos', no 'no está pagado'.[/dim]")

    if args.csv:
        print("--- CSV_PARA_CLAUDE: pagos_recibidos ---")
        print(resumen.to_csv(index=False))


if __name__ == "__main__":
    main()
