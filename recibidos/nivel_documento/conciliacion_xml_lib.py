"""
Libreria compartida de los reportes 02/03/04 de conciliacion XML recibido
<-> registro de MPro (.205 / TRIVASADB3).

Tres piezas:

1. `xml_recibidos()`  -- universo de CFDI RECIBIDOS desde `Comprobante_Digital`,
   con el XML crudo (`Cd_XML`) parseado: subtotal / descuento / total /
   impuestos trasladados y retenidos a nivel COMPROBANTE.
2. `registros_mpro()` -- cabeceras de los modulos de MPro que reciben CFDI
   (gasto, compra, cxp, cheque, anticipo, compra indirecta, nota de credito
   de proveedor, factura), normalizadas a un shape unico
   ORIGEN/FOLIO/DOC_ID/SUBTOTAL/IMPUESTOS/TOTAL.
3. `impuestos_mpro()` -- detalle de impuestos por documento, normalizado al
   codigo del SAT (001 ISR / 002 IVA / 003 IEPS) usando el catalogo
   `Impuesto.Im_Codigo_SAT`, y separado en TRASLADO vs RETENCION.

Decisiones tomadas y VERIFICADAS contra la BD el 2026-09-04 (no heredadas
de documentacion previa):

- "Recibido" = `Cd_RFC_Receptor = TRI970922TL2` y `Cd_RFC_Emisor <> ese`.
  Verificado en enero 2026: la clasificacion por RFC es limpia y no ambigua
  -- COMPRA/CHEQUE/CUENTA_X_PAGAR/NOTA_CREDITO_PROVEEDOR/ANTICIPO_CXP/
  COMPRA_INDIRECTO son 100% recibidos; COMPROBANTE_PAGO/NOTA_CREDITO/
  CONSTANCIA_RETENCION son 100% emitidos; FACTURA es 99.6% emitida (8 filas
  recibidas, ver hallazgos); GASTO_REGISTRO es 98% recibido.
- `Cd_Tabla='TRASLADO'` (3,686 filas en enero) queda FUERA del universo:
  es 100% AUTOEMITIDO (emisor = receptor = TRI970922TL2), Cd_Monto = 0,
  moneda XXX -- carta porte, sin importe que conciliar. Se cuenta aparte.
- Llave de union XML -> registro: `LEFT(Cd_Documento,10)` = folio del modulo.
  Verificado: 100% de match contra la tabla de cada origen en enero (1,301
  folios de gasto, 692 de compra, 342 de cheque, 84 de cxp, 6 de ncp, 1 de
  anticipo, 1 de compra indirecta, 8 de factura).
  Para GASTO_REGISTRO hay un segundo nivel: `SUBSTRING(Cd_Documento,11,4)`
  = `Grd_ID` (100% de match contra Gasto_Registro_Documento, tanto en los
  Cd_Documento de 14 chars como en los de 18). En los demas modulos ese
  mismo tramo es un CONSECUTIVO de comprobante por folio (ej. COMPRA
  05-0029612 tiene sufijo 0002 y un solo registro), no un sub-documento.
- Impuestos del XML: se leen SOLO del nodo `cfdi:Impuestos` hijo directo de
  `cfdi:Comprobante`. El mismo nodo existe dentro de cada `cfdi:Concepto`;
  sumar ambos duplica el IVA (bug ya visto en el ELT de raw_sat, aqui se
  evita por construccion usando `find('{*}Impuestos')` sobre la raiz).
- Impuestos de MPro: el signo de `Impuesto.Im_Tasa` separa traslado (> 0) de
  retencion (< 0). El codigo SAT sale de `Impuesto.Im_Codigo_SAT`
  (001/002/003). Dos claves del catalogo NO son impuestos de CFDI aunque
  traigan codigo SAT: `0022` IMSS PATRON (Im_Codigo_SAT='001', tasa +1) y
  `0019`/`0020`/`0021` (nomina) -- se marcan como NO_CFDI y se excluyen de
  la comparacion, contandolas aparte.

Uso: los tres scripts (`02_`, `03_`, `04_`) importan de aqui.
"""
import re
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
from sqlalchemy import text

from connection_205_trivasadb3 import engine

RFC_TRIVASA = "TRI970922TL2"

# Modulos de Comprobante_Digital que documentan un CFDI RECIBIDO (compra o
# gasto). TRASLADO se excluye a proposito (autoemitido, ver docstring); los
# modulos de venta (COMPROBANTE_PAGO, NOTA_CREDITO, CONSTANCIA_RETENCION)
# no aparecen nunca como recibidos y por eso no se listan.
ORIGENES_RECIBIDOS = [
    "GASTO_REGISTRO",
    "COMPRA",
    "CHEQUE",
    "CUENTA_X_PAGAR",
    "ANTICIPO_CXP",
    "COMPRA_INDIRECTO",
    "NOTA_CREDITO_PROVEEDOR",
    "FACTURA",
]

# Claves del catalogo Impuesto que traen Im_Codigo_SAT pero NO son impuestos
# trasladados/retenidos de un CFDI de proveedor (son provisiones de nomina).
IMPUESTOS_NO_CFDI = {"0019", "0020", "0021", "0022"}

SAT_NOMBRE = {"001": "ISR", "002": "IVA", "003": "IEPS"}


# ---------------------------------------------------------------------------
# 1. XML recibidos
# ---------------------------------------------------------------------------

CD_SQL = """
SELECT
    cd.Cd_Tabla                        AS ORIGEN,
    cd.Cd_Documento                    AS CD_DOCUMENTO,
    UPPER(LTRIM(RTRIM(cd.Cd_Timbre_UUID))) AS UUID,
    cd.Cd_Timbre_Fecha                 AS FECHA_TIMBRADO,
    LTRIM(RTRIM(cd.Cd_RFC_Emisor))     AS RFC_EMISOR,
    LTRIM(RTRIM(cd.Cd_RFC_Receptor))   AS RFC_RECEPTOR,
    cd.Cd_Monto                        AS CD_MONTO,
    cd.Cd_Moneda                       AS CD_MONEDA,
    cd.Cd_Tipo_CFDI                    AS CD_TIPO_CFDI,
    cd.Cd_Serie_Folio                  AS CD_SERIE_FOLIO,
    cd.Es_Cve_Estado                   AS CD_ESTADO,
    CAST(cd.Cd_XML AS nvarchar(MAX))   AS XML
FROM Comprobante_Digital cd
WHERE cd.Cd_Timbre_Fecha >= :fi AND cd.Cd_Timbre_Fecha < :ff
  AND LTRIM(RTRIM(cd.Cd_RFC_Receptor)) = :rfc
  AND LTRIM(RTRIM(cd.Cd_RFC_Emisor)) <> :rfc
  AND cd.Cd_Timbre_UUID IS NOT NULL AND LTRIM(RTRIM(cd.Cd_Timbre_UUID)) <> ''
"""

# Igual que CD_SQL pero SIN filtro de fecha y sin traer el XML -- para el
# reporte 04, donde la base son los registros de MPro del mes y el XML puede
# haberse timbrado en otro mes (caso real: compra 05-0029612 con Co_Fecha
# 2025-12-31 y XML timbrado en enero).
CD_LIGERO_SQL = """
SELECT
    cd.Cd_Tabla                        AS ORIGEN,
    cd.Cd_Documento                    AS CD_DOCUMENTO,
    UPPER(LTRIM(RTRIM(cd.Cd_Timbre_UUID))) AS UUID,
    cd.Cd_Timbre_Fecha                 AS FECHA_TIMBRADO,
    LTRIM(RTRIM(cd.Cd_RFC_Emisor))     AS RFC_EMISOR,
    cd.Cd_Monto                        AS CD_MONTO,
    cd.Cd_Tipo_CFDI                    AS CD_TIPO_CFDI,
    cd.Cd_Serie_Folio                  AS CD_SERIE_FOLIO,
    cd.Es_Cve_Estado                   AS CD_ESTADO
FROM Comprobante_Digital cd
WHERE LTRIM(RTRIM(cd.Cd_RFC_Receptor)) = :rfc
  AND LTRIM(RTRIM(cd.Cd_RFC_Emisor)) <> :rfc
  AND cd.Cd_Timbre_UUID IS NOT NULL AND LTRIM(RTRIM(cd.Cd_Timbre_UUID)) <> ''
"""

