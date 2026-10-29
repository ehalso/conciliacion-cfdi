"""Vista resumen: cantidad y monto de CFDI por tipo, SAT (Postgres raw_sat_api) vs Mpro, más el detalle de diferencias."""
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
    ("Retención", None, "Sin fuente en raw_sat_api ni en Mpro por ahora"),
)
TIPOS_EMI = (("Ingreso", "I", ""), ("Egreso", "E", ""), ("Traslado", "T", ""), ("Nómina", "N", "Se timbra en Nominpaq, no en Mpro"),
             ("Pago", "P", ""), ("Retención", None, "Sin fuente en raw_sat_api por ahora"))

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


def _sat(c: pd.DataFrame, sentido: str) -> dict[str, dict]:
    """Cifras SAT por letra de tipo de comprobante, para RECIBIDO o EMITIDO."""
    c = c[c.tipo == sentido]
    return {r.tc: _cifras(r.n, r.monto) for r in c.itertuples()}


def _seccion(tipos, sat: dict, mpro: dict | None) -> list[dict]:
    filas = []
    for tipo, letra, nota in tipos:
        s = sat.get(letra, _cifras(0, 0))
        if mpro is None:
            m, dif = _cifras(0, None), {"n": None, "monto": None}
            m["n"] = None
        else:
            m = mpro.get(tipo, _cifras(0, None if tipo == "Pago" else 0))
            dif = {"n": s["n"] - m["n"], "monto": None if m["monto"] is None else round(s["monto"] - m["monto"], 2)}
        filas.append({"tipo": tipo, "nota": nota, "sat": s, "mpro": m, "dif": dif})
    return filas


def resumir(d: pd.DataFrame, sat: pd.DataFrame | None) -> dict:
    """Recibidos y emitidos (SAT de raw_sat_api vs Mpro) más la lista de diferencias del cruce por UUID."""
    if sat is None or "SAT_UUID" not in d:
        return {"disponible": False}
    recibidos = _seccion(TIPOS_REC, _sat(sat, "RECIBIDO"), _mpro(d))
    emitidos = _seccion(TIPOS_EMI, _sat(sat, "EMITIDO"), None)
    malo = d[(d.CONC_EXISTENCIA == "No") | (d.CONC_IMPORTES == "No")]
    cols = [c for c in DIFERENCIAS if c in d]
    malo = malo.sort_values(["Tipo", "FOLIO"], kind="stable")[cols]
    rows = [[None if pd.isna(v) else (v.item() if hasattr(v, "item") else v) for v in r] for r in malo.itertuples(index=False)]
    return {"disponible": True, "recibidos": recibidos, "emitidos": emitidos, "diferencias": {"cols": cols, "rows": rows}}
