"""Compras, compras indirectas y notas de crédito de proveedor con las mismas columnas que el reporte de gastos.

Fuente: las consultas de auditoría RPTRV79 v2/v3 (reportes-mpro), reescritas a grano documento:
cada bloque (cabecera, impuestos, XML, pago, póliza) se une por folio, sin el fan-out por línea de producto
que obligaba a usar SELECT DISTINCT. Solo se incluyen campos comunes con gastos (sin comprador, almacén,
causa, estado, descuentos ni cantidades).

Además incluye las cuentas por pagar (05 de RPTRV79): CxP libre (Cxp_Tabla='Cuenta_X_Pagar') y CxP de origen
orden de compra (Cxp_Tabla='ORDEN_COMPRA': inversiones que parten de una OC pero generan una CxP en vez de un documento
Compra). A diferencia de los demás tipos, la póliza de la CxP puede ser compartida por varios documentos, por lo que
las líneas se filtran por Pd_Referencia (folio de la CxP o su referencia) y se omiten las cuentas 1170/2110/2150/2130.
"""
import numpy as np, pandas as pd
from sqlalchemy import text

CXP_FILTRO = "AND c.Cxp_Tabla='{t}'"
# Tablas con prefijo {p}_ID: el impuesto se une por folio+ID. Cuenta_X_Pagar no tiene ID (Cxp_Folio es único).
IMP_JOIN_STD = "i.{p}_Folio=c.{p}_Folio AND i.{p}_ID=c.{p}_ID"
IMP_JOIN_CXP = "i.Cxp_Folio=c.Cxp_Folio"

SPECS = [
    dict(tipo='Compra', p='Co', tabla='Compra', imp='Compra_Impuesto', cd='COMPRA', pc='COMPRA', cxp='Compra',
         c05=True, signo=1,
         neto='(c.Co_Precio_Lista_Importe - CASE WHEN c.Co_Descuento_Global_Factor<>0 THEN c.Co_Descuento_Global_Importe ELSE c.Co_Descuento_Importe END)*c.Co_Tipo_Cambio'),
    dict(tipo='Indirecto', p='Ci', tabla='Compra_Indirecto', imp='Compra_Indirecto_Impuesto', cd='COMPRA_INDIRECTO', pc='COMPRA_INDIRECTO', cxp='Compra_Indirecto',
         c05=True, signo=1,
         neto='(c.Ci_Precio_Lista_Importe - CASE WHEN c.Ci_Descuento_Global_Factor<>0 THEN c.Ci_Descuento_Global_Importe ELSE c.Ci_Descuento_Importe END)*c.Ci_Tipo_Cambio'),
    dict(tipo='NC proveedor', p='Nc', tabla='Nota_Credito_Proveedor', imp='Nota_Credito_Proveedor_Impuesto', cd='NOTA_CREDITO_PROVEEDOR', pc='NOTA_CREDITO_PROVEEDOR', cxp=None,
         c05=False, signo=-1,
         neto='(c.Nc_Precio_Descontado_Importe - c.Nc_Descuento_Global_Importe)*c.Nc_Tipo_Cambio'),
    dict(tipo='CxP libre', p='Cxp', tabla='Cuenta_X_Pagar', imp='Cuenta_X_Pagar_Impuesto', cd='Cuenta_X_Pagar', pc='Cuenta_X_Pagar', cxp='SELF',
         c05=False, signo=1, cxp_tabla='Cuenta_X_Pagar',
         neto='c.Cxp_Precio_Descontado_Importe*c.Cxp_Tipo_Cambio'),
    dict(tipo='CxP orden compra', p='Cxp', tabla='Cuenta_X_Pagar', imp='Cuenta_X_Pagar_Impuesto', cd='Cuenta_X_Pagar', pc='Cuenta_X_Pagar', cxp='SELF',
         c05=False, signo=1, cxp_tabla='ORDEN_COMPRA',
         neto='c.Cxp_Precio_Descontado_Importe*c.Cxp_Tipo_Cambio'),
]

