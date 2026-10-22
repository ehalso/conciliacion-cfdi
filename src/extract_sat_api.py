"""Extracción del lado SAT desde Postgres `raw_sat_api` (descarga masiva por API).

Alimenta el bloque "Base de datos SAT" (columnas BM:BW) del modelo de
conciliación Mpro vs SAT. Mapeo:

  UUID / Serie UUID / Folio UUID -> cfdi.uuid / serie / folio
  Estatus                        -> 'Cancelado' si el UUID está en cancelados
                                    con estatus '0', si no 'Activo'
  Tipo de CFDI                   -> cfdi.tipo_comprobante (I/E/P/T/N traducido)
  Fecha UUID                     -> cfdi.fecha
  Concepto UUID                  -> Descripcion del primer Concepto del XML
  RFC / Nombre del proveedor     -> rfc_emisor / nombre_emisor (recibidos)
  Importe                        -> cfdi.total
  No localizados                 -> no existe en raw_sat_api (lista 69-B); None

`raw_sat_api.cfdi` trae un mismo UUID más de una vez (paquetes repetidos):
se conserva la fila más reciente por `cargado_en`.
"""
from __future__ import annotations

import re

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote

PAGE_SIZE = 2000
TIPOS_VALIDOS = {"recibidos", "emitidos"}
TIPO_CFDI = {"I": "Ingreso", "E": "Egreso", "P": "Pago", "T": "Traslado", "N": "Nómina"}

_CONCEPTO_RE = re.compile(r"<(?:\w+:)?Concepto\b[^>]*?\bDescripcion=\"([^\"]*)\"", re.I)


def _primer_concepto(xml: str | None) -> str:
    m = _CONCEPTO_RE.search(xml or "")
    return m.group(1).strip() if m else ""


def extract_sat_api(tipo: str = "recibidos", periodos: list[str] | None = None,
                    con_concepto: bool = True, uuids: list[str] | None = None,
                    _uuids: list[str] | None = None) -> pd.DataFrame:
    """CFDI de `raw_sat_api.cfdi` para `tipo` ('recibidos'|'emitidos'), opcionalmente
    acotado a periodos 'YYYY-MM' o a una lista de `uuids`. Devuelve las columnas BM:BW de la hoja
    Recibidos. `con_concepto=False` evita traer el XML (mucho más rápido)."""
    if tipo not in TIPOS_VALIDOS:
        raise ValueError(f"tipo debe ser uno de {TIPOS_VALIDOS}, se recibió {tipo!r}")

    filtro = f"c.direccion = {sql_quote(tipo[:-1].upper())}"  # recibidos->RECIBIDO, emitidos->EMITIDO
    if periodos:
        lista = ", ".join(sql_quote(p) for p in periodos)
        filtro += f" AND to_char(c.fecha, 'YYYY-MM') IN ({lista})"
    if uuids is not None:
        lista = sorted({u.strip().upper() for u in uuids if u and re.fullmatch(r"[0-9A-Fa-f-]{36}", u.strip())})
        if not lista:
            return extract_sat_api(tipo, periodos=["0000-00"], con_concepto=con_concepto)
        partes = [extract_sat_api(tipo, con_concepto=con_concepto, _uuids=lista[i:i + 400])
                  for i in range(0, len(lista), 400)]
        return pd.concat(partes, ignore_index=True)
    if _uuids:
        filtro += " AND upper(c.uuid) IN (" + ", ".join(sql_quote(u) for u in _uuids) + ")"
    xml_sql = ", c.xml" if con_concepto else ""
    # recibidos: la contraparte es el emisor; emitidos: el receptor
    prefijo = "emisor" if tipo == "recibidos" else "receptor"

    rows: list[dict] = []
    offset = 0
    while True:
        sql = (
            "SELECT DISTINCT ON (c.uuid) upper(c.uuid) AS uuid, c.serie, c.folio, "
            "c.tipo_comprobante, c.fecha, "
            f"c.rfc_{prefijo} AS rfc, c.nombre_{prefijo} AS nombre, c.total, "
            "(k.uuid IS NOT NULL) AS cancelado" + xml_sql + " "
            "FROM raw_sat_api.cfdi c "
            "LEFT JOIN (SELECT DISTINCT upper(uuid) AS uuid FROM raw_sat_api.cancelados "
            "WHERE estatus = '0') k ON k.uuid = upper(c.uuid) "
            f"WHERE {filtro} "
            f"ORDER BY c.uuid, c.cargado_en DESC LIMIT {PAGE_SIZE} OFFSET {offset}"
        )
        page = rows_as_dicts(run_query("postgres_dw", sql))
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    cols = ["uuid", "serie", "folio", "tipo_comprobante", "fecha", "rfc", "nombre",
            "total", "cancelado"] + (["xml"] if con_concepto else [])
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return pd.DataFrame(columns=[
            "UUID", "Serie UUID", "Folio UUID", "Estatus", "Tipo de CFDI", "Fecha UUID",
            "Concepto UUID", "RFC del proveedor", "Nombre del proveedor", "Importe",
            "No localizados"])

    out = pd.DataFrame({
        "UUID": df["uuid"],
        "Serie UUID": df["serie"].fillna(""),
        "Folio UUID": df["folio"].fillna(""),
        "Estatus": df["cancelado"].map({True: "Cancelado", False: "Activo"}),
        "Tipo de CFDI": df["tipo_comprobante"].map(TIPO_CFDI).fillna(df["tipo_comprobante"]),
        "Fecha UUID": pd.to_datetime(df["fecha"]),
        "Concepto UUID": df["xml"].map(_primer_concepto) if con_concepto else "",
        "RFC del proveedor": df["rfc"].fillna(""),
        "Nombre del proveedor": df["nombre"].fillna(""),
        "Importe": pd.to_numeric(df["total"], errors="coerce").fillna(0),
        "No localizados": None,
    })
    return out
