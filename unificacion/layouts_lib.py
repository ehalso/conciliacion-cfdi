"""Unifica a grano documento los layouts de mpro que originan un CFDI
Recibido tipo I/E, para poder correr la conciliacion en sentido inverso
(mpro -> SAT) contra `raw_sat.cfdi_recibidos`.

Cinco layouts, cinco tablas de mpro. Cuatro vienen de ~/ehalso/reportes-mpro
(compras, compra indirecto, cxp libre, nota de credito proveedor) y el quinto
es el de gastos de este repo. Se reusa la LOGICA de cada layout (mismos joins,
mismos filtros, mismos calculos de importe), no su codigo: los scripts de
reportes-mpro devuelven los importes ya formateados como string y con una fila
de TOTAL anexada, ninguna de las dos cosas sirve para reconciliar.

Todos los importes salen en MXN (cada layout ya multiplica por su tipo de
cambio) y como numero, no como texto.

Falta CHEQUE y ANTICIPO_CXP: no tienen layout hecho todavia. Su ausencia baja
el porcentaje de conciliacion y esta contabilizada aparte en el reporte.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from bridge_client import run_query, sql_quote  # noqa: E402

from config import MPRO_TARGET  # noqa: E402

# Codigos de retencion usados por el layout de cxp libre (rptrv79_05).
RETENCION_IVA_CODES = ("0015", "0016", "0017", "0018", "0023", "0024")
RETENCION_ISR_CODES = ("0009", "0010", "0011", "0012", "0013", "0014", "0026")
TODOS_RETENCION_CODES = RETENCION_IVA_CODES + RETENCION_ISR_CODES

# Columnas del layout unificado. Solo lo util para reconciliar: identificacion
# del documento, importes y la liga al CFDI. Los layouts traen muchos mas
# campos (comprador, almacen, uso de CFDI, concepto) que se pueden sumar
# despues si hacen falta.
COLUMNAS = [
    "origen",         # tabla de mpro / Cd_Tabla
    "sub_origen",     # Gr_Tabla, Cxp_Tabla, causa de NC — para filtrar despues
    "folio",          # Operacion_ID del layout
    "doc_key",        # llave de match contra Comprobante_Digital.Cd_Documento
    "fecha",
    "moneda",
    "rfc",
    "razon_social",
    "referencia",     # Factura_REF / numero de factura del proveedor
    "subtotal_neto",
    "iva",
    "total",
    "uuid",
    "tipo_comprobante_cfdi",
]


def _lista_sql(valores: tuple[str, ...]) -> str:
    return "(" + ", ".join(sql_quote(v) for v in valores) + ")"


def _sql_gasto_registro(fi: str, ff: str, empresa: str) -> str:
    """Gasto_Registro_Documento — grano documento (folio + Grd_ID).

    A diferencia de los otros cuatro, el layout de gastos de este repo trabaja
    a grano FOLIO x POLIZA x CUENTA x CECO. Aqui se colapsa a documento, que es
    el grano que tiene sentido cruzar contra un CFDI.

    `Cd_Documento` para GASTO_REGISTRO viene en 14 o 18 chars; los primeros 14
    son Gr_Folio (10) + Grd_ID (4), que es la llave real del documento.
    """
    return f"""
SELECT
    'GASTO_REGISTRO'                                    AS origen,
    CASE WHEN ISNULL(gr.Gr_Tabla,'') = '' THEN 'GASTO_DIRECTO'
         ELSE gr.Gr_Tabla END                           AS sub_origen,
    gr.Gr_Folio                                         AS folio,
    gr.Gr_Folio + grd.Grd_ID                            AS doc_key,
    gr.Gr_Fecha                                         AS fecha,
    grd.Mn_Cve_Moneda                                   AS moneda,
    ISNULL(pv.Pv_R_F_C,'')                              AS rfc,
    ISNULL(pv.Pv_Razon_Social,'')                       AS razon_social,
    ISNULL(grd.Grd_Referencia,'')                       AS referencia,
    SUM(grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio) AS subtotal_neto,
    SUM(grd.Grd_Impuesto_Importe * grd.Grd_Tipo_Cambio)          AS iva,
    SUM(grd.Grd_Precio_Neto_Importe * grd.Grd_Tipo_Cambio)       AS total,
    ISNULL(cd.Cd_Timbre_UUID,'')                        AS uuid,
    ISNULL(cd.Cd_Tipo_Comprobante_CFDI,'')              AS tipo_comprobante_cfdi