SETUP_SQL = """
SELECT d.FOLIO, d.REF, d.COM INTO #docs FROM (
    SELECT c.{p}_Folio AS FOLIO, MAX(c.{p}_Referencia) AS REF, MAX(CONVERT(varchar(500), c.{p}_Comentario)) AS COM
    FROM {tabla} c JOIN Sucursal s ON s.Sc_Cve_Sucursal=c.Sc_Cve_Sucursal
    WHERE c.Es_Cve_Estado<>'CA' AND c.{p}_Fecha>=:fi AND c.{p}_Fecha<:ff AND s.Em_Cve_Empresa=:emp {filtro_doc}
    GROUP BY c.{p}_Folio) d;
SELECT FOLIO, REF AS Gr_Referencia INTO #folios FROM #docs;
SELECT DISTINCT d.FOLIO, cxp.Cxp_Folio INTO #cxp_d FROM #docs d
    JOIN Cuenta_X_Pagar cxp ON cxp.Cxp_Tabla='{cxp}' AND cxp.Cxp_Documento=d.FOLIO AND cxp.Es_Cve_Estado<>'CA';
"""
SETUP_CXP_SQL = SETUP_SQL.split('SELECT DISTINCT')[0] + "SELECT FOLIO, FOLIO AS Cxp_Folio INTO #cxp_d FROM #docs;"
SETUP_SIN_PAGO_SQL = SETUP_SQL.split('SELECT DISTINCT')[0] + "SELECT CAST(NULL AS varchar(30)) AS FOLIO, CAST(NULL AS varchar(30)) AS Cxp_Folio INTO #cxp_d WHERE 1=0;"
TEARDOWN_SQL = "DROP TABLE #docs; DROP TABLE #folios; DROP TABLE #cxp_d"

# K: 3 exento (0004), 2 tasa 0 (0003), 1 gravada (0001/0002 o sin impuesto)
CABECERA_SQL = """
WITH b AS (
    SELECT c.{p}_Folio AS FOLIO, c.{p}_Fecha AS FECHA, c.Mn_Cve_Moneda AS MONEDA, c.Pv_Cve_Proveedor AS CLAVE_PROVEEDOR,
           {neto} AS NETO, c.{p}_Precio_Neto_Importe*c.{p}_Tipo_Cambio AS TOT,
           ISNULL((SELECT MAX(CASE i.Im_Cve_Impuesto WHEN '0004' THEN 3 WHEN '0003' THEN 2 ELSE 1 END) FROM {imp} i
                   WHERE {imp_join}),1) AS K
    FROM {tabla} c JOIN #docs d ON d.FOLIO=c.{p}_Folio
    WHERE c.Es_Cve_Estado<>'CA')
SELECT b.FOLIO, MAX(b.FECHA) AS FECHA, MAX(b.MONEDA) AS MONEDA, MAX(b.CLAVE_PROVEEDOR) AS CLAVE_PROVEEDOR, MAX(d.REF) AS REFERENCIA,
       SUM(CASE WHEN K=2 THEN NETO ELSE 0 END) AS SUBTOTAL_0,
       SUM(CASE WHEN K=1 THEN NETO ELSE 0 END) AS SUBTOTAL_16,
       SUM(CASE WHEN K=3 THEN NETO ELSE 0 END) AS SUBTOTAL_EXENTA,
       SUM(NETO) AS SUBTOTAL_NETO, SUM(TOT) AS TOTAL_SQL
FROM b JOIN #docs d ON d.FOLIO=b.FOLIO GROUP BY b.FOLIO
"""

IMPUESTO_SQL = """
SELECT c.{p}_Folio AS FOLIO, i.Im_Cve_Impuesto AS CLAVE, SUM(i.{imp_col}*c.{p}_Tipo_Cambio) AS IMPORTE
FROM {tabla} c JOIN #docs d ON d.FOLIO=c.{p}_Folio
JOIN {imp} i ON {imp_join}
WHERE c.Es_Cve_Estado<>'CA'
GROUP BY c.{p}_Folio, i.Im_Cve_Impuesto
"""

PROVEEDOR_SQL = "SELECT Pv_Cve_Proveedor AS CLAVE_PROVEEDOR, Pv_R_F_C AS RFC_PROVEEDOR, Pv_Descripcion AS NOMBRE_PROVEEDOR FROM Proveedor"

