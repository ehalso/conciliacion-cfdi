"""Detalle a nivel LÍNEA de póliza / control de gasto — para la vista de
"detalle" (drill-down) del reporte Streamlit: mostrar, por CFDI, las líneas
reales que suman el cargo ya validado por `baseline_universal.calcular()`.

No reemplaza a `extract_poliza_por_origen.py` / `extract_gasto_registro.py`
(esos siguen siendo la fuente de verdad para la comprobación, ya validados)
— este módulo repite las mismas queries SIN el `GROUP BY`/colapso final, para
poder mostrar la línea individual. Confirmado en vivo (2026-09-09,
`validar_detalle_lineas.py`, feb-2026): sumar estas líneas reproduce
exactamente `cargo_agregado` para las 1,442 CFDI que cuadran por regla 1
("cargo = base CFDI") — 100% de coincidencia.

Alcance actual: solo regla 1 (documento propio de este CFDI, cargo). Las
vías especiales (arrendamiento, folios hermanos, cheque agrupado, etc.)
jalan líneas de documentos que no son de este CFDI — quedan fuera por ahora,
ver docs/pendientes.md.
"""
from __future__ import annotations

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET

BATCH_SIZE = 150

DETALLE_COLS = ["origen", "documento", "Pl_Folio", "tipo", "importe", "cuenta", "cuenta_descripcion",
                "concepto", "centro_costo"]


def extract_lineas_poliza(origen: str, documentos: list[str]) -> pd.DataFrame:
    """Una fila por línea real de `Poliza_Detalle` (cargo y abono) para
    `documentos` de `origen` — mismo filtro (pólizas activas, sin cuentas de
    orden) que `extract_poliza_por_origen`, sin el `SUM`/`GROUP BY`."""
    documentos = sorted(set(documentos))
    out: list[dict] = []
    for i in range(0, len(documentos), BATCH_SIZE):
        chunk = documentos[i:i + BATCH_SIZE]
        in_list = ", ".join(sql_quote(d) for d in chunk)
        sql = (
            "SELECT pc.Pl_Folio, pd.Pd_Referencia AS documento, pd.Pd_Tipo, "
            "pd.Pd_Importe AS importe, pd.Cc_Cve_Cuenta_Contable AS cuenta, "
            "cc.Cc_Descripcion AS cuenta_descripcion, pd.Pd_Concepto AS concepto, "
            "pd.Pd_Centro_Costo AS centro_costo "
            "FROM Poliza_Control pc "
            "JOIN Poliza p ON p.Pl_Folio = pc.Pl_Folio "
            "JOIN Poliza_Detalle pd ON pd.Pl_Folio = pc.Pl_Folio AND pd.Pd_Referencia = pc.Pc_Documento "
            "LEFT JOIN Poliza_Configuracion pcf ON pcf.Pc_Cve_Poliza_Configuracion = p.Pl_Configuracion "
            "LEFT JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable "
            f"WHERE UPPER(pc.Pc_Tabla) = UPPER({sql_quote(origen)}) "
            "AND p.Es_Cve_Estado <> 'CA' "
            "AND (pcf.Pc_Descripcion IS NULL OR UPPER(pcf.Pc_Descripcion) NOT LIKE '%CUENTAS DE ORDEN%') "
            "AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '10[1-6]00%' "
            f"AND pc.Pc_Documento IN ({in_list})"
        )
        out.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))

    df = pd.DataFrame(out, columns=["Pl_Folio", "documento", "Pd_Tipo", "importe", "cuenta",
                                    "cuenta_descripcion", "concepto", "centro_costo"])
    if df.empty:
        return pd.DataFrame(columns=DETALLE_COLS)
    df["importe"] = pd.to_numeric(df["importe"], errors="coerce").fillna(0.0)
    df["tipo"] = df["Pd_Tipo"].map({1: "Cargo", 2: "Abono"}).fillna("?")
    df["origen"] = origen
    return df[DETALLE_COLS]


def extract_lineas_gasto_registro(documentos_completos: list[str]) -> pd.DataFrame:
    """Una fila por renglón de `Gasto_Registro_Control` (`Grc_ID`, el
    prorrateo por centro de costo) para los documentos GASTO_REGISTRO dados
    (`Cd_Documento` completo, folio(10)+Grd_ID(4)) — sin colapsar a
    (folio, Grd_ID) como hace `extract_gasto_registro_granular`."""
    documentos_completos = sorted(set(d for d in documentos_completos if d and len(d) >= 14))
    parsed = {d: (d[:10], d[10:14]) for d in documentos_completos}
    folios = sorted({p[0] for p in parsed.values()})

    out: list[dict] = []
    for i in range(0, len(folios), BATCH_SIZE):
        chunk = folios[i:i + BATCH_SIZE]
        in_list = ", ".join(sql_quote(f) for f in chunk)
        sql = (
            "SELECT Gr_Folio, Grd_ID, Grc_ID, Grc_Importe, Cc_Cve_Centro_Costo "
            f"FROM Gasto_Registro_Control WHERE Gr_Folio IN ({in_list})"
        )
        out.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))

    df = pd.DataFrame(out, columns=["Gr_Folio", "Grd_ID", "Grc_ID", "Grc_Importe", "Cc_Cve_Centro_Costo"])
    if df.empty:
        return pd.DataFrame(columns=DETALLE_COLS)
    df["Grd_ID"] = df["Grd_ID"].astype(str).str.zfill(4)
    df["Grc_Importe"] = pd.to_numeric(df["Grc_Importe"], errors="coerce").fillna(0.0)
    df["_key"] = list(zip(df["Gr_Folio"], df["Grd_ID"]))

    rows = []
    for documento, (folio, grd_id) in parsed.items():
        key = (folio, grd_id.zfill(4))
        for _, r in df[df["_key"] == key].iterrows():
            rows.append({
                "origen": "GASTO_REGISTRO", "documento": documento, "Pl_Folio": None,
                "tipo": "Cargo", "importe": r["Grc_Importe"], "cuenta": None,
                "cuenta_descripcion": None, "concepto": f"Grc_ID {r['Grc_ID']}",
                "centro_costo": r["Cc_Cve_Centro_Costo"],
            })
    return pd.DataFrame(rows, columns=DETALLE_COLS) if rows else pd.DataFrame(columns=DETALLE_COLS)