FROM Gasto_Registro gr
    INNER JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = gr.Gr_Folio
    INNER JOIN Sucursal sc ON sc.Sc_Cve_Sucursal = gr.Sc_Cve_Sucursal AND sc.Es_Cve_Estado <> 'BA'
    LEFT JOIN Proveedor pv ON pv.Pv_Cve_Proveedor = grd.Pv_Cve_Proveedor
    LEFT JOIN Comprobante_Digital cd
        ON LEFT(cd.Cd_Documento, 14) = gr.Gr_Folio + grd.Grd_ID
        AND cd.Cd_Tabla = 'GASTO_REGISTRO'
WHERE gr.Es_Cve_Estado <> 'CA'
    AND gr.Gr_Fecha BETWEEN {sql_quote(fi)} AND {sql_quote(ff)}
    AND sc.Em_Cve_Empresa = {sql_quote(empresa)}
GROUP BY
    CASE WHEN ISNULL(gr.Gr_Tabla,'') = '' THEN 'GASTO_DIRECTO' ELSE gr.Gr_Tabla END,
    gr.Gr_Folio, grd.Grd_ID, gr.Gr_Fecha, grd.Mn_Cve_Moneda,
    ISNULL(pv.Pv_R_F_C,''), ISNULL(pv.Pv_Razon_Social,''), ISNULL(grd.Grd_Referencia,''),
    ISNULL(cd.Cd_Timbre_UUID,''), ISNULL(cd.Cd_Tipo_Comprobante_CFDI,'')
"""


def _sql_compra(fi: str, ff: str, empresa: str) -> str:
    """Compra — copia la cabecera de rptrv79_01_compras_v2."""
    return f"""
SELECT
    'COMPRA'                                            AS origen,
    ''                                                  AS sub_origen,
    c.Co_Folio                                          AS folio,
    c.Co_Folio                                          AS doc_key,
    c.Co_Fecha                                          AS fecha,
    c.Mn_Cve_Moneda                                     AS moneda,
    ISNULL(pv.Pv_R_F_C,'')                              AS rfc,
    ISNULL(pv.Pv_Razon_Social,'')                       AS razon_social,
    ISNULL(c.Co_Referencia,'')                          AS referencia,
    SUM(CASE WHEN ISNULL(im.Im_cve_Impuesto,0) IN ('0001','0002','0','0003')
             THEN c.Co_Precio_Lista_Importe * c.Co_Tipo_Cambio ELSE 0 END)
      - SUM(CASE WHEN c.Co_Descuento_Global_Factor <> 0
                 THEN c.Co_Descuento_Global_Importe * c.Co_Tipo_Cambio
                 ELSE c.Co_Descuento_Importe * c.Co_Tipo_Cambio END) AS subtotal_neto,
    SUM(CASE WHEN im.Im_cve_Impuesto IN ('0001','0002')
             THEN c.Co_Impuesto_Importe * c.Co_Tipo_Cambio ELSE 0 END) AS iva,
    SUM(CASE WHEN ISNULL(im.Im_cve_Impuesto,0) IN ('0001','0002','0','0003')
             THEN c.Co_Precio_Neto_Importe * c.Co_Tipo_Cambio ELSE 0 END) AS total,
    ISNULL(cd.Cd_Timbre_UUID,'')                        AS uuid,
    ISNULL(cd.Cd_Tipo_Comprobante_CFDI,'')              AS tipo_comprobante_cfdi
FROM Compra c
    INNER JOIN Proveedor pv ON c.Pv_Cve_Proveedor = pv.Pv_Cve_Proveedor
    INNER JOIN Sucursal sc ON sc.Sc_Cve_Sucursal = c.Sc_Cve_Sucursal AND sc.Es_Cve_Estado <> 'BA'
    LEFT JOIN Comprobante_Digital cd
        ON cd.Cd_Documento LIKE c.Co_Folio + '%' AND cd.Cd_Tabla = 'COMPRA'
    LEFT JOIN Compra_Impuesto ci ON ci.Co_Folio = c.Co_Folio AND ci.Co_ID = c.Co_ID
    LEFT JOIN Impuesto im ON ci.Im_cve_Impuesto = im.Im_cve_Impuesto
WHERE c.Es_Cve_Estado <> 'CA'
    AND c.Co_Fecha BETWEEN {sql_quote(fi)} AND {sql_quote(ff)}
    AND sc.Em_Cve_Empresa = {sql_quote(empresa)}
