#!/usr/bin/env python3
"""Baseline UNIVERSAL de conciliación CFDI recibidos ↔ mpro — todos los
orígenes a la vez, chequeo agregado por CFDI (no por documento individual).

Motivación (2026-09-09): `baseline_conciliacion.py` concilia un origen a la
vez (hoy: COMPRA) exigiendo que UN documento cuadre exacto contra el CFDI.
Eso choca con un patrón real: un mismo CFDI puede estar repartido entre
VARIOS documentos de mpro — mismo origen (folio duplicado) o distinto
origen (COMPRA + COMPRA_INDIRECTO, GASTO_REGISTRO + CUENTA_X_PAGAR, o el
patrón de liquidación directa COMPRA cancelada + CHEQUE activo). Exigir 1
documento = 1 CFDI descarta esos casos aunque el dinero sí esté, solo que
repartido.

Este script no elige "el" documento: para cada CFDI SUMA el cargo de TODOS
los documentos con los que aparece etiquetado en `Comprobante_Digital`
(cualquier `Cd_Tabla`/origen). Es un chequeo de un solo lado (cargo =
reconocimiento de inventario/gasto) — NO exige además que el abono cuadre.

Tras la revisión folio por folio del 2026-09-09/10, el chequeo dejó de ser una
sola comparación y es una **cascada de vías de cuadre**: un CFDI puede estar
perfectamente contabilizado sin que el cargo iguale su base, porque el
tratamiento contable correcto es otro (arrendamiento financiero partido entre
interés y capital, nota de crédito contra el total, IVA no acreditable, gasto
repartido entre sucursales…). Cada vía deja su etiqueta en la columna "Vía de
cuadre" del reporte, para que el resultado sea auditable y no una caja negra.

Además, la base fiscal contra la que se compara ya no es el subtotal crudo:

    base = (SubTotal - Descuento + IEPS + impuestos_locales) x tipo_de_cambio

porque `raw_sat` guarda el subtotal bruto y en la moneda original del CFDI,
mientras que mpro postea el importe neto y en MXN.

Resultado en vivo, H1 2026: **9,511 de 9,572 (99.36%)** — ene 99.2%, feb 99.5%,
mar 99.2%, abr 99.8%, may 99.2%, jun 99.4%. Febrero venía en 90.1%. El detalle
de cada hallazgo, con evidencia, y la clasificación de los 61 pendientes que
quedan está en docs/investigacion_pendientes.md.

Uso:
    python3 baseline_universal.py --periodo 2026-02
    python3 baseline_universal.py --periodo 2026-02 --salida output/universal_feb2026.xlsx
"""
from __future__ import annotations

import argparse
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
from extract_poliza_por_origen import extract_poliza_por_origen, extract_poliza_cheque  # noqa: E402
from extract_gasto_registro import extract_gasto_registro_granular  # noqa: E402
from extract_detalle_lineas import extract_lineas_poliza, extract_lineas_gasto_registro, DETALLE_COLS  # noqa: E402
from extract_moneda import extract_moneda_documento  # noqa: E402
from extract_empresa import filtra_empresa_trivasa  # noqa: E402
from extract_vias_extra import (cuadre_arrendamiento_financiero, cuadre_repartido_por_referencia,  # noqa: E402
                                resumen_folios_gasto, cuadre_cheque_agrupado,
                                extract_moneda_e_importe_documento, extract_referencia_cxp,
                                IMPORTE_DOCUMENTO)

TOL = 1.00
TOL_RELATIVA = 0.00005  # 0.005% de la base: materialidad para redondeo de tipo de cambio

# Universo comparado: solo Ingreso y Egreso -- Traslado (Carta Porte) y Pago
# (REP) traen SubTotal/Total en $0 por diseño del SAT (el monto real de un
# Pago vive en el complemento, no en estos campos; ver conciliacion_xml_lib.py
# si se quiere incorporar ese universo más adelante). Antes se aproximaba
# este filtro con `subtotal > $1`, que fallaba en 30 CFDI I/E de valor
# simbólico (ej. $0.01) del periodo 2026-02: quedaban excluidos del universo
# y además "cuadraban" por accidente contra cualquier cargo (la tolerancia de
# $1 los cubre completos). Filtrar por tipo es la regla real, no un proxy.
TIPOS_CON_VALOR = {"I", "E"}

# Orígenes cuyo Pd_Referencia no liga de forma confiable al folio del
# documento (ver poliza-explor/index.md) — se manejan aparte, no con el
# query genérico por Pd_Referencia=documento.
ORIGEN_MONTO_ESPECIAL = {"CHEQUE"}
# GASTO_REGISTRO tiene su propia llave granular (folio+Grd_ID, sumando
# todos los Grc_ID/centros de costo de esa llave, ver extract_gasto_registro.py)
# — no usa el query genérico por Pd_Referencia.
ORIGEN_GRANULAR = {"GASTO_REGISTRO"}
# Orígenes que son "complementos" sin valor propio (Carta Porte, REP) — se
# excluyen de la búsqueda de cargo (no aportan, y consultarlos es ruido).
ORIGEN_SIN_VALOR = {"TRASLADO", "COMPROBANTE_PAGO"}

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
    "origenes": ("Orígen(es) en mpro", 26),
    "subtotal": ("Subtotal CFDI", 14),
    "iva": ("IVA CFDI", 12),
    "total": ("Total CFDI", 14),
    "cargo_agregado": ("Cargo agregado (todos los docs)", 18),
    "diferencia": ("Diferencia vs Subtotal", 16),
    "cuadra_via": ("Vía de cuadre", 20),
    "motivo_pendiente": ("Motivo pendiente", 20),
}


