"""Cruce por UUID contra el SAT (Postgres `raw_sat_api`): bloque "Base de datos SAT" y bloque de conciliación."""
import html
import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

TOLERANCIA = 0.05
LOTE = 5000
TIPOS_CFDI = {"I": "Ingreso", "E": "Egreso", "P": "Pago", "T": "Traslado", "N": "Nómina"}
SI, NO = "Sí", "No"

# Un CFDI recibido puede venir como AUTOEMITIDO (emisor y receptor son empresas del grupo).
SQL_CFDI = """
SELECT upper(c.uuid) AS uuid, c.serie, c.folio, c.tipo_comprobante, c.fecha, c.rfc_emisor, c.nombre_emisor, c.total,
       (k.uuid IS NOT NULL) AS cancelado,
       substring(c.xml::text from 'Concepto[^>]*?Descripcion="([^"]*)"') AS concepto
FROM raw_sat_api.cfdi c
LEFT JOIN (SELECT DISTINCT upper(uuid) AS uuid FROM raw_sat_api.cancelados WHERE estatus = '0') k ON k.uuid = upper(c.uuid)
WHERE c.tipo IN ('RECIBIDO', 'AUTOEMITIDO') AND upper(c.uuid) = ANY(:uuids)
"""


def _uuid_valido(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.upper().where(lambda x: x.str.fullmatch(r"[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}", na=False))


def consultar_sat(engine: Engine, uuids: list[str]) -> pd.DataFrame:
    """CFDI del SAT para los `uuids` dados, con columnas SAT_*. Un renglón por UUID."""
    partes = []
    with engine.connect() as con:
        for i in range(0, len(uuids), LOTE):
            partes.append(pd.read_sql(text(SQL_CFDI), con, params={"uuids": uuids[i:i + LOTE]}))
    d = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=["uuid"])
    d = d.drop_duplicates("uuid")
    if d.empty:
        return pd.DataFrame(columns=["UUID_CRUCE"])
    return pd.DataFrame({
        "UUID_CRUCE": d.uuid,
        "SAT_UUID": d.uuid,
        "SAT_SERIE": d.serie,
        "SAT_FOLIO": d.folio,
        "SAT_ESTATUS": d.cancelado.map({True: "Cancelado", False: "Activo"}),
        "SAT_TIPO_CFDI": d.tipo_comprobante.map(TIPOS_CFDI).fillna(d.tipo_comprobante),
        "SAT_FECHA": pd.to_datetime(d.fecha, utc=True).dt.tz_convert(None),
        "SAT_CONCEPTO": d.concepto.map(lambda c: html.unescape(c).strip() if isinstance(c, str) else None),
        "SAT_RFC": d.rfc_emisor,
        "SAT_PROVEEDOR": d.nombre_emisor,
        "SAT_IMPORTE": pd.to_numeric(d.total, errors="coerce"),
    })


def agregar_sat(d: pd.DataFrame, engine: Engine) -> pd.DataFrame:
    """Agrega SAT_* y CONC_* al reporte. Si el SAT no responde, devuelve el reporte sin esas columnas."""
    uuid = _uuid_valido(d.UUID) if "UUID" in d else pd.Series(pd.NA, index=d.index, dtype="string")
    try:
        sat = consultar_sat(engine, sorted(uuid.dropna().unique()))
    except Exception as e:
        log.error("Cruce con el SAT omitido: %r", e)
        return d
    out = d.assign(UUID_CRUCE=uuid).merge(sat, on="UUID_CRUCE", how="left").drop(columns="UUID_CRUCE")
    out.index = d.index

    en_mpro = uuid.notna()
    en_sat = out.SAT_UUID.notna()
    dif = (pd.to_numeric(out.XML_MONTO, errors="coerce") - out.SAT_IMPORTE).abs()
    out["CONC_EXISTE_MPRO"] = _si_no(en_mpro)
    out["CONC_EXISTE_SAT"] = _si_no(en_sat, en_mpro)
    out["CONC_EXISTENCIA"] = _si_no(en_mpro == en_sat, en_mpro)
    out["CONC_IMPORTES"] = _si_no(dif <= TOLERANCIA, en_mpro & en_sat & dif.notna())
    out["SAT_NO_LOCALIZADOS"] = None
    return out


def _si_no(cond: pd.Series, donde: pd.Series | None = None) -> pd.Series:
    """Sí/No según `cond`; vacío donde `donde` es False (no evaluable)."""
    r = cond.map({True: SI, False: NO})
    return r if donde is None else r.where(donde, "")