GROUP BY
    c.Co_Folio, c.Co_Fecha, c.Mn_Cve_Moneda, ISNULL(pv.Pv_R_F_C,''),
    ISNULL(pv.Pv_Razon_Social,''), ISNULL(c.Co_Referencia,''),
    ISNULL(cd.Cd_Timbre_UUID,''), ISNULL(cd.Cd_Tipo_Comprobante_CFDI,'')
"""


def _sql_compra_indirecto(fi: str, ff: str, empresa: str) -> str:
    """Compra_Indirecto — copia la cabecera de rptrv79_02_compra_indirectos_v2."""
    return f"""
SELECT
    'COMPRA_INDIRECTO'                                  AS origen,
    ''                                                  AS sub_origen,
    ci.Ci_Folio                                         AS folio,
    ci.Ci_Folio                                         AS doc_key,
    ci.Ci_Fecha                                         AS fecha,
    ci.Mn_Cve_Moneda                                    AS moneda,
    ISNULL(pv.Pv_R_F_C,'')                              AS rfc,
    ISNULL(pv.Pv_Razon_Social,'')                       AS razon_social,
    ISNULL(ci.Ci_Referencia,'')                         AS referencia,
    SUM(ci.Ci_Precio_Lista_Importe * ci.Ci_Tipo_Cambio)
      - SUM(CASE WHEN ci.Ci_Descuento_Global_Factor <> 0
                 THEN ci.Ci_Descuento_Global_Importe * ci.Ci_Tipo_Cambio
                 ELSE ci.Ci_Descuento_Importe * ci.Ci_Tipo_Cambio END) AS subtotal_neto,
    ISNULL((SELECT SUM(Im_Importe) FROM Compra_Indirecto_Impuesto cii
            WHERE cii.Ci_Folio = ci.Ci_Folio AND cii.Im_Tasa > 0),0) AS iva,
    SUM(ci.Ci_Precio_Neto_Importe * ci.Ci_Tipo_Cambio)  AS total,
    ISNULL(cd.Cd_Timbre_UUID,'')                        AS uuid,
    ISNULL(cd.Cd_Tipo_Comprobante_CFDI,'')              AS tipo_comprobante_cfdi
FROM Compra_Indirecto ci
    INNER JOIN Proveedor pv ON ci.Pv_Cve_Proveedor = pv.Pv_Cve_Proveedor
    INNER JOIN Sucursal sc ON sc.Sc_Cve_Sucursal = ci.Sc_Cve_Sucursal AND sc.Es_Cve_Estado <> 'BA'
    LEFT JOIN Comprobante_Digital cd
        ON cd.Cd_Documento LIKE ci.Ci_Folio + '%' AND cd.Cd_Tabla = 'Compra_Indirecto'
WHERE ci.Es_Cve_Estado <> 'CA'
    AND ci.Ci_Fecha BETWEEN {sql_quote(fi)} AND {sql_quote(ff)}
    AND sc.Em_Cve_Empresa = {sql_quote(empresa)}
GROUP BY
    ci.Ci_Folio, ci.Ci_Fecha, ci.Mn_Cve_Moneda, ISNULL(pv.Pv_R_F_C,''),
    ISNULL(pv.Pv_Razon_Social,''), ISNULL(ci.Ci_Referencia,''),
    ISNULL(cd.Cd_Timbre_UUID,''), ISNULL(cd.Cd_Tipo_Comprobante_CFDI,'')
"""


def _sql_cuenta_x_pagar(fi: str, ff: str, empresa: str) -> str:
    """Cuenta_X_Pagar — copia la cabecera de rptrv79_05_cxp_libre_v2.

    `Cxp_Tabla` es el campo origen que el usuario pidio filtrar
    (cuenta_x_pagar / orden_compra); el layout original lo usa en el WHERE
    pero no lo proyecta. Aqui si se proyecta, como `sub_origen`.
    """
    ret_todas = _lista_sql(TODOS_RETENCION_CODES)
    return f"""