CD_AUTOEMITIDO_SQL = """
SELECT cd.Cd_Tabla AS ORIGEN, COUNT(*) AS N, SUM(cd.Cd_Monto) AS MONTO
FROM Comprobante_Digital cd
WHERE cd.Cd_Timbre_Fecha >= :fi AND cd.Cd_Timbre_Fecha < :ff
  AND LTRIM(RTRIM(cd.Cd_RFC_Receptor)) = :rfc
  AND LTRIM(RTRIM(cd.Cd_RFC_Emisor)) = :rfc
GROUP BY cd.Cd_Tabla
"""


def _f(v):
    """float() tolerante: '' / None / basura -> 0.0"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def parsear_cfdi(xml_str):
    """Extrae del CFDI los campos fiscales a nivel COMPROBANTE.

    Namespace-agnostico (`{*}`) porque conviven CFDI 3.3 y 4.0. Los impuestos
    se leen del nodo `Impuestos` hijo DIRECTO de la raiz -- nunca de los
    `Impuestos` que cuelgan de cada `Concepto` (sumarlos duplica el IVA).
    """
    vacio = {
        "XML_OK": False, "XML_ERROR": "", "XML_VERSION": "", "XML_FECHA": pd.NaT,
        "XML_SERIE": "", "XML_FOLIO": "", "XML_TIPO": "", "XML_MONEDA": "",
        "XML_TIPO_CAMBIO": 1.0, "XML_METODO_PAGO": "", "XML_FORMA_PAGO": "",
        "XML_EMISOR_NOMBRE": "", "XML_USO_CFDI": "",
        "XML_SUBTOTAL": 0.0, "XML_DESCUENTO": 0.0, "XML_TOTAL": 0.0,
        "XML_IVA_TRASLADADO": 0.0, "XML_IEPS_TRASLADADO": 0.0,
        "XML_RET_IVA": 0.0, "XML_RET_ISR": 0.0,
        "XML_TRASLADOS_TOTAL": 0.0, "XML_RETENIDOS_TOTAL": 0.0,
        "XML_BASE_EXENTA": 0.0, "XML_PAGOS_MONTO": 0.0, "XML_PAGOS_IVA": 0.0,
        "XML_N_CONCEPTOS": 0,
        # Importe que NO viaja en el Total del comprobante sino en un
        # complemento -- ver `parsear_cfdi` y COMPLEMENTOS_CON_IMPORTE.
        "XML_COMPLEMENTOS": "", "XML_VALES_DESPENSA": 0.0, "XML_VALES_N_TRAB": 0,
        "XML_IMP_LOCAL_TRAS": 0.0, "XML_IMP_LOCAL_RET": 0.0,
        "XML_DR_UUIDS": "", "XML_DR_PAGADO": 0.0,
    }
    if not xml_str or not xml_str.strip():
        return {**vacio, "XML_ERROR": "Cd_XML vacio"}
    try:
        root = ET.fromstring(xml_str.encode("utf-8", "ignore"))
    except Exception as e:  # XML corrupto / pagina HTML guardada como .xml
        return {**vacio, "XML_ERROR": f"{type(e).__name__}: {e}"[:120]}

    a = root.attrib
    r = dict(vacio)
    r["XML_OK"] = True
    r["XML_VERSION"] = a.get("Version") or a.get("version") or ""
    r["XML_FECHA"] = pd.to_datetime(a.get("Fecha") or a.get("fecha"), errors="coerce")
    r["XML_SERIE"] = a.get("Serie", "")
    r["XML_FOLIO"] = a.get("Folio", "")
    r["XML_TIPO"] = a.get("TipoDeComprobante", "")
    r["XML_MONEDA"] = a.get("Moneda", "")
    r["XML_TIPO_CAMBIO"] = _f(a.get("TipoCambio")) or 1.0
    r["XML_METODO_PAGO"] = a.get("MetodoPago", "")
    r["XML_FORMA_PAGO"] = a.get("FormaPago", "")
    r["XML_SUBTOTAL"] = _f(a.get("SubTotal"))
    r["XML_DESCUENTO"] = _f(a.get("Descuento"))
    r["XML_TOTAL"] = _f(a.get("Total"))

    em = root.find("{*}Emisor")
    if em is not None:
        r["XML_EMISOR_NOMBRE"] = em.get("Nombre", "")
    rec = root.find("{*}Receptor")
    if rec is not None:
        r["XML_USO_CFDI"] = rec.get("UsoCFDI", "")
    conceptos = root.find("{*}Conceptos")
    if conceptos is not None:
        r["XML_N_CONCEPTOS"] = len(conceptos.findall("{*}Concepto"))

    imp = root.find("{*}Impuestos")  # hijo DIRECTO -- no el de los conceptos
    if imp is not None:
        r["XML_TRASLADOS_TOTAL"] = _f(imp.get("TotalImpuestosTrasladados"))
        r["XML_RETENIDOS_TOTAL"] = _f(imp.get("TotalImpuestosRetenidos"))
        tr = imp.find("{*}Traslados")
        if tr is not None:
            for t in tr.findall("{*}Traslado"):
                cod, tf, importe = t.get("Impuesto", ""), t.get("TipoFactor", ""), _f(t.get("Importe"))
                if tf == "Exento":
                    r["XML_BASE_EXENTA"] += _f(t.get("Base"))
                elif cod == "002":
                    r["XML_IVA_TRASLADADO"] += importe
                elif cod == "003":
                    r["XML_IEPS_TRASLADADO"] += importe
        re_ = imp.find("{*}Retenciones")
        if re_ is not None:
            for t in re_.findall("{*}Retencion"):
                cod, importe = t.get("Impuesto", ""), _f(t.get("Importe"))
                if cod == "002":
                    r["XML_RET_IVA"] += importe
                elif cod == "001":
                    r["XML_RET_ISR"] += importe

    # El Total del comprobante NO siempre es el importe de la operacion:
    # hay complementos del SAT que lo llevan por dentro. Censados en el
    # universo de enero 2026: Pagos (416), ValesDeDespensa (19),
    # ImpuestosLocales (12). EstadoDeCuentaCombustible (436) y CartaPorte
    # (290) NO mueven el importe -- su Total del comprobante ya es el bueno,
    # verificado contra los 436 CFDI de combustible del mes.
    comp = root.find("{*}Complemento")
    if comp is not None:
        r["XML_COMPLEMENTOS"] = ";".join(sorted({c.tag.split("}")[-1] for c in comp
                                                 if c.tag.split("}")[-1] != "TimbreFiscalDigital"}))
        # CFDI de Pago (tipo P): Total/SubTotal son 0 por diseno del SAT.
        pagos = comp.find("{*}Pagos")
        if pagos is not None:
            tot = pagos.find("{*}Totales")
            if tot is not None:
                r["XML_PAGOS_MONTO"] = _f(tot.get("MontoTotalPagos"))
                r["XML_PAGOS_IVA"] = (
                    _f(tot.get("TotalTrasladosImpuestoIVA16"))
                    + _f(tot.get("TotalTrasladosImpuestoIVA8"))
                )
            drs = []
            for p in pagos.findall("{*}Pago"):
                # `tot is None`, no `not tot`: <Totales/> es un elemento sin
                # hijos y su valor de verdad es False -- eso duplicaba el monto.
                if tot is None:
                    r["XML_PAGOS_MONTO"] += _f(p.get("Monto"))
                for dr in p.findall("{*}DoctoRelacionado"):
                    u = (dr.get("IdDocumento") or "").upper().strip()
                    if u:
                        drs.append(u)
                    r["XML_DR_PAGADO"] += _f(dr.get("ImpPagado"))
            r["XML_DR_UUIDS"] = ";".join(sorted(set(drs)))
        # Vales de despensa: el comprobante se timbra por la COMISION (a
        # veces $0.01) y la dispersion real -- desglosada por trabajador --
        # vive en el atributo `total` del complemento. Enero 2026: 19 CFDI
        # con Total $0.01 cada uno y $792,344.95 en el complemento.
        vales = comp.find("{*}ValesDeDespensa")
        if vales is not None:
            r["XML_VALES_DESPENSA"] = _f(vales.get("total"))
            cs = vales.find("{*}Conceptos")
            r["XML_VALES_N_TRAB"] = len(cs) if cs is not None else 0
        # Impuestos locales (ISH y similares): MPro los suma dentro de su
        # columna de impuestos, asi que hay que leerlos o el IVA descuadra.
        iloc = comp.find("{*}ImpuestosLocales")
        if iloc is not None:
            r["XML_IMP_LOCAL_TRAS"] = _f(iloc.get("TotaldeTraslados"))
            r["XML_IMP_LOCAL_RET"] = _f(iloc.get("TotaldeRetenciones"))
    return r


def xml_recibidos(fi, ff, con_xml=True):
    """CFDI recibidos timbrados en [fi, ff). Grano: (ORIGEN, CD_DOCUMENTO)."""
    sql = CD_SQL if con_xml else CD_LIGERO_SQL
    params = {"rfc": RFC_TRIVASA}
    if con_xml:
        params |= {"fi": fi, "ff": ff}
    df = pd.read_sql(text(sql), engine, params=params)
    for c in ("ORIGEN", "CD_DOCUMENTO", "UUID", "RFC_EMISOR", "CD_SERIE_FOLIO", "CD_ESTADO"):
        if c in df.columns:
            df[c] = df[c].astype("string").fillna("").str.strip()
    df["FOLIO"] = df["CD_DOCUMENTO"].str[:10].str.strip()
    # Segundo nivel de llave: solo GASTO_REGISTRO lo tiene (= Grd_ID).
    df["DOC_ID"] = ""
    m = df["ORIGEN"] == "GASTO_REGISTRO"
    df.loc[m, "DOC_ID"] = df.loc[m, "CD_DOCUMENTO"].str[10:14]

    if con_xml:
        parsed = pd.DataFrame([parsear_cfdi(x) for x in df["XML"]], index=df.index)
        df = pd.concat([df.drop(columns=["XML"]), parsed], axis=1)
    return df


MONTO_POR_UUID_SQL = """
SELECT UPPER(LTRIM(RTRIM(Cd_Timbre_UUID))) AS UUID, MAX(Cd_Monto) AS MONTO
FROM Comprobante_Digital
WHERE UPPER(LTRIM(RTRIM(Cd_Timbre_UUID))) IN ({lista})
GROUP BY UPPER(LTRIM(RTRIM(Cd_Timbre_UUID)))
"""


def montos_por_uuid(uuids):
    """{UUID: Cd_Monto} para los comprobantes que un REP dice liquidar.
    Sirve para detectar el caso en que un REP paga mucho mas de lo que dice
    el Total de la factura -- senal de que el importe real de esa factura
    viaja en un complemento (vales de despensa) y no en el comprobante."""
    vals = sorted({u for u in uuids if u and re.match(r"^[0-9A-Fa-f-]{10,50}$", u)})
    out = {}
    for i in range(0, len(vals), 500):
        lista = ", ".join("'" + v + "'" for v in vals[i:i + 500])
        d = pd.read_sql(text(MONTO_POR_UUID_SQL.format(lista=lista)), engine)
        out |= dict(zip(d.UUID.astype(str), pd.to_numeric(d.MONTO, errors="coerce").fillna(0.0)))
    return out


EMPRESAS_SQL = "SELECT Em_Cve_Empresa, Em_Descripcion, LTRIM(RTRIM(Em_R_F_C)) RFC FROM Empresa"


def rfcs_del_grupo():
    """RFC de las OTRAS empresas que viven en la misma base de MPro.

    `TRIVASADB3` alberga varias razones sociales del grupo (Trivasa 0001,
    Facilitadores de la Construccion 0002, Flexbeel 0003, Triturados de
    Valladolid 0004). Un CFDI emitido por una de ellas a Trivasa ES un
    comprobante recibido -- operacion intercompania real -- pero su registro
    vive en el modulo de VENTA de la otra empresa, que estos reportes no
    leen. Sin esta marca esos grupos salen como 'SIN_REGISTRO' y se leen
    como hueco cuando no lo son.

    Medido: enero 2026, 83 CFDI intercompania; febrero, 22."""
    d = pd.read_sql(text(EMPRESAS_SQL), engine)
    d["RFC"] = d.RFC.astype("string").fillna("").str.strip()
    return {r.RFC: r.Em_Descripcion for r in d.itertuples() if r.RFC and r.RFC != RFC_TRIVASA}


def autoemitidos(fi, ff):
    """Conteo de CFDI con Trivasa como emisor Y receptor (carta porte)."""
    return pd.read_sql(text(CD_AUTOEMITIDO_SQL), engine,
                       params={"fi": fi, "ff": ff, "rfc": RFC_TRIVASA})


# ---------------------------------------------------------------------------
# 2. Registros de MPro, normalizados
# ---------------------------------------------------------------------------
# Shape unico: ORIGEN, FOLIO, DOC_ID, FECHA, ESTADO, SUBORIGEN, PROVEEDOR,
#              MONEDA, TIPO_CAMBIO, SUBTOTAL, IMPUESTOS, TOTAL
# DOC_ID solo se usa en GASTO_REGISTRO (Grd_ID); en el resto va ''.

REG_SQL = {
    "GASTO_REGISTRO": """
        SELECT 'GASTO_REGISTRO' ORIGEN, grd.Gr_Folio FOLIO, grd.Grd_ID DOC_ID,
               gr.Gr_Fecha FECHA, gr.Es_Cve_Estado ESTADO,
               CASE WHEN ISNULL(gr.Gr_Tabla,'')='' THEN 'GASTO_DIRECTO' ELSE gr.Gr_Tabla END SUBORIGEN,
               grd.Pv_Cve_Proveedor PROVEEDOR, grd.Mn_Cve_Moneda MONEDA, grd.Grd_Tipo_Cambio TIPO_CAMBIO,
               grd.Grd_Precio_Descontado_Importe SUBTOTAL, grd.Grd_Impuesto_Importe IMPUESTOS,
               grd.Grd_Precio_Neto_Importe TOTAL,
               ISNULL(tg.Tg_Descripcion, grd.Tg_Cve_Tipo_Gasto) CONCEPTO
        FROM Gasto_Registro_Documento grd
        JOIN Gasto_Registro gr ON gr.Gr_Folio = grd.Gr_Folio
        LEFT JOIN Tipo_Gasto tg ON tg.Tg_Cve_Tipo_Gasto = grd.Tg_Cve_Tipo_Gasto
        WHERE {filtro}
    """,
    "COMPRA": """
        SELECT 'COMPRA' ORIGEN, ce.Co_Folio FOLIO, '' DOC_ID, ce.Co_Fecha FECHA,
               ce.Es_Cve_Estado ESTADO,
               CASE WHEN ISNULL(ce.Co_Tabla,'')='' THEN 'COMPRA_DIRECTA' ELSE ce.Co_Tabla END SUBORIGEN,
               ce.Pv_Cve_Proveedor PROVEEDOR, ce.Mn_Cve_Moneda MONEDA, ce.Co_Tipo_Cambio TIPO_CAMBIO,
               ce.Co_Precio_Descontado_Importe SUBTOTAL, ce.Co_Impuesto_Importe IMPUESTOS,
               ce.Co_Precio_Neto_Importe TOTAL, ce.Co_Referencia CONCEPTO
        FROM Compra_Encabezado ce
        WHERE {filtro}
    """,
    "CUENTA_X_PAGAR": """
        SELECT 'CUENTA_X_PAGAR' ORIGEN, cx.Cxp_Folio FOLIO, '' DOC_ID, cx.Cxp_Fecha FECHA,
               cx.Es_Cve_Estado ESTADO,
               CASE WHEN ISNULL(cx.Cxp_Tabla,'')='' THEN '(sin origen)'
                    WHEN CHARINDEX(':', cx.Cxp_Tabla) > 0 THEN LEFT(cx.Cxp_Tabla, CHARINDEX(':', cx.Cxp_Tabla)-1)
                    ELSE cx.Cxp_Tabla END SUBORIGEN,
               cx.Pv_Cve_Proveedor PROVEEDOR, cx.Mn_Cve_Moneda MONEDA, cx.Cxp_Tipo_Cambio TIPO_CAMBIO,
               cx.Cxp_Precio_Descontado_Importe SUBTOTAL, cx.Cxp_Impuesto_Importe IMPUESTOS,
               cx.Cxp_Precio_Neto_Importe TOTAL, cx.Cxp_Concepto CONCEPTO
        FROM Cuenta_X_Pagar cx
        WHERE {filtro}
    """,
    "CHEQUE": """
        SELECT 'CHEQUE' ORIGEN, ch.Ch_Folio FOLIO, '' DOC_ID, ch.Ch_Fecha FECHA,
               ch.Es_Cve_Estado ESTADO,
               CASE WHEN ISNULL(ch.Ch_Tabla,'')='' THEN '(sin origen)'
                    WHEN CHARINDEX(':', ch.Ch_Tabla) > 0 THEN LEFT(ch.Ch_Tabla, CHARINDEX(':', ch.Ch_Tabla)-1)
                    ELSE ch.Ch_Tabla END SUBORIGEN,
               ch.Ch_Beneficiario PROVEEDOR, 'MXN' MONEDA, ch.Ch_Tipo_Cambio TIPO_CAMBIO,
               CAST(NULL AS money) SUBTOTAL, CAST(NULL AS money) IMPUESTOS, ch.Ch_Importe TOTAL,
               ch.Ch_Concepto CONCEPTO
        FROM Cheque ch
        WHERE {filtro}
    """,
    "ANTICIPO_CXP": """
        SELECT 'ANTICIPO_CXP' ORIGEN, an.An_Folio FOLIO, '' DOC_ID, an.An_Fecha FECHA,
               an.Es_Cve_Estado ESTADO,
               CASE WHEN ISNULL(an.An_Tabla,'')='' THEN '(sin origen)' ELSE an.An_Tabla END SUBORIGEN,
               an.Pv_Cve_Proveedor PROVEEDOR, an.Mn_Cve_Moneda MONEDA, an.An_Tipo_Cambio TIPO_CAMBIO,
               CAST(NULL AS money) SUBTOTAL, CAST(NULL AS money) IMPUESTOS, an.An_Importe TOTAL,
               an.An_Comentario CONCEPTO
        FROM Anticipo_CXP an
        WHERE {filtro}
    """,
    "COMPRA_INDIRECTO": """
        SELECT 'COMPRA_INDIRECTO' ORIGEN, ci.Ci_Folio FOLIO, '' DOC_ID, MIN(ci.Ci_Fecha) FECHA,
               MIN(ci.Es_Cve_Estado) ESTADO, MIN(ISNULL(NULLIF(ci.Ci_Tabla,''),'(sin origen)')) SUBORIGEN,
               MIN(ci.Pv_Cve_Proveedor) PROVEEDOR, MIN(ci.Mn_Cve_Moneda) MONEDA, MIN(ci.Ci_Tipo_Cambio) TIPO_CAMBIO,
               SUM(ci.Ci_Precio_Descontado_Importe) SUBTOTAL, SUM(ci.Ci_Impuesto_Importe) IMPUESTOS,
               SUM(ci.Ci_Precio_Neto_Importe) TOTAL, MIN(ci.Ci_Comentario) CONCEPTO
        FROM Compra_Indirecto ci
        WHERE {filtro}
        GROUP BY ci.Ci_Folio
    """,
    "NOTA_CREDITO_PROVEEDOR": """
        SELECT 'NOTA_CREDITO_PROVEEDOR' ORIGEN, nc.Nc_Folio FOLIO, '' DOC_ID, MIN(nc.Nc_Fecha) FECHA,
               MIN(nc.Es_Cve_Estado) ESTADO, MIN(ISNULL(NULLIF(nc.Nc_Tabla,''),'(sin origen)')) SUBORIGEN,
               MIN(nc.Pv_Cve_Proveedor) PROVEEDOR, MIN(nc.Mn_Cve_Moneda) MONEDA, MIN(nc.Nc_Tipo_Cambio) TIPO_CAMBIO,
               SUM(nc.Nc_Precio_Descontado_Importe) SUBTOTAL, SUM(nc.Nc_Impuesto_Importe) IMPUESTOS,
               SUM(nc.Nc_Precio_Neto_Importe) TOTAL, MIN(nc.Nc_Comentario) CONCEPTO
        FROM Nota_Credito_Proveedor nc
        WHERE {filtro}
        GROUP BY nc.Nc_Folio
    """,
    "FACTURA": """
        SELECT 'FACTURA' ORIGEN, fe.Fc_Folio FOLIO, '' DOC_ID, fe.Fc_Fecha FECHA,
               fe.Es_Cve_Estado ESTADO,
               CASE WHEN ISNULL(fe.Fc_Tabla,'')='' THEN '(sin origen)' ELSE fe.Fc_Tabla END SUBORIGEN,
               fe.Cl_Cve_Cliente PROVEEDOR, fe.Mn_Cve_Moneda MONEDA, fe.Fc_Tipo_Cambio TIPO_CAMBIO,
               fe.Fc_Precio_Descontado_Importe SUBTOTAL, fe.Fc_Impuesto_Importe IMPUESTOS,
               fe.Fc_Precio_Neto_Importe TOTAL, fe.Fc_Referencia CONCEPTO
        FROM Factura_Encabezado fe
        WHERE {filtro}
    """,
}

# Columna de fecha y columna de folio de cada modulo -- las dos formas de
# acotar el universo: por mes (reporte 04) o por lista de folios (02/03).
FILTRO_FECHA = {
    "GASTO_REGISTRO": "gr.Gr_Fecha",
    "COMPRA": "ce.Co_Fecha",
    "CUENTA_X_PAGAR": "cx.Cxp_Fecha",
    "CHEQUE": "ch.Ch_Fecha",
    "ANTICIPO_CXP": "an.An_Fecha",
    "COMPRA_INDIRECTO": "ci.Ci_Fecha",
    "NOTA_CREDITO_PROVEEDOR": "nc.Nc_Fecha",
    "FACTURA": "fe.Fc_Fecha",
}
FILTRO_FOLIO = {
    "GASTO_REGISTRO": "grd.Gr_Folio",
    "COMPRA": "ce.Co_Folio",
    "CUENTA_X_PAGAR": "cx.Cxp_Folio",
    "CHEQUE": "ch.Ch_Folio",
    "ANTICIPO_CXP": "an.An_Folio",
    "COMPRA_INDIRECTO": "ci.Ci_Folio",
    "NOTA_CREDITO_PROVEEDOR": "nc.Nc_Folio",
    "FACTURA": "fe.Fc_Folio",
}

_FOLIO_OK = re.compile(r"^[A-Za-z0-9 ._/-]{1,30}$")


def _in_list(col, folios):
    """IN (...) con los folios saneados. Los folios salen de la propia BD
    (Cd_Documento), pero se filtran igual antes de inyectarlos."""
    vals = sorted({f for f in folios if f and _FOLIO_OK.match(f)})
    if not vals:
        return "1=0", []
    return col, vals


def _leer_por_folios(origen, folios, sql_dict, chunk=500):
    col, vals = _in_list(FILTRO_FOLIO[origen], folios)
    if col == "1=0":
        return pd.DataFrame()
    partes = []
    for i in range(0, len(vals), chunk):
        lista = ", ".join("'" + v.replace("'", "''") + "'" for v in vals[i:i + chunk])
        sql = sql_dict[origen].format(filtro=f"{col} IN ({lista})")
        partes.append(pd.read_sql(text(sql), engine))
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def _normalizar_reg(df):
    for c in ("ORIGEN", "FOLIO", "DOC_ID", "ESTADO", "SUBORIGEN", "PROVEEDOR", "MONEDA", "CONCEPTO"):
        df[c] = df[c].astype("string").fillna("").str.strip()
    for c in ("SUBTOTAL", "IMPUESTOS", "TOTAL", "TIPO_CAMBIO"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def registros_mpro_por_mes(fi, ff, origenes=None):
    """Cabeceras normalizadas de los modulos de MPro fechados en [fi, ff)."""
    origenes = origenes or list(REG_SQL)
    partes = []
    for o in origenes:
        sql = REG_SQL[o].format(filtro=f"{FILTRO_FECHA[o]} >= :fi AND {FILTRO_FECHA[o]} < :ff")
        partes.append(pd.read_sql(text(sql), engine, params={"fi": fi, "ff": ff}))
    return _normalizar_reg(pd.concat(partes, ignore_index=True))


def registros_mpro_por_folios(folios_por_origen):
    """Cabeceras normalizadas de folios especificos: {origen: [folios]}.
    Sin filtro de fecha a proposito -- un XML timbrado en enero puede apuntar
    a un registro fechado en diciembre (caso real: compra 05-0029612)."""
    partes = []
    for o, folios in folios_por_origen.items():
        if o not in REG_SQL:
            continue
        d = _leer_por_folios(o, folios, REG_SQL)
        if len(d):
            partes.append(d)
    if not partes:
        return pd.DataFrame(columns=["ORIGEN", "FOLIO", "DOC_ID", "FECHA", "ESTADO",
                                     "SUBORIGEN", "PROVEEDOR", "MONEDA", "TIPO_CAMBIO",
                                     "SUBTOTAL", "IMPUESTOS", "TOTAL", "CONCEPTO"])
    return _normalizar_reg(pd.concat(partes, ignore_index=True))


# ---------------------------------------------------------------------------
# 3. Impuestos de MPro, normalizados al codigo del SAT
# ---------------------------------------------------------------------------

IMP_SQL = {
    "GASTO_REGISTRO": """
        SELECT 'GASTO_REGISTRO' ORIGEN, gri.Gr_Folio FOLIO, gri.Grd_ID DOC_ID,
               gri.Im_Cve_Impuesto CVE, gri.Gri_Importe IMPORTE, gri.Gri_Base_Gravable BASE
        FROM Gasto_Registro_Impuesto gri
        JOIN Gasto_Registro gr ON gr.Gr_Folio = gri.Gr_Folio
        WHERE {filtro}
    """,
    "COMPRA": """
        SELECT 'COMPRA' ORIGEN, cti.Co_Folio FOLIO, '' DOC_ID,
               cti.Ct_Impuesto CVE, cti.Ct_Impuesto_Importe IMPORTE, cti.Ct_Subtotal_Importe BASE
        FROM Compra_Total_Impuesto cti
        JOIN Compra_Encabezado ce ON ce.Co_Folio = cti.Co_Folio
        WHERE {filtro}
    """,
    "CUENTA_X_PAGAR": """
        SELECT 'CUENTA_X_PAGAR' ORIGEN, cxi.Cxp_Folio FOLIO, '' DOC_ID,
               cxi.Im_Cve_Impuesto CVE, cxi.Cxpi_Importe IMPORTE, CAST(NULL AS money) BASE
        FROM Cuenta_X_Pagar_Impuesto cxi
        JOIN Cuenta_X_Pagar cx ON cx.Cxp_Folio = cxi.Cxp_Folio
        WHERE {filtro}
    """,
    "COMPRA_INDIRECTO": """
        SELECT 'COMPRA_INDIRECTO' ORIGEN, cii.Ci_Folio FOLIO, '' DOC_ID,
               cii.Im_Cve_Impuesto CVE, cii.Im_Importe IMPORTE, CAST(NULL AS money) BASE
        FROM Compra_Indirecto_Impuesto cii
        JOIN Compra_Indirecto ci ON ci.Ci_Folio = cii.Ci_Folio AND ci.Ci_ID = cii.Ci_ID
        WHERE {filtro}
    """,
    "NOTA_CREDITO_PROVEEDOR": """
        SELECT 'NOTA_CREDITO_PROVEEDOR' ORIGEN, nci.Nc_Folio FOLIO, '' DOC_ID,
               nci.Im_Cve_Impuesto CVE, nci.Im_Importe IMPORTE, CAST(NULL AS money) BASE
        FROM Nota_Credito_Proveedor_Impuesto nci
        JOIN Nota_Credito_Proveedor nc ON nc.Nc_Folio = nci.Nc_Folio AND nc.Nc_ID = nci.Nc_ID
        WHERE {filtro}
    """,
    "FACTURA": """
        SELECT 'FACTURA' ORIGEN, fti.Fc_Folio FOLIO, '' DOC_ID,
               fti.Ft_Impuesto CVE, fti.Ft_Impuesto_Importe IMPORTE, fti.Ft_SubTotal_Importe BASE
        FROM Factura_Total_Impuesto fti
        JOIN Factura_Encabezado fe ON fe.Fc_Folio = fti.Fc_Folio
        WHERE {filtro}
    """,
}

IMP_FILTRO_FOLIO = {
    "GASTO_REGISTRO": "gri.Gr_Folio", "COMPRA": "cti.Co_Folio",
    "CUENTA_X_PAGAR": "cxi.Cxp_Folio", "COMPRA_INDIRECTO": "cii.Ci_Folio",
    "NOTA_CREDITO_PROVEEDOR": "nci.Nc_Folio", "FACTURA": "fti.Fc_Folio",
}

CATALOGO_SQL = """
SELECT LTRIM(RTRIM(Im_Cve_Impuesto)) CVE, Im_Descripcion DESCRIPCION,
       Im_Tipo_Impuesto TIPO, Im_Tasa TASA,
       LTRIM(RTRIM(ISNULL(Im_Codigo_SAT,''))) CODIGO_SAT
