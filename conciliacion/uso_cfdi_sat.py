"""Completa Uso CFDI desde la BD SAT solo donde el XML de Mpro no lo trae (único uso del SAT en esta versión)."""
import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

SQL_USO = """
SELECT upper(uuid) AS uuid, substring(xml::text from 'UsoCFDI="([^"]*)"') AS uso
FROM raw_sat_api.cfdi WHERE upper(uuid) = ANY(:uuids)
"""
SQL_CATALOGO = "SELECT RTRIM(Uc_Cve_Uso_CFDI) AS clave, Uc_Descripcion AS descripcion FROM Uso_CFDI"
UUID_RE = r"[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}"


def completar_uso_cfdi(d: pd.DataFrame, engine_sat: Engine | None, engine_mpro: Engine) -> pd.DataFrame:
    """Llena CLAVE/DESCRIPCION_USO_BIEN_SERVICIO vacías con el UsoCFDI del SAT (por UUID). Si algo falla, no cambia nada."""
    if engine_sat is None or "UUID" not in d:
        return d
    uuid = d.UUID.astype("string").str.strip().str.upper().where(lambda s: s.str.fullmatch(UUID_RE, na=False))
    vacio = d.CLAVE_USO_BIEN_SERVICIO.isna() | (d.CLAVE_USO_BIEN_SERVICIO.astype("string").str.strip() == "")
    faltan = sorted(uuid[vacio].dropna().unique())
    if not faltan:
        return d
    try:
        with engine_sat.connect() as con:
            uso = pd.read_sql(text(SQL_USO), con, params={"uuids": faltan}).drop_duplicates("uuid").set_index("uuid").uso
        with engine_mpro.connect() as con:
            catalogo = pd.read_sql(text(SQL_CATALOGO), con).drop_duplicates("clave").set_index("clave").descripcion
    except Exception as e:
        log.error("Uso CFDI desde el SAT omitido: %r", e)
        return d
    clave = uuid.map(uso).where(vacio)
    d = d.copy()
    d["CLAVE_USO_BIEN_SERVICIO"] = d.CLAVE_USO_BIEN_SERVICIO.where(~vacio | clave.isna(), clave)
    d["DESCRIPCION_USO_BIEN_SERVICIO"] = d.DESCRIPCION_USO_BIEN_SERVICIO.where(~vacio | clave.isna(), clave.map(catalogo))
    return d