SELECT
    'CUENTA_X_PAGAR'                                    AS origen,
    cxp.Cxp_Tabla                                       AS sub_origen,
    cxp.Cxp_Folio                                       AS folio,
    cxp.Cxp_Folio                                       AS doc_key,
    cxp.Cxp_Fecha                                       AS fecha,
    cxp.Mn_Cve_Moneda                                   AS moneda,
    ISNULL(pv.Pv_R_F_C,'')                              AS rfc,
    ISNULL(pv.Pv_Razon_Social,'')                       AS razon_social,
    ISNULL(cxp.Cxp_Referencia,'')                       AS referencia,
    (SELECT SUM(x.Cxp_Precio_Descontado_Importe * x.Cxp_Tipo_Cambio)
       FROM Cuenta_X_Pagar x WHERE x.Cxp_Folio = cxp.Cxp_Folio) AS subtotal_neto,
    (SELECT ISNULL(SUM(i.Cxpi_Importe * x.Cxp_Tipo_Cambio),0)
       FROM Cuenta_X_Pagar x
       INNER JOIN Cuenta_X_Pagar_Impuesto i ON x.Cxp_Folio = i.Cxp_Folio
        AND i.Im_cve_Impuesto NOT IN {ret_todas}
      WHERE x.Cxp_Folio = cxp.Cxp_Folio)                AS iva,
    (SELECT SUM(x.Cxp_Precio_Neto_Importe * x.Cxp_Tipo_Cambio)
       FROM Cuenta_X_Pagar x WHERE x.Cxp_Folio = cxp.Cxp_Folio) AS total,
    ISNULL(cd.Cd_Timbre_UUID,'')                        AS uuid,
    ISNULL(cd.Cd_Tipo_Comprobante_CFDI,'')              AS tipo_comprobante_cfdi
FROM Cuenta_X_Pagar cxp
    INNER JOIN Sucursal sc ON sc.Sc_Cve_Sucursal = cxp.Sc_Cve_Sucursal
    INNER JOIN Proveedor pv ON cxp.Pv_Cve_Proveedor = pv.Pv_Cve_Proveedor
    LEFT JOIN Comprobante_Digital cd
        ON cxp.Cxp_Folio = LEFT(cd.Cd_Documento, 10) AND cd.Cd_Tabla = 'Cuenta_X_Pagar'
WHERE cxp.Es_Cve_Estado <> 'CA'
    AND cxp.Cxp_Fecha BETWEEN {sql_quote(fi)} AND {sql_quote(ff)}
    AND sc.Em_Cve_Empresa = {sql_quote(empresa)}
    AND cxp.Cxp_Tabla IN ('Cuenta_X_Pagar', 'ORDEN_COMPRA')
    AND cxp.CXP_CONCEPTO NOT IN ('0023', '0019', '0016', '0017')
    AND cxp.Pv_Cve_Proveedor <> '0000000021'
"""


def _sql_nota_credito_proveedor(fi: str, ff: str, empresa: str) -> str:
    """Nota_Credito_Proveedor — copia la cabecera de rptrv79_11_*_v2.

    `sub_origen` lleva la causa de la nota de credito, que es el campo por el
    que tiene sentido filtrar despues.
    """
    return f"""
SELECT
    'NOTA_CREDITO_PROVEEDOR'                            AS origen,
    ISNULL(nc.Cn_Cve_Causa_Nota_Credito_Proveedor,'')   AS sub_origen,
    nc.Nc_Folio                                         AS folio,
    nc.Nc_Folio                                         AS doc_key,
    nc.Nc_Fecha                                         AS fecha,
    nc.Mn_Cve_Moneda                                    AS moneda,
    ISNULL(pv.Pv_R_F_C,'')                              AS rfc,
    ISNULL(pv.Pv_Razon_Social,'')                       AS razon_social,
    ISNULL(nc.Nc_Referencia,'')                         AS referencia,
    SUM((nc.Nc_Precio_Descontado_Importe - nc.Nc_Descuento_Global_Importe) * nc.Nc_Tipo_Cambio) AS subtotal_neto,
    SUM(nc.Nc_Impuesto_Importe * nc.Nc_Tipo_Cambio)     AS iva,
    SUM(nc.Nc_Precio_Neto_Importe * nc.Nc_Tipo_Cambio)  AS total,
    ISNULL(cd.Cd_Timbre_UUID,'')                        AS uuid,
    ISNULL(cd.Cd_Tipo_Comprobante_CFDI,'')              AS tipo_comprobante_cfdi
FROM Nota_Credito_Proveedor nc
    INNER JOIN Proveedor pv ON nc.Pv_Cve_Proveedor = pv.Pv_Cve_Proveedor
    INNER JOIN Sucursal sc ON nc.Sc_Cve_Sucursal = sc.Sc_Cve_Sucursal AND sc.Es_Cve_Estado <> 'BA'
    LEFT JOIN Comprobante_Digital cd
        ON cd.Cd_Documento LIKE nc.Nc_Folio + '%' AND cd.Cd_Tabla = 'NOTA_CREDITO_PROVEEDOR'
