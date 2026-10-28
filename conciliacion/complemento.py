"""Complemento de pago (CFDI tipo P) de cada documento, por UUID de la factura.

Los complementos recibidos se adjuntan al cheque (`Comprobante_Digital`, Cd_Tabla='CHEQUE', Cd_Tipo_CFDI='P'); la tabla
ZTRV_Comprobante_Digital_Pago detalla, por complemento, cada factura que cubre (DoctoRelacionado del XML).
"""
import pandas as pd
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

from .atribucion import VARIOS

LOTE = 1000
SQL = """
SELECT UPPER(z.Cdp_IdDocumento) AS FACTURA, UPPER(cd.Cd_Timbre_UUID) AS COMPLEMENTO, cd.Cd_Timbre_Fecha AS FECHA
FROM ZTRV_Comprobante_Digital_Pago z
JOIN Comprobante_Digital cd ON cd.Cd_Timbre_UUID=z.Cdp_Uuid_Pago AND cd.Cd_Tabla='CHEQUE'
     AND cd.Cd_Tipo_CFDI='P' AND cd.Es_Cve_Estado='AC'
WHERE z.Cdp_IdDocumento IN :uuids
"""


def consultar(engine: Engine, uuids: list[str]) -> pd.DataFrame:
    partes = []
    with engine.connect() as con:
        for i in range(0, len(uuids), LOTE):
            partes.append(pd.read_sql(text(SQL).bindparams(bindparam("uuids", expanding=True)), con,
                                      params={"uuids": uuids[i:i + LOTE]}))
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=["FACTURA", "COMPLEMENTO", "FECHA"])


def resumir(c: pd.DataFrame) -> pd.DataFrame:
    """Un renglón por factura: su complemento, o VARIOS (sin fecha) si la cubren dos o más."""
    c = c.drop_duplicates(["FACTURA", "COMPLEMENTO"])
    g = c.groupby("FACTURA")
    n = g.COMPLEMENTO.transform("nunique")
    c = c.assign(COMPLEMENTO=lambda x: x.COMPLEMENTO.where(n < 2, VARIOS), FECHA=lambda x: x.FECHA.where(n < 2))
    return c.drop_duplicates("FACTURA").set_index("FACTURA")


def agregar_complemento(d: pd.DataFrame, engine: Engine) -> pd.DataFrame:
    """Reemplaza COMPLEMENTO_PAGO y FECHA_COMPLEMENTO_PAGO por el complemento tipo P real de cada UUID."""
    d = d.copy()
    uuid = d.UUID.astype("string").str.strip().str.upper() if "UUID" in d else pd.Series(pd.NA, index=d.index, dtype="string")
    uuid = uuid.where(uuid.str.fullmatch(r"[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}", na=False))
    r = resumir(consultar(engine, sorted(uuid.dropna().unique())))
    d["COMPLEMENTO_PAGO"] = uuid.map(r.COMPLEMENTO)
    d["FECHA_COMPLEMENTO_PAGO"] = uuid.map(r.FECHA)
    return d
