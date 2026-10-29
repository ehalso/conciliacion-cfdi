"""Vista resumen: cantidad y monto de CFDI por tipo, SAT (Postgres raw_sat_api) vs Mpro, más el detalle de diferencias."""
import os

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .sat import TIPO_SOLO_SAT

UUID_RE = r"[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}"
TIPOS_REC = (
    ("Ingreso", "I", "Compras, gastos, indirectos y CxP"),
    ("Egreso", "E", "Notas de crédito de proveedor"),
    ("Traslado", "T", "Número de XML"),
    ("Pago", "P", "Mpro: complementos de pago adjuntos a cheques (sin monto)"),
    ("Retención", None, "SAT: raw_sat_api.retenciones (monto retenido)"),
)
TIPOS_EMI = (("Ingreso", "I", ""), ("Egreso", "E", ""), ("Traslado", "T", ""), ("Nómina", "N", "Se timbra en Nominpaq, no en Mpro"),
             ("Pago", "P", ""), ("Retención", None, "Mpro: constancias de retención; SAT: monto retenido"))

# CFDI vigentes (sin cancelados) del periodo por fecha del CFDI. Los autoemitidos (emisor = receptor, p. ej. nómina) son EMITIDO.
# En complementos de pago el monto es pagos_monto_total (el total del CFDI P es 0).
SQL_SAT = """
SELECT c.tipo, c.tipo_comprobante AS tc, count(DISTINCT upper(c.uuid)) AS n,
       coalesce(sum(CASE WHEN c.tipo_comprobante = 'P' THEN c.pagos_monto_total ELSE c.total END), 0) AS monto
FROM (SELECT DISTINCT ON (upper(uuid)) * FROM raw_sat_api.cfdi WHERE fecha >= :fi AND fecha < :ff ORDER BY upper(uuid), cargado_en DESC) c
LEFT JOIN (SELECT DISTINCT upper(uuid) AS uuid FROM raw_sat_api.cancelados WHERE estatus = '0') k ON k.uuid = upper(c.uuid)
WHERE k.uuid IS NULL
GROUP BY c.tipo, c.tipo_comprobante
"""
RFC_PROPIO = os.environ.get("RFC_PROPIO", "TRI970922TL2")
# CFDI emitidos registrados en Mpro (Comprobante_Digital, RFC emisor propio); se excluyen los UUID con todos sus documentos cancelados (CA).
SQL_MPRO_EMITIDOS = """
SELECT upper(Cd_Timbre_UUID) AS uuid, max(Cd_Tipo_CFDI) AS tipo, max(Cd_Tabla) AS tabla, max(Cd_Monto) AS monto
FROM Comprobante_Digital
WHERE Cd_Timbre_Fecha >= :fi AND Cd_Timbre_Fecha < :ff AND Cd_RFC_Emisor = :rfc AND Cd_Timbre_UUID IS NOT NULL AND Cd_Timbre_UUID <> ''
GROUP BY upper(Cd_Timbre_UUID)
HAVING sum(CASE WHEN Es_Cve_Estado = 'CA' THEN 0 ELSE 1 END) > 0
"""
SQL_SAT_RET = """
SELECT tipo, count(DISTINCT upper(uuid)) AS n, coalesce(sum(monto_tot_ret), 0) AS monto
FROM raw_sat_api.retenciones WHERE fecha_exp >= :fi AND fecha_exp < :ff GROUP BY tipo
"""
DIFERENCIAS = ("Tipo", "FOLIO", "UUID", "NOMBRE_PROVEEDOR", "XML_MONTO", "SAT_UUID", "SAT_ESTATUS", "SAT_TIPO_CFDI", "SAT_IMPORTE",
               "CONC_EXISTE_MPRO", "CONC_EXISTE_SAT", "CONC_EXISTENCIA", "CONC_IMPORTES")