FROM Impuesto
"""


def catalogo_impuestos():
    cat = pd.read_sql(text(CATALOGO_SQL), engine)
    cat["CVE"] = cat["CVE"].astype("string").str.strip()
    cat["CODIGO_SAT"] = cat["CODIGO_SAT"].astype("string").fillna("").str.strip()
    cat["TASA"] = pd.to_numeric(cat["TASA"], errors="coerce").fillna(0)
    cat["CLASE"] = cat["TASA"].apply(lambda t: "RETENCION" if t < 0 else "TRASLADO")
    cat["ES_CFDI"] = ~cat["CVE"].isin(IMPUESTOS_NO_CFDI) & cat["CODIGO_SAT"].isin(SAT_NOMBRE)
    return cat


def _detalle_impuestos(fi, ff, origenes, folios_por_origen):
    partes = []
    for o in origenes:
        if o not in IMP_SQL:
            continue
        if folios_por_origen is None:
            sql = IMP_SQL[o].format(filtro=f"{FILTRO_FECHA[o]} >= :fi AND {FILTRO_FECHA[o]} < :ff")
            partes.append(pd.read_sql(text(sql), engine, params={"fi": fi, "ff": ff}))
        else:
            col, vals = _in_list(IMP_FILTRO_FOLIO[o], folios_por_origen.get(o, []))
            if col == "1=0":
                continue
            for i in range(0, len(vals), 500):
                lista = ", ".join("'" + v.replace("'", "''") + "'" for v in vals[i:i + 500])
                partes.append(pd.read_sql(text(IMP_SQL[o].format(filtro=f"{col} IN ({lista})")), engine))
    cols = ["ORIGEN", "FOLIO", "DOC_ID", "CVE", "IMPORTE", "BASE"]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=cols)


def impuestos_mpro(fi=None, ff=None, origenes=None, folios_por_origen=None):
    """Impuestos por documento, pivoteados a las 4 columnas que el CFDI
    expone a nivel comprobante (IVA/IEPS trasladado, IVA/ISR retenido).

    Se acota por mes (fi/ff) o por lista de folios ({origen: [folios]})."""
    origenes = origenes or list(IMP_SQL)
    det = _detalle_impuestos(fi, ff, origenes, folios_por_origen)
    for c in ("ORIGEN", "FOLIO", "DOC_ID", "CVE"):
        det[c] = det[c].astype("string").fillna("").str.strip()
    det["IMPORTE"] = pd.to_numeric(det["IMPORTE"], errors="coerce").fillna(0.0)

    cat = catalogo_impuestos()
    det = det.merge(cat[["CVE", "CODIGO_SAT", "CLASE", "ES_CFDI", "DESCRIPCION"]], on="CVE", how="left")
    det["ES_CFDI"] = det["ES_CFDI"].fillna(False).astype(bool)
    det["CODIGO_SAT"] = det["CODIGO_SAT"].astype("string").fillna("")
    det["CLASE"] = det["CLASE"].astype("string").fillna("TRASLADO")

    def col(row):
        if not row.ES_CFDI:
            return "MPRO_IMP_NO_CFDI"
        if row.CLASE == "TRASLADO":
            return {"002": "MPRO_IVA_TRASLADADO", "003": "MPRO_IEPS_TRASLADADO"}.get(row.CODIGO_SAT, "MPRO_IMP_OTRO")
        return {"002": "MPRO_RET_IVA", "001": "MPRO_RET_ISR"}.get(row.CODIGO_SAT, "MPRO_IMP_OTRO")

    if len(det):
        det["COL"] = det.apply(col, axis=1)
        # MPro guarda las retenciones en negativo; el CFDI en positivo.
        m = det["COL"].str.startswith("MPRO_RET")
        det.loc[m, "IMPORTE"] = det.loc[m, "IMPORTE"].abs()
        piv = (det.pivot_table(index=["ORIGEN", "FOLIO", "DOC_ID"], columns="COL",
                               values="IMPORTE", aggfunc="sum", fill_value=0.0).reset_index())
        piv.columns.name = None
    else:
        det["COL"] = pd.Series(dtype="string")
        piv = pd.DataFrame(columns=["ORIGEN", "FOLIO", "DOC_ID"])
    for c in ("MPRO_IVA_TRASLADADO", "MPRO_IEPS_TRASLADADO", "MPRO_RET_IVA",
              "MPRO_RET_ISR", "MPRO_IMP_NO_CFDI", "MPRO_IMP_OTRO"):
        if c not in piv.columns:
            piv[c] = 0.0
    return piv, det


# ---------------------------------------------------------------------------
# Semaforo comun
# ---------------------------------------------------------------------------
TOL_CENTAVOS = 0.05   # ruido de redondeo puro
TOL_MENOR = 1.00      # diferencia < 1 peso: no material

# Estatus que NO son descuadre: los dos primeros porque cuadran, el tercero
# porque el importe del CFDI vive en un complemento y MPro registra -- bien --
# el Total del comprobante.
ESTATUS_CUADRA = {"CONCILIA", "DIF_CENTAVOS"}
ESTATUS_EXPLICADO = ESTATUS_CUADRA | {"IMPORTE_EN_COMPLEMENTO", "REPARTIDO_ENTRE_MODULOS"}


def clasificar_dif(dif, comparable=True, motivo=""):
    if not comparable:
        return "NO_COMPARABLE"
    d = abs(dif)
    if d <= TOL_CENTAVOS:
        return "CONCILIA"
    if d <= TOL_MENOR:
        return "DIF_CENTAVOS"
    return "DIF_MATERIAL"


# ---------------------------------------------------------------------------
# 4. Grupos de conciliacion (componentes conexas XML <-> registro)
# ---------------------------------------------------------------------------
# La relacion XML <-> registro NO es 1:1. Verificado en enero 2026:
#   - 1:N  un CFDI repartido en varios documentos de gasto (hasta 108).
#   - N:1  varios REP de proveedores distintos colgados de un mismo cheque
#          (hasta 33) -- un pago cubre muchas facturas.
#   - N:M  ambas cosas a la vez.
# Comparar fila por fila da falsos descuadres, asi que el grano de la
# conciliacion es la COMPONENTE CONEXA del grafo bipartito, por ORIGEN
# (nunca entre origenes: la CXP se genera desde el gasto y sumar los dos
# lados duplicaria el importe de MPro).
#
# Ademas la componente se CIERRA de forma iterativa: un folio de cheque
# acumula CFDI de varios ejercicios (caso real 01-0060062: un anticipo con
# comprobantes de 2024, 2025 y 2026 colgando del mismo folio), asi que
# partir solo de los XML del mes deja componentes truncadas y descuadres
# artificiales. Se expande folio -> todos sus XML -> todos sus documentos
# hasta que no entra nada nuevo.

CD_POR_FOLIO_SQL = """
SELECT
    cd.Cd_Tabla                        AS ORIGEN,
    cd.Cd_Documento                    AS CD_DOCUMENTO,
    UPPER(LTRIM(RTRIM(cd.Cd_Timbre_UUID))) AS UUID,
    cd.Cd_Timbre_Fecha                 AS FECHA_TIMBRADO,
    LTRIM(RTRIM(cd.Cd_RFC_Emisor))     AS RFC_EMISOR,
    cd.Cd_Monto                        AS CD_MONTO,
    cd.Cd_Moneda                       AS CD_MONEDA,
    cd.Cd_Tipo_CFDI                    AS CD_TIPO_CFDI,
    cd.Cd_Serie_Folio                  AS CD_SERIE_FOLIO,
    cd.Es_Cve_Estado                   AS CD_ESTADO,
    CAST(cd.Cd_XML AS nvarchar(MAX))   AS XML