XML_SQL = """
WITH xml AS (
    SELECT d.FOLIO, cd.Cd_Timbre_UUID, cd.Cd_Timbre_Fecha, cd.Cd_RFC_Emisor, cd.Cd_Monto, cd.Cd_Serie, cd.Cd_Serie_Folio,
           cd.Cd_Uso_CFDI, cd.Cd_Tipo_CFDI, COALESCE(cd.Cd_Metdo_Pago_CFDI, cd.Cd_Metodo_Pago) AS METODO_PAGO, cd.Cd_Forma_Pago
    FROM #docs d JOIN Comprobante_Digital cd
      ON cd.Cd_Tabla='{cd}' AND cd.Cd_Documento LIKE d.FOLIO+'%' AND cd.Es_Cve_Estado='AC'
),
xa AS (
    SELECT FOLIO, COUNT(DISTINCT Cd_Timbre_UUID) AS N_UUID, MIN(Cd_Timbre_UUID) AS UUID_UNICO, MIN(Cd_RFC_Emisor) AS RFC_EMISOR,
           MIN(Cd_Monto) AS MONTO, MIN(Cd_Serie) AS SERIE, MIN(Cd_Serie_Folio) AS SERIE_FOLIO, MIN(METODO_PAGO) AS METODO,
           MIN(Cd_Forma_Pago) AS FORMA, MIN(Cd_Tipo_CFDI) AS TIPO_CFDI
    FROM xml GROUP BY FOLIO
),
uso AS (
    SELECT FOLIO, COUNT(DISTINCT Cd_Uso_CFDI) AS N_USO, MIN(Cd_Uso_CFDI) AS USO FROM xml
    WHERE Cd_Uso_CFDI IS NOT NULL AND LTRIM(RTRIM(Cd_Uso_CFDI))<>'' GROUP BY FOLIO
)
SELECT d.FOLIO, d.COM AS CONCEPTO_GASTO,
    CASE WHEN u.N_USO>=2 THEN 'VARIOS' ELSE u.USO END AS CLAVE_USO_BIEN_SERVICIO,
    CASE WHEN u.N_USO>=2 THEN 'VARIOS' ELSE uc.Uc_Descripcion END AS DESCRIPCION_USO_BIEN_SERVICIO,
    CASE WHEN x.N_UUID>=2 THEN 'VARIOS' ELSE x.UUID_UNICO END AS UUID,
    CASE WHEN x.N_UUID>=2 THEN 'VARIOS' ELSE x.RFC_EMISOR END AS XML_RFC_EMISOR,
    CASE WHEN x.N_UUID>=2 THEN NULL ELSE x.MONTO END AS XML_MONTO,
    CASE WHEN x.N_UUID>=2 THEN 'VARIOS' ELSE x.SERIE END AS XML_SERIE,
    CASE WHEN x.N_UUID>=2 THEN 'VARIOS' ELSE x.SERIE_FOLIO END AS XML_FOLIO,
    CASE WHEN x.N_UUID>=2 THEN 'VARIOS' ELSE x.METODO END AS XML_METODO_PAGO,
    CASE WHEN x.N_UUID>=2 THEN 'VARIOS' ELSE x.FORMA END AS XML_FORMA_PAGO,
    CASE WHEN x.N_UUID>=2 THEN 'VARIOS' WHEN x.TIPO_CFDI='I' THEN 'Ingreso' WHEN x.TIPO_CFDI='E' THEN 'Egreso'
         WHEN x.TIPO_CFDI='D' THEN 'Diario' ELSE NULL END AS TIPO_COMPROBANTE,
    CASE WHEN x.N_UUID>=2 THEN 'VARIOS' ELSE x.SERIE_FOLIO END AS NUMERO_FACTURA
FROM #docs d LEFT JOIN xa x ON x.FOLIO=d.FOLIO LEFT JOIN uso u ON u.FOLIO=d.FOLIO LEFT JOIN Uso_CFDI uc ON uc.Uc_Cve_Uso_CFDI=u.USO
"""

POLIZA_SQL = """
SELECT d.FOLIO, pl.Pl_Folio AS POLIZA, pl.Pl_Fecha AS FECHA_POLIZA, pl.Pl_Tipo AS TIPO_POLIZA, pl.Pl_Numero AS NUMERO_POLIZA,
       pl.Pl_Comentario AS CONCEPTO_POLIZA, pd.Cc_Cve_Cuenta_Contable AS CUENTA_REGISTRO, cc.Cc_Descripcion AS NOMBRE_CUENTA_REGISTRO,
       NULLIF(LTRIM(RTRIM(pd.Pd_Centro_Costo)),'') AS CECO, cco.Cc_Descripcion AS CECO_DESCRIPCION,
       CASE WHEN pd.Pd_Tipo=1 THEN pd.Pd_Importe ELSE 0 END AS CARGO, CASE WHEN pd.Pd_Tipo=2 THEN pd.Pd_Importe ELSE 0 END AS ABONO
FROM #docs d
JOIN Poliza_Control plc ON plc.Pc_Tabla='{pc}' AND plc.Pc_Documento=d.FOLIO AND plc.Es_Cve_Estado<>'CA'
JOIN Poliza pl ON pl.Pl_Folio=plc.Pl_Folio AND pl.Es_Cve_Estado<>'CA'
JOIN Poliza_Detalle pd ON pd.Pl_Folio=plc.Pl_Folio AND {pol_ref}
LEFT JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable=pd.Cc_Cve_Cuenta_Contable
LEFT JOIN Centro_Costo cco ON cco.Cc_Cve_Centro_Costo=pd.Pd_Centro_Costo
WHERE ISNULL(pd.Pd_Importe,0)<>0 {filtro05}
  AND LEFT(pd.Cc_Cve_Cuenta_Contable,5) NOT IN ('10500','10600')
  AND LEFT(pd.Cc_Cve_Cuenta_Contable,4) NOT IN ('1170','2110','2150'{excl_pol})
"""

