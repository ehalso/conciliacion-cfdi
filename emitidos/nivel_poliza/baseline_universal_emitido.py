#!/usr/bin/env python3
"""Baseline UNIVERSAL de conciliación CFDI EMITIDOS ↔ mpro — primera pasada
(2026-09-10), calcada de `baseline_universal.py` (recibidos) pero mucho más
simple porque el universo real de emitidos, a diferencia de recibidos, no
trae GASTO_REGISTRO/CHEQUE/arrendamiento: el censo confirmado en
`docs/pendientes.md` (enero 2026) es solo

    FACTURA (venta con valor), NOTA_CREDITO (venta, devolución/bonificación),
    COMPROBANTE_PAGO y TRASLADO (complementos SAT sin valor propio — mismo
    patrón ya conocido del lado recibidos, se excluyen del cuadre).

Hallazgo de esta sesión (2026-09-10), vía exploración directa a `mssql_205`
(no documentado antes en `trivasa-context` ni en este repo) — INCLUYE UNA
CORRECCIÓN a media sesión, dejada explícita porque casi se documenta mal:

1. **`Comprobante_Digital.Cd_Tabla = 'FACTURA'` NO tiene módulo homónimo en
   `Poliza_Control`** — ahí no existe `Pc_Tabla = 'FACTURA'`; se contabiliza
   bajo `Pc_Tabla = 'VENTA'`. `Cd_Tabla = 'NOTA_CREDITO'` sí es homónimo
   directo (`Pc_Tabla = 'NOTA_CREDITO'` = `Nc_Folio`, confirmado con fecha —
   sin problema, ver punto 3).
2. **CORRECCIÓN — `Pc_Documento` de VENTA NO es `Fc_Folio` directamente.**
   El primer intento de esta sesión probó `Poliza_Control WHERE Pc_Documento
   = '<Fc_Folio>'` y SÍ devolvió filas con `Pc_Tabla='VENTA'` — parecía
   confirmado. Es un **falso positivo por reciclaje de folio**: la serie
   `XX-NNNNNNN` de `Venta_Encabezado.Vn_Folio` es independiente de la de
   `Factura_Encabezado.Fc_Folio` y ambas reciclan el mismo rango de números
   en años distintos. Se detectó cruzando `Poliza.Pl_Fecha` contra `Factura_
   Encabezado.Fc_Fecha`: para una muestra de 8 FACTURA de enero 2026, TODOS
   los matches por texto traían pólizas de 2018 a 2025, sin relación con la
   fecha real. La cadena correcta, verificada con fecha, es `Fc_Folio` ->
   `Venta_Encabezado.Fc_Folio` -> `Vn_Folio` (puede haber varios por
   factura — hasta 382 en enero 2026, el caso "una factura consolida muchas
   ventas/tickets") -> `Vn_Folio` = `Poliza_Control.Pc_Documento`, exigiendo
   además `Poliza.Pl_Fecha` cerca de `Vn_Fecha` (mismo reciclaje aplica un
   nivel más abajo). Implementado en `extract_poliza_factura()` — ver ese
   docstring para el detalle completo y por qué la cobertura sigue siendo
   muy baja incluso con la cadena correcta.
3. **VENTA postea DOS pólizas separadas por documento**, cada una con su
   propia `Poliza_Configuracion.Pc_Descripcion` (censo real, enero 2026):
   - `VENTAS 2019 EN ADELANTE` — la de ingreso: Cargo a Clientes (cuenta
     `1120.xxx`) = TOTAL del CFDI (con IVA); Abono a Ventas (`4100.xxx`,
     ≈ subtotal) + IVA Trasladado (`2160.xxx`, ≈ iva).
   - `COSTO DE VENTA 2018 EN ADELANTE` — la de costo: Cargo a Costo de Venta
     (`5100.xxx`) = Abono a Inventario (`1140.xxx`) — el costo del producto
     vendido, NO relacionado con el importe fiscal del CFDI.
   **Hallazgo adicional (grave para el método)**: de las dos, la que SÍ aísla
   el documento por `Pd_Referencia` de forma consistente es la de COSTO DE
   VENTA — la de INGRESO (la que sí importa para conciliar contra el CFDI)
   casi nunca trae `Pd_Referencia` al documento individual; aparenta
   postearse consolidada por sucursal/día. Por eso `extract_poliza_factura()`
   EXCLUYE la póliza de costo de venta (para no confundir "encontré algo" con
   "encontré el ingreso") pero el resultado es que casi no queda nada que
   aislar — cobertura real ~1%. Ver docstring de esa función y
   `docs/pendientes.md` para el detalle y las hipótesis sin confirmar.

4. **NOTA_CREDITO tiene el mismo problema que el punto 3 (dos pólizas
   mezcladas bajo el mismo `Pd_Referencia`), y la misma solución: separar por
   cuenta contable.** El primer intento (sumar TODO el Cargo, como hace
   `extract_poliza_por_origen` genérico) daba solo 33.5% porque, para las
   variantes con devolución física de mercancía (`DEVOL C/REF`, `DEVOL
   S/REF`), la MISMA póliza/`Pd_Referencia` trae Cargo a `4200.xxx`
   (Devoluciones sobre Ventas, = SUBTOTAL del CFDI — el número correcto) MÁS
   un segundo Cargo a `2140.xxx` que empareja exacto con un Abono a
   `5100.xxx` (reversión de costo de venta por la mercancía devuelta, sin
   relación con el importe fiscal — verificado: 102 folios `DEVOL C/REF` de
   enero 2026, `SUM(Cargo 2140) = SUM(Abono 5100)` exacto, $1,296,132.74).
   Sumar ambos Cargos infla el número sin sentido. La cuarta variante,
   `DIRECTA` (ajuste de precio sin devolución física), no tiene este
   problema: Cargo `2140.xxx` (=subtotal) + Cargo `2160.xxx` (=iva) = Abono
   `2140.xxx` (sub-cuenta distinta) = TOTAL, verificado exacto en 5/5 casos
   reales. Implementado en `extract_poliza_nota_credito()` — separa
   `cargo_4200` (compara vs SUBTOTAL) de `cargo_resto` (compara vs TOTAL).
   **Resultado: NOTA_CREDITO subió de 33.5% a 99.5% (187/188, un solo
   pendiente residual: una `BONIFICACION` con la línea de devolución
   capturada por error en la cuenta `8200` en vez de `4200` — ruido de
   captura real, no un patrón, no vale la pena modelarlo para n=1).**

Método de comparación: a diferencia de recibidos (cargo = SUBTOTAL neto),
aquí se compara contra el **TOTAL** del CFDI (o el SUBTOTAL, según la vía —
ver punto 4), sin ajuste de XML (Descuento/IEPS/locales) — porque los campos
`subtotal`/`total` de `raw_sat.cfdi_emitidos` YA son los importes finales del
XML, netos de cualquier descuento; el problema de "raw_sat guarda el bruto"
que sí afecta a `subtotal` en recibidos no aplica aquí.

    FACTURA (→ VENTA, vía Vn_Folio):  cargo Clientes (sin costo de venta) vs Total
                                       — cobertura ~1%, ver punto 3 arriba.
    NOTA_CREDITO devolución (4200):   cargo 4200 vs Subtotal — 99.5% de cobertura.
    NOTA_CREDITO directa (resto):     cargo/abono resto vs Total — cubierto en el mismo 99.5%.

ESTADO REAL: NOTA_CREDITO ya es un resultado confiable y reportable (99.5%).
FACTURA (el 92% del universo monetario, ver censo en docs/pendientes.md)
sigue sin método nivel 3 funcional — la vía de ingreso de VENTA no se aísla
por documento con las columnas conocidas hoy. Ver docs/pendientes.md para el
detalle completo y las hipótesis para la siguiente sesión (candidata más
fuerte: preguntar directo a alguien de Trivasa cómo se referencia el
documento en la póliza de ingreso, en vez de seguir explorando a ciegas).

Uso:
    python3 baseline_universal_emitido.py --periodo 2026-01
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

from extract_sat import extract_sat_emitidos  # noqa: E402
from extract_origen import extract_origenes_por_uuids  # noqa: E402
from extract_poliza_por_origen import extract_poliza_factura, extract_poliza_nota_credito  # noqa: E402
from extract_moneda import extract_moneda_documento  # noqa: E402

TOL = 1.00
TOL_RELATIVA = 0.00005
SUBTOTAL_MIN = 1.00

# Complementos SAT sin valor propio (Carta Porte / REP) — mismo patrón que
# recibidos, se excluyen de la búsqueda de cargo.
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
    "rfc_receptor": ("RFC Receptor", 14),
    "origenes": ("Orígen(es) en mpro", 22),
    "subtotal": ("Subtotal CFDI", 14),
    "iva": ("IVA CFDI", 12),
    "total": ("Total CFDI", 14),
    "monto_agregado": ("Monto reconocido (Clientes/NC)", 20),
    "diferencia": ("Diferencia vs Total", 16),
    "cuadra_via": ("Vía de cuadre", 24),
    "motivo_pendiente": ("Motivo pendiente", 20),
}


def calcular(periodo: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    print(f"[1/4] SAT emitidos {periodo}")
    sat = extract_sat_emitidos(periodo=periodo)
    print(f"     {len(sat)} CFDI emitidos")

    print("[2/4] Orígenes en Comprobante_Digital")
    origenes = extract_origenes_por_uuids(sat["uuid"].tolist())
    origenes = origenes.dropna(subset=["documento"]).copy()
    origenes["origen_up"] = origenes["origen"].str.upper()
    # A diferencia de recibidos, Cd_Documento para FACTURA/NOTA_CREDITO viene
    # siempre en 10 caracteres exactos (verificado en vivo, enero 2026) — no
    # hace falta truncar ni distinguir un formato granular.
    origenes = origenes.drop_duplicates(subset=["uuid", "origen_up", "documento"])
    print(f"     {origenes['uuid'].nunique()} CFDI con al menos 1 etiqueta en mpro"
          f" ({len(origenes)} etiquetas documento)")

    print("[3/4] Cargo/abono por documento (FACTURA vía Venta_Encabezado->VENTA, NOTA_CREDITO por cuenta 4200 vs resto)")
    # Dos "cubetas" de importe reconocido, cada una contra su propia base
    # fiscal (ver extract_poliza_nota_credito() para el porqué de la
    # separación por cuenta contable):
    #   monto_subtotal: NOTA_CREDITO con devolución física (Cargo 4200,
    #                   "Devoluciones sobre Ventas") -> compara vs SUBTOTAL.
    #   monto_total:    FACTURA (Cargo Clientes) + NOTA_CREDITO directa
    #                   (Cargo resto, sin devolución) -> compara vs TOTAL.
    monto_subtotal_parts = []
    monto_total_parts = []
    tc_parts = []
    for origen in sorted(origenes["origen"].unique()):
        if origen.upper() in ORIGEN_SIN_VALOR:
            continue
        docs = origenes.loc[origenes["origen"] == origen, "documento"].dropna().unique().tolist()
        if not docs:
            continue
        mapa_doc = origenes.loc[origenes["origen"] == origen, ["uuid", "documento"]]
        if origen.upper() == "FACTURA":
            # Pc_Documento NO es Fc_Folio directamente (ver docstring del
            # módulo, punto 2 — falso positivo por reciclaje de folio). Usa
            # la cadena correcta vía Venta_Encabezado, con filtro de fecha.
            pol = extract_poliza_factura(docs)
            if not pol.empty:
                monto_total_parts.append(mapa_doc.merge(pol[["documento", "cargo"]], on="documento", how="inner")
                                          .rename(columns={"cargo": "monto"})[["uuid", "monto"]])
                print(f"     {origen}: {len(docs)} documentos -> {len(pol)} con cargo en póliza")
        elif origen.upper() == "NOTA_CREDITO":
            # Pc_Documento = Nc_Folio sí es directo y confiable (sin
            # reciclaje de folio, verificado con fecha).
            pol = extract_poliza_nota_credito(docs)
            if not pol.empty:
                m = mapa_doc.merge(pol, on="documento", how="inner")
                # Devolución física (4200, = subtotal) tiene prioridad; si no
                # hay, cae a "resto" (DIRECTA, = total); si tampoco, al abono
                # (red de seguridad, no confirmado que se use en la práctica).
                usa_4200 = m["cargo_4200"].abs() > TOL
                m["monto_resto"] = m["cargo_resto"].where(m["cargo_resto"].abs() > TOL, m["abono"])
                monto_subtotal_parts.append(m.loc[usa_4200, ["uuid"]].assign(monto=m.loc[usa_4200, "cargo_4200"]))
                monto_total_parts.append(m.loc[~usa_4200, ["uuid"]].assign(monto=m.loc[~usa_4200, "monto_resto"]))
                print(f"     {origen}: {len(docs)} documentos -> {len(pol)} con cargo/abono en póliza"
                      f" ({int(usa_4200.sum())} devolución/4200, {int((~usa_4200).sum())} directa/resto)")
        tc = extract_moneda_documento(origen, docs)
        if not tc.empty:
            tc_parts.append(tc)

    monto_subtotal = (pd.concat(monto_subtotal_parts, ignore_index=True).groupby("uuid")["monto"].sum()
                       .rename("monto_subtotal") if monto_subtotal_parts else pd.Series(dtype=float, name="monto_subtotal"))
    monto_total = (pd.concat(monto_total_parts, ignore_index=True).groupby("uuid")["monto"].sum()
                    .rename("monto_total") if monto_total_parts else pd.Series(dtype=float, name="monto_total"))

    tc_df = pd.concat(tc_parts, ignore_index=True) if tc_parts else pd.DataFrame(
        columns=["documento", "moneda", "tipo_cambio"])
    if not tc_df.empty:
        tc_map = origenes.merge(tc_df, on="documento", how="left")
        tc_uuid = tc_map.groupby("uuid").agg(
            tipo_cambio=("tipo_cambio", "max")).reset_index()
    else:
        tc_uuid = pd.DataFrame(columns=["uuid", "tipo_cambio"])

    print("[4/4] Armando resultado")
    origenes_str = origenes.groupby("uuid")["origen"].apply(lambda s: ", ".join(sorted(set(s)))).rename("origenes")

    resumen = (sat.set_index("uuid").join(monto_subtotal, how="left").join(monto_total, how="left")
               .join(origenes_str, how="left").reset_index())
    resumen = resumen.merge(tc_uuid, on="uuid", how="left")
    resumen["monto_subtotal"] = resumen["monto_subtotal"].fillna(0.0)
    resumen["monto_total"] = resumen["monto_total"].fillna(0.0)
    resumen["monto_agregado"] = resumen["monto_subtotal"] + resumen["monto_total"]
    resumen["tipo_cambio"] = pd.to_numeric(resumen.get("tipo_cambio"), errors="coerce").fillna(1.0)
    resumen.loc[resumen["tipo_cambio"] <= 0, "tipo_cambio"] = 1.0
    resumen["subtotal_mxn"] = resumen["subtotal"] * resumen["tipo_cambio"]
    resumen["total_mxn"] = resumen["total"] * resumen["tipo_cambio"]
    resumen["en_mpro"] = resumen["uuid"].isin(set(origenes["uuid"]))
    resumen["monetario"] = resumen["subtotal"].abs() > SUBTOTAL_MIN

    resumen["tolerancia"] = pd.concat([
        pd.Series(TOL, index=resumen.index),
        resumen["total_mxn"].abs() * TOL_RELATIVA], axis=1).max(axis=1)
    tol = resumen["tolerancia"]

    # --- Regla A: NOTA_CREDITO con devolución física (Cargo 4200) vs SUBTOTAL.
    resumen["cuadra_devolucion"] = (resumen["monto_subtotal"].abs() > TOL) & (
        (resumen["monto_subtotal"] - resumen["subtotal_mxn"]).abs() <= tol)
    # --- Regla B: FACTURA (Cargo Clientes) o NOTA_CREDITO directa (Cargo
    # resto/Abono) vs TOTAL.
    resumen["cuadra_total"] = (~resumen["cuadra_devolucion"]) & (
        (resumen["monto_total"] - resumen["total_mxn"]).abs() <= tol)
    resumen["cuadra_agregado"] = resumen["cuadra_devolucion"] | resumen["cuadra_total"]
    # Diferencia informativa: contra la base que aplicó (subtotal si cuadró
    # por devolución, si no total) — o contra total por default si no cuadró.
    resumen["diferencia"] = (resumen["monto_agregado"] - resumen[
        "subtotal_mxn"].where(resumen["cuadra_devolucion"], resumen["total_mxn"])).round(2)

    def via(row):
        if row["cuadra_devolucion"]:
            return "NC devolución (4200) = subtotal"
        if row["cuadra_total"]:
            if "NOTA_CREDITO" in str(row["origenes"]):
                return "NC directa (2140+2160) = total"
            return "cargo Clientes = total"
        return ""

    def motivo(row):
        if row["cuadra_agregado"]:
            return "OK"
        if not row["en_mpro"]:
            return "no encontrado en mpro"
        return "monto reconocido ≠ subtotal/total"

    resumen["cuadra_via"] = resumen.apply(via, axis=1)
    resumen["motivo_pendiente"] = resumen.apply(motivo, axis=1)

    universo = resumen[resumen["monetario"] & resumen["en_mpro"]].copy()
    cols_base = ["uuid", "fecha", "rfc_receptor", "origenes", "subtotal", "iva", "total",
                 "monto_agregado", "diferencia"]
    conciliados = universo[universo["cuadra_agregado"]][cols_base + ["cuadra_via"]].copy()
    pendientes = universo[~universo["cuadra_agregado"]][cols_base + ["motivo_pendiente"]].copy()

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

    money_cols = {"subtotal", "iva", "total", "monto_agregado", "diferencia"}
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
    ws.column_dimensions["A"].width = 100
    ws["A1"] = "Conciliación CFDI ↔ mpro — Baseline UNIVERSAL EMITIDOS"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Periodo: {periodo}   ·   Generado: {datetime.now().strftime('%Y-%m-%d')}"
    ws["A2"].font = SUB_FONT

    total_universo = len(conciliados) + len(pendientes)
    n_total_cfdi = len(resumen)
    n_en_mpro = int(resumen["en_mpro"].sum())
    n_sin_valor = int((resumen["en_mpro"] & ~resumen["monetario"]).sum())

    filas = [
        "",
        "MÉTODO (2026-09-10 — ver docstring de baseline_universal_emitido.py para el detalle completo)",
        "FACTURA (Cd_Tabla) NO tiene módulo homónimo en Poliza_Control: se contabiliza bajo Pc_Tabla='VENTA',",
        "vía Venta_Encabezado (Fc_Folio -> Vn_Folio, con filtro de fecha para evitar reciclaje de folio).",
        "NOTA_CREDITO es homónimo directo (Pc_Documento=Nc_Folio) y confiable. Ambos orígenes postean, por",
        "documento, DOS movimientos contables en cuentas distintas dentro de la misma póliza — hay que",
        "separarlos por cuenta contable, no sumarlos:",
        "",
        "  FACTURA (-> VENTA):            Cargo a Clientes (excluye la póliza de Costo de Venta) vs Total.",
        "                                 Cobertura ~1% — la póliza de ingreso casi nunca aísla el documento",
        "                                 por Pd_Referencia (ver PENDIENTE abajo).",
        "  NOTA_CREDITO con devolución:   Cargo a cuenta 4200 (Devoluciones sobre Ventas) vs Subtotal —",
        "                                 excluye el Cargo/Abono de reversión de costo de venta (cuentas",
        "                                 2140/5100 emparejadas, sin relación con el importe fiscal).",
        "  NOTA_CREDITO directa:          Cargo resto (cuentas 2140+2160) o Abono vs Total.",
        "                                 Cobertura NOTA_CREDITO: 99.5% (187/188).",
        "",
        "PENDIENTE EXPLÍCITO (FACTURA): no se investigó por qué la póliza de ingreso de VENTA no aísla el",
        "documento por Pd_Referencia (hipótesis sin confirmar: se postea consolidada por sucursal/día).",
        "Ver docs/pendientes.md y docs/hallazgos.md punto 28 para el detalle completo.",
        "",
        "UNIVERSO",
        f"  • {n_total_cfdi} CFDI emitidos en el periodo.",
        f"  • {n_en_mpro} encontrados en mpro (al menos 1 etiqueta en Comprobante_Digital).",
        f"  • {n_sin_valor} de esos son complementos sin valor monetario (Subtotal ≤ $1) — se excluyen.",
        f"  • {total_universo} CFDI con valor monetario real, encontrados en mpro — universo comparado.",
        "",
        "RESULTADO",
        f"  • Conciliados: {len(conciliados)} CFDI  ({len(conciliados)/total_universo*100:.1f}%)" if total_universo else "  • Sin datos",
        f"  • Pendientes: {len(pendientes)} CFDI  ({len(pendientes)/total_universo*100:.1f}%)" if total_universo else "",
    ]
    for i, texto in enumerate(filas, start=3):
        cell = ws.cell(row=i, column=1, value=texto)
        cell.font = Font(name=FONT, size=10, bold=(texto in ("MÉTODO (primera pasada, 2026-09-10 — ver docstring de baseline_universal_emitido.py)", "UNIVERSO", "RESULTADO")))
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

    cols1 = ["uuid", "fecha", "rfc_receptor", "origenes", "subtotal", "iva", "total",
             "monto_agregado", "diferencia", "cuadra_via"]
    ws1 = wb.create_sheet("Conciliados")
    escribe_hoja(ws1, conciliados, cols1, fill_status=GOOD_FILL)

    cols2 = ["uuid", "fecha", "rfc_receptor", "origenes", "subtotal", "iva", "total",
             "monto_agregado", "diferencia", "motivo_pendiente"]
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
    salida = args.salida or f"output/baseline_universal_emitido_{args.periodo}.xlsx"
    run(args.periodo, salida)
