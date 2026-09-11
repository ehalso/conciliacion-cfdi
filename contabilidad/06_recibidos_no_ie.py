#!/usr/bin/env python3
"""CFDI recibidos que NO son tipo Ingreso ni Egreso — censo y vías de conciliación.

`baseline_universal.py` limita su universo a `tipo_comprobante IN ('I','E')`
porque Traslado (T) y Pago (P) traen `SubTotal`/`Total` en $0 **por diseño
del SAT** (el monto real vive en el complemento, no en los campos base) — no
porque carezcan de valor. Ese universo queda hoy completamente fuera de
cualquier conciliación. Este reporte lo censa y propone/mide una vía para
el que sí tiene valor real: el REP (tipo P).

## Qué es cada tipo aquí

  T  Traslado — Carta Porte. Confirmado: 100% autoemitido (`direccion` =
     AUTOEMITIDO, Trivasa se transporta su propia mercancía) y `uso_cfdi=
     'S01'` — es evidencia de transporte, no de una operación con proveedor.
     Sin valor fiscal propio, no debería conciliarse contra nada.

  P  Pago (REP) — Recibo Electrónico de Pago. El monto real vive en el
     complemento de Pagos, ya parseado en `raw_sat.cfdi_recibidos`:
     `pagos_monto_total`, `pagos_iva_total`, `pagos_dr_uuids` (los UUID de
     las FACTURAS que el REP dice estar pagando, `;`-separado),
     `pagos_dr_pagado`. Un REP es la evidencia FISCAL de que una factura se
     pagó — por eso es la pieza que más conecta con el frente de pagos
     (`05_pagos_recibidos.py`): si `pagos_dr_uuids` apunta a un UUID que
     nuestro universo de facturas ya tiene, ese REP CONFIRMA el pago desde
     el lado del SAT, independiente de lo que diga mpro.

  N  Nómina — CFDI de nómina. Del lado RECIBIDOS (Trivasa como receptor) es
     conceptualmente raro: la nómina de Trivasa la emite Trivasa, no la
     recibe de terceros. Se censa para confirmar si aparece y qué es.

Uso:
    python3 contabilidad/06_recibidos_no_ie.py --periodo 2026-02
    python3 contabilidad/06_recibidos_no_ie.py --periodo 2026-02 --tipo P --csv
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

BATCH = 300


def censo(periodos: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Todo raw_sat.cfdi_recibidos del periodo (sin filtrar por tipo), ligado
    a Comprobante_Digital."""
    sat, origenes = ul.universo(periodos=periodos, solo_monetarios=False)
    return sat, origenes


def cd_tabla_por_tipo(sat: pd.DataFrame, origenes: pd.DataFrame) -> pd.DataFrame:
    liga = sat[["uuid", "tipo_comprobante"]].merge(origenes[["uuid", "origen"]], on="uuid", how="left")
    liga["origen"] = liga["origen"].fillna("(sin etiqueta en mpro)")
    return (liga.groupby(["tipo_comprobante", "origen"]).size()
            .rename("n").reset_index().sort_values(["tipo_comprobante", "n"], ascending=[True, False]))


def tipo_comprobante_mpro_vs_sat(origenes: pd.DataFrame, sat: pd.DataFrame) -> pd.DataFrame:
    """Cruza tipo_comprobante (SAT) contra Cd_Tipo_Comprobante_CFDI (mpro) --
    inconsistencias entre ambas clasificaciones."""
    liga = origenes.merge(sat[["uuid", "tipo_comprobante"]], on="uuid", how="left")
    return (liga.groupby(["tipo_comprobante", "tipo_comprobante_mpro"]).size()
            .rename("n").reset_index().sort_values("n", ascending=False))


def rep_a_facturas(sat_p: pd.DataFrame, universo_uuids: set[str]) -> pd.DataFrame:
    """Para cada REP (tipo P), separa pagos_dr_uuids y verifica si esas
    facturas están en el universo de CFDI recibidos ya conocido."""
    filas = []
    for _, r in sat_p.iterrows():
        dr = str(r.get("pagos_dr_uuids") or "").strip()
        uuids_dr = [u.strip().upper() for u in dr.split(";") if u.strip()] if dr else []
        for u in uuids_dr:
            filas.append({"uuid_rep": r["uuid"], "uuid_factura": u,
                          "en_universo_recibidos": u in universo_uuids})
        if not uuids_dr:
            filas.append({"uuid_rep": r["uuid"], "uuid_factura": None,
                          "en_universo_recibidos": False})
    return pd.DataFrame(filas)


