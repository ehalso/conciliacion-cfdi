"""Extracción del universo de CFDI EMITIDOS (Trivasa como emisor) desde
Comprobante_Digital, y de los documentos de mpro que los originaron.

Adaptado de la investigación de Claude Code (2026-09-10,
conciliacion-emitidos/) al bridge_client de este repo. Cinco poblaciones
(ver docs/emitidos_retenciones.md, confirmado en vivo contra
mssql_205 el 2026-09-10):

  FACTURA                → venta                    → Factura_Encabezado
  NOTA_CREDITO            → egreso de venta          → Nota_Credito (detalle, agregar por folio)
  COMPROBANTE_PAGO (REP)  → cobranza (sin cabecera)  → Recibo_Pago / Pago_CXC
  CONSTANCIA_RETENCION    → retención (fila principal) → Constancia_Retencion
  GASTO_REGISTRO (RETENCIONES) → retención (a veces fila hermana) → Gasto_Registro_Documento

Universo: Cd_RFC_Emisor = 'TRI970922TL2' AND Cd_RFC_Receptor <> ese (deja
fuera TRASLADO/autoemitido y lo recibido).
"""
from __future__ import annotations

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET

RFC_TRIVASA = "TRI970922TL2"

ORIGENES_EMITIDO = ("FACTURA", "NOTA_CREDITO", "COMPROBANTE_PAGO", "CONSTANCIA_RETENCION", "GASTO_REGISTRO")


def extract_comprobante_digital_emitido(fecha_ini: str, fecha_fin: str) -> pd.DataFrame:
    """Universo de Comprobante_Digital emitido por Trivasa en [fecha_ini, fecha_fin).
    Filtra a los 5 orígenes emitidos (excluye TRASLADO/autoemitido)."""
    origenes_sql = ", ".join(sql_quote(o) for o in ORIGENES_EMITIDO)
    sql = (
        "SELECT Cd_Timbre_UUID AS uuid, Cd_Tabla AS origen, Cd_Documento AS documento, "
        "Cd_Tipo_Comprobante_CFDI AS tipo_cfdi, Cd_Monto AS monto, Es_Cve_Estado AS estado, "
        "Cd_Timbre_Fecha AS fecha_timbre "
        "FROM Comprobante_Digital "
        f"WHERE Cd_RFC_Emisor = {sql_quote(RFC_TRIVASA)} AND Cd_RFC_Receptor <> {sql_quote(RFC_TRIVASA)} "
        f"AND Cd_Tabla IN ({origenes_sql}) "
        f"AND Cd_Timbre_Fecha >= {sql_quote(fecha_ini)} AND Cd_Timbre_Fecha < {sql_quote(fecha_fin)}"
    )
    result = run_query(MPRO_TARGET, sql)
    df = pd.DataFrame(rows_as_dicts(result))
    if df.empty:
        return df
    df["uuid"] = df["uuid"].str.upper()
    return df


def extract_xml_por_uuids(uuids: list[str], batch_size: int = 150) -> pd.DataFrame:
    """Trae Cd_XML para una lista de UUIDs (una fila por UUID — toma la
    primera fila con XML parseable si hay más de una, igual que
    extract_mpro.py del lado recibido)."""
    uuids = sorted({u.upper() for u in uuids if u})
    filas: list[dict] = []
    for i in range(0, len(uuids), batch_size):
        in_list = ", ".join(sql_quote(u) for u in uuids[i : i + batch_size])
        sql = (
            "SELECT Cd_Timbre_UUID AS uuid, Cd_XML AS xml "
            f"FROM Comprobante_Digital WHERE Cd_Timbre_UUID IN ({in_list})"
        )
        result = run_query(MPRO_TARGET, sql)
        filas.extend(rows_as_dicts(result))
    df = pd.DataFrame(filas)
    if df.empty:
        return df
    df["uuid"] = df["uuid"].str.upper()
    # una fila por UUID: prioriza XML no vacío
    df["xml_len"] = df["xml"].fillna("").str.len()
    df = df.sort_values("xml_len", ascending=False).drop_duplicates("uuid").drop(columns="xml_len")
    return df