def ajustes_desde_sat(sat: pd.DataFrame, uuids: list[str]) -> pd.DataFrame:
    """Ajuste que hay que aplicarle al subtotal del SAT para obtener la base
    que mpro captura:

        ajuste = -Descuento + IEPS + impuestos_locales_trasladados - retenidos_locales

    (todo en la moneda original del CFDI; la conversión a MXN es un paso aparte).

    Hasta 2026-09-10 esto requería volver a bajar y parsear el `Cd_XML` de
    cada CFDI desde `Comprobante_Digital` (mpro) en cada corrida — el paso
    más caro del pipeline (~1,500+ XML por mes, sin caché entre worktrees).
    Desde esa fecha, `raw_sat.cfdi_recibidos`/`cfdi_emitidos` ya traen estos
    campos parseados en la propia ingesta (`descuento`, `ieps_trasladado`,
    `impuestos_locales_trasladados`, `impuestos_locales_retenidos` — ver
    `src/cfdi_parser.py` para el detalle de cómo se extraen del XML), así que
    basta leerlos de `sat` — validado en vivo contra el parseo directo del
    XML de mpro, exacto en los casos probados.
    """
    cols = ["uuid", "descuento", "ieps_trasladado",
            "impuestos_locales_trasladados", "impuestos_locales_retenidos"]
    df = sat.loc[sat["uuid"].isin(set(uuids)), cols].drop_duplicates(subset=["uuid"]).copy()
    for c in cols[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df = df.rename(columns={"ieps_trasladado": "ieps"})
    df["local"] = df["impuestos_locales_trasladados"] - df["impuestos_locales_retenidos"]
    df["ajuste"] = -df["descuento"] + df["local"] + df["ieps"]
    return df.set_index("uuid")


def calcular(periodo: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    print(f"[1/5] SAT recibidos {periodo}")
    sat = extract_sat_recibidos(periodo=periodo)
    print(f"     {len(sat)} CFDI recibidos")

    print("[2/5] Orígenes en Comprobante_Digital (TODOS, no solo un origen)")
    origenes = extract_origenes_por_uuids(sat["uuid"].tolist())
    origenes = origenes.dropna(subset=["documento"]).copy()
    origenes["documento_real"] = origenes["documento"].str.slice(0, 10)
    origenes["origen_up"] = origenes["origen"].str.upper()
    # Dedup origin-aware: para orígenes normales, colapsar por folio corto
    # (documento_real) evita doble-conteo cuando el mismo folio aparece
    # repetido con distinto sufijo (folio "fantasma" duplicado).
    # Para GASTO_REGISTRO la llave real es folio(10)+Grd_ID(4) = los primeros 14
    # caracteres. NO sirve deduplicar por el `documento` completo: el mismo
    # (folio, Grd_ID) aparece capturado DOS VECES en Comprobante_Digital, una
    # vez en formato de 14 caracteres y otra en el de 18 (gotcha ya documentado
    # en trivasa-context) — con el mismo UUID y el mismo monto. Deduplicar por
    # el documento completo deja pasar las dos filas y **duplica el cargo**:
    # eso era lo que hacía ver 7 CFDI de feb-2026 con exactamente 2x su importe,
    # que parecían doble captura en mpro y en realidad eran doble conteo nuestro.
    origenes["_dedup_doc"] = origenes["documento_real"].where(
        ~origenes["origen_up"].isin(ORIGEN_GRANULAR), origenes["documento"].str.slice(0, 14))
    origenes = origenes.drop_duplicates(subset=["uuid", "origen_up", "_dedup_doc"]).drop(columns=["_dedup_doc"])
    print(f"     {origenes['uuid'].nunique()} CFDI con al menos 1 etiqueta en mpro"
          f" ({len(origenes)} etiquetas documento, algunos CFDI tienen varias)")

    print("[2b/5] Filtrando ruido intercompañía (Comprobante_Digital es compartida entre empresas del mpro)")
    n_antes = len(origenes)
    origenes = filtra_empresa_trivasa(origenes)
    print(f"     {n_antes - len(origenes)} etiquetas descartadas por no ser de la empresa Trivasa"
          f" (quedan {len(origenes)}, {origenes['uuid'].nunique()} CFDI con al menos 1 etiqueta propia)")

    print("[3/5] Cargo por documento, para cada origen presente (genérico, excluye cuentas de orden)")
    origenes_cargo = sorted(o for o in origenes["origen"].unique()
                             if o.upper() not in ORIGEN_MONTO_ESPECIAL | ORIGEN_SIN_VALOR | ORIGEN_GRANULAR)
    cargo_parts = []
    for origen in origenes_cargo:
        docs = origenes.loc[origenes["origen"] == origen, "documento_real"].dropna().unique().tolist()
        if not docs:
            continue
        pol = extract_poliza_por_origen(origen, docs)
        if pol.empty:
            continue
        pol = pol.rename(columns={"documento": "documento_real"})
        pol["origen"] = origen
        cargo_parts.append(pol[["origen", "documento_real", "cargo", "abono"]])
        print(f"     {origen}: {len(docs)} documentos -> {len(pol)} con cargo/abono en póliza")
    cargo_df = pd.concat(cargo_parts, ignore_index=True) if cargo_parts else pd.DataFrame(
        columns=["origen", "documento_real", "cargo", "abono"])

    merged = origenes[~origenes["origen_up"].isin(ORIGEN_GRANULAR)].merge(
        cargo_df, on=["origen", "documento_real"], how="left")
    merged["cargo"] = merged["cargo"].fillna(0.0)
    merged["abono"] = merged["abono"].fillna(0.0)
    total_cargo = merged.groupby("uuid")["cargo"].sum().rename("cargo_agregado")
    # Nota de crédito de proveedor: hay dos configuraciones vivas y solo una
    # deja el importe del lado del CARGO. La de "BONIFICACION" (config 0350)
    # registra únicamente abonos con `Pd_Referencia` (inventario + IVA); su
    # cargo a proveedores va en la póliza sin referencia al documento, así que
    # el cargo aislado sale en cero. En ese caso el abono ES el importe
    # reconocido — y en ambas variantes cuadra contra el TOTAL del CFDI, no
    # contra el subtotal (una nota de crédito reduce el adeudo con IVA
    # incluido). Confirmado 2026-09-09 en las 13 notas de crédito de feb-2026.
    nc = merged[merged["origen_up"] == "NOTA_CREDITO_PROVEEDOR"]
    if not nc.empty:
        nc_monto = nc.assign(monto=nc["cargo"].where(nc["cargo"].abs() > TOL, nc["abono"]))
        monto_nota_credito = nc_monto.groupby("uuid")["monto"].sum().rename("monto_nota_credito")
    else:
        monto_nota_credito = pd.Series(dtype=float, name="monto_nota_credito")

    print("[3b/5] GASTO_REGISTRO: llave granular folio+Grd_ID, suma de Grc_Importe (Gasto_Registro_Control)")
    docs_gasto = origenes.loc[origenes["origen_up"] == "GASTO_REGISTRO", "documento"].dropna().unique().tolist()
    if docs_gasto:
        gasto_cargo = extract_gasto_registro_granular(docs_gasto)
        gasto_cargo["cargo"] = gasto_cargo["cargo"].fillna(0.0)
        gasto_map = origenes[origenes["origen_up"] == "GASTO_REGISTRO"][["uuid", "documento"]].merge(
            gasto_cargo, on="documento", how="left")
        gasto_map["cargo"] = gasto_map["cargo"].fillna(0.0)
        gasto_map["neto"] = pd.to_numeric(gasto_map.get("neto"), errors="coerce").fillna(0.0)
        gasto_total = gasto_map.groupby("uuid")["cargo"].sum().rename("cargo_gasto")
        gasto_neto = gasto_map.groupby("uuid")["neto"].sum().rename("gasto_neto")
        gasto_refs = gasto_map.groupby("uuid")["referencia"].apply(
            lambda s: sorted({str(x).strip() for x in s if str(x).strip()})).rename("gasto_referencias")
        gasto_map["descontado"] = pd.to_numeric(gasto_map.get("descontado"), errors="coerce").fillna(0.0)
        gasto_folios = gasto_map.groupby("uuid")["folio"].apply(
            lambda s: sorted({str(x) for x in s if pd.notna(x)})).rename("gasto_folios")
        gasto_renglones = gasto_map.groupby("uuid").apply(
            lambda d: [(float(a), float(b)) for a, b in zip(d["neto"], d["descontado"])],
            include_groups=False).rename("gasto_renglones")
        n_dif = int((gasto_map.groupby("uuid")["cargo"].sum() - gasto_neto).abs().gt(TOL).sum())
        print(f"     {len(docs_gasto)} documentos GASTO_REGISTRO (llave completa) -> "
              f"{gasto_cargo['cargo'].notna().sum()} con cargo encontrado, "
              f"{n_dif} CFDI donde el gasto distribuido != importe del documento")
        total_cargo = total_cargo.add(gasto_total, fill_value=0.0).rename("cargo_agregado")
        # Moneda/tipo de cambio de GASTO_REGISTRO ya vienen en gasto_map --
        # misma consulta que cargo/neto (fusionadas 2026-09-10 en
        # extract_gasto_registro_granular(); antes era una consulta aparte
        # a la MISMA tabla Gasto_Registro_Documento, ver [3d/5] anterior).
        gasto_map["tipo_cambio"] = pd.to_numeric(gasto_map.get("tipo_cambio"), errors="coerce").fillna(1.0)
        gasto_map.loc[gasto_map["tipo_cambio"] <= 0, "tipo_cambio"] = 1.0
        gasto_map["moneda"] = gasto_map.get("moneda", "").fillna("")
        gasto_tc = gasto_map[["uuid", "moneda", "tipo_cambio"]].copy()
    else:
        gasto_neto = pd.Series(dtype=float, name="gasto_neto")
        gasto_refs = pd.Series(dtype=object, name="gasto_referencias")
        gasto_folios = pd.Series(dtype=object, name="gasto_folios")
        gasto_renglones = pd.Series(dtype=object, name="gasto_renglones")
        gasto_tc = pd.DataFrame(columns=["uuid", "moneda", "tipo_cambio"])

    print("[3c/5] Descuento + IEPS + impuestos locales (ya parseados en raw_sat, sin volver a bajar XML)")
    # Antes: se parseaba el XML de TODOS los CFDI con etiqueta en mpro (no solo
    # GASTO_REGISTRO) porque el `Descuento` a nivel Comprobante no existía como
    # columna en `raw_sat.cfdi_recibidos`. Desde 2026-09-10 el ingest de
    # ctunlinux ya lo trae — ver `ajustes_desde_sat()`.
    ajuste_xml = ajustes_desde_sat(sat, origenes["uuid"].unique().tolist())
    ajuste_series = ajuste_xml["ajuste"].rename("ajuste_local")
    n_desc = int((ajuste_xml["descuento"] > 0.01).sum())
    n_local = int((ajuste_xml["local"].abs() > 0.01).sum())
    n_ieps = int((ajuste_xml["ieps"] > 0.01).sum())
    print(f"     {len(ajuste_xml)} CFDI — {n_desc} con Descuento, "
          f"{n_ieps} con IEPS, {n_local} con impuesto local")

    print("[3d/5] Moneda + importe del documento (fusionadas: misma tabla/folio que antes eran 2 consultas)")
    # GASTO_REGISTRO ya se resolvió en [3b/5] (gasto_tc, misma consulta que
    # cargo/neto). Para los orígenes con columna de importe propia
    # (IMPORTE_DOCUMENTO: COMPRA, COMPRA_INDIRECTO, CUENTA_X_PAGAR,
    # NOTA_CREDITO_PROVEEDOR, FACTURA) se trae moneda+tipo_cambio+importe en
    # una sola consulta por lote en vez de dos loops separados ([3d/5] viejo
    # + el de importe_documento que vivía en [4b/5]). El resto (ej. CHEQUE,
    # que no tiene columna de importe de documento aquí) sigue con
    # extract_moneda_documento().
    tc_partes = [gasto_tc] if len(gasto_tc) else []
    imp_partes = []
    for origen in sorted(origenes["origen"].unique()):
        if origen.upper() == "GASTO_REGISTRO":
            continue
        docs_or = origenes[origenes["origen"] == origen]
        docs_list = docs_or["documento_real"].dropna().unique().tolist()
        if origen.upper() in IMPORTE_DOCUMENTO:
            m = extract_moneda_e_importe_documento(origen, docs_list)
            if m.empty:
                continue
            merged_or = docs_or.merge(m.rename(columns={"documento": "documento_real"}),
                                       on="documento_real", how="left")
            tc_partes.append(merged_or[["uuid", "moneda", "tipo_cambio"]])
            imp_partes.append(merged_or.dropna(subset=["importe_documento"])[["uuid", "importe_documento"]])
        else:
            m = extract_moneda_documento(origen, docs_list)
            if m.empty:
                continue
            merged_or = docs_or.merge(m.rename(columns={"documento": "documento_real"}),
                                       on="documento_real", how="left")
            tc_partes.append(merged_or[["uuid", "moneda", "tipo_cambio"]])
    importe_doc = (pd.concat(imp_partes, ignore_index=True).groupby("uuid")["importe_documento"].sum()
                   .rename("importe_documento") if imp_partes
                   else pd.Series(dtype=float, name="importe_documento"))

    if tc_partes:
        tc_df = pd.concat(tc_partes, ignore_index=True)
        tc_df["tipo_cambio"] = pd.to_numeric(tc_df["tipo_cambio"], errors="coerce").fillna(1.0)
        tc_df.loc[tc_df["tipo_cambio"] <= 0, "tipo_cambio"] = 1.0
        tc_uuid = tc_df.groupby("uuid").agg(
            moneda_mpro=("moneda", lambda s: ",".join(sorted({str(x) for x in s if pd.notna(x) and str(x).strip()})) or "MXN"),
            tipo_cambio=("tipo_cambio", "max")).reset_index()
        n_div = int((tc_uuid["tipo_cambio"] > 1.0001).sum())
        print(f"     {n_div} CFDI capturados en moneda extranjera (se convierte el subtotal a MXN)")
    else:
        tc_uuid = pd.DataFrame(columns=["uuid", "moneda_mpro", "tipo_cambio"])

    print("[4/5] CHEQUE: match por monto (Pd_Referencia no es confiable para este origen)")
    docs_cheque = origenes.loc[origenes["origen_up"] == "CHEQUE", "documento_real"].dropna().unique().tolist()
    if docs_cheque:
        cheque = extract_poliza_cheque(docs_cheque)
        cheque_map = origenes[origenes["origen_up"] == "CHEQUE"][["uuid", "documento_real"]].merge(
            cheque.rename(columns={"documento": "documento_real"})[["documento_real", "abono"]],
            on="documento_real", how="left")
        cheque_abono = cheque_map.groupby("uuid")["abono"].sum().rename("cheque_abono")
    else:
        cheque_abono = pd.Series(dtype=float, name="cheque_abono")

    print("[4b/5] Vías extra: arrendamiento financiero y gasto repartido entre folios")
    # Referencias del proveedor por CFDI: las de Gasto_Registro más las de
    # Cuenta_X_Pagar (parte del arrendamiento financiero se captura por ese
    # módulo y sin ellas la regla de arrendamiento no lo alcanza).
    cxp_ref = extract_referencia_cxp(
        origenes.loc[origenes["origen_up"] == "CUENTA_X_PAGAR", "documento_real"].dropna().unique().tolist())
    if not cxp_ref.empty:
        cxp_por_uuid = (origenes[origenes["origen_up"] == "CUENTA_X_PAGAR"][["uuid", "documento_real"]]
                        .merge(cxp_ref.rename(columns={"documento": "documento_real"}),
                               on="documento_real", how="inner")
                        .groupby("uuid")["referencia"]
                        .apply(lambda s: sorted({str(x).strip() for x in s if str(x).strip()})).to_dict())
    else:
        cxp_por_uuid = {}

    refs_todas = sorted({r for lista in (gasto_refs.tolist() if len(gasto_refs) else [])
                         for r in (lista or [])}
                        | {r for lista in cxp_por_uuid.values() for r in lista})
    leasing = cuadre_arrendamiento_financiero(refs_todas)
    repartido = cuadre_repartido_por_referencia(refs_todas)
    print(f"     {len(refs_todas)} referencias de proveedor -> "
          f"{leasing['referencia'].nunique() if not leasing.empty else 0} con póliza de pago de arrendamiento, "
          f"{repartido['referencia'].nunique() if not repartido.empty else 0} con grupo de folios hermanos")

    folios_gasto_todos = sorted({f for lista in (gasto_folios.tolist() if len(gasto_folios) else [])
                                 for f in (lista or [])})
    folios_resumen = resumen_folios_gasto(folios_gasto_todos)
    cheques_agrupados = cuadre_cheque_agrupado(
        origenes.loc[origenes["origen_up"] == "CHEQUE", "documento_real"].dropna().unique().tolist())
    n_ch = int(((cheques_agrupados["importe_cheque"] - cheques_agrupados["suma_cfdi"]).abs() <= TOL).sum()) \
        if not cheques_agrupados.empty else 0
    print(f"     {len(folios_resumen)} folios de gasto resumidos, "
          f"{n_ch} cheques cuyo importe = suma de los CFDI que liquidan")

    print("[5/5] Armando resultado")
    origenes_str = origenes.groupby("uuid")["origen"].apply(lambda s: ", ".join(sorted(set(s)))).rename("origenes")

    resumen = (sat.set_index("uuid").join(total_cargo, how="left").join(cheque_abono, how="left")
               .join(origenes_str, how="left").join(ajuste_series, how="left")
               .join(gasto_neto, how="left").join(gasto_refs, how="left")
               .join(gasto_folios, how="left").join(gasto_renglones, how="left")
               .join(monto_nota_credito, how="left").join(importe_doc, how="left").reset_index())
    resumen = resumen.merge(tc_uuid, on="uuid", how="left")
    resumen["cargo_agregado"] = resumen["cargo_agregado"].fillna(0.0)
    resumen["cheque_abono"] = resumen["cheque_abono"].fillna(0.0)
    resumen["ajuste_local"] = resumen["ajuste_local"].fillna(0.0)
    resumen["gasto_neto"] = pd.to_numeric(resumen.get("gasto_neto"), errors="coerce").fillna(0.0)
    resumen["monto_nota_credito"] = pd.to_numeric(resumen.get("monto_nota_credito"), errors="coerce").fillna(0.0)
    resumen["importe_documento"] = pd.to_numeric(resumen.get("importe_documento"), errors="coerce").fillna(0.0)
    resumen["referencias"] = [
        sorted(set(g if isinstance(g, list) else []) | set(cxp_por_uuid.get(u, [])))
        for u, g in zip(resumen["uuid"], resumen["gasto_referencias"])]
    resumen["tipo_cambio"] = pd.to_numeric(resumen.get("tipo_cambio"), errors="coerce").fillna(1.0)
    resumen.loc[resumen["tipo_cambio"] <= 0, "tipo_cambio"] = 1.0
    # El subtotal/total del SAT están en la moneda original del CFDI; la póliza
    # de mpro postea SIEMPRE en MXN. Se lleva la base fiscal a MXN con el tipo
    # de cambio del propio documento de mpro (no uno de mercado): así el cuadre
    # compara peras con peras. Para CFDI en MXN el factor es 1.0 y no cambia nada.
    resumen["subtotal_ajustado"] = (resumen["subtotal"] + resumen["ajuste_local"]) * resumen["tipo_cambio"]
    resumen["total_mxn"] = resumen["total"] * resumen["tipo_cambio"]
    resumen["en_mpro"] = resumen["uuid"].isin(set(origenes["uuid"]))
    resumen["monetario"] = resumen["tipo_comprobante"].isin(TIPOS_CON_VALOR)

    # Tolerancia por materialidad: $1 fijo, o 0.005% de la base si es mayor.
    # El componente relativo cubre el redondeo de convertir moneda extranjera
    # renglón por renglón (un CFDI de $70,000 puede diferir $1.02 solo por eso)
    # sin volverse permisivo: en el CFDI más grande del periodo son ~$45.
    resumen["tolerancia"] = pd.concat([
        pd.Series(TOL, index=resumen.index),
        resumen["subtotal_ajustado"].abs() * TOL_RELATIVA], axis=1).max(axis=1)
    tol = resumen["tolerancia"]

    solo_nota_credito = resumen["origenes"].fillna("") == "NOTA_CREDITO_PROVEEDOR"

    # --- Regla 1: el cargo contabilizado iguala la base fiscal del CFDI.
    resumen["cuadra_cargo_subtotal"] = (
        (resumen["cargo_agregado"] - resumen["subtotal_ajustado"]).abs() <= tol) & ~solo_nota_credito

    # --- Regla 2: nota de crédito de proveedor -> contra el TOTAL (con IVA).
    resumen["cuadra_nota_credito"] = solo_nota_credito & (
        (resumen["monto_nota_credito"] - resumen["total_mxn"]).abs() <= tol)

    # --- Regla 3: IVA no acreditable. mpro manda el IVA al gasto en vez de
    # acreditarlo (gastos menores, gasolina, abarrotes), así que el importe
    # contabilizado es el TOTAL del CFDI y no su base. Es un tratamiento
    # contable legítimo, no un descuadre.
    resumen["cuadra_iva_al_gasto"] = (~resumen["cuadra_cargo_subtotal"]) & (~solo_nota_credito) & (
        ((resumen["cargo_agregado"] - resumen["total_mxn"]).abs() <= tol)
        | ((resumen["gasto_neto"] * resumen["tipo_cambio"] - resumen["total_mxn"]).abs() <= tol)
        ) & ((resumen["cargo_agregado"].abs() > TOL) | (resumen["gasto_neto"].abs() > TOL)) & (
        # Solo tiene sentido llamarle "IVA no acreditable" si el total difiere
        # de la base: si el CFDI no trae impuestos (cuotas IMSS, derechos),
        # base y total son el mismo número y el caso es otro (regla 4).
        (resumen["total_mxn"] - resumen["subtotal_ajustado"]).abs() > tol)

    # --- Regla 4: el documento de Gasto_Registro capturó el importe del CFDI
    # exacto, pero el gasto distribuido a centros de costo es menor porque mpro
    # aplicó un descuento propio (caso confirmado: cuotas IMSS, donde la parte
    # obrera no es gasto de la empresa). El CFDI sí está reconocido y por el
    # importe correcto.
    resumen["cuadra_neto_documento"] = (
        (~resumen["cuadra_cargo_subtotal"]) & (~resumen["cuadra_nota_credito"])
        & (~resumen["cuadra_iva_al_gasto"]) & (resumen["gasto_neto"].abs() > TOL)
        & ((resumen["gasto_neto"] * resumen["tipo_cambio"] - resumen["subtotal_ajustado"]).abs() <= tol))

    # --- Regla 5 (ya existente): liquidación directa vía Cheque.
    resumen["cuadra_pago_directo"] = (
        ~(resumen["cuadra_cargo_subtotal"] | resumen["cuadra_nota_credito"]
          | resumen["cuadra_iva_al_gasto"] | resumen["cuadra_neto_documento"])) & (
        (resumen["cheque_abono"] - resumen["total_mxn"]).abs() <= tol)

    # --- Regla 6: arrendamiento financiero. El CFDI se parte entre gasto por
    # intereses y amortización de capital; la póliza de pago abona al banco el
    # TOTAL del CFDI. Ver src/extract_vias_extra.py.
    banco_por_uuid = {}
    if not leasing.empty:
        # (referencia -> {póliza: abono a banco}). Se guarda por póliza para
        # poder sumar: un mismo CFDI puede amparar VARIAS unidades arrendadas,
        # cada una con su propia póliza de pago (caso CATERPILLAR CREDITO: el
        # CFDI de $370,808.62 se paga en dos pólizas, $211,890.64 + $158,917.98).
        por_ref = {r: dict(zip(g["Pl_Folio"], g["abono_banco"]))
                   for r, g in leasing.groupby("referencia")}
        for u, refs in resumen[["uuid", "referencias"]].itertuples(index=False):
            if isinstance(refs, list):
                polizas = {}
                for r in refs:
                    polizas.update(por_ref.get(r, {}))
                if polizas:
                    montos = list(polizas.values())
                    if len(montos) > 1:
                        montos = montos + [sum(montos)]
                    banco_por_uuid[u] = montos
    resumen["cuadra_arrendamiento"] = [
        (not (a or b or c or d or e))
        and any(abs(m - t) <= tl for m in banco_por_uuid.get(u, []))
        for u, a, b, c, d, e, t, tl in zip(
            resumen["uuid"], resumen["cuadra_cargo_subtotal"], resumen["cuadra_nota_credito"],
            resumen["cuadra_iva_al_gasto"], resumen["cuadra_neto_documento"],
            resumen["cuadra_pago_directo"], resumen["total_mxn"], tol)]

    # --- Regla 7: el CFDI se capturó repartido en varios folios de
    # Gasto_Registro (uno por sucursal) y solo uno quedó etiquetado. Se suma el
    # gasto de todos los folios hermanos (misma Grd_Referencia y misma fecha).
    grupo_por_uuid = {}
    if not repartido.empty:
        # Solo grupos REALES: más de un folio compartiendo la referencia en la
        # misma fecha. Un grupo de un solo folio no es un reparto, y aceptarlo
        # cuadraría por accidente los CFDI capturados dos veces (donde cada
        # captura, por separado, sí trae el importe correcto).
        rep = repartido[repartido["n_folios"] > 1]
        por_ref2 = rep.groupby("referencia")["suma_grupo"].apply(list).to_dict()
        for u, refs in resumen[["uuid", "gasto_referencias"]].itertuples(index=False):
            if isinstance(refs, list):
                montos = [m for r in refs for m in por_ref2.get(r, [])]
                if montos:
                    grupo_por_uuid[u] = montos
    # Además: el documento etiquetado tiene que capturar DE MENOS (es una parte
    # del CFDI). Si captura de más, no es un reparto — es doble captura.
    resumen["cuadra_repartido"] = [
        (not (a or b or c or d or e or f)) and (cg < s_ - tl)
        and any(abs(m - s_) <= tl or abs(m - t) <= tl for m in grupo_por_uuid.get(u, []))
        for u, a, b, c, d, e, f, s_, t, tl, cg in zip(
            resumen["uuid"], resumen["cuadra_cargo_subtotal"], resumen["cuadra_nota_credito"],
            resumen["cuadra_iva_al_gasto"], resumen["cuadra_neto_documento"],
            resumen["cuadra_pago_directo"], resumen["cuadra_arrendamiento"],
            resumen["subtotal_ajustado"], resumen["total_mxn"], tol,
            resumen["cargo_agregado"])]

    # --- Regla 8: el CFDI cubre el folio COMPLETO de Gasto_Registro, pero solo
    # uno de sus renglones quedó etiquetado en Comprobante_Digital. Se exige que
    # el folio no tenga otro CFDI etiquetado, para no atribuirle gasto ajeno.
    folio_suma = dict(zip(folios_resumen.get("folio", []), folios_resumen.get("suma_folio", []))) \
        if not folios_resumen.empty else {}
    folio_ncfdi = dict(zip(folios_resumen.get("folio", []), folios_resumen.get("n_cfdi", []))) \
        if not folios_resumen.empty else {}

    def _suma_folios(folios):
        if not isinstance(folios, list) or not folios:
            return None
        if any(folio_ncfdi.get(f, 99) != 1 for f in folios):
            return None
        return sum(folio_suma.get(f, 0.0) for f in folios)

    suma_folio_uuid = resumen["gasto_folios"].apply(_suma_folios)
    ya = (resumen["cuadra_cargo_subtotal"] | resumen["cuadra_nota_credito"]
          | resumen["cuadra_iva_al_gasto"] | resumen["cuadra_neto_documento"]
          | resumen["cuadra_pago_directo"] | resumen["cuadra_arrendamiento"]
          | resumen["cuadra_repartido"])
    resumen["cuadra_folio_completo"] = (~ya) & suma_folio_uuid.notna() & (
        (suma_folio_uuid.fillna(0.0) * resumen["tipo_cambio"] - resumen["subtotal_ajustado"]).abs() <= tol)

    # --- Regla 9: el folio mezcla renglones de varios conceptos y uno de ellos
    # es exactamente este CFDI (el resto es gasto de otra factura del mismo
    # reporte). Se pide coincidencia exacta de un renglón contra la base o el
    # total, no un ajuste por diferencia.
    def _renglon_coincide(renglones, base, total_, tl, tc):
        if not isinstance(renglones, list):
            return False
        for neto, desc in renglones:
            for v in (neto * tc, desc * tc):
                if abs(v - base) <= tl or abs(v - total_) <= tl:
                    return True
        return False

    ya = ya | resumen["cuadra_folio_completo"]
    resumen["cuadra_renglon"] = [
        (not y) and _renglon_coincide(r, b, t, tl, tc)
        for y, r, b, t, tl, tc in zip(ya, resumen["gasto_renglones"], resumen["subtotal_ajustado"],
                                      resumen["total_mxn"], tol, resumen["tipo_cambio"])]

    # --- Regla 10: un cheque liquida VARIAS facturas; el importe del cheque
    # coincide con la suma de los CFDI que tiene etiquetados.
    ch_ok = set()
    if not cheques_agrupados.empty:
        ok = cheques_agrupados[(cheques_agrupados["importe_cheque"] - cheques_agrupados["suma_cfdi"]).abs() <= TOL]
        ch_ok = set(ok["documento"])
    docs_por_uuid = origenes[origenes["origen_up"] == "CHEQUE"].groupby("uuid")["documento_real"].apply(set).to_dict()
    ya = ya | pd.Series(resumen["cuadra_renglon"], index=resumen.index)
    resumen["cuadra_cheque_agrupado"] = [
        (not y) and bool(docs_por_uuid.get(u, set()) & ch_ok)
        for y, u in zip(ya, resumen["uuid"])]

    # --- Regla 11: no se pudo aislar el cargo en la póliza, pero el documento
    # de origen sí capturó el importe del CFDI (su propia columna
    # `Xx_Precio_Neto_Importe`). Casos confirmados: una FACTURA y una
    # CUENTA_X_PAGAR de feb-2026 donde el renglón contable quedó redondeado o
    # sin referencia aislable, pero el documento trae el total exacto.
    ya = ya | pd.Series(resumen["cuadra_cheque_agrupado"], index=resumen.index)
    resumen["cuadra_importe_documento"] = (~ya) & (resumen["importe_documento"].abs() > TOL) & (
        ((resumen["importe_documento"] * resumen["tipo_cambio"] - resumen["subtotal_ajustado"]).abs() <= tol)
        | ((resumen["importe_documento"] * resumen["tipo_cambio"] - resumen["total_mxn"]).abs() <= tol))

    resumen["cuadra_agregado"] = (ya | resumen["cuadra_importe_documento"])

    def via(row):
        if row["cuadra_cargo_subtotal"]:
            return "cargo = base CFDI"
        if row["cuadra_nota_credito"]:
            return "nota de crédito = total"
        if row["cuadra_iva_al_gasto"]:
            return "IVA no acreditable (cargo = total)"
        if row["cuadra_neto_documento"]:
            return "capturado en el documento (gasto distribuido menor)"
        if row["cuadra_pago_directo"]:
            return "pago directo (Cheque = total)"
        if row["cuadra_arrendamiento"]:
            return "arrendamiento financiero (interés + capital)"
        if row["cuadra_repartido"]:
            return "gasto repartido entre folios hermanos"
        if row["cuadra_folio_completo"]:
            return "el CFDI cubre el folio completo"
        if row["cuadra_renglon"]:
            return "capturado en un renglón del folio"
        if row["cuadra_cheque_agrupado"]:
            return "cheque que liquida varias facturas"
        if row["cuadra_importe_documento"]:
            return "capturado en el documento de origen"
        return ""

    def motivo(row):
        if row["cuadra_agregado"]:
            return "OK"
        if not row["en_mpro"]:
            return "no encontrado en mpro"
        return "cargo agregado ≠ subtotal"

    resumen["cuadra_via"] = resumen.apply(via, axis=1)
    resumen["motivo_pendiente"] = resumen.apply(motivo, axis=1)
    resumen["diferencia"] = (resumen["cargo_agregado"] - resumen["subtotal_ajustado"]).round(2)

    universo = resumen[resumen["monetario"] & resumen["en_mpro"]].copy()
    cols_base = ["uuid", "fecha", "rfc_emisor", "nombre_emisor", "origenes",
                 "subtotal", "iva", "total", "cargo_agregado", "diferencia"]

    conciliados = universo[universo["cuadra_agregado"]][cols_base + ["cuadra_via"]].copy()
    pendientes = universo[~universo["cuadra_agregado"]][cols_base + ["motivo_pendiente"]].copy()

    return conciliados, pendientes, resumen


def detalle_regla1(uuids: list[str]) -> pd.DataFrame:
    """Detalle a nivel línea de póliza / control de gasto para un conjunto
    de CFDI que cuadran por regla 1 ("cargo = base CFDI") — para la vista
    de drill-down. Independiente del periodo: `Comprobante_Digital` se
    consulta directo por UUID, así que sirve igual para un solo CFDI (modo
    perezoso) que para todos los de un periodo (modo carga completa).

    Validado en vivo (2026-09-09): sumar el `importe` devuelto aquí por
    `uuid` reproduce exactamente `cargo_agregado` de `calcular()` para el
    100% de las CFDI de regla 1 en febrero 2026 (1,442/1,442) — ver
    `docs/hallazgos.md` punto 27 (o el que corresponda tras reordenar).

    Alcance: solo orígenes "normales" (vía `Poliza_Detalle.Pd_Referencia`) y
    GASTO_REGISTRO (vía `Gasto_Registro_Control`). Excluye CHEQUE (monto por
    match, no por referencia) y los complementos sin valor — igual que
    `calcular()`. Las vías especiales (2-11) no están cubiertas: sus líneas
    viven en documentos que no son propios del CFDI (folios hermanos,
    póliza de banco, cheque agrupado) — ver docs/pendientes.md.
    """
    if not uuids:
        return pd.DataFrame(columns=["uuid"] + DETALLE_COLS)

    origenes = extract_origenes_por_uuids(list(uuids))
    origenes = origenes.dropna(subset=["documento"]).copy()
    if origenes.empty:
        return pd.DataFrame(columns=["uuid"] + DETALLE_COLS)
    origenes["documento_real"] = origenes["documento"].str.slice(0, 10)
    origenes["origen_up"] = origenes["origen"].str.upper()
    origenes["_dedup_doc"] = origenes["documento_real"].where(
        ~origenes["origen_up"].isin(ORIGEN_GRANULAR), origenes["documento"].str.slice(0, 14))
    origenes = origenes.drop_duplicates(subset=["uuid", "origen_up", "_dedup_doc"]).drop(columns=["_dedup_doc"])
    origenes = filtra_empresa_trivasa(origenes)
    if origenes.empty:
        return pd.DataFrame(columns=["uuid"] + DETALLE_COLS)

    partes = []

    origenes_normales = sorted(o for o in origenes["origen"].unique()
                                if o.upper() not in ORIGEN_MONTO_ESPECIAL | ORIGEN_SIN_VALOR | ORIGEN_GRANULAR)
    for origen in origenes_normales:
        docs = origenes.loc[origenes["origen"] == origen, "documento_real"].dropna().unique().tolist()
        if not docs:
            continue
        lineas = extract_lineas_poliza(origen, docs)
        if lineas.empty:
            continue
        mapa = origenes.loc[origenes["origen"] == origen, ["uuid", "documento_real"]].rename(
            columns={"documento_real": "documento"})
        partes.append(lineas.merge(mapa, on="documento", how="inner"))

    docs_gasto = origenes.loc[origenes["origen_up"] == "GASTO_REGISTRO", "documento"].dropna().unique().tolist()
    if docs_gasto:
        lineas_gasto = extract_lineas_gasto_registro(docs_gasto)
        if not lineas_gasto.empty:
            mapa = origenes.loc[origenes["origen_up"] == "GASTO_REGISTRO", ["uuid", "documento"]]
            partes.append(lineas_gasto.merge(mapa, on="documento", how="inner"))

    if not partes:
        return pd.DataFrame(columns=["uuid"] + DETALLE_COLS)
    detalle = pd.concat(partes, ignore_index=True)
    # Solo el lado que efectivamente suma cargo_agregado (regla 1 es cargo).
    detalle = detalle[detalle["tipo"] == "Cargo"].reset_index(drop=True)
    return detalle[["uuid"] + DETALLE_COLS]


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

    money_cols = {"subtotal", "iva", "total", "cargo_agregado", "diferencia"}
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


def hoja_portada(ws, periodo, conciliados, pendientes, resumen):
    ws.column_dimensions["A"].width = 96
    ws["A1"] = "Conciliación CFDI ↔ mpro — Baseline UNIVERSAL (recibidos, todos los orígenes)"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Periodo: {periodo}   ·   Generado: {datetime.now().strftime('%Y-%m-%d')}"
    ws["A2"].font = SUB_FONT

    total_universo = len(conciliados) + len(pendientes)
    n_total_cfdi = len(resumen)
    n_en_mpro = int(resumen["en_mpro"].sum())
    n_sin_valor = int((resumen["en_mpro"] & ~resumen["monetario"]).sum())

    vias = (resumen.loc[resumen["cuadra_agregado"] & resumen["monetario"] & resumen["en_mpro"], "cuadra_via"]
            .value_counts())

    filas = [
        "",
        "MÉTODO",
        "Para cada CFDI se SUMA el cargo de TODOS los documentos de mpro con los que aparece etiquetado en",
        "Comprobante_Digital, sin importar el origen (Cd_Tabla), y se compara contra la base fiscal del CFDI.",
        "Así, un CFDI repartido entre COMPRA + COMPRA_INDIRECTO, o entre GASTO_REGISTRO + CUENTA_X_PAGAR, cuadra",
        "sin necesidad de elegir 'el' documento correcto.",
        "",
        "La base fiscal NO es el subtotal crudo del SAT. Es:",
        "      (SubTotal - Descuento + IEPS + impuestos locales)  ×  tipo de cambio del documento de mpro",
        "porque raw_sat guarda el subtotal BRUTO y en la MONEDA ORIGINAL del CFDI, mientras que mpro captura el",
        "importe neto y postea siempre en MXN. El Descuento no existe como columna en raw_sat: se lee del XML.",
        "",
        "Un CFDI puede estar bien contabilizado aunque el cargo no iguale su base, porque el tratamiento contable",
        "correcto es otro. Por eso el cuadre es una CASCADA de vías, y cada CFDI conciliado dice por cuál cuadró",
        "(columna 'Vía de cuadre' en la hoja Conciliados):",
        "",
        "  1. cargo = base CFDI ................. el chequeo de siempre.",
        "  2. nota de crédito = total ........... reduce el adeudo con IVA incluido; nunca cuadra contra la base.",
        "  3. IVA no acreditable ................ mpro manda el IVA al gasto (gasolina, abarrotes): cargo = total.",
        "  4. capturado en el documento ......... el documento trae el importe del CFDI pero el gasto distribuido",
        "                                        es menor por un descuento propio de mpro (cuota obrera del IMSS).",
        "  5. pago directo (Cheque = total) ..... liquidación sin pasar por COMPRA/GASTO_REGISTRO.",
        "  6. arrendamiento financiero .......... solo el interés es gasto; el capital amortiza el pasivo y la",
        "                                        póliza de pago abona al banco el total del CFDI.",
        "  7. gasto repartido entre folios ...... una factura capturada como varios folios, uno por sucursal.",
        "  8. el CFDI cubre el folio completo ... todos los renglones del folio son del CFDI, uno solo etiquetado.",
        "  9. capturado en un renglón del folio . el folio mezcla conceptos y uno de ellos es este CFDI.",
        " 10. cheque que liquida varias facturas  el importe del cheque = suma de los CFDI que tiene etiquetados.",
        " 11. capturado en el documento de origen el cargo no se aísla en la póliza pero el documento sí lo trae.",
        "",
        "Tolerancia: $1.00, o 0.005% de la base si es mayor (cubre el redondeo de convertir moneda extranjera).",
        "Se excluyen de la búsqueda de cargo TRASLADO y COMPROBANTE_PAGO (complementos SAT — Carta Porte y REP —",
        "sin valor propio) y, del universo comparado, cualquier CFDI que no sea tipo Ingreso o Egreso (Traslado y",
        "Pago traen SubTotal/Total en $0 por diseño del SAT, no por carecer de valor real).",
        "",
        "IMPORTANTE — esto es un chequeo de UN SOLO LADO (cargo = reconocimiento de inventario/gasto). NO exige",
        "que el abono (pago) también cuadre, a diferencia de baseline_conciliacion.py (COMPRA, doble chequeo).",
        "",
        "UNIVERSO",
        f"  • {n_total_cfdi} CFDI recibidos en el periodo.",
        f"  • {n_en_mpro} encontrados en mpro (al menos 1 etiqueta en Comprobante_Digital).",
        f"  • {n_sin_valor} de esos son Traslado o Pago (no Ingreso/Egreso) — se excluyen del cuadre.",
        f"  • {total_universo} CFDI tipo Ingreso/Egreso, encontrados en mpro — este es el universo comparado.",
        "",
        "RESULTADO",
        f"  • Conciliados: {len(conciliados)} CFDI  ({len(conciliados)/total_universo*100:.1f}%)" if total_universo else "  • Sin datos",
        f"  • Pendientes: {len(pendientes)} CFDI  ({len(pendientes)/total_universo*100:.1f}%)" if total_universo else "",
        "",
        "POR VÍA DE CUADRE",
    ] + [f"  • {via}: {n}" for via, n in vias.items()] + [
        "",
        "HOJAS",
        "  • Conciliados: CFDI + orígenes donde aparece + cargo agregado + vía de cuadre.",
        "  • Pendientes: CFDI encontrados en mpro pero sin cuadrar, con el motivo.",
        "",
        "El detalle de cómo se llegó a cada vía, con la evidencia caso por caso, y la clasificación de los",
        "pendientes que quedan está en docs/investigacion_pendientes.md del repo.",
    ]
    for i, texto in enumerate(filas, start=3):
        cell = ws.cell(row=i, column=1, value=texto)
        cell.font = Font(name=FONT, size=10, bold=(texto in ("MÉTODO", "UNIVERSO", "RESULTADO", "HOJAS", "POR VÍA DE CUADRE")))
        cell.alignment = Alignment(wrap_text=True, vertical="top")


def run(periodo: str, salida: str):
    conciliados, pendientes, resumen = calcular(periodo)
    total = len(conciliados) + len(pendientes)
    print(f"\nUniverso monetario en mpro: {total}   Conciliados: {len(conciliados)} "
          f"({len(conciliados)/total*100:.1f}%)   Pendientes: {len(pendientes)}")

    Path(salida).parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws0 = wb.active
    ws0.title = "Resumen"
    hoja_portada(ws0, periodo, conciliados, pendientes, resumen)

    cols1 = ["uuid", "fecha", "rfc_emisor", "nombre_emisor", "origenes", "subtotal", "iva", "total",
             "cargo_agregado", "diferencia", "cuadra_via"]
    ws1 = wb.create_sheet("Conciliados")
    escribe_hoja(ws1, conciliados, cols1, fill_status=GOOD_FILL)

    cols2 = ["uuid", "fecha", "rfc_emisor", "nombre_emisor", "origenes", "subtotal", "iva", "total",
             "cargo_agregado", "diferencia", "motivo_pendiente"]
    ws2 = wb.create_sheet("Pendientes")
    escribe_hoja(ws2, pendientes, cols2, fill_status=WARN_FILL)

    wb.save(salida)
    print(f"\nReporte: {salida}")
    return conciliados, pendientes, resumen


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--periodo", required=True)
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()
    salida = args.salida or f"output/baseline_universal_{args.periodo}.xlsx"
    run(args.periodo, salida)