def _strip(d):
    d['FOLIO'] = d.FOLIO.astype(str).str.strip()
    return d

def construir_tipo(s, fi, ff, engine, emp, pago_sql):
    """DataFrame previo a post() de un tipo de documento: una fila por línea de póliza (o una sola si no tiene póliza)."""
    p = {'fi': fi, 'ff': ff, 'emp': emp}
    f = {k: s[k] for k in ('p', 'tabla', 'imp', 'cd', 'pc', 'neto')}
    cxp = s['cxp'] == 'SELF'
    f.update(imp_join=(IMP_JOIN_CXP if cxp else IMP_JOIN_STD).format(p=s['p']), imp_col='Cxpi_Importe' if cxp else 'Im_Importe',
             filtro_doc=CXP_FILTRO.format(t=s['cxp_tabla']) if cxp else '',
             pol_ref="(pd.Pd_Referencia=d.FOLIO OR (ISNULL(d.REF,'')<>'' AND pd.Pd_Referencia=d.REF))" if cxp else 'pd.Pd_Referencia=d.FOLIO',
             excl_pol=",'2130'" if cxp else '')
    setup = SETUP_CXP_SQL if cxp else SETUP_SQL if s['cxp'] else SETUP_SIN_PAGO_SQL
    with engine.connect() as c:
        c.execute(text(setup.format(cxp=s['cxp'], **f)), p)
        try:
            q = lambda sql: pd.read_sql(text(sql.format(**f, filtro05="AND ISNULL(cc.cc_titulo,'')<>'05'" if s['c05'] else '')), c, params=p)
            hdr = q(CABECERA_SQL); imp = q(IMPUESTO_SQL); xml = q(XML_SQL); pol = q(POLIZA_SQL)
            pago = pd.read_sql(text(pago_sql), c, params=p) if s['cxp'] else None
        finally:
            c.execute(text(TEARDOWN_SQL))
    prov = pd.read_sql(text(PROVEEDOR_SQL), engine)
    for x in (hdr, imp, xml, pol) + ((pago,) if pago is not None else ()):
        _strip(x)
    for x in (hdr, prov):
        x['CLAVE_PROVEEDOR'] = x.CLAVE_PROVEEDOR.astype(str).str.strip()
    prov['RFC_PROVEEDOR'] = prov.RFC_PROVEEDOR.astype(str).str.strip()
    prov = prov.drop_duplicates('CLAVE_PROVEEDOR')

    imp['CLAVE'] = imp.CLAVE.astype(str).str.strip()
    ip = imp.pivot_table(index='FOLIO', columns='CLAVE', values='IMPORTE', aggfunc='sum')
    ip.columns = ['IMP_' + k for k in ip.columns]
    ip = ip.reset_index()

    num = [c for c in hdr.columns if c.startswith('SUBTOTAL_') or c == 'TOTAL_SQL']
    for c in num:
        hdr[c] = pd.to_numeric(hdr[c], errors='coerce').astype(float)
    ipc = [c for c in ip.columns if c.startswith('IMP_')]
    for c in ipc:
        ip[c] = pd.to_numeric(ip[c], errors='coerce').astype(float)

    d = hdr.merge(prov, on='CLAVE_PROVEEDOR', how='left').merge(ip, on='FOLIO', how='left').merge(xml, on='FOLIO', how='left')
    if pago is not None:
        d = d.merge(pago.drop(columns='REFERENCIA'), on='FOLIO', how='left')
    for c in ipc:
        d[c] = d[c].fillna(0.0)
    sg = float(s['signo'])
    for c in num + ipc:
        d[c] = d[c] * sg
    d = d.sort_values(['FECHA', 'FOLIO'], kind='stable').reset_index(drop=True)
    pol['_ord'] = np.arange(len(pol))
    d = d.merge(pol, on='FOLIO', how='left').sort_values(['FECHA', 'FOLIO', '_ord'], kind='stable').drop(columns='_ord').reset_index(drop=True)
    d['Tipo'] = s['tipo']
    d['ORIGEN'] = None
    return d
