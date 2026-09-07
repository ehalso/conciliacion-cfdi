"""Parseo de CFDI (3.3 y 4.0) para extraer los importes que se concilian.

Soporta el XML como str, bytes, o ya decodificado. Es tolerante a namespaces
distintos (cfdi 3.3 usa el mismo prefijo 'cfdi' que 4.0 pero con distinto
namespace URI) y al TimbreFiscalDigital para obtener el UUID.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from lxml import etree

NS_CFDI_40 = "http://www.sat.gob.mx/cfd/4"
NS_CFDI_33 = "http://www.sat.gob.mx/cfd/3"
NS_TFD_11 = "http://www.sat.gob.mx/TimbreFiscalDigital"


@dataclass
class CfdiAmounts:
    uuid: str
    version: str
    fecha: Optional[str]
    rfc_emisor: Optional[str]
    rfc_receptor: Optional[str]
    tipo_comprobante: Optional[str]
    subtotal: Decimal
    descuento: Decimal
    total_impuestos_trasladados: Decimal
    total_impuestos_retenidos: Decimal
    total: Decimal


def _dec(value: Optional[str]) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(value)
    except InvalidOperation:
        return Decimal("0")


def parse_cfdi(xml_data) -> CfdiAmounts:
    """Parsea un CFDI y devuelve los importes relevantes para conciliación.

    Lanza ValueError si no se encuentra el nodo Comprobante o el UUID
    (TimbreFiscalDigital), ya que sin UUID no hay forma de cruzar registros.
    """
    if isinstance(xml_data, str):
        xml_data = xml_data.encode("utf-8")

    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(xml_data, parser=parser)
    if root is None:
        raise ValueError("XML vacío o no parseable")

    ns_uri = root.tag.split("}")[0].strip("{") if "}" in root.tag else None
    ns = {"cfdi": ns_uri or NS_CFDI_40, "tfd": NS_TFD_11}

    comprobante = root if root.tag.endswith("Comprobante") else root.find(".//cfdi:Comprobante", ns)
    if comprobante is None:
        comprobante = root  # el root ya es el Comprobante en la mayoría de los casos

    attrib = comprobante.attrib if comprobante.tag.endswith("Comprobante") else root.attrib

    emisor = root.find(".//cfdi:Emisor", ns)
    receptor = root.find(".//cfdi:Receptor", ns)
    # OJO: hay un cfdi:Impuestos por cada Concepto (sin totales) además del
    # de nivel Comprobante (el que trae TotalImpuestosTrasladados/
    # TotalImpuestosRetenidos). Buscar solo como hijo directo del
    # Comprobante, nunca con ".//" (recursivo agarraría el primero de un
    # Concepto, que siempre da 0).
    impuestos = comprobante.find("cfdi:Impuestos", ns)
    timbre = root.find(".//tfd:TimbreFiscalDigital", ns)

    if timbre is None:
        # buscar sin importar el namespace exacto del complemento
        for el in root.iter():
            if etree.QName(el).localname == "TimbreFiscalDigital":
                timbre = el
                break

    uuid = timbre.attrib.get("UUID") if timbre is not None else None
    if not uuid:
        raise ValueError("No se encontró UUID (TimbreFiscalDigital) en el CFDI")

    total_trasladados = Decimal("0")
    total_retenidos = Decimal("0")
    if impuestos is not None:
        total_trasladados = _dec(impuestos.attrib.get("TotalImpuestosTrasladados"))
        total_retenidos = _dec(impuestos.attrib.get("TotalImpuestosRetenidos"))

    return CfdiAmounts(
        uuid=uuid.upper(),
        version=attrib.get("Version") or attrib.get("version") or "",
        fecha=attrib.get("Fecha"),
        rfc_emisor=(emisor.attrib.get("Rfc") if emisor is not None else None),
        rfc_receptor=(receptor.attrib.get("Rfc") if receptor is not None else None),
        tipo_comprobante=attrib.get("TipoDeComprobante"),
        subtotal=_dec(attrib.get("SubTotal")),
        descuento=_dec(attrib.get("Descuento")),
        total_impuestos_trasladados=total_trasladados,
        total_impuestos_retenidos=total_retenidos,
        total=_dec(attrib.get("Total")),
    )
