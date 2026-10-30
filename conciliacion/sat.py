"""Cruce por UUID contra el SAT (Postgres `raw_sat_api`): bloque "Base de datos SAT" y bloque de conciliación."""
import html
import logging

import pandas as pd
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

TOLERANCIA = 0.05
TOLERANCIA_FOLIO = 0.01  # redondeo acumulado por cada folio adicional del mismo UUID
LOTE = 5000
TIPOS_CFDI = {"I": "Ingreso", "E": "Egreso", "P": "Pago", "T": "Traslado", "N": "Nómina"}
SI, NO = "Sí", "No"
TIPO_SOLO_SAT = "Solo SAT"

# `tipo` solo tiene RECIBIDO y EMITIDO; lo autoemitido (emisor = receptor, p. ej. nómina) llega como EMITIDO.
SQL_CFDI = """
SELECT upper(c.uuid) AS uuid, c.serie, c.folio, c.tipo_comprobante, c.fecha, c.rfc_emisor, c.nombre_emisor, c.total,
       (k.uuid IS NOT NULL) AS cancelado,
       substring(c.xml::text from 'Concepto[^>]*?Descripcion="([^"]*)"') AS concepto,
       substring(c.xml::text from 'UsoCFDI="([^"]*)"') AS uso_cfdi,
       substring(c.xml::text from '<ecc12:EstadoDeCuentaCombustible[^>]*? Total="([0-9.]+)"') AS complemento
FROM raw_sat_api.cfdi c
LEFT JOIN (SELECT DISTINCT upper(uuid) AS uuid FROM raw_sat_api.cancelados WHERE estatus = '0') k ON k.uuid = upper(c.uuid)
WHERE (c.tipo = 'RECIBIDO' OR (c.tipo = 'EMITIDO' AND c.rfc_emisor = c.rfc_receptor)) AND upper(c.uuid) = ANY(:uuids)
"""

# CFDI recibidos vigentes del periodo (por fecha del CFDI); luego se descartan los que ya están en Mpro.
SQL_SOLO_SAT = SQL_CFDI.replace("(c.tipo = 'RECIBIDO' OR (c.tipo = 'EMITIDO' AND c.rfc_emisor = c.rfc_receptor)) AND upper(c.uuid) = ANY(:uuids)",
                                "c.tipo = 'RECIBIDO' AND c.fecha >= :fi AND c.fecha < :ff AND k.uuid IS NULL")
SQL_EN_MPRO = "SELECT DISTINCT UPPER(Cd_Timbre_UUID) AS uuid FROM Comprobante_Digital WHERE Cd_Timbre_UUID IN :uuids"


def _uuid_valido(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.upper().where(lambda x: x.str.fullmatch(r"[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}", na=False))


def consultar_sat(engine: Engine, uuids: list[str]) -> pd.DataFrame:
    """CFDI del SAT para los `uuids` dados, con columnas SAT_*. Un renglón por UUID."""
    partes = []
    with engine.connect() as con:
        for i in range(0, len(uuids), LOTE):
            partes.append(pd.read_sql(text(SQL_CFDI), con, params={"uuids": uuids[i:i + LOTE]}))
    d = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=["uuid"])
    return _formatear(d.drop_duplicates("uuid"))


