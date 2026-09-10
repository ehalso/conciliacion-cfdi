#!/usr/bin/env python3
"""Baseline de conciliación CFDI recibidos ↔ mpro, por origen de documento.

Separa los CFDI de un origen (por ahora: COMPRA, el único con el método de
doble chequeo ya validado) en dos listas:

  - CONCILIADOS: CARGO (posteado bajo el folio de compra en mpro) == SUBTOTAL
    del CFDI, Y ABONO (posteado bajo la Serie+Folio del propio CFDI,
    normalizada) == TOTAL del CFDI. Ambos con tolerancia de $1.00.
  - PENDIENTES: encontrados en mpro (Comprobante_Digital) pero sin cuadrar
    en alguno de los dos lados — con el motivo, para revisión dirigida.

Metodología completa y supuestos documentados en la hoja "Resumen" del
.xlsx de salida. Validado en vivo 2026-09-09 sobre COMPRA feb-2026: 583/713
(81.8%) conciliados.

Uso:
    python3 baseline_conciliacion.py --periodo 2026-02
    python3 baseline_conciliacion.py --periodo 2026-02 --salida output/baseline_compra_feb2026.xlsx
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pandas as pd  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

from extract_sat import extract_sat_recibidos  # noqa: E402
from extract_origen import extract_origenes_por_uuids  # noqa: E402
from extract_poliza_por_origen import extract_poliza_por_origen  # noqa: E402
from bridge_client import run_query, rows_as_dicts, sql_quote  # noqa: E402
from config import MPRO_TARGET  # noqa: E402

TOL = 1.00
BATCH = 150

FONT = "Arial"
HEADER_FILL = PatternFill(start_color="2E4374", end_color="2E4374", fill_type="solid")
HEADER_FONT = Font(name=FONT, bold=True, color="FFFFFF", size=10)
TITLE_FONT = Font(name=FONT, bold=True, size=14, color="1A2233")
SUB_FONT = Font(name=FONT, size=10, italic=True, color="5B6472")
CELL_FONT = Font(name=FONT, size=10)
GOOD_FILL = PatternFill(start_color="E1F2EA", end_color="E1F2EA", fill_type="solid")
WARN_FILL = PatternFill(start_color="FBEEDA", end_color="FBEEDA", fill_type="solid")
THIN = Side(style="thin", color="D7DCE3")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
MONEY_FMT = "$#,##0.00"
DATE_FMT = "yyyy-mm-dd"

COLS = {
    "uuid": ("UUID CFDI", 38),
    "fecha": ("Fecha", 12),
    "rfc_emisor": ("RFC Emisor", 14),
    "nombre_emisor": ("Proveedor", 32),
    "documento_real": ("Folio Compra (mpro)", 16),
    "subtotal": ("Subtotal CFDI", 14),
    "iva": ("IVA CFDI", 12),
    "total": ("Total CFDI", 14),
    "cargo_mpro": ("Cargo mpro", 14),
    "abono_mpro": ("Abono mpro", 14),
    "diferencia_cargo": ("Dif. Cargo-Subtotal", 16),
    "diferencia_abono": ("Dif. Abono-Total", 16),
    "pl_folio_cargo": ("Poliza(s) Cargo", 16),
    "pl_folio_abono": ("Poliza Abono", 14),
    "motivo_pendiente": ("Motivo pendiente", 22),
}


def normaliza(ref):
    """Normaliza una referencia de Poliza_Detalle: quita prefijo 'Fact: ',
    espacios y guiones, y ceros a la izquierda del número — para poder
    comparar 'NT1997' (Comprobante_Digital) contra 'NT00001997' o
    'Fact: NT0000199' (captura manual en Poliza_Detalle)."""
    if not ref or not isinstance(ref, str):
        return None
    ref = ref.strip().upper()
    if ref.startswith("FACT:") or ref.startswith("FACT "):
        ref = ref.split(":", 1)[-1].strip() if ":" in ref else ref[4:].strip()
    ref = ref.replace(" ", "").replace("-", "")
    m = re.match(r"^([A-Z]*)0*([0-9]+)$", ref)
    if not m:
        return ref
    letras, numero = m.groups()
    return f"{letras}{int(numero)}"


def calcular(periodo: str, origen: str = "COMPRA") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    print(f"[1/6] SAT recibidos {periodo}")
    sat = extract_sat_recibidos(periodo=periodo)

    print("[2/6] Origenes en Comprobante_Digital")
    origenes = extract_origenes_por_uuids(sat["uuid"].tolist())
    df = origenes[origenes["origen"] == origen].drop_duplicates(subset=["uuid", "documento"]).copy()
    df["documento_real"] = df["documento"].str.slice(0, 10)
    df = df.merge(sat[["uuid", "fecha", "rfc_emisor", "nombre_emisor", "subtotal", "iva", "total"]], on="uuid", how="left")
    print(f"     {df['uuid'].nunique()} CFDI en origen {origen}")

    print("[3/6] Cargo por documento (funcion validada del pipeline)")
    docs = df["documento_real"].dropna().unique().tolist()
    pol = extract_poliza_por_origen(origen, docs)
    df = df.merge(
        pol.rename(columns={"documento": "documento_real", "cargo": "cargo_mpro"})[["documento_real", "cargo_mpro"]],
        on="documento_real", how="left")
    df["cargo_mpro"] = df["cargo_mpro"].fillna(0.0)

    # Un mismo CFDI puede quedar etiquetado con MAS DE UN Cd_Documento bajo el
    # mismo origen en Comprobante_Digital (confirmado en vivo 2026-09-09: 50/713
    # CFDI de COMPRA en feb-2026) — normalmente una etiqueta real y una
    # "fantasma" con cargo $0 (renglon vacio o mal capturado). Sin este paso,
    # quedarse con el primer duplicado (orden arbitrario) puede tomar la
    # fantasma y reportar cargo=0 aunque el CFDI si tenga su cargo real bajo el
    # otro folio. Nos quedamos con el folio cuyo cargo esta mas cerca del
    # subtotal del CFDI.
    df["_dist_cargo"] = (df["cargo_mpro"] - df["subtotal"]).abs()
    df = df.loc[df.groupby("uuid")["_dist_cargo"].idxmin()].drop(columns="_dist_cargo").reset_index(drop=True)

    print("[4/6] Serie+Folio de cada CFDI (Cd_Serie / Cd_Serie_Folio)")
    uuids = df["uuid"].unique().tolist()
    serie_rows = []
    for i in range(0, len(uuids), BATCH):
        batch = uuids[i:i + BATCH]
        in_list = ", ".join(sql_quote(u) for u in batch)
        sql = f"SELECT DISTINCT Cd_Timbre_UUID, Cd_Serie, Cd_Serie_Folio FROM Comprobante_Digital WHERE Cd_Timbre_UUID IN ({in_list})"
        serie_rows.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    serie_df = pd.DataFrame(serie_rows)
    serie_df["Cd_Timbre_UUID"] = serie_df["Cd_Timbre_UUID"].str.upper()
    serie_df = serie_df.drop_duplicates(subset=["Cd_Timbre_UUID"])
    serie_df["serie_folio"] = (serie_df["Cd_Serie"].fillna("") + serie_df["Cd_Serie_Folio"].fillna("")).str.upper().str.replace("-", "", regex=False)
    serie_df = serie_df.rename(columns={"Cd_Timbre_UUID": "uuid"})
    df = df.merge(serie_df[["uuid", "serie_folio"]], on="uuid", how="left")
    df["serie_folio_norm"] = df["serie_folio"].apply(normaliza)

    print("[5/6] Abono por Serie+Folio (dentro de la(s) poliza(s) propia(s) del documento)")
    pc_rows = []
    for i in range(0, len(docs), BATCH):
        batch = docs[i:i + BATCH]
        in_list = ", ".join(sql_quote(d) for d in batch)
        sql = f"""
        SELECT DISTINCT pc.Pc_Documento AS documento_real, pc.Pl_Folio
        FROM Poliza_Control pc
        JOIN Poliza p ON p.Pl_Folio = pc.Pl_Folio
        LEFT JOIN Poliza_Configuracion pcf ON pcf.Pc_Cve_Poliza_Configuracion = p.Pl_Configuracion
        WHERE UPPER(pc.Pc_Tabla) = {sql_quote(origen)} AND pc.Pc_Documento IN ({in_list})
          AND p.Es_Cve_Estado <> 'CA'
          AND (pcf.Pc_Descripcion IS NULL OR UPPER(pcf.Pc_Descripcion) NOT LIKE '%CUENTAS DE ORDEN%')
        """
        pc_rows.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    pc_df = pd.DataFrame(pc_rows)
    doc_to_folios = pc_df.groupby("documento_real")["Pl_Folio"].apply(set).to_dict() if not pc_df.empty else {}

    folios = pc_df["Pl_Folio"].unique().tolist() if not pc_df.empty else []
    det_rows = []
    for i in range(0, len(folios), BATCH):
        batch = folios[i:i + BATCH]
        in_list = ", ".join(sql_quote(f) for f in batch)
        sql = f"SELECT Pl_Folio, Pd_Referencia, Pd_Tipo, Pd_Importe FROM Poliza_Detalle WHERE Pl_Folio IN ({in_list}) AND Pd_Tipo=2"
        det_rows.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    det_df = pd.DataFrame(det_rows)
    if not det_df.empty:
        det_df["Pd_Importe"] = pd.to_numeric(det_df["Pd_Importe"], errors="coerce")
        det_df["ref_norm_folio"] = det_df["Pd_Referencia"].apply(normaliza)

    def abono_para(row):
        doc = row["documento_real"]
        norm = row["serie_folio_norm"]
        total = row["total"]
        folios_doc = doc_to_folios.get(doc, set())
        if not folios_doc or not norm or det_df.empty:
            return 0.0, ""
        cand = det_df[(det_df["Pl_Folio"].isin(folios_doc)) & (det_df["ref_norm_folio"] == norm)]
        if cand.empty:
            return 0.0, ""
        best_idx = (cand["Pd_Importe"] - total).abs().idxmin()
        return cand.loc[best_idx, "Pd_Importe"], cand.loc[best_idx, "Pl_Folio"]

    resultado = df.apply(abono_para, axis=1, result_type="expand")
    df["abono_mpro"] = resultado[0]
    df["pl_folio_abono"] = resultado[1]
    df["pl_folio_cargo"] = df["documento_real"].map(lambda d: ", ".join(sorted(doc_to_folios.get(d, []))))

    df["cuadra_cargo_subtotal"] = (df["cargo_mpro"] - df["subtotal"]).abs() <= TOL
    df["cuadra_abono_total"] = (df["abono_mpro"] - df["total"]).abs() <= TOL
    df["cuadra_ambos"] = df["cuadra_cargo_subtotal"] & df["cuadra_abono_total"]

    def motivo(row):
        if row["cuadra_ambos"]:
            return "OK"
        faltan = []
        if not row["cuadra_cargo_subtotal"]:
            faltan.append("cargo≠subtotal")
        if not row["cuadra_abono_total"]:
            faltan.append("abono≠total" if row["abono_mpro"] > 0 else "sin abono encontrado")
        return " / ".join(faltan)

    df["motivo_pendiente"] = df.apply(motivo, axis=1)

    print("[6/6] Armando baselines")
    resumen = df.drop_duplicates("uuid").copy()

    cols_base = ["uuid", "fecha", "rfc_emisor", "nombre_emisor", "documento_real",
                 "subtotal", "iva", "total", "cargo_mpro", "abono_mpro",
                 "pl_folio_cargo", "pl_folio_abono"]

    conciliados = resumen[resumen["cuadra_ambos"]][cols_base].copy()
    conciliados["diferencia_cargo"] = (conciliados["cargo_mpro"] - conciliados["subtotal"]).round(2)
    conciliados["diferencia_abono"] = (conciliados["abono_mpro"] - conciliados["total"]).round(2)

    pendientes = resumen[~resumen["cuadra_ambos"]][cols_base].copy()
    pendientes["motivo_pendiente"] = resumen[~resumen["cuadra_ambos"]]["motivo_pendiente"]
    pendientes["diferencia_cargo"] = (pendientes["cargo_mpro"] - pendientes["subtotal"]).round(2)
    pendientes["diferencia_abono"] = (pendientes["abono_mpro"] - pendientes["total"]).round(2)

    return conciliados, pendientes, resumen


def escribe_hoja(ws, df, cols, fill_status=None):
    headers = [COLS[c][0] for c in cols]
    ws.append(headers)
    for j, c in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=j)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
        ws.column_dimensions[get_column_letter(j)].width = COLS[c][1]
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}1"

    money_cols = {"subtotal", "iva", "total", "cargo_mpro", "abono_mpro", "diferencia_cargo", "diferencia_abono"}
    for _, row in df.iterrows():
        vals = []
        for c in cols:
            v = row.get(c)
            if pd.isna(v):
                v = "" if c not in money_cols else 0
            vals.append(v)
        ws.append(vals)
        r = ws.max_row
        for j, c in enumerate(cols, start=1):
            cell = ws.cell(row=r, column=j)
            cell.font = CELL_FONT
            cell.border = BORDER
            if c in money_cols:
                cell.number_format = MONEY_FMT
            if c == "fecha":
                cell.number_format = DATE_FMT
            if fill_status is not None:
                cell.fill = fill_status


def hoja_portada(ws, periodo, origen, conciliados, pendientes):
    ws.column_dimensions["A"].width = 90
    ws["A1"] = f"Conciliación CFDI ↔ mpro — Baseline {origen} (recibidos)"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Periodo: {periodo}   ·   Generado: {datetime.now().strftime('%Y-%m-%d')}   ·   Fuente: raw_sat.cfdi_recibidos vs {MPRO_TARGET} (mpro)"
    ws["A2"].font = SUB_FONT
    total = len(conciliados) + len(pendientes)
    filas = [
        "",
        "MÉTODO",
        f"Para cada CFDI de origen {origen} se validan dos lados de la póliza, de forma independiente:",
        "  • CARGO: el importe posteado en Poliza_Detalle referenciado por el folio de compra de mpro (Comprobante_Digital.Cd_Documento, truncado a 10",
        "    caracteres) debe igualar el SUBTOTAL del CFDI (tolerancia $1.00). Cuando un CFDI tiene mas de un folio etiquetado bajo el mismo origen,",
        "    se elige el que de el cargo mas cercano al subtotal.",
        "  • ABONO: el importe posteado y referenciado por la Serie+Folio del propio CFDI (Comprobante_Digital.Cd_Serie + Cd_Serie_Folio, normalizado —",
        "    sin ceros a la izquierda, ignorando prefijos como 'Fact:') debe igualar el TOTAL del CFDI (tolerancia $1.00), dentro de la(s) póliza(s)",
        "    activa(s) ligadas a ese folio de compra vía Poliza_Control (se excluyen pólizas canceladas y la duplicada de 'cuentas de orden').",
        "Un CFDI se marca CONCILIADO solo si AMBOS lados cuadran.",
        "",
        "SUPUESTOS Y LIMITACIONES",
        "  • El IVA se postea en mpro como una sola línea consolidada por día/póliza (no por documento) — no es verificable por CFDI individual,",
        "    por eso no se incluye un chequeo de IVA línea por línea; se reporta el IVA del CFDI como referencia.",
        "  • Un CFDI puede aparecer también bajo COMPRA_INDIRECTO (costo indirecto prorrateado hacia otras compras) — esa porción NO se suma aquí;",
        "    algunos 'pendientes' son en realidad CFDI cuya diferencia coincide con su porción de COMPRA_INDIRECTO.",
        "  • Se detectó un patrón (proveedor GLM/Gas LP de Mérida, y posiblemente otros pagados de contado): la póliza de COMPRA se cancela y el",
        "    pago se registra directo en el módulo Cheque — el ABONO no se encuentra en COMPRA para esos casos, aunque el CARGO sí cuadra.",
        "  • También hay casos sueltos de typo de captura: el Cd_Documento apunta a un folio de compra que en realidad es de OTRA compra distinta",
        "    (cargo con un importe que no tiene relacion con el CFDI) — no es un patron sistematico, es ruido de captura manual caso por caso.",
        f"  • Base: {total} CFDI de origen {origen} en Comprobante_Digital para el periodo indicado.",
        "",
        "RESULTADO",
        f"  • Conciliados (cargo Y abono cuadran): {len(conciliados)} CFDI  ({len(conciliados)/total*100:.1f}%)" if total else "  • Sin datos",
        f"  • Pendientes (encontrados en mpro, sin cuadrar aún): {len(pendientes)} CFDI  ({len(pendientes)/total*100:.1f}%)" if total else "",
        "",
        "HOJAS",
        "  • Conciliados: CFDI + folio de compra en mpro que lo concilió + suma de sus movimientos de póliza (cargo y abono).",
        "  • Pendientes: CFDI encontrados en mpro pero aún sin conciliar, con el motivo (qué lado no cuadra) para revisión dirigida.",
    ]
    for i, texto in enumerate(filas, start=3):
        cell = ws.cell(row=i, column=1, value=texto)
        cell.font = Font(name=FONT, size=10, bold=(texto in ("MÉTODO", "SUPUESTOS Y LIMITACIONES", "RESULTADO", "HOJAS")))
        cell.alignment = Alignment(wrap_text=True, vertical="top")


def run(periodo: str, origen: str, salida: str):
    conciliados, pendientes, _ = calcular(periodo, origen)
    print(f"Conciliados: {len(conciliados)}   Pendientes: {len(pendientes)}")

    Path(salida).parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws0 = wb.active
    ws0.title = "Resumen"
    hoja_portada(ws0, periodo, origen, conciliados, pendientes)

    cols1 = ["uuid", "fecha", "rfc_emisor", "nombre_emisor", "documento_real", "subtotal", "iva", "total",
             "cargo_mpro", "abono_mpro", "diferencia_cargo", "diferencia_abono", "pl_folio_cargo", "pl_folio_abono"]
    ws1 = wb.create_sheet("Conciliados")
    escribe_hoja(ws1, conciliados, cols1, fill_status=GOOD_FILL)

    cols2 = ["uuid", "fecha", "rfc_emisor", "nombre_emisor", "documento_real", "subtotal", "iva", "total",
             "cargo_mpro", "abono_mpro", "diferencia_cargo", "diferencia_abono", "motivo_pendiente"]
    ws2 = wb.create_sheet("Pendientes")
    escribe_hoja(ws2, pendientes, cols2, fill_status=WARN_FILL)

    wb.save(salida)
    print(f"\nReporte: {salida}")
    return conciliados, pendientes


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--periodo", required=True)
    ap.add_argument("--origen", default="COMPRA")
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()
    salida = args.salida or f"output/baseline_{args.origen.lower()}_{args.periodo}.xlsx"
    run(args.periodo, args.origen, salida)
