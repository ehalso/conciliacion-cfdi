"""Extracción y cruce SAT/MPRO para CFDI de retención (constancias de
retención e información de pagos, emitidas por Trivasa a arrendadores,
clave de retención 16/ISR arrendamiento en la práctica observada).

Dos diferencias de fondo contra recibido/emitido que hacen que este origen
necesite su propio extractor en vez de reusar `extract_sat.py`/
`extract_mpro.py`:

1. **`raw_sat.cfdi_retencion` no comparte columnas** con
   `cfdi_recibidos`/`cfdi_emitidos` (confirmado en vivo, information_schema
   2026-09-10): no hay subtotal/iva/total, sino
   `monto_total_operacion`/`monto_total_gravado`/`monto_total_exento`/
   `monto_total_retenido`, más `cve_retenc`/`impuesto_retenido_codigo`.

2. **El XML embebido en `Comprobante_Digital.Cd_XML` para estos UUID
   (`Cd_Tabla='CONSTANCIA_RETENCION'`) no es un CFDI normal**: es un
   "Comprobante de Retenciones e Información de Pagos" — root
   `retenciones:Retenciones`, namespace `.../esquemas/retencionpago/2`,
   sin los atributos `SubTotal`/`Total`/`TipoDeComprobante` que trae un
   `cfdi:Comprobante`. `cfdi_parser.parse_cfdi` NO lo rechaza: como no
   encuentra el nodo `Comprobante` cae de vuelta al root por diseño (para
   tolerar el caso normal en el que el root ya ES el Comprobante), y los
   atributos que busca simplemente no existen ahí — devuelve
   `subtotal=0`/`total=0` en silencio en vez de lanzar `ValueError`. Por
   eso este módulo NUNCA llama a `extract_mpro_por_uuids`/`parse_cfdi`
   para retención.

   En su lugar, compara directo la columna nativa `Cd_Monto` (sin parsear
   XML) contra `monto_total_operacion` del SAT — confirmado exacto en vivo
   (2026-09-10, 2 UUID de enero 2026): `Cd_Monto` 51574.000000000 ==
   `monto_total_operacion` 51574.00; 20000.000000000 == 20000.00.

Patrón de cobertura ya documentado en `docs/hallazgos.md` punto 12 (y
`docs/pendientes.md`): de los CFDI de retención de un periodo, solo una
fracción tiene la fila `CONSTANCIA_RETENCION` con folio/monto reales; el
resto solo trae un stub en `GASTO_REGISTRO` con `Cd_Monto=0`, o no tiene
ninguna fila. Este módulo clasifica exactamente esos tres casos.
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET

SAT_COLUMNS = [
    "uuid", "fecha_emision", "rfc_emisor", "nombre_emisor",
    "rfc_receptor", "nombre_receptor", "periodo", "cve_retenc",
    "impuesto_retenido_codigo", "monto_total_operacion",
    "monto_total_gravado", "monto_total_exento", "monto_total_retenido",
]

SAT_NUMERIC = [
    "monto_total_operacion", "monto_total_gravado",
    "monto_total_exento", "monto_total_retenido",
]

PAGE_SIZE = 2000
BATCH_SIZE_MPRO = 200


def extract_sat_retencion(periodo: str | None = None, periodos: list[str] | None = None) -> pd.DataFrame:
    """Trae CFDI de retención de uno o varios periodos ('YYYY-MM') de
    `raw_sat.cfdi_retencion`."""
    if periodos is None:
        if periodo is None:
            raise ValueError("hay que pasar periodo o periodos")
        periodos = [periodo]

    where_periodos = ", ".join(sql_quote(p) for p in periodos)
    cols_sql = ", ".join(SAT_COLUMNS)

    all_rows: list[dict] = []
    offset = 0
    while True:
        sql = (
            f"SELECT {cols_sql} FROM raw_sat.cfdi_retencion "
            f"WHERE periodo IN ({where_periodos}) "
            f"ORDER BY uuid LIMIT {PAGE_SIZE} OFFSET {offset}"
        )
        result = run_query("postgres_dw", sql)
        page = rows_as_dicts(result)
        all_rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    df = pd.DataFrame(all_rows, columns=SAT_COLUMNS)
    if df.empty:
        return df

    df["uuid"] = df["uuid"].str.upper()
    for f in SAT_NUMERIC:
        df[f] = pd.to_numeric(df[f], errors="coerce").fillna(0)
    df = df.rename(columns={"fecha_emision": "fecha"})
    return df


def _fetch_mpro_batch(uuids: list[str]) -> list[dict]:
    in_list = ", ".join(sql_quote(u) for u in uuids)
    sql = (
        "SELECT Cd_Timbre_UUID, Cd_Tabla, Cd_Documento, Cd_Monto "
        f"FROM Comprobante_Digital WHERE Cd_Timbre_UUID IN ({in_list})"
    )
    result = run_query(MPRO_TARGET, sql)
    return rows_as_dicts(result)


def extract_mpro_retencion(uuids: list[str]) -> pd.DataFrame:
    """Para cada UUID, busca sus filas en `Comprobante_Digital` (cualquier
    `Cd_Tabla`) y arma una fila resumen sin parsear XML:

    - `tiene_constancia` + `folio_constancia`/`monto_constancia`: si existe
      una fila `Cd_Tabla='CONSTANCIA_RETENCION'` (el caso "bueno").
    - `tiene_stub_gasto_registro`: si existe una fila
      `Cd_Tabla='GASTO_REGISTRO'` con `Cd_Monto=0` (stub sin monto real).
    - `en_mpro`: si hay CUALQUIER fila para ese UUID.
    """
    by_uuid: dict[str, list[dict]] = defaultdict(list)
    uuids = [u.upper() for u in uuids]
    for i in range(0, len(uuids), BATCH_SIZE_MPRO):
        batch = uuids[i : i + BATCH_SIZE_MPRO]
        for row in _fetch_mpro_batch(batch):
            u = (row.get("Cd_Timbre_UUID") or "").upper()
            if u:
                by_uuid[u].append(row)

    out_rows = []
    for uuid, matches in by_uuid.items():
        modulos = sorted({m.get("Cd_Tabla") for m in matches if m.get("Cd_Tabla")})
        constancia = next((m for m in matches if m.get("Cd_Tabla") == "CONSTANCIA_RETENCION"), None)
        stub_gasto = next(
            (m for m in matches if m.get("Cd_Tabla") == "GASTO_REGISTRO" and float(m.get("Cd_Monto") or 0) == 0),
            None,
        )

        row = {
            "uuid": uuid,
            "en_mpro": True,
            "n_modulos_mpro": len(modulos),
            "modulos_mpro": ", ".join(modulos),
            "tiene_constancia": constancia is not None,
            "folio_constancia": constancia.get("Cd_Documento") if constancia else None,
            "monto_constancia": float(constancia["Cd_Monto"]) if constancia else None,
            "tiene_stub_gasto_registro": stub_gasto is not None,
        }
        out_rows.append(row)

    return pd.DataFrame(out_rows)


def reconcile_retencion(sat_df: pd.DataFrame, mpro_df: pd.DataFrame, tolerancia) -> pd.DataFrame:
    """Clasifica cada CFDI de retención en:

    - `CONCILIADO`: tiene fila CONSTANCIA_RETENCION y su monto cuadra
      contra `monto_total_operacion` del SAT.
    - `DIFERENCIA_IMPORTE`: tiene CONSTANCIA_RETENCION pero el monto no
      cuadra.
    - `STUB_GASTO_REGISTRO_SIN_MONTO`: no tiene CONSTANCIA_RETENCION, solo
      un stub en GASTO_REGISTRO con monto cero (aparece en mpro pero sin
      monto real registrado).
    - `SIN_MAPEO_MPRO`: no aparece en `Comprobante_Digital` bajo ningún
      `Cd_Tabla`.
    """
    mpro = mpro_df.set_index("uuid", drop=False) if not mpro_df.empty else mpro_df

    rows = []
    for _, sat_row in sat_df.iterrows():
        uuid = sat_row["uuid"]
        en_mpro = uuid in mpro.index if not mpro.empty else False

        row = {
            "uuid": uuid,
            "fecha": sat_row["fecha"],
            "rfc_emisor": sat_row["rfc_emisor"],
            "rfc_receptor": sat_row["rfc_receptor"],
            "cve_retenc": sat_row["cve_retenc"],
            "monto_total_operacion": sat_row["monto_total_operacion"],
            "monto_total_retenido": sat_row["monto_total_retenido"],
        }

        if not en_mpro:
            row["estatus"] = "SIN_MAPEO_MPRO"
            row["modulos_mpro"] = None
            row["folio_constancia"] = None
            row["monto_constancia"] = None
            row["diff"] = None
            rows.append(row)
            continue

        m = mpro.loc[uuid]
        row["modulos_mpro"] = m["modulos_mpro"]
        row["folio_constancia"] = m["folio_constancia"]
        row["monto_constancia"] = m["monto_constancia"]

        if m["tiene_constancia"]:
            diff = float(sat_row["monto_total_operacion"]) - float(m["monto_constancia"])
            row["diff"] = diff
            row["estatus"] = "CONCILIADO" if abs(diff) <= float(tolerancia) else "DIFERENCIA_IMPORTE"
        elif m["tiene_stub_gasto_registro"]:
            row["diff"] = None
            row["estatus"] = "STUB_GASTO_REGISTRO_SIN_MONTO"
        else:
            row["diff"] = None
            row["estatus"] = "SIN_MAPEO_MPRO"

        rows.append(row)

    return pd.DataFrame(rows)


def resumen(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["estatus", "conteo", "monto_total_operacion"])
    return (
        df.groupby("estatus")
        .agg(conteo=("uuid", "count"), monto_total_operacion=("monto_total_operacion", "sum"))
        .reset_index()
    )