def extract_factura(folios: list[str]) -> pd.DataFrame:
    folios = sorted({f for f in folios if f})
    if not folios:
        return pd.DataFrame()
    filas: list[dict] = []
    for i in range(0, len(folios), 150):
        in_list = ", ".join(sql_quote(f) for f in folios[i : i + 150])
        sql = (
            "SELECT Fc_Folio AS folio, Fc_Precio_Neto_Importe AS importe, "
            "Fc_Fecha AS fecha, Es_Cve_Estado AS estado "
            f"FROM Factura_Encabezado WHERE Fc_Folio IN ({in_list})"
        )
        filas.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    return pd.DataFrame(filas)


def extract_nota_credito(folios: list[str]) -> pd.DataFrame:
    """Nota_Credito es tabla de DETALLE (varias filas por folio) — se agrega."""
    folios = sorted({f for f in folios if f})
    if not folios:
        return pd.DataFrame()
    filas: list[dict] = []
    for i in range(0, len(folios), 150):
        in_list = ", ".join(sql_quote(f) for f in folios[i : i + 150])
        sql = (
            "SELECT Nc_Folio AS folio, SUM(Nc_Precio_Neto_Importe) AS importe, "
            "MIN(Nc_Fecha) AS fecha, MIN(Es_Cve_Estado) AS estado "
            f"FROM Nota_Credito WHERE Nc_Folio IN ({in_list}) "
            "GROUP BY Nc_Folio"
        )
        filas.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    return pd.DataFrame(filas)


def extract_constancia_retencion(folios: list[str]) -> pd.DataFrame:
    folios = sorted({f for f in folios if f})
    if not folios:
        return pd.DataFrame()
    filas: list[dict] = []
    for i in range(0, len(folios), 150):
        in_list = ", ".join(sql_quote(f) for f in folios[i : i + 150])
        sql = (
            "SELECT Cr_Folio AS folio, Cr_Importe AS importe, "
            "Cr_Fecha AS fecha, Es_Cve_Estado AS estado "
            f"FROM Constancia_Retencion WHERE Cr_Folio IN ({in_list})"
        )
        filas.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    return pd.DataFrame(filas)


def extract_gasto_registro_retenciones(documentos: list[str]) -> pd.DataFrame:
    """documentos = Cd_Documento completo (folio 10 + Grd_ID 4 [+ sufijo]).
    El comparable, según la investigación previa, es Grd_Precio_Descontado_Importe
    (el bruto/subtotal), NO Grd_Precio_Neto_Importe (que ya viene neto de la
    retención)."""
    llaves = sorted({d[:14] for d in documentos if d and len(d) >= 14})
    folios = sorted({k[:10] for k in llaves})
    if not folios:
        return pd.DataFrame()
    filas: list[dict] = []
    for i in range(0, len(folios), 150):
        in_list = ", ".join(sql_quote(f) for f in folios[i : i + 150])
        sql = (
            "SELECT Gr_Folio, Grd_ID, Grd_Precio_Descontado_Importe AS importe_bruto, "
            "Grd_Precio_Neto_Importe AS importe_neto, Grd_Impuesto_Importe AS importe_retenido, "
            "Grd_Referencia AS referencia "
            f"FROM Gasto_Registro_Documento WHERE Gr_Folio IN ({in_list})"
        )
        filas.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    df = pd.DataFrame(filas)
    if df.empty:
        return df
    df["Grd_ID"] = df["Grd_ID"].astype(str).str.zfill(4)
    df["documento"] = df["Gr_Folio"].astype(str) + df["Grd_ID"]
    return df[["documento", "importe_bruto", "importe_neto", "importe_retenido", "referencia"]]


def extract_recibo_pago(folios: list[str]) -> pd.DataFrame:
    folios = sorted({f for f in folios if f})
    if not folios:
        return pd.DataFrame()
    filas: list[dict] = []
    for i in range(0, len(folios), 150):
        in_list = ", ".join(sql_quote(f) for f in folios[i : i + 150])
        sql = (
            "SELECT Rp_Folio AS folio, Rp_Importe AS importe, "
            "Rp_Fecha AS fecha, Es_Cve_Estado AS estado "
            f"FROM Recibo_Pago WHERE Rp_Folio IN ({in_list})"
        )
        filas.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    return pd.DataFrame(filas)
