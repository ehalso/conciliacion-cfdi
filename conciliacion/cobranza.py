"""Cobranza: complementos de pago emitidos (CFDI tipo P) desde Pago_Parcial; solo Mpro (SQL Server).

Un documento por Pp_Folio (folio del COMPROBANTE_PAGO); varias facturas pagadas en el mismo P se resumen en una fila.
El periodo es la fecha del pago en Mpro (Pp_Fecha). El importe del documento es el pagado (en el SAT, pagos_monto_total).
"""
import numpy as np
import pandas as pd
from sqlalchemy.engine import Connection

from . import sql
from .db import consultar, tablas_temporales

TIPO = "Cobranza"
_UNO = ("FACTURA_PAGADA", "UUID_FACTURA_PAGADA", "PARCIALIDAD", "SALDO_ANTERIOR", "SALDO_INSOLUTO")
_SUMA = ("IMPORTE_PAGADO", "SUBTOTAL_NETO", "IMP_0006", "TOTAL_SQL")


def _documentos(cab: pd.DataFrame) -> pd.DataFrame:
    """Una fila por folio: sumas de importes; facturas pagadas distintas → VARIOS (sin saldos)."""
    for c in _SUMA + ("SALDO_ANTERIOR", "SALDO_INSOLUTO"):
        cab[c] = pd.to_numeric(cab[c], errors="coerce").astype(float)
    cab["_n"] = cab.groupby("FOLIO").PP_ID.transform("size")
    multi = cab._n > 1
    cab["PARCIALIDAD"] = pd.to_numeric(cab.PARCIALIDAD, errors="coerce").astype("Int64").astype("string")
    for c in ("FACTURA_PAGADA", "UUID_FACTURA_PAGADA", "PARCIALIDAD"):
        cab[c] = cab[c].astype("string").str.strip()
        cab.loc[multi, c] = "VARIOS"
    cab.loc[multi, ["SALDO_ANTERIOR", "SALDO_INSOLUTO"]] = np.nan
    g = cab.groupby("FOLIO", sort=False)
    suma = g[list(_SUMA)].sum(min_count=1)
    d = g.first().drop(columns=list(_SUMA) + ["PP_ID", "_n"]).join(suma).reset_index()
    return d


TOLERANCIA = 0.05


def _lineas_poliza(pol: pd.DataFrame) -> pd.DataFrame:
    """Líneas de la póliza de cobranza que corresponden a cada cobro.

    Un recibo puede cubrir varios cobros: su cargo a bancos es único (va al primer cobro del recibo) y cada abono a clientes
    se asigna al cobro de importe más cercano (±TOLERANCIA, uno a uno); el abono que no empata va también al primer cobro.
    """
    if pol.empty:
        return pol
    pol = pol.sort_values(["POLIZA", "RECIBO", "PD_ID", "FOLIO"], kind="stable")
    asignadas = []
    for _, g in pol.groupby(["POLIZA", "RECIBO"], sort=False):
        cobros = g.drop_duplicates("FOLIO").set_index("FOLIO").TOTAL_COBRO.astype(float)
        libres = dict(cobros)
        primero = min(libres)
        for _, l in g.drop_duplicates("PD_ID").iterrows():
            folio = primero
            if l.ABONO > 0 and libres:
                mejor = min(libres, key=lambda f: abs(libres[f] - l.ABONO))
                if abs(libres[mejor] - l.ABONO) <= TOLERANCIA:
                    folio = mejor
                    del libres[mejor]
            asignadas.append((l.POLIZA, l.PD_ID, folio))
    a = pd.DataFrame(asignadas, columns=["POLIZA", "PD_ID", "FOLIO"])
    return a.merge(pol.drop(columns="FOLIO").drop_duplicates(["POLIZA", "PD_ID"]), on=["POLIZA", "PD_ID"]).sort_values(["FOLIO", "PD_ID"], kind="stable")


def construir_cobranza(con: Connection, p: dict, clientes: pd.DataFrame) -> pd.DataFrame:
    with tablas_temporales(con, sql.COBRANZA_SETUP, p, "#cob"):
        cab = consultar(con, sql.COBRANZA_CABECERA_SQL, p)
        pol = consultar(con, sql.COBRANZA_POLIZA_SQL, p)
    cab["CLAVE_PROVEEDOR"] = cab.CLAVE_PROVEEDOR.astype(str).str.strip()
    cab["FOLIO_PAGO"] = cab.FOLIO_PAGO.astype("string").str.strip()
    d = _documentos(cab).merge(clientes, on="CLAVE_PROVEEDOR", how="left")
    gravado = d.IMP_0006.fillna(0) > 0
    d["SUBTOTAL_16"] = d.SUBTOTAL_NETO.where(gravado, 0.0)
    d["SUBTOTAL_0"] = d.SUBTOTAL_NETO.where(~gravado, 0.0)
    d["TIPO_COMPROBANTE"] = "Pago"
    d = d.sort_values(["FECHA", "FOLIO"], kind="stable").reset_index(drop=True)
    lineas = _lineas_poliza(pol).drop(columns=["PDOC", "RECIBO", "PD_REF", "TOTAL_COBRO"], errors="ignore")
    lineas["_ord"] = np.arange(len(lineas))
    d = (d.merge(lineas, on="FOLIO", how="left")
          .sort_values(["FECHA", "FOLIO", "_ord"], kind="stable").drop(columns=["_ord", "PD_ID"], errors="ignore").reset_index(drop=True))
    d["Tipo"] = TIPO
    d["ORIGEN"] = None
    return d