WHERE nc.Es_Cve_Estado <> 'CA'
    AND nc.Nc_Fecha BETWEEN {sql_quote(fi)} AND {sql_quote(ff)}
    AND sc.Em_Cve_Empresa = {sql_quote(empresa)}
GROUP BY
    ISNULL(nc.Cn_Cve_Causa_Nota_Credito_Proveedor,''),
    nc.Nc_Folio, nc.Nc_Fecha, nc.Mn_Cve_Moneda, ISNULL(pv.Pv_R_F_C,''),
    ISNULL(pv.Pv_Razon_Social,''), ISNULL(nc.Nc_Referencia,''),
    ISNULL(cd.Cd_Timbre_UUID,''), ISNULL(cd.Cd_Tipo_Comprobante_CFDI,'')
"""


LAYOUTS = {
    "GASTO_REGISTRO": _sql_gasto_registro,
    "COMPRA": _sql_compra,
    "COMPRA_INDIRECTO": _sql_compra_indirecto,
    "CUENTA_X_PAGAR": _sql_cuenta_x_pagar,
    "NOTA_CREDITO_PROVEEDOR": _sql_nota_credito_proveedor,
}

# Sin layout todavia. Se cuentan aparte para que el % de conciliacion se lea
# contra un universo honesto en vez de esconder el hueco.
SIN_LAYOUT = ("CHEQUE", "ANTICIPO_CXP")

# Estados del documento de mpro frente al SAT.
CONCILIADO = "CONCILIADO"                # UUID existe en raw_sat como I/E
UUID_FUERA_IE = "UUID_NO_ES_I_NI_E"      # UUID existe en el SAT pero es P/N/T
UUID_NO_EN_SAT = "UUID_NO_EN_SAT"        # mpro tiene UUID que el SAT no conoce
SIN_UUID = "SIN_UUID_EN_MPRO"            # documento sin comprobante digital

# Sub-origenes que por definicion no generan un CFDI Recibido I/E. Medidos en
# la corrida sin filtrar de feb-2026, los tres dan 0.0% de conciliacion sobre
# 5,230 documentos, que es la evidencia de que no pertenecen al universo y no
# un hueco por resolver:
#   GASTO_REGISTRO_NOMINA  — la nomina timbra CFDI tipo N, no I/E
#   CONSUMO_INTERNO        — movimiento interno, no hay proveedor que facture
#   GASTO_RECLASIFICACION  — reasienta gasto ya registrado, importe neto cero
SIN_CFDI_POR_DEFINICION = {
    ("GASTO_REGISTRO", "GASTO_REGISTRO_NOMINA"),
    ("GASTO_REGISTRO", "CONSUMO_INTERNO"),
    ("GASTO_REGISTRO", "GASTO_RECLASIFICACION"),
}


def cargar_sat() -> pd.DataFrame:
    sql = """
SELECT upper(trim(uuid)) AS uuid, tipo_comprobante, periodo, total AS total_sat,
       subtotal AS subtotal_sat, rfc_emisor
FROM raw_sat.cfdi_recibidos
"""
    res = run_query("postgres_dw", sql)
    sat = pd.DataFrame(res["rows"], columns=res["columns"])
    sat["total_sat"] = pd.to_numeric(sat["total_sat"], errors="coerce").fillna(0.0)
    sat["subtotal_sat"] = pd.to_numeric(sat["subtotal_sat"], errors="coerce").fillna(0.0)
    return sat.drop_duplicates(subset="uuid")


def clasificar(mpro: pd.DataFrame, sat: pd.DataFrame) -> pd.DataFrame:
    """Cruza el layout unificado de mpro contra el SAT y etiqueta cada
    documento con su estado (CONCILIADO / UUID_FUERA_IE / UUID_NO_EN_SAT /
    SIN_UUID)."""
    df = mpro.merge(sat, on="uuid", how="left", suffixes=("", "_sat"))
    tiene_uuid = df["uuid"] != ""
    en_sat = df["tipo_comprobante"].notna()
    es_ie = df["tipo_comprobante"].isin(["I", "E"])

    df["estado"] = SIN_UUID
    df.loc[tiene_uuid & ~en_sat, "estado"] = UUID_NO_EN_SAT
    df.loc[tiene_uuid & en_sat & ~es_ie, "estado"] = UUID_FUERA_IE
    df.loc[tiene_uuid & en_sat & es_ie, "estado"] = CONCILIADO
    return df


def cobertura_sat(conc: pd.DataFrame, periodos: list[str]) -> pd.DataFrame:
    """Cuanto del universo SAT del periodo alcanza a explicar este cruce.

    Es el puente con el reporte SAT -> mpro (pages/recibido_conciliacion.py):
    alli el universo es el CFDI y aqui el documento de mpro, asi que los
    porcentajes no son comparables, pero el importe alcanzado si deberia
    parecerse.
    """
    lista = ", ".join(f"'{p}'" for p in periodos)
    sql = f"""
