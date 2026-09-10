#!/usr/bin/env python3
"""Conciliación CFDI EMITIDO (factura, nota de crédito, retenciones) contra
el documento de mpro que lo originó — nivel "documento", puerto directo (a
`bridge_client`, conexión SQL directa, sin bridge HTTP) de la metodología ya
validada en
`~/proyectos/conciliacion-master/conciliacion-emitidos/conciliacion_emitidos_lib.py`
(ver `docs/emitidos_retenciones.md` y `docs/pendientes.md` de este repo).

Por qué esto es un nivel distinto de `baseline_universal_emitido.py`: aquél
pregunta "¿la PÓLIZA contable cuadra con el CFDI?" (nivel 3, útil para
detectar errores de contabilización) y se estancó en FACTURA porque la
póliza de ingreso de VENTA no aísla el documento. Este script pregunta algo
más simple y, del lado emitido, más fundamental: **"¿el CFDI que se timbró
es exactamente el que generó el documento?"** — tiene sentido porque, a
diferencia de recibidos, **el CFDI emitido se genera DESDE el documento de
mpro**, así que la relación es 1:1 estricta (nunca N:M) y, si no hay
corrupción de datos entre el documento y el timbrado, el importe no puede
diferir. Confirmar esto primero, y no asumirlo, es la base de conciliación
más elemental de emitidos.

Aceleración (2026-09-10, ver `docs/hallazgos.md`): a diferencia del proyecto
original, que parseaba `Comprobante_Digital.Cd_XML` para los cinco módulos,
aquí NO SE PARSEA XML en ningún caso:

- FACTURA / NOTA_CREDITO / CONSTANCIA_RETENCION: `Cd_Monto` YA es el importe
  comparable (`Total` del CFDI para los dos primeros, `MontoTotOperacion`
  para el tercero) — medido y documentado en el proyecto original
  (`docs/esquema-datos.md` §1), no hace falta bajar el XML para leer un
  número que ya está en una columna.
- GASTO_REGISTRO con retenciones (`Cd_Monto=0` por diseño — el importe real
  solo vive en el XML de retención): en vez de parsear `Cd_XML`, se lee
  `raw_sat.cfdi_retencion.monto_total_operacion`, ya parseado desde la
  ingesta (proyecto `consulta-xmls`) y con cobertura histórica completa
  (2016-2026, a diferencia de `cfdi_emitidos` que solo cubre enero 2026) —
  join por UUID, sin volver a tocar el XML.

Uso:
    python3 conciliacion_emitidos_documento.py --periodo 2026-01
    python3 conciliacion_emitidos_documento.py --periodos 2026-01,...,2026-06
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd  # noqa: E402

from bridge_client import run_query, rows_as_dicts, sql_quote  # noqa: E402
from config import MPRO_TARGET  # noqa: E402

RFC_TRIVASA = "TRI970922TL2"
TOL_CENTAVOS = 0.05
TOL_MENOR = 1.00


def _rango(periodo: str) -> tuple[str, str]:
    y, m = int(periodo[:4]), int(periodo[5:7])
    fi = f"{y:04d}-{m:02d}-01"
    y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
    return fi, f"{y2:04d}-{m2:02d}-01"


def extract_comprobante_digital(fi: str, ff: str) -> pd.DataFrame:
    """Universo de CFDI emitidos (Cd_RFC_Emisor=Trivasa, receptor distinto),
    los 5 módulos que le importan a este reporte."""
    sql = (
        "SELECT Cd_Tabla AS origen, Cd_Documento AS cd_documento, "
        "LEFT(Cd_Documento, 10) AS folio, "
        "UPPER(LTRIM(RTRIM(Cd_Timbre_UUID))) AS uuid, Cd_Timbre_Fecha AS fecha_timbrado, "
        "Cd_Monto AS cd_monto, Cd_Tipo_CFDI AS cd_tipo_cfdi, Es_Cve_Estado AS cd_estado "
        "FROM Comprobante_Digital "
        f"WHERE Cd_Timbre_Fecha >= {sql_quote(fi)} AND Cd_Timbre_Fecha < {sql_quote(ff)} "
        f"AND LTRIM(RTRIM(Cd_RFC_Emisor)) = {sql_quote(RFC_TRIVASA)} "
        f"AND LTRIM(RTRIM(Cd_RFC_Receptor)) <> {sql_quote(RFC_TRIVASA)} "
        "AND Cd_Timbre_UUID IS NOT NULL AND LTRIM(RTRIM(Cd_Timbre_UUID)) <> ''"
    )
    df = pd.DataFrame(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    if df.empty:
        return df
    df["uuid"] = df["uuid"].str.upper()
    df["cd_monto"] = pd.to_numeric(df["cd_monto"], errors="coerce").fillna(0.0)
    origenes_utiles = {"FACTURA", "NOTA_CREDITO", "CONSTANCIA_RETENCION", "GASTO_REGISTRO"}
    df = df[df["origen"].isin(origenes_utiles)].copy()
    # GASTO_REGISTRO solo entra por sus filas de retenciones (el resto del
    # censo de GASTO_REGISTRO es recibidos/gasto normal, fuera de alcance).
    df = df[(df["origen"] != "GASTO_REGISTRO") | (df["cd_tipo_cfdi"].fillna("").str.strip() == "RETENCIONES")]
    return df.reset_index(drop=True)


def extract_retenciones_sat(uuids: list[str]) -> pd.DataFrame:
    """`monto_total_operacion` ya parseado desde la ingesta — sin tocar XML.
    Cobertura histórica completa, a diferencia de cfdi_emitidos."""
    if not uuids:
        return pd.DataFrame(columns=["uuid", "monto_total_operacion", "monto_total_retenido"])
    in_list = ", ".join(sql_quote(u) for u in uuids)
    sql = (
        "SELECT UPPER(uuid) AS uuid, monto_total_operacion, monto_total_retenido "
        f"FROM raw_sat.cfdi_retencion WHERE UPPER(uuid) IN ({in_list})"
    )
    df = pd.DataFrame(rows_as_dicts(run_query("postgres_dw", sql)))
    if df.empty:
        return df
    df["uuid"] = df["uuid"].str.upper()
    return df.drop_duplicates("uuid")


def extract_mpro_factura(folios: list[str]) -> pd.DataFrame:
    if not folios:
        return pd.DataFrame(columns=["folio", "fecha", "estado", "comparable"])
    in_list = ", ".join(sql_quote(f) for f in folios)
    sql = (
        "SELECT Fc_Folio AS folio, Fc_Fecha AS fecha, Es_Cve_Estado AS estado, "
        "Fc_Precio_Neto_Importe AS comparable FROM Factura_Encabezado "
        f"WHERE Fc_Folio IN ({in_list})"
    )
    return pd.DataFrame(rows_as_dicts(run_query(MPRO_TARGET, sql)))


def extract_mpro_nota_credito(folios: list[str]) -> pd.DataFrame:
    if not folios:
        return pd.DataFrame(columns=["folio", "fecha", "estado", "comparable"])
    in_list = ", ".join(sql_quote(f) for f in folios)
    sql = (
        "SELECT Nc_Folio AS folio, MIN(Nc_Fecha) AS fecha, MAX(Es_Cve_Estado) AS estado, "
        "SUM(Nc_Precio_Neto_Importe) AS comparable FROM Nota_Credito "
        f"WHERE Nc_Folio IN ({in_list}) GROUP BY Nc_Folio"
    )
    return pd.DataFrame(rows_as_dicts(run_query(MPRO_TARGET, sql)))


def extract_mpro_constancia_retencion(folios: list[str]) -> pd.DataFrame:
    if not folios:
        return pd.DataFrame(columns=["folio", "fecha", "estado", "comparable"])
    in_list = ", ".join(sql_quote(f) for f in folios)
    sql = (
        "SELECT Cr_Folio AS folio, Cr_Fecha AS fecha, Es_Cve_Estado AS estado, "
        "Cr_Importe AS comparable FROM Constancia_Retencion "
        f"WHERE Cr_Folio IN ({in_list})"
    )
    return pd.DataFrame(rows_as_dicts(run_query(MPRO_TARGET, sql)))


def extract_mpro_gasto_retencion(folio_docid: list[tuple[str, str]]) -> pd.DataFrame:
    """`(Gr_Folio, Grd_ID)` — el comparable es SUBTOTAL (Grd_Precio_Descontado_
    Importe), no TOTAL: el CFDI de retención reporta la operación BRUTA, y el
    documento de gasto ya trae el NETO (Grd_Impuesto_Importe, la retención,
    va en negativo) — comparar contra TOTAL marca descuadre por exactamente
    el monto retenido. Confirmado en el proyecto original (metodologia.md §4)."""
    folios = sorted({f for f, _ in folio_docid})
    if not folios:
        return pd.DataFrame(columns=["folio", "doc_id", "fecha", "estado", "comparable"])
    in_list = ", ".join(sql_quote(f) for f in folios)
    sql = (
        "SELECT d.Gr_Folio AS folio, d.Grd_ID AS doc_id, g.Gr_Fecha AS fecha, "
        "g.Es_Cve_Estado AS estado, d.Grd_Precio_Descontado_Importe AS comparable "
        "FROM Gasto_Registro_Documento d JOIN Gasto_Registro g ON g.Gr_Folio = d.Gr_Folio "
        f"WHERE d.Gr_Folio IN ({in_list})"
    )
    return pd.DataFrame(rows_as_dicts(run_query(MPRO_TARGET, sql)))


def conciliar(periodo: str) -> pd.DataFrame:
    fi, ff = _rango(periodo)
    cd = extract_comprobante_digital(fi, ff)
    if cd.empty:
        return cd

    cd["doc_id"] = ""
    es_gasto_ret = cd["origen"] == "GASTO_REGISTRO"
    cd.loc[es_gasto_ret, "doc_id"] = cd.loc[es_gasto_ret, "cd_documento"].str.slice(10, 14)

    # CFDI de retención dividido en dos filas hermanas (mismo UUID): la
    # CONSTANCIA_RETENCION ya trae Cd_Monto real; GASTO_REGISTRO trae 0.
    # Se prioriza CONSTANCIA_RETENCION como fila principal para no duplicar
    # el importe al totalizar.
    cd["n_filas_uuid"] = cd.groupby("uuid")["uuid"].transform("size")
    prioridad = cd["origen"].map({"CONSTANCIA_RETENCION": 0}).fillna(1)
    cd["fila_principal"] = prioridad.groupby(cd["uuid"]).rank(method="first") == 1

    # Importe comparable del lado CFDI: Cd_Monto de por sí, salvo
    # GASTO_REGISTRO-retención (Cd_Monto=0 por diseño) -> raw_sat.cfdi_retencion.
    cd["cfdi_importe"] = cd["cd_monto"]
    uuids_gasto_ret = cd.loc[es_gasto_ret, "uuid"].unique().tolist()
    sat_ret = extract_retenciones_sat(uuids_gasto_ret)
    if not sat_ret.empty:
        cd = cd.merge(sat_ret.rename(columns={"monto_total_operacion": "sat_operacion"}),
                       on="uuid", how="left")
        cd["sat_operacion"] = pd.to_numeric(cd["sat_operacion"], errors="coerce")
        cd.loc[es_gasto_ret, "cfdi_importe"] = cd.loc[es_gasto_ret, "sat_operacion"]
    else:
        cd["sat_operacion"] = pd.NA

    folios_factura = cd.loc[cd["origen"] == "FACTURA", "folio"].unique().tolist()
    folios_nc = cd.loc[cd["origen"] == "NOTA_CREDITO", "folio"].unique().tolist()
    folios_cr = cd.loc[cd["origen"] == "CONSTANCIA_RETENCION", "folio"].unique().tolist()
    folio_docid_gr = list(cd.loc[es_gasto_ret, ["folio", "doc_id"]].itertuples(index=False, name=None))

    m_factura = extract_mpro_factura(folios_factura)
    m_nc = extract_mpro_nota_credito(folios_nc)
    m_cr = extract_mpro_constancia_retencion(folios_cr)
    m_gr = extract_mpro_gasto_retencion(folio_docid_gr)

    partes = []
    if not m_factura.empty:
        d = m_factura.copy(); d["origen"] = "FACTURA"; d["doc_id"] = ""; partes.append(d)
    if not m_nc.empty:
        d = m_nc.copy(); d["origen"] = "NOTA_CREDITO"; d["doc_id"] = ""; partes.append(d)
    if not m_cr.empty:
        d = m_cr.copy(); d["origen"] = "CONSTANCIA_RETENCION"; d["doc_id"] = ""; partes.append(d)
    if not m_gr.empty:
        d = m_gr.copy(); d["origen"] = "GASTO_REGISTRO"; partes.append(d)

    mpro = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(
        columns=["folio", "doc_id", "fecha", "estado", "comparable", "origen"])
    if not mpro.empty:
        mpro["folio"] = mpro["folio"].astype(str).str.strip()
        mpro["doc_id"] = mpro["doc_id"].fillna("").astype(str).str.strip()
        mpro["comparable"] = pd.to_numeric(mpro["comparable"], errors="coerce")

    df = cd.merge(
        mpro.rename(columns={"fecha": "mpro_fecha", "estado": "mpro_estado", "comparable": "mpro_comparable"}),
        on=["origen", "folio", "doc_id"], how="left")

    df["dif"] = df["cfdi_importe"].fillna(0) - df["mpro_comparable"].fillna(0)
    df["estatus"] = df.apply(_estatus, axis=1)
    df["periodo"] = periodo
    return df


def _estatus(r) -> str:
    if r["n_filas_uuid"] > 1 and not r["fila_principal"]:
        if pd.notna(r["mpro_comparable"]) and abs(r["dif"]) <= TOL_CENTAVOS:
            return "CONCILIA_FILA_HERMANA"
    if pd.isna(r["mpro_comparable"]):
        return "SIN_REGISTRO"
    if r["cd_estado"] == "CA" and str(r["mpro_estado"]).strip() == "CA":
        return "AMBOS_CANCELADOS"
    d = abs(r["dif"])
    if d <= TOL_CENTAVOS:
        return "CONCILIA"
    if d <= TOL_MENOR:
        return "DIF_CENTAVOS"
    if abs(r["mpro_comparable"]) <= TOL_CENTAVOS and abs(r["cfdi_importe"] or 0) > 1:
        return "REGISTRO_EN_CERO"
    return "DIF_MATERIAL"


ESTATUS_CUADRA = {"CONCILIA", "DIF_CENTAVOS", "CONCILIA_FILA_HERMANA"}
ESTATUS_EXPLICADO = {"AMBOS_CANCELADOS"}


def run(periodos: list[str]):
    partes = []
    for periodo in periodos:
        print(f"[{periodo}] conciliando documento <-> CFDI ...")
        df = conciliar(periodo)
        if df.empty:
            print("     sin CFDI emitidos en este periodo")
            continue
        partes.append(df)
        n = len(df)
        conciliable = df[~df["estatus"].isin(ESTATUS_EXPLICADO)]
        cuadra = conciliable["estatus"].isin(ESTATUS_CUADRA).sum()
        print(f"     {n} CFDI · {len(conciliable)} conciliables (sin AMBOS_CANCELADOS) · "
              f"{cuadra} cuadran ({cuadra / len(conciliable) * 100:.2f}%)" if len(conciliable) else "     sin universo conciliable")

    if not partes:
        print("Sin datos para los periodos pedidos.")
        return None

    todo = pd.concat(partes, ignore_index=True)
    resumen = todo.groupby(["periodo", "estatus"]).size().unstack(fill_value=0)
    print()
    print(resumen.to_string())

    out = Path("output") / f"conciliacion_emitidos_documento_{periodos[0]}_a_{periodos[-1]}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    todo.to_csv(out, index=False)
    print(f"\nDetalle: {out}")

    n_total = len(todo)
    conciliable = todo[~todo["estatus"].isin(ESTATUS_EXPLICADO)]
    cuadra = conciliable["estatus"].isin(ESTATUS_CUADRA).sum()
    print(f"\nTOTAL {n_total} CFDI · {len(conciliable)} conciliables · "
          f"{cuadra} cuadran ({cuadra / len(conciliable) * 100:.2f}%)")
    return todo


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--periodo", help="YYYY-MM")
    g.add_argument("--periodos", help="Varios periodos separados por coma")
    args = ap.parse_args()
    periodos = [args.periodo] if args.periodo else [p.strip() for p in args.periodos.split(",")]
    run(periodos)
