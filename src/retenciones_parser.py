"""Parseo del CFDI de retenciones (esquema `retenciones:Retenciones` v2.0),
distinto de `cfdi:Comprobante`.

Aparece en dos módulos de mpro (`Comprobante_Digital.Cd_Tabla`):
CONSTANCIA_RETENCION (con Cd_Monto = MontoTotOperacion, la fila "principal")
y GASTO_REGISTRO con Cd_Tipo_CFDI='RETENCIONES' (Cd_Monto=0, fila "hermana"
para los de dividendos; única fila para los de intereses).

Basado en la documentación de la sesión de Claude Code 2026-09-10
(conciliacion-emitidos/docs/esquema-datos.md §4): el importe conciliable es
Totales/@MontoTotOperacion (la base bruta de la operación), no el neto — ver
docs/emitidos_retenciones.md para el porqué (comparable contra el subtotal
del documento de gasto, no contra el neto ya retenido).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from lxml import etree

NS_RET_2 = "http://www.sat.gob.mx/esquemas/retencionpago/2"


@dataclass
class RetencionAmounts:
    uuid: str
    version: str
    fecha_timbrado: Optional[str]
    rfc_emisor: Optional[str]
    rfc_receptor: Optional[str]
    cve_retenc: Optional[str]
    monto_operacion: Decimal
    monto_total_retenido: Decimal
    periodo_mes_ini: Optional[str]
    periodo_mes_fin: Optional[str]
    periodo_ejercicio: Optional[str]


def _dec(value: Optional[str]) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(value)
    except InvalidOperation:
        return Decimal("0")


def es_retenciones(xml_data) -> bool:
    """True si la raíz del XML es retenciones:Retenciones (vs cfdi:Comprobante).
    Decide por la raíz, no por Cd_Tipo_CFDI (que viene vacío en
    CONSTANCIA_RETENCION) — mismo criterio que la doc de referencia."""
    if isinstance(xml_data, str):
        xml_data = xml_data.encode("utf-8")
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(xml_data, parser=parser)
    if root is None:
        return False
    return etree.QName(root).localname == "Retenciones"


def parse_retencion(xml_data) -> RetencionAmounts:
    """Parsea un CFDI de retenciones y devuelve los importes relevantes."""
    if isinstance(xml_data, str):
        xml_data = xml_data.encode("utf-8")

    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(xml_data, parser=parser)
    if root is None:
        raise ValueError("XML vacío o no parseable")

    ns_uri = root.tag.split("}")[0].strip("{") if "}" in root.tag else NS_RET_2
    ns = {"ret": ns_uri}

    emisor = root.find(".//ret:Emisor", ns)
    receptor_nacional = root.find(".//ret:Receptor/ret:Nacional", ns)
    periodo = root.find(".//ret:Periodo", ns)
    totales = root.find(".//ret:Totales", ns)

    uuid = None
    for el in root.iter():
        if etree.QName(el).localname == "TimbreFiscalDigital":
            uuid = el.attrib.get("UUID")
            break
    if not uuid:
        raise ValueError("No se encontró UUID (TimbreFiscalDigital) en el CFDI de retenciones")

    monto_operacion = Decimal("0")
    monto_ret = Decimal("0")
    if totales is not None:
        monto_operacion = _dec(totales.attrib.get("MontoTotOperacion"))
        monto_ret = _dec(totales.attrib.get("MontoTotRet"))

    return RetencionAmounts(
        uuid=uuid.upper(),
        version=root.attrib.get("Version") or "",
        fecha_timbrado=root.attrib.get("FechaExp"),
        rfc_emisor=(emisor.attrib.get("RfcE") if emisor is not None else None),
        rfc_receptor=(receptor_nacional.attrib.get("RfcR") if receptor_nacional is not None else None),
        cve_retenc=root.attrib.get("CveRetenc"),
        monto_operacion=monto_operacion,
        monto_total_retenido=monto_ret,
        periodo_mes_ini=(periodo.attrib.get("MesIni") if periodo is not None else None),
        periodo_mes_fin=(periodo.attrib.get("MesFin") if periodo is not None else None),
        periodo_ejercicio=(periodo.attrib.get("Ejercicio") if periodo is not None else None),
    )