def _formatear(d: pd.DataFrame) -> pd.DataFrame:
    """Filas crudas de SQL_CFDI → columnas SAT_* (más UUID_CRUCE como llave)."""
    if d.empty:
        return pd.DataFrame(columns=["UUID_CRUCE"])
    return pd.DataFrame({
        "UUID_CRUCE": d.uuid,
        "SAT_UUID": d.uuid,
        "SAT_SERIE": d.serie,
        "SAT_FOLIO": d.folio,
        "SAT_ESTATUS": d.cancelado.map({True: "Cancelado", False: "Activo"}),
        "SAT_TIPO_CFDI": d.tipo_comprobante.map(TIPOS_CFDI).fillna(d.tipo_comprobante),
        "SAT_USO_CFDI": d.uso_cfdi,
        "SAT_FECHA": pd.to_datetime(d.fecha, utc=True).dt.tz_convert(None),
        "SAT_CONCEPTO": d.concepto.map(lambda c: html.unescape(c).strip() if isinstance(c, str) else None),
        "SAT_RFC": d.rfc_emisor,
        "SAT_PROVEEDOR": d.nombre_emisor,
        "SAT_IMPORTE": pd.to_numeric(d.total, errors="coerce"),
        "SAT_IMPORTE_COMPLEMENTO": pd.to_numeric(d.complemento, errors="coerce"),
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
    out["CONC_EXISTE_MPRO"] = _si_no(en_mpro)
    out["CONC_EXISTE_SAT"] = _si_no(en_sat, en_mpro)
    out["CONC_EXISTENCIA"] = _si_no(en_mpro == en_sat, en_mpro)
    out["DIF_IMPORTE_UUID"], out["CONC_IMPORTES"] = _conciliar_importes(out, en_mpro & en_sat)
    out["SAT_NO_LOCALIZADOS"] = None
    return out


def _conciliar_importes(out: pd.DataFrame, evaluable: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Diferencia y Sí/No por UUID: |Σ TOTAL de los folios| vs el importe del SAT (cuerpo + complemento de combustible).

    Las filas "CxP libre" se excluyen de la suma porque repiten el dinero de los folios de gasto con el mismo UUID;
    "CxP orden compra" sí suma: es un documento propio (con o sin Compra que cubra el resto del CFDI).
    El resultado se repite en cada línea del UUID.
    """
    es_cxp = out.Tipo.astype("string").eq("CxP libre").fillna(False)
    base = out.assign(_t=pd.to_numeric(out.TOTAL, errors="coerce").where(~es_cxp, 0).fillna(0), _f=(~es_cxp).astype(int))
    g = base[evaluable].groupby("SAT_UUID")
    suma = g._t.sum().abs()
    n = g._f.sum()
    esperado = out.drop_duplicates("SAT_UUID").set_index("SAT_UUID")
    esperado = esperado.SAT_IMPORTE + esperado.SAT_IMPORTE_COMPLEMENTO.fillna(0)
    dif = (suma - esperado.reindex(suma.index)).round(2)
    tol = TOLERANCIA + TOLERANCIA_FOLIO * (n - 1).clip(lower=0)
    dif_fila = out.SAT_UUID.map(dif).where(evaluable)
    ok = (dif.abs() <= tol).reindex(out.SAT_UUID).set_axis(out.index)
    return dif_fila, _si_no(ok.astype(bool), evaluable & dif_fila.notna())


def _si_no(cond: pd.Series, donde: pd.Series | None = None) -> pd.Series:
    """Sí/No según `cond`; vacío donde `donde` es False (no evaluable)."""
    r = cond.map({True: SI, False: NO})
    return r if donde is None else r.where(donde, "")


def agregar_solo_sat(d: pd.DataFrame, engine_sat: Engine, engine_mpro: Engine, fi: str, ff: str) -> pd.DataFrame:
    """Agrega al reporte los CFDI recibidos vigentes en el SAT que no están registrados en Mpro (Tipo "Solo SAT").

    "Registrado en Mpro" = su UUID existe en Comprobante_Digital (cualquier módulo y fecha de registro).
    Si el SAT no responde, devuelve el reporte sin cambios.
    """
    try:
        with engine_sat.connect() as con:
            c = pd.read_sql(text(SQL_SOLO_SAT), con, params={"fi": fi, "ff": ff})
        uuids = sorted(c.uuid.unique())
        with engine_mpro.connect() as con:
            en_mpro = pd.concat([pd.read_sql(text(SQL_EN_MPRO).bindparams(bindparam("uuids", expanding=True)), con,
                                             params={"uuids": uuids[i:i + 1000]}).uuid
                                 for i in range(0, len(uuids), 1000)] or [pd.Series(dtype=str)])
    except Exception as e:
        log.error("SAT sin Mpro omitido: %r", e)
        return d
    nuevos = _formatear(c[~c.uuid.isin(set(en_mpro))].drop_duplicates("uuid")).drop(columns="UUID_CRUCE")
    if nuevos.empty:
        return d
    nuevos = nuevos.sort_values(["SAT_FECHA", "SAT_UUID"]).reset_index(drop=True)
    nuevos["Tipo"] = TIPO_SOLO_SAT
    nuevos["FOLIO"] = "SAT-" + nuevos.SAT_UUID.str[:13]
    nuevos["CONC_EXISTE_MPRO"], nuevos["CONC_EXISTE_SAT"] = NO, SI
    nuevos["CONC_EXISTENCIA"], nuevos["CONC_IMPORTES"] = NO, NO
    return pd.concat([d, nuevos], ignore_index=True, sort=False)
