"""Extracción del lado MPRO: SQL Server .207 (TRIVASADB), tabla
Comprobante_Digital, vía el bridge.

Comprobante_Digital NO tiene columnas de subtotal/impuestos separadas
(confirmado en vivo, information_schema: solo trae `Cd_Monto`, un importe
único). Sí trae `Cd_XML` (ntext) con el CFDI completo — confirmado con una
fila real. Por eso el importe MPRO se obtiene parseando ese XML con
cfdi_parser, no de una columna.

Un mismo UUID puede aparecer en más de un módulo (`Cd_Tabla`) — se toma el
XML de la primera fila con XML parseable por UUID (debería ser el mismo
documento) y se listan todos los módulos donde aparece.
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET
from cfdi_parser import parse_cfdi

BATCH_SIZE = 200


def _fetch_batch(uuids: list[str]) -> list[dict]:
    in_list = ", ".join(sql_quote(u) for u in uuids)
    sql = (
        "SELECT Cd_Timbre_UUID, Cd_Tabla, Cd_Tipo_Comprobante_CFDI, Cd_Monto, Cd_XML "
        f"FROM Comprobante_Digital WHERE Cd_Timbre_UUID IN ({in_list})"
    )
    result = run_query(MPRO_TARGET, sql)
    return rows_as_dicts(result)


def extract_mpro_por_uuids(uuids: list[str]) -> pd.DataFrame:
    """Busca en Comprobante_Digital los UUIDs dados (en lotes) y devuelve un
    DataFrame de una fila por UUID encontrado, con importes parseados del
    XML: subtotal, iva (neto trasladados-retenidos), total, más
    modulos_mpro (lista de Cd_Tabla donde aparece) y n_modulos.
    """
    by_uuid: dict[str, list[dict]] = defaultdict(list)
    uuids = [u.upper() for u in uuids]
    for i in range(0, len(uuids), BATCH_SIZE):
        batch = uuids[i : i + BATCH_SIZE]
        for row in _fetch_batch(batch):
            u = (row.get("Cd_Timbre_UUID") or "").upper()
            if u:
                by_uuid[u].append(row)

    out_rows = []
    for uuid, matches in by_uuid.items():
        modulos = sorted({m.get("Cd_Tabla") for m in matches if m.get("Cd_Tabla")})
        parsed = None
        parse_error = None
        for m in matches:
            xml = m.get("Cd_XML")
            if not xml:
                continue
            try:
                parsed = parse_cfdi(xml)
                break
            except Exception as exc:  # noqa: BLE001 - registramos y seguimos
                parse_error = str(exc)

        row = {
            "uuid": uuid,
            "n_modulos": len(modulos),
            "modulos_mpro": ", ".join(modulos),
            "cd_monto_primero": matches[0].get("Cd_Monto"),
        }
        if parsed is not None:
            row["subtotal"] = float(parsed.subtotal)
            # Validado empíricamente (2026-09-07, periodo 2026-08): el `iva`
            # de raw_sat.cfdi_recibidos es TotalImpuestosTrasladados tal
            # cual, SIN restar TotalImpuestosRetenidos. Los casos con
            # retención (ISR/IVA retenido en servicios) tenían diff == el
            # importe retenido exacto cuando se probó neto — confirma que
            # el loader SAT no lo netea.
            row["iva"] = float(parsed.total_impuestos_trasladados)
            row["retenciones_mpro"] = float(parsed.total_impuestos_retenidos)
            row["total"] = float(parsed.total)
            row["fecha"] = parsed.fecha
            row["xml_parseado"] = True
        else:
            row["subtotal"] = None
            row["iva"] = None
            row["total"] = None
            row["fecha"] = None
            row["xml_parseado"] = False
            row["xml_parse_error"] = parse_error or "sin Cd_XML en ninguna fila"

        out_rows.append(row)

    return pd.DataFrame(out_rows)
