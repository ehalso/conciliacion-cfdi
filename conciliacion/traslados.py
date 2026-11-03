"""Traslados: todos los folios de Traslado del periodo (REMISION, TRANSFERENCIA, PEDIDO, ORDEN_COMPRA); solo Mpro (SQL Server).

Una fila por folio (Tr_Folio), con o sin CFDI: la conciliación contra el SAT se hace después. Origen = Tr_Tabla.
"""
import pandas as pd
from sqlalchemy.engine import Connection

from . import sql
from .db import consultar, tablas_temporales

TIPO = "Traslado"
TIPO_COMPROBANTE = "Traslado"
ESTATUS_MPRO = {"AC": "Activo", "CA": "Cancelado", "PXC": "Por cancelar"}
ESTATUS_CCP = {"AC": "Activa", "CA": "Cancelada"}


def construir_traslados(con: Connection, p: dict, clientes: pd.DataFrame) -> pd.DataFrame:
    with tablas_temporales(con, sql.TRASLADO_SETUP, p, "#tr"):
        d = consultar(con, sql.TRASLADO_SQL, p)
    for c in ("CLAVE_PROVEEDOR", "SUCURSAL", "ORIGEN", "ESTATUS_MPRO", "XML_ESTATUS", "CCP_ESTATUS"):
        d[c] = d[c].astype("string").str.strip()
    for c in ("CANTIDAD", "COSTO", "CCP_DISTANCIA", "CCP_PESO_BRUTO", "CCP_PESO_NETO", "CCP_MERCANCIAS"):
        d[c] = pd.to_numeric(d[c], errors="coerce").astype(float)
    d["SUCURSAL"] = (d.SUCURSAL + " " + d.NOMBRE_SUCURSAL.astype("string").str.strip()).str.strip()
    d["REFERENCIA"] = d.REFERENCIA.fillna(d.OE_FOLIO)
    d["ESTATUS_MPRO"] = d.ESTATUS_MPRO.map(ESTATUS_MPRO).fillna(d.ESTATUS_MPRO)
    d["XML_ESTATUS"] = d.XML_ESTATUS.map(ESTATUS_MPRO).fillna(d.XML_ESTATUS)
    d["CCP_ESTATUS"] = d.CCP_ESTATUS.map(ESTATUS_CCP).fillna(d.CCP_ESTATUS)
    d = d.drop(columns=["OE_FOLIO", "NOMBRE_SUCURSAL", "CLAVE_TR"]).merge(clientes, on="CLAVE_PROVEEDOR", how="left")
    d["TIPO_COMPROBANTE"] = d.UUID.notna().map({True: TIPO_COMPROBANTE, False: None})
    d["Tipo"] = TIPO
    return d.sort_values(["FECHA", "FOLIO"], kind="stable").reset_index(drop=True)


def conciliar_estatus(d: pd.DataFrame) -> pd.DataFrame:
    """CONC_ESTATUS: el CFDI de Mpro (Activo/Cancelado) coincide con el del SAT; solo donde el UUID está en ambos."""
    d = d.copy()
    ambos = d.CONC_EXISTE_MPRO.eq("Sí") & d.CONC_EXISTE_SAT.eq("Sí")
    d["CONC_ESTATUS"] = (d.XML_ESTATUS == d.SAT_ESTATUS).map({True: "Sí", False: "No"}).where(ambos, "")
    return d