def cheque_de_rep(uuids_rep: list[str]) -> pd.DataFrame:
    """¿El REP está etiquetado a un Cheque en mpro, y ese cheque cuadra
    contra pagos_dr_pagado?"""
    uuids_rep = sorted({u.upper() for u in uuids_rep if u})
    out = []
    for i in range(0, len(uuids_rep), BATCH):
        chunk = uuids_rep[i:i + BATCH]
        in_list = ", ".join(sql_quote(u) for u in chunk)
        sql = (
            "SELECT cd.Cd_Timbre_UUID AS uuid_rep, cd.Cd_Tabla AS origen, "
            "ch.Ch_Folio AS cheque_folio, ch.Ch_Importe AS ch_importe "
            "FROM Comprobante_Digital cd "
            "LEFT JOIN Cheque ch ON ch.Ch_Folio = LEFT(cd.Cd_Documento, 10) "
            f"AND UPPER(cd.Cd_Tabla) = 'CHEQUE' "
            f"WHERE cd.Cd_Timbre_UUID IN ({in_list})"
        )
        out.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    df = pd.DataFrame(out, columns=["uuid_rep", "origen", "cheque_folio", "ch_importe"])
    if not df.empty:
        df["uuid_rep"] = df["uuid_rep"].str.upper()
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--periodo", required=True)
    ap.add_argument("--tipo", choices=["P", "T", "N", "todos"], default="todos")
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()
    periodos = [args.periodo]

    sat, origenes = censo(periodos)
    console_err.print(f"[bold]Censo — {args.periodo}: {len(sat)} CFDI recibidos totales[/bold]")

    por_tipo = sat["tipo_comprobante"].value_counts().reset_index()
    por_tipo.columns = ["tipo_comprobante", "n_cfdi"]
    con_etiqueta = (sat.assign(en_mpro=sat["uuid"].isin(set(origenes["uuid"])))
                    .groupby("tipo_comprobante")["en_mpro"].sum().rename("n_en_mpro"))
    por_tipo = por_tipo.merge(con_etiqueta, on="tipo_comprobante", how="left").fillna(0)
    mostrar_tabla_err(por_tipo, "CFDI recibidos por tipo_comprobante", max_filas=10)

    tab_tipo = cd_tabla_por_tipo(sat, origenes)
    mostrar_tabla_err(tab_tipo, "Cd_Tabla (mpro) por tipo_comprobante (SAT)", max_filas=30)

    cruce = tipo_comprobante_mpro_vs_sat(origenes, sat)
    mostrar_tabla_err(cruce, "tipo_comprobante (SAT) vs Cd_Tipo_Comprobante_CFDI (mpro)", max_filas=20)

    resultados_csv = {}

    if args.tipo in ("T", "todos"):
        t = sat[sat["tipo_comprobante"] == "T"]
        console_err.print(f"\n[bold]Tipo T (Traslado) — {len(t)} CFDI[/bold]")
        if not t.empty:
            pct_auto = (f"{(t['rfc_emisor'] == t['rfc_receptor']).mean() * 100:.1f}%"
                        if "rfc_receptor" in t.columns else "n/d (columna no traída)")
            resumen_err(pct_autoemitido=pct_auto,
                        subtotal_total_suma=f"${t['subtotal'].sum():,.2f} / ${t['total'].sum():,.2f}")
            liga_t = t[["uuid"]].merge(origenes[["uuid", "origen"]], on="uuid", how="left")
            mostrar_tabla_err(liga_t["origen"].fillna("(sin etiqueta)").value_counts().reset_index(),
                              "Tipo T — a qué Cd_Tabla se liga en mpro (si acaso)", max_filas=10)
            console_err.print("[dim]Recomendación: NO conciliar. Autoemitido, sin valor fiscal "
                              "propio (evidencia de transporte, no de compra/venta).[/dim]")

    if args.tipo in ("P", "todos"):
        p = sat[sat["tipo_comprobante"] == "P"]
        console_err.print(f"\n[bold]Tipo P (REP) — {len(p)} CFDI[/bold]")
        if not p.empty:
            universo_uuids = set(sat.loc[sat["tipo_comprobante"] == "I", "uuid"])
            rel = rep_a_facturas(p, universo_uuids)
            n_rep_con_dr = rel.loc[rel["uuid_factura"].notna(), "uuid_rep"].nunique()
            n_dr_total = rel["uuid_factura"].notna().sum()
            n_dr_en_universo = rel["en_universo_recibidos"].sum()
            resumen_err(reps=len(p), reps_con_doctorelacionado=n_rep_con_dr,
                        facturas_referenciadas=n_dr_total,
                        de_esas_en_universo_del_mes=int(n_dr_en_universo),
                        pct=f"{n_dr_en_universo / n_dr_total * 100:.1f}%" if n_dr_total else "n/d")
            console_err.print("[dim]'en universo del mes' exige que la factura pagada sea del MISMO "
                              "periodo que el REP -- una factura de enero pagada por un REP de "
                              "febrero cuenta como 'no en universo' aquí; ver el detalle.[/dim]")

            ch = cheque_de_rep(p["uuid"].tolist())
            p_merge = p.merge(ch, left_on="uuid", right_on="uuid_rep", how="left")
            con_cheque = p_merge["cheque_folio"].notna().sum()
            resumen_err(reps_ligados_a_cheque=int(con_cheque),
                        reps_sin_ninguna_etiqueta_mpro=int((p_merge["origen"].isna()).sum()))

            p_merge["dif_pagado_vs_cheque"] = (
                pd.to_numeric(p_merge["pagos_dr_pagado"], errors="coerce").fillna(0.0)
                - pd.to_numeric(p_merge["ch_importe"], errors="coerce").fillna(0.0)).round(2)
            con_cheque_df = p_merge[p_merge["cheque_folio"].notna()]
            if not con_cheque_df.empty:
                n_cuadra = (con_cheque_df["dif_pagado_vs_cheque"].abs() <= 1.0).sum()
                resumen_err(reps_con_cheque_que_cuadra=f"{n_cuadra}/{len(con_cheque_df)}")

            mostrar_tabla_err(p_merge[["uuid", "fecha", "rfc_emisor", "pagos_monto_total",
                                        "pagos_dr_pagado", "cheque_folio", "ch_importe",
                                        "dif_pagado_vs_cheque"]].head(20),
                              "REP: monto del complemento vs Cheque ligado (muestra 20)", max_filas=20)

            console_err.print(
                "[dim]Vía propuesta para tipo P: (a) tomar pagos_dr_uuids como confirmación fiscal "
                "de que esas facturas se pagaron -- cruzar contra 05_pagos_recibidos.py para ver si "
                "coincide con la vía Pago_Cxp_Comprobante ya encontrada; (b) cuando el REP se liga a "
                "un Cheque en mpro, pagos_dr_pagado debería igualar Ch_Importe -- medido arriba.[/dim]")
            resultados_csv["rep_detalle"] = p_merge

    if args.tipo in ("N", "todos"):
        n = sat[sat["tipo_comprobante"] == "N"]
        console_err.print(f"\n[bold]Tipo N (Nómina) — {len(n)} CFDI recibidos[/bold]")
        if n.empty:
            console_err.print("[dim]Ninguno este periodo -- consistente con que Trivasa no "
                              "'recibe' nómina de terceros. Cerrado, no aplica conciliar.[/dim]")
        else:
            mostrar_tabla_err(n[["uuid", "fecha", "rfc_emisor", "nombre_emisor", "subtotal", "total"]],
                              "CFDI tipo N recibidos (inesperado, revisar)", max_filas=20)

    recomendaciones = pd.DataFrame([
        {"tipo": "T", "recomendacion": "NO conciliar", "motivo": "autoemitido, Carta Porte, sin valor fiscal propio"},
        {"tipo": "P", "recomendacion": "Conciliar vía pagos_dr_uuids + cruce con 05_pagos_recibidos.py",
         "motivo": "es la evidencia SAT de qué factura se pagó; complementa (no reemplaza) la vía mpro"},
        {"tipo": "N", "recomendacion": "No aplica del lado recibidos", "motivo": "Trivasa no recibe nómina de terceros"},
    ])
    mostrar_tabla_err(recomendaciones, "Recomendación por tipo", max_filas=10)

    if args.csv:
        print("--- CSV_PARA_CLAUDE: censo_por_tipo ---")
        print(por_tipo.to_csv(index=False))
        for nombre, df in resultados_csv.items():
            print(f"--- CSV_PARA_CLAUDE: {nombre} ---")
            print(df.to_csv(index=False))


if __name__ == "__main__":
    main()