FROM Comprobante_Digital cd
WHERE cd.Cd_Tabla = '{origen}'
  AND LEFT(cd.Cd_Documento, 10) IN ({lista})
  AND LTRIM(RTRIM(cd.Cd_RFC_Receptor)) = '{rfc}'
  AND LTRIM(RTRIM(cd.Cd_RFC_Emisor)) <> '{rfc}'
  AND cd.Cd_Timbre_UUID IS NOT NULL AND LTRIM(RTRIM(cd.Cd_Timbre_UUID)) <> ''
"""


def xml_por_folios(folios_por_origen, con_xml=True):
    """Todos los CFDI recibidos colgados de esos folios, sin filtro de fecha."""
    partes = []
    for origen, folios in folios_por_origen.items():
        col, vals = _in_list("x", folios)
        if col == "1=0":
            continue
        for i in range(0, len(vals), 500):
            lista = ", ".join("'" + v.replace("'", "''") + "'" for v in vals[i:i + 500])
            sql = CD_POR_FOLIO_SQL.format(origen=origen.replace("'", "''"), lista=lista, rfc=RFC_TRIVASA)
            partes.append(pd.read_sql(text(sql), engine))
    if not partes:
        return pd.DataFrame()
    df = pd.concat(partes, ignore_index=True)
    for c in ("ORIGEN", "CD_DOCUMENTO", "UUID", "RFC_EMISOR", "CD_SERIE_FOLIO", "CD_ESTADO"):
        df[c] = df[c].astype("string").fillna("").str.strip()
    df["FOLIO"] = df["CD_DOCUMENTO"].str[:10].str.strip()
    df["DOC_ID"] = ""
    m = df["ORIGEN"] == "GASTO_REGISTRO"
    df.loc[m, "DOC_ID"] = df.loc[m, "CD_DOCUMENTO"].str[10:14]
    if con_xml:
        parsed = pd.DataFrame([parsear_cfdi(v) for v in df["XML"]], index=df.index)
        df = pd.concat([df.drop(columns=["XML"]), parsed], axis=1)
    else:
        df = df.drop(columns=["XML"])
    return df


def cerrar_universo(x_mes, max_iter=5):
    """Expande el universo de XML hasta cerrar las componentes por folio.

    Devuelve (x_completo, n_iteraciones). `x_mes` es la salida de
    `xml_recibidos()`; el resultado la contiene y agrega los CFDI de otros
    periodos que cuelgan de los mismos folios (marcados EN_PERIODO=False)."""
    x = x_mes.copy()
    x["EN_PERIODO"] = True
    consultados = set()
    for it in range(1, max_iter + 1):
        pendientes = {}
        for o, g in x.groupby("ORIGEN"):
            faltan = sorted(set(g.FOLIO) - consultados)
            if faltan:
                pendientes[o] = faltan
        if not pendientes:
            return x, it - 1
        for o, fs in pendientes.items():
            consultados |= set(fs)
        extra = xml_por_folios(pendientes)
        if extra.empty:
            return x, it
        extra["EN_PERIODO"] = False
        nuevos = extra.merge(x[["ORIGEN", "CD_DOCUMENTO"]].drop_duplicates(),
                             on=["ORIGEN", "CD_DOCUMENTO"], how="left", indicator=True)
        nuevos = nuevos[nuevos["_merge"] == "left_only"].drop(columns=["_merge"])
        if nuevos.empty:
            return x, it
        x = pd.concat([x, nuevos], ignore_index=True)
    return x, max_iter


def asignar_grupos(x):
    """Etiqueta cada fila de XML con su componente conexa (por ORIGEN).

    Devuelve el DataFrame con columna GRUPO y un dict {(ORIGEN, DOC): GRUPO}
    para poder etiquetar tambien el lado de los registros."""
    x = x.copy()
    x["DOC"] = x["FOLIO"] + "|" + x["DOC_ID"]
    x["GRUPO"] = ""
    mapa_doc = {}
    for origen, gx in x.groupby("ORIGEN"):
        padre = {}

        def find(a):
            padre.setdefault(a, a)
            while padre[a] != a:
                padre[a] = padre[padre[a]]
                a = padre[a]
            return a

        for u, d in zip(gx.UUID, gx.DOC):
            ra, rb = find(("X", u)), find(("D", d))
            if ra != rb:
                padre[ra] = rb
        # id legible y estable: origen + folio mas chico de la componente
        raiz_folio = {}
        for (tipo, val) in list(padre):
            if tipo == "D":
                r = find((tipo, val))
                f = val.split("|")[0]
                if r not in raiz_folio or f < raiz_folio[r]:
                    raiz_folio[r] = f
        etiqueta = {r: f"{origen}:{f}" for r, f in raiz_folio.items()}
        x.loc[gx.index, "GRUPO"] = [etiqueta[find(("X", u))] for u in gx.UUID]
        for d in gx.DOC.unique():
            mapa_doc[(origen, d)] = etiqueta[find(("D", d))]
    return x, mapa_doc


# ---------------------------------------------------------------------------
# 5. Conciliacion de importes (nucleo del reporte 02; el 03 lo extiende)
# ---------------------------------------------------------------------------

def _p(console, *a, **k):
    if console is not None:
        console.print(*a, **k)


def _txt(serie, sep=";", maxn=8):
    vals = sorted({str(v) for v in serie if str(v) not in ("", "nan", "None", "<NA>")})
    if len(vals) > maxn:
        return sep.join(vals[:maxn]) + f"{sep}(+{len(vals)-maxn})"
    return sep.join(vals)


def conciliar_importes(fi, ff, console=None):
    _p(console, "[bold]02 -- Conciliacion de importes: CFDI recibido vs registro MPro[/bold]")
    _p(console, f"[dim]Periodo (fecha de timbrado): {fi} a {ff} -- .205/TRIVASADB3[/dim]\n")

    x_mes = xml_recibidos(fi, ff)
    _p(console, f"CFDI recibidos timbrados en el periodo: [bold]{len(x_mes)}[/bold] vinculos, "
                  f"{x_mes.UUID.nunique()} UUID distintos")
    auto = autoemitidos(fi, ff)
    if len(auto):
        _p(console, f"[dim]Fuera del universo -- autoemitidos (emisor = receptor = Trivasa): "
                      f"{int(auto.N.sum())} comprobantes, importe {float(auto.MONTO.sum()):,.2f} "
                      f"({', '.join(f'{r.ORIGEN}={int(r.N)}' for r in auto.itertuples())})[/dim]")

    x, iters = cerrar_universo(x_mes)
    fuera = int((~x.EN_PERIODO).sum())
    _p(console, f"Cierre de grupos: +{fuera} CFDI de otros periodos colgados de los mismos "
                  f"folios ({iters} pasada(s))\n")

    x, mapa_doc = asignar_grupos(x)

    # --- CFDI cuyo importe real NO esta en el Total del comprobante.
    # Dos formas, las dos verificadas en enero 2026:
    #  a) el propio comprobante trae el complemento (ValesDeDespensa: 19 CFDI
    #     con Total $0.01 y $792,344.95 en el complemento).
    #  b) es un REP que liquida uno de esos comprobantes -- paga mucho mas de
    #     lo que dice el Total de la factura que referencia (12 REP de TOKA
    #     en enero, $518,357.30 contra facturas de $0.01).
    x["COMPLEMENTO_IMPORTE"] = x["XML_VALES_DESPENSA"].astype(float)
    dr_all = sorted({u for cad in x.XML_DR_UUIDS for u in str(cad).split(";") if u})
    montos_fac = montos_por_uuid(dr_all) if dr_all else {}

    def _rep_sobre_complemento(row):
        if row.XML_TIPO != "P" or not row.XML_DR_UUIDS:
            return 0.0
        us = [u for u in str(row.XML_DR_UUIDS).split(";") if u]
        suma = sum(montos_fac.get(u, 0.0) for u in us)
        pagado = float(row.XML_DR_PAGADO or 0)
        return pagado if pagado > suma + TOL_MENOR else 0.0

    rep_c = x.apply(_rep_sobre_complemento, axis=1)
    x["COMPLEMENTO_IMPORTE"] = x["COMPLEMENTO_IMPORTE"].where(x["COMPLEMENTO_IMPORTE"] > 0, rep_c)

    # Emisores que son otra empresa del grupo dentro de la misma base
    grupo = rfcs_del_grupo()
    x["INTERCOMPANIA"] = x.RFC_EMISOR.isin(grupo)
    x["EMPRESA_GRUPO"] = x.RFC_EMISOR.map(grupo).fillna("")

    folios = {o: sorted(g.FOLIO.unique()) for o, g in x.groupby("ORIGEN")}
    reg = registros_mpro_por_folios(folios)
    reg["DOC"] = reg.FOLIO + "|" + reg.DOC_ID
    reg["GRUPO"] = [mapa_doc.get((o, d), "") for o, d in zip(reg.ORIGEN, reg.DOC)]
    reg = reg[reg.GRUPO != ""]

    # --- lado XML (un UUID puede repetirse en varios documentos del grupo:
    #     el importe del CFDI se cuenta UNA vez por grupo)
    xu = x.drop_duplicates(["GRUPO", "UUID"]).copy()
    xu["IMPORTE_XML"] = np.where(xu.XML_TIPO == "P", xu.XML_PAGOS_MONTO, xu.XML_TOTAL)
    lado_x = xu.groupby(["ORIGEN", "GRUPO"]).agg(
        N_XML=("UUID", "size"),
        N_XML_PERIODO=("EN_PERIODO", "sum"),
        UUIDS=("UUID", _txt),
        RFC_EMISOR=("RFC_EMISOR", _txt),
        EMISOR=("XML_EMISOR_NOMBRE", lambda s: _txt(s, maxn=3)),
        TIPOS_CFDI=("XML_TIPO", _txt),
        MONEDAS=("XML_MONEDA", _txt),
        FECHA_XML_MIN=("XML_FECHA", "min"),
        FECHA_XML_MAX=("XML_FECHA", "max"),
        XML_SUBTOTAL=("XML_SUBTOTAL", "sum"),
        XML_TOTAL=("XML_TOTAL", "sum"),
        XML_PAGOS_MONTO=("XML_PAGOS_MONTO", "sum"),
        XML_IMPORTE=("IMPORTE_XML", "sum"),
        XML_COMPLEMENTO_IMPORTE=("COMPLEMENTO_IMPORTE", "sum"),
        XML_VALES_N_TRAB=("XML_VALES_N_TRAB", "sum"),
        XML_COMPLEMENTOS=("XML_COMPLEMENTOS", lambda s: _txt(s, maxn=4)),
        XML_IMP_LOCAL_TRAS=("XML_IMP_LOCAL_TRAS", "sum"),
        INTERCOMPANIA=("INTERCOMPANIA", "any"),
        EMPRESA_GRUPO=("EMPRESA_GRUPO", lambda s: _txt(s, maxn=2)),
        XML_CANCELADOS=("CD_ESTADO", lambda s: int((s == "CA").sum())),
    ).reset_index()

    # --- lado MPro
    lado_r = reg.drop_duplicates(["GRUPO", "DOC"]).groupby(["ORIGEN", "GRUPO"]).agg(
        N_DOC=("DOC", "size"),
        FOLIOS=("FOLIO", _txt),
        SUBORIGEN=("SUBORIGEN", _txt),
        PROVEEDOR=("PROVEEDOR", lambda s: _txt(s, maxn=3)),
        CONCEPTO=("CONCEPTO", lambda s: _txt(s, maxn=2)),
        FECHA_MPRO_MIN=("FECHA", "min"),
        FECHA_MPRO_MAX=("FECHA", "max"),
        MPRO_SUBTOTAL=("SUBTOTAL", "sum"),
        MPRO_IMPUESTOS=("IMPUESTOS", "sum"),
        MPRO_TOTAL=("TOTAL", "sum"),
        ESTADOS_MPRO=("ESTADO", _txt),
    ).reset_index()

    g = lado_x.merge(lado_r, on=["ORIGEN", "GRUPO"], how="left")
    g["N_DOC"] = g.N_DOC.fillna(0).astype(int)
    g["DIF"] = (g.XML_IMPORTE - g.MPRO_TOTAL).round(2)
    g["DIF_PCT"] = np.where(g.XML_IMPORTE.abs() > 0.005,
                            (100 * g.DIF / g.XML_IMPORTE).round(2), np.nan)
    g["FORMA"] = np.where((g.N_XML == 1) & (g.N_DOC == 1), "1:1",
                  np.where(g.N_DOC == 0, "SIN_REGISTRO",
                  np.where(g.N_XML == 1, "1:N", np.where(g.N_DOC == 1, "N:1", "N:M"))))

    def estatus(r):
        if r.N_DOC == 0:
            # El modulo de origen no es de compra/gasto: el reporte no sabe
            # leerlo. Pasa con los CFDI intercompania, cuyo registro vive en
            # el modulo de venta de la otra empresa del grupo.
            if r.ORIGEN not in REG_SQL:
                return "MODULO_NO_CUBIERTO"
            return "SIN_REGISTRO"
        d = abs(r.DIF)
        if d <= TOL_CENTAVOS:
            return "CONCILIA"
        if d <= TOL_MENOR:
            return "DIF_CENTAVOS"
        # El descuadre no existe: el importe del CFDI vive en un complemento
        # (vales de despensa) y MPro registra el Total del comprobante.
        if r.XML_COMPLEMENTO_IMPORTE > TOL_MENOR:
            return "IMPORTE_EN_COMPLEMENTO"
        if abs(r.MPRO_TOTAL) <= TOL_CENTAVOS and abs(r.XML_IMPORTE) > TOL_MENOR:
            return "REGISTRO_EN_CERO"
        return "DIF_MATERIAL"

    g["ESTATUS"] = g.apply(estatus, axis=1)

    def motivo(r):
        m = []
        if r.ESTATUS in ("CONCILIA", "DIF_CENTAVOS"):
            return ""
        if r.ESTATUS == "IMPORTE_EN_COMPLEMENTO":
            return "CFDI_VALES_DE_DESPENSA" if r.XML_VALES_N_TRAB else "REP_LIQUIDA_CFDI_CON_COMPLEMENTO"
        if r.INTERCOMPANIA:
            m.append("INTERCOMPANIA")
        if r.N_XML > r.N_XML_PERIODO:
            m.append("ARRASTRA_CFDI_DE_OTRO_PERIODO")
        if "I" in str(r.TIPOS_CFDI).split(";") and "E" in str(r.TIPOS_CFDI).split(";"):
            m.append("MEZCLA_INGRESO_Y_EGRESO")
        if r.XML_CANCELADOS:
            m.append("CFDI_CANCELADO_EN_MPRO")
        if "CA" in str(r.ESTADOS_MPRO).split(";"):
            m.append("REGISTRO_CANCELADO")
        if r.ESTATUS == "DIF_MATERIAL":
            m.append("MPRO_REGISTRA_MENOS" if r.DIF > 0 else "MPRO_REGISTRA_MAS")
        return "|".join(m)

    g["MOTIVO"] = g.apply(motivo, axis=1)

    # Un mismo CFDI puede estar ligado en dos modulos. D3 los concilia por
    # separado para no duplicar el lado de MPro, y eso es correcto cuando un
    # modulo se DERIVA del otro (la CxP hereda el importe del gasto: cada uno
    # vale lo mismo que el CFDI). Pero hay pares COMPLEMENTARIOS, donde el
    # CFDI se reparte y cada modulo registra una parte -- ninguno cuadra solo
    # y la suma si.
    #
    # Caso real feb-2026: CFDI 90227AAD por 161,190.75 repartido entre
    # COMPRA:23-0007859 (160,070.26, la mercancia) y
    # COMPRA_INDIRECTO:23-0000126 (1,120.49, el cargo accesorio) -- suma
    # exacta. Sin esta deteccion los dos salen como descuadre material.
    #
    # La regla se auto-protege del caso derivado: si dos modulos registran
    # cada uno el importe completo, la suma da el doble y NO se marca.
    uuid_grupo = (xu[["UUID", "ORIGEN", "GRUPO", "IMPORTE_XML"]]
                  .merge(g[["ORIGEN", "GRUPO", "MPRO_TOTAL"]], on=["ORIGEN", "GRUPO"], how="left"))
    n_grupos = uuid_grupo.groupby("UUID").GRUPO.nunique()
    multi = set(n_grupos[n_grupos > 1].index)
    rep = uuid_grupo[uuid_grupo.UUID.isin(multi)]
    suma_mpro = rep.drop_duplicates(["UUID", "ORIGEN", "GRUPO"]).groupby("UUID").MPRO_TOTAL.sum()
    imp_cfdi = rep.drop_duplicates("UUID").set_index("UUID").IMPORTE_XML
    cuadra = {u for u in multi
              if pd.notna(suma_mpro.get(u)) and abs(imp_cfdi.get(u, 0) - suma_mpro[u]) <= TOL_MENOR}
    marcados = (rep[rep.UUID.isin(cuadra)]
                .groupby(["ORIGEN", "GRUPO"]).UUID.size().to_dict())
    g["CFDI_REPARTIDO"] = [marcados.get(k, 0) > 0 for k in zip(g.ORIGEN, g.GRUPO)]
    # No se toca un grupo sin registro: ahi no hay reparto que demostrar, y
    # 'MODULO_NO_CUBIERTO' dice mas sobre la limitacion del reporte.
    reparte = (g.CFDI_REPARTIDO & ~g.ESTATUS.isin(ESTATUS_EXPLICADO)
               & ~g.ESTATUS.isin({"SIN_REGISTRO", "MODULO_NO_CUBIERTO"}))
    g.loc[reparte, "ESTATUS"] = "REPARTIDO_ENTRE_MODULOS"
    g.loc[reparte, "MOTIVO"] = "CFDI_REPARTIDO_ENTRE_MODULOS"

    cols = ["ORIGEN", "GRUPO", "FORMA", "ESTATUS", "MOTIVO", "N_XML", "N_XML_PERIODO", "N_DOC",
            "XML_SUBTOTAL", "XML_TOTAL", "XML_PAGOS_MONTO", "XML_IMPORTE",
            "XML_COMPLEMENTO_IMPORTE", "XML_VALES_N_TRAB", "XML_COMPLEMENTOS",
            "MPRO_SUBTOTAL", "MPRO_IMPUESTOS", "MPRO_TOTAL", "DIF", "DIF_PCT",
            "TIPOS_CFDI", "MONEDAS", "RFC_EMISOR", "EMISOR", "INTERCOMPANIA", "EMPRESA_GRUPO",
            "PROVEEDOR", "SUBORIGEN", "CONCEPTO",
            "FECHA_XML_MIN", "FECHA_XML_MAX", "FECHA_MPRO_MIN", "FECHA_MPRO_MAX",
            "ESTADOS_MPRO", "XML_CANCELADOS", "CFDI_REPARTIDO", "FOLIOS", "UUIDS"]
    for c in ("XML_SUBTOTAL", "XML_TOTAL", "XML_PAGOS_MONTO", "XML_IMPORTE",
              "XML_COMPLEMENTO_IMPORTE", "MPRO_SUBTOTAL", "MPRO_IMPUESTOS", "MPRO_TOTAL"):
        g[c] = g[c].astype(float).round(2)
    return g[cols].sort_values(["ORIGEN", "ESTATUS", "DIF"], key=lambda s: s.abs() if s.name == "DIF" else s,
                               ascending=[True, True, False]), x, reg