SELECT periodo, tipo_comprobante, COUNT(*) AS cfdi, SUM(total) AS total_sat
FROM raw_sat.cfdi_recibidos
WHERE tipo_comprobante IN ('I','E') AND periodo IN ({lista})
GROUP BY periodo, tipo_comprobante
"""
    res = run_query("postgres_dw", sql)
    universo = pd.DataFrame(res["rows"], columns=res["columns"])
    universo["total_sat"] = pd.to_numeric(universo["total_sat"], errors="coerce").fillna(0.0)

    alcanzado = (conc.drop_duplicates("uuid")
                 .groupby(["periodo", "tipo_comprobante"])
                 .agg(cfdi_alcanzados=("uuid", "size"), total_alcanzado=("total_sat", "sum"))
                 .reset_index())
    out = universo.merge(alcanzado, on=["periodo", "tipo_comprobante"], how="left").fillna(0)
    out["pct_cfdi"] = (out["cfdi_alcanzados"] / out["cfdi"] * 100).round(1)
    out["pct_importe"] = (out["total_alcanzado"] / out["total_sat"] * 100).round(1)
    return out


def tabla_por(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    """Documentos e importe mpro por corte, con su % conciliado."""
    if df.empty:
        cols = columnas + ["docs", "importe_mpro", "docs_conc", "importe_conc", "pct_docs", "pct_importe"]
        return pd.DataFrame(columns=cols)
    g = df.groupby(columnas, dropna=False)
    out = g.agg(
        docs=("folio", "size"),
        importe_mpro=("total", "sum"),
        docs_conc=("estado", lambda s: (s == CONCILIADO).sum()),
    ).reset_index()
    conc = df[df["estado"] == CONCILIADO].groupby(columnas, dropna=False)["total"].sum()
    out = out.merge(conc.rename("importe_conc").reset_index(), on=columnas, how="left")
    out["importe_conc"] = out["importe_conc"].fillna(0.0)
    out["pct_docs"] = (out["docs_conc"] / out["docs"] * 100).round(1)
    out["pct_importe"] = (out["importe_conc"] / out["importe_mpro"].replace(0, float("nan")) * 100).round(1)
    return out.sort_values("importe_mpro", ascending=False)


def cargar_documentos(fecha_ini: str, fecha_fin: str, empresa: str = "0001") -> pd.DataFrame:
    """Layout unificado a grano documento. Fechas en 'YYYYMMDD'."""
    partes = []
    for origen, constructor in LAYOUTS.items():
        res = run_query(MPRO_TARGET, constructor(fecha_ini, fecha_fin, empresa))
        df = pd.DataFrame(res["rows"], columns=res["columns"])
        partes.append(df)
    out = pd.concat(partes, ignore_index=True)[COLUMNAS]
    for col in ("subtotal_neto", "iva", "total"):
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    out["uuid"] = out["uuid"].fillna("").str.strip().str.upper()
    return out


def contar_sin_layout(fecha_ini: str, fecha_fin: str) -> pd.DataFrame:
    """Cuantos CFDI hay colgados de CHEQUE / ANTICIPO_CXP en el periodo.

    No es el layout (no existe todavia) — es el tamano del hueco, medido
    desde Comprobante_Digital, para poder reportarlo en vez de ignorarlo.
    """
    tablas = _lista_sql(SIN_LAYOUT)
    sql = f"""
SELECT cd.Cd_Tabla AS origen,
       COUNT(*) AS comprobantes,
       COUNT(DISTINCT cd.Cd_Timbre_UUID) AS uuids,
       SUM(ISNULL(cd.Cd_Monto,0)) AS monto_cfdi
FROM Comprobante_Digital cd
WHERE cd.Cd_Tabla IN {tablas}
    AND cd.Cd_Timbre_Fecha BETWEEN {sql_quote(fecha_ini)} AND {sql_quote(fecha_fin)}
GROUP BY cd.Cd_Tabla
"""
    res = run_query(MPRO_TARGET, sql)
    return pd.DataFrame(res["rows"], columns=res["columns"])