def _uuid(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.upper().where(lambda x: x.str.fullmatch(UUID_RE, na=False))


def _cifras(n: int, monto) -> dict:
    return {"n": int(n), "monto": None if monto is None else round(float(monto), 2)}


def _mpro(d: pd.DataFrame) -> dict[str, dict]:
    """Documentos de Mpro con UUID (uno por UUID): NC proveedor = Egreso, el resto = Ingreso; Pago por complemento."""
    m = d[d.Tipo != TIPO_SOLO_SAT].assign(_u=lambda x: _uuid(x.UUID) if "UUID" in x else pd.NA).dropna(subset=["_u"]).drop_duplicates("_u")
    m = m.assign(_t=m.Tipo.map(lambda t: "Egreso" if t == "NC proveedor" else "Ingreso"),
                 _m=pd.to_numeric(m.XML_MONTO, errors="coerce").fillna(0) if "XML_MONTO" in m else 0.0)
    out = {t: _cifras(g.shape[0], g._m.sum()) for t, g in m.groupby("_t")}
    comp = _uuid(d.COMPLEMENTO_PAGO).dropna().unique() if "COMPLEMENTO_PAGO" in d else []
    out["Pago"] = _cifras(len(comp), None)
    return out


def consultar_sat(engine: Engine, fi: str, ff: str) -> pd.DataFrame:
    with engine.connect() as con:
        return pd.read_sql(text(SQL_SAT), con, params={"fi": fi, "ff": ff})


def consultar_mpro_emitidos(engine: Engine, fi: str, ff: str) -> dict[str, dict]:
    """Emitidos de Mpro por tipo de CFDI (un documento por UUID). Constancias de retención y Gasto_Registro 'RETENCIONES' = Retención."""
    with engine.connect() as con:
        e = pd.read_sql(text(SQL_MPRO_EMITIDOS), con, params={"fi": fi, "ff": ff, "rfc": RFC_PROPIO})
    letra = {"I": "Ingreso", "E": "Egreso", "T": "Traslado", "P": "Pago", "N": "Nómina"}
    e["t"] = [("Retención" if (a == "CONSTANCIA_RETENCION" or (t or "").strip().upper() == "RETENCIONES") else letra.get((t or "").strip().upper()))
              for t, a in zip(e.tipo, e.tabla)]
    e["m"] = pd.to_numeric(e.monto, errors="coerce").fillna(0)
    return {t: _cifras(g.shape[0], None if t == "Pago" else g.m.sum()) for t, g in e.dropna(subset=["t"]).groupby("t")}


def consultar_retenciones(engine: Engine, fi: str, ff: str) -> pd.DataFrame | None:
    """Constancias de retención del SAT por tipo; None si el usuario de lectura no tiene permiso sobre la tabla."""
    try:
        with engine.connect() as con:
            return pd.read_sql(text(SQL_SAT_RET), con, params={"fi": fi, "ff": ff})
    except Exception:
        return None


def _sat(c: pd.DataFrame, sentido: str) -> dict[str, dict]:
    """Cifras SAT por letra de tipo de comprobante, para RECIBIDO o EMITIDO."""
    c = c[c.tipo == sentido]
    return {r.tc: _cifras(r.n, r.monto) for r in c.itertuples()}


def _ret(r: pd.DataFrame | None, sentido: str) -> dict:
    if r is None:
        return {}
    return {None: _cifras(r[r.tipo == sentido].n.sum(), r[r.tipo == sentido].monto.sum())}


def _seccion(tipos, sat: dict, mpro: dict | None) -> list[dict]:
    filas = []
    for tipo, letra, nota in tipos:
        s = sat.get(letra, _cifras(0, 0))
        if tipo == "Retención" and None not in sat:
            s = {"n": None, "monto": None}
        if mpro is None or tipo == "Nómina":
            m, dif = _cifras(0, None), {"n": None, "monto": None}
            m["n"] = None
        else:
            m = mpro.get(tipo, _cifras(0, None if tipo == "Pago" else 0))
            dif = {"n": None if s["n"] is None else s["n"] - m["n"],
                   "monto": None if m["monto"] is None or s["monto"] is None else round(s["monto"] - m["monto"], 2)}
        filas.append({"tipo": tipo, "nota": nota, "sat": s, "mpro": m, "dif": dif})
    return filas


def resumir(d: pd.DataFrame, sat: pd.DataFrame | None, emitidos: dict | None = None, ret: pd.DataFrame | None = None) -> dict:
    """Recibidos y emitidos (SAT de raw_sat_api vs Mpro) más la lista de diferencias del cruce por UUID."""
    if sat is None or "SAT_UUID" not in d:
        return {"disponible": False}
    recibidos = _seccion(TIPOS_REC, {**_sat(sat, "RECIBIDO"), **_ret(ret, "RECIBIDO")}, _mpro(d))
    emitidos = _seccion(TIPOS_EMI, {**_sat(sat, "EMITIDO"), **_ret(ret, "EMITIDO")}, emitidos)
    malo = d[(d.CONC_EXISTENCIA == "No") | (d.CONC_IMPORTES == "No")]
    cols = [c for c in DIFERENCIAS if c in d]
    malo = malo.sort_values(["Tipo", "FOLIO"], kind="stable")[cols]
    rows = [[None if pd.isna(v) else (v.item() if hasattr(v, "item") else v) for v in r] for r in malo.itertuples(index=False)]
    return {"disponible": True, "recibidos": recibidos, "emitidos": emitidos, "diferencias": {"cols": cols, "rows": rows}}
