"""Consultas SQL Server (Mpro). Parámetros: :fi (inclusive), :ff (exclusivo), :emp.

.205 no tiene STRING_AGG: se usa STUFF(... FOR XML PATH('')).
Las plantillas con {llaves} se completan con str.format (solo identificadores internos, nunca entrada del usuario).
"""

# ----------------------------------------------------------------------------------------------
# Gasto: universo de documentos (tablas temporales de la sesión)
# ----------------------------------------------------------------------------------------------
GASTO_DOCS_SETUP = """
SELECT gr.Gr_Folio AS FOLIO, gr.Gr_Referencia AS REF, gr.Gr_Comentario AS COM, gr.Gr_Fecha AS FECHA,
       CASE WHEN ISNULL(gr.Gr_Tabla,'')='' THEN 'GASTO_DIRECTO' ELSE gr.Gr_Tabla END AS ORIGEN
INTO #docs
FROM Gasto_Registro gr JOIN Sucursal s ON gr.Sc_Cve_Sucursal=s.Sc_Cve_Sucursal
WHERE gr.Gr_Fecha>=:fi AND gr.Gr_Fecha<:ff AND gr.Es_Cve_Estado<>'CA' AND s.Em_Cve_Empresa=:emp;
SELECT FOLIO, REF AS Gr_Referencia INTO #folios FROM #docs;
SELECT * INTO #cxp_d FROM (
    SELECT DISTINCT d.FOLIO, cxp.Cxp_Folio FROM #docs d
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio=d.FOLIO
    JOIN Cuenta_X_Pagar cxp ON cxp.Cxp_Tabla='Gasto_Registro:'+d.FOLIO AND cxp.Cxp_Documento=grd.Grd_ID
    UNION
    SELECT DISTINCT d.FOLIO, cxp.Cxp_Folio FROM #docs d
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio=d.FOLIO
    JOIN Cuenta_X_Pagar cxp ON cxp.Cxp_Tabla='Cuenta_X_Pagar' AND cxp.Cxp_Referencia=grd.Grd_Referencia AND cxp.Pv_Cve_Proveedor=grd.Pv_Cve_Proveedor
    WHERE grd.Grd_Referencia IS NOT NULL AND LTRIM(RTRIM(grd.Grd_Referencia))<>''
) u;
"""
TEMPORALES = ("#docs", "#folios", "#cxp_d")

GASTO_ORIGEN_SQL = "SELECT FOLIO, ORIGEN FROM #docs"

# Proveedor representativo: el documento de mayor importe del folio.
GASTO_PROVEEDOR_SQL = """
WITH doc_rank AS (
    SELECT d.FOLIO, grd.Mn_Cve_Moneda, grd.Pv_Cve_Proveedor,
           ROW_NUMBER() OVER (PARTITION BY d.FOLIO ORDER BY grd.Grd_Precio_Neto_Importe DESC, grd.Grd_ID) AS rn
    FROM #docs d JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio=d.FOLIO
),
n_prov AS (
    SELECT d.FOLIO, COUNT(DISTINCT grd.Pv_Cve_Proveedor) AS n
    FROM #docs d JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio=d.FOLIO GROUP BY d.FOLIO
)
SELECT d.FOLIO, d.FECHA, r.Mn_Cve_Moneda AS MONEDA, r.Pv_Cve_Proveedor AS CLAVE_PROVEEDOR,
       p.Pv_R_F_C AS RFC_PROVEEDOR, p.Pv_Descripcion AS NOMBRE_PROVEEDOR,
       CASE WHEN n.n>1 THEN 'SI' ELSE 'NO' END AS PROVEEDOR_MULTIPLE
FROM #docs d
LEFT JOIN doc_rank r ON r.FOLIO=d.FOLIO AND r.rn=1
LEFT JOIN n_prov n ON n.FOLIO=d.FOLIO
LEFT JOIN Proveedor p ON p.Pv_Cve_Proveedor=r.Pv_Cve_Proveedor
"""

# ----------------------------------------------------------------------------------------------
# Gasto: póliza
# ----------------------------------------------------------------------------------------------
_COLS_POLIZA = """pl.Pl_Folio AS POLIZA, pl.Pl_Fecha AS FECHA_POLIZA, pl.Pl_Tipo AS TIPO_POLIZA,
       pl.Pl_Numero AS NUMERO_POLIZA, pl.Pl_Comentario AS CONCEPTO_POLIZA"""

GASTO_POLIZA_SQL = f"""
SELECT gr.Gr_Folio AS FOLIO,
       CASE WHEN ISNULL(gr.Gr_Tabla,'')='' THEN 'GASTO_DIRECTO' ELSE gr.Gr_Tabla END AS ORIGEN,
       {_COLS_POLIZA},
       pd.Cc_Cve_Cuenta_Contable AS CUENTA_REGISTRO, cc.Cc_Descripcion AS NOMBRE_CUENTA_REGISTRO,
       pd.Pd_Centro_Costo AS CECO, cco.Cc_Descripcion AS CECO_DESCRIPCION,
       CASE WHEN pd.Pd_Tipo=1 THEN pd.Pd_Importe ELSE 0 END AS CARGO,
       CASE WHEN pd.Pd_Tipo=2 THEN pd.Pd_Importe ELSE 0 END AS ABONO
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal=s.Sc_Cve_Sucursal
JOIN Poliza_Control plc ON plc.Pc_Tabla='GASTO_REGISTRO' AND plc.Pc_Documento=gr.Gr_Folio AND plc.Es_Cve_Estado<>'CA'
JOIN Poliza pl ON pl.Pl_Folio=plc.Pl_Folio AND pl.Es_Cve_Estado<>'CA'
JOIN Poliza_Detalle pd ON pd.Pl_Folio=plc.Pl_Folio AND pd.Pd_Referencia=gr.Gr_Folio
LEFT JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable=pd.Cc_Cve_Cuenta_Contable
LEFT JOIN Centro_Costo cco ON cco.Cc_Cve_Centro_Costo=pd.Pd_Centro_Costo
WHERE gr.Gr_Fecha>=:fi AND gr.Gr_Fecha<:ff AND gr.Es_Cve_Estado<>'CA' AND s.Em_Cve_Empresa=:emp
  AND pd.Pd_Centro_Costo<>''
  -- CONSUMO_INTERNO genera 2 pólizas paralelas por folio (memo de inventario vs. gasto real):
  -- se descarta la de memo por comentario.
  AND (ISNULL(gr.Gr_Tabla,'')<>'CONSUMO_INTERNO'
       OR (UPPER(ISNULL(pl.Pl_Comentario,'')) NOT LIKE '%CUENTAS DE ORDEN%'
       AND UPPER(ISNULL(pl.Pl_Comentario,'')) NOT LIKE '%CTS ORDEN%'
       AND UPPER(ISNULL(pl.Pl_Comentario,'')) NOT LIKE '%CUENTA ORDEN%'))
ORDER BY gr.Gr_Folio, pd.Pl_Folio, pd.Pd_ID
"""

# Capitalización de activo fijo de CONSUMO_INTERNO (configuraciones 0295/0414): su Pd_Referencia es el
# código corto Gr_Referencia y no Gr_Folio, por lo que GASTO_POLIZA_SQL no las encuentra.
GASTO_ACTIVO_FIJO_POLIZA_SQL = f"""
SELECT {_COLS_POLIZA}, pd.Pd_Referencia AS REFERENCIA,
       pd.Cc_Cve_Cuenta_Contable AS CUENTA_REGISTRO, cc.Cc_Descripcion AS NOMBRE_CUENTA_REGISTRO,
       pd.Pd_Centro_Costo AS CECO, cco.Cc_Descripcion AS CECO_DESCRIPCION, pd.Pd_Importe AS IMPORTE_PD
FROM Poliza pl
JOIN Poliza_Detalle pd ON pd.Pl_Folio=pl.Pl_Folio
LEFT JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable=pd.Cc_Cve_Cuenta_Contable
LEFT JOIN Centro_Costo cco ON cco.Cc_Cve_Centro_Costo=pd.Pd_Centro_Costo
WHERE pl.Es_Cve_Estado<>'CA' AND pl.Pl_Configuracion IN ('0295','0414')
  AND pl.Pl_Fecha>=:fi AND pl.Pl_Fecha<:ff AND pd.Pd_Tipo=1 AND pd.Pd_Centro_Costo<>''
"""

GASTO_ACTIVO_FIJO_FOLIOS_SQL = """
SELECT gr.Gr_Folio AS FOLIO, gr.Gr_Referencia AS REFERENCIA, plc.Pl_Folio AS POLIZA,
       ABS(SUM(grd.Grd_Precio_Descontado_Importe*grd.Grd_Tipo_Cambio)) AS VALOR_CMP
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal=s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio=gr.Gr_Folio
JOIN Poliza_Control plc ON plc.Pc_Tabla='GASTO_REGISTRO' AND plc.Pc_Documento=gr.Gr_Folio AND plc.Es_Cve_Estado<>'CA'
JOIN Poliza pl ON pl.Pl_Folio=plc.Pl_Folio AND pl.Es_Cve_Estado<>'CA'
WHERE gr.Gr_Fecha>=:fi AND gr.Gr_Fecha<:ff AND gr.Es_Cve_Estado<>'CA' AND s.Em_Cve_Empresa=:emp
  AND gr.Gr_Tabla='CONSUMO_INTERNO' AND pl.Pl_Configuracion IN ('0295','0414') AND ISNULL(gr.Gr_Referencia,'')<>''
GROUP BY gr.Gr_Folio, gr.Gr_Referencia, plc.Pl_Folio
"""

# Líneas de póliza del documento sin CECO: se atribuyen por importe a filas que la póliza no cubre.
GASTO_POLIZA_SIN_CECO_SQL = f"""
SELECT gr.Gr_Folio AS FOLIO, {_COLS_POLIZA},
       pd.Cc_Cve_Cuenta_Contable AS CUENTA_REGISTRO, cc.Cc_Descripcion AS NOMBRE_CUENTA_REGISTRO,
       CASE WHEN pd.Pd_Tipo=1 THEN pd.Pd_Importe ELSE 0 END AS CARGO,
       CASE WHEN pd.Pd_Tipo=2 THEN pd.Pd_Importe ELSE 0 END AS ABONO
FROM Gasto_Registro gr JOIN Sucursal s ON gr.Sc_Cve_Sucursal=s.Sc_Cve_Sucursal
JOIN Poliza_Control plc ON plc.Pc_Tabla='GASTO_REGISTRO' AND plc.Pc_Documento=gr.Gr_Folio AND plc.Es_Cve_Estado<>'CA'
JOIN Poliza pl ON pl.Pl_Folio=plc.Pl_Folio AND pl.Es_Cve_Estado<>'CA'
JOIN Poliza_Detalle pd ON pd.Pl_Folio=plc.Pl_Folio AND pd.Pd_Referencia=gr.Gr_Folio
LEFT JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable=pd.Cc_Cve_Cuenta_Contable
WHERE gr.Gr_Fecha>=:fi AND gr.Gr_Fecha<:ff AND gr.Es_Cve_Estado<>'CA' AND s.Em_Cve_Empresa=:emp
  AND ISNULL(pd.Pd_Centro_Costo,'')=''
  AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '1170%' AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '2110%' AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '2150%'
  AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '10500%' AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '10600%'
"""

CENTRO_COSTO_SQL = "SELECT Cc_Cve_Centro_Costo AS CECO, Cc_Descripcion AS CECO_DESCRIPCION FROM Centro_Costo"

# ----------------------------------------------------------------------------------------------
# Gasto: importes por documento, reparto por CECO e impuestos por clave
# ----------------------------------------------------------------------------------------------
GASTO_SUBTOTALES_SQL = """
SELECT gr.Gr_Folio AS FOLIO, grd.Grd_ID,
    SUM(CASE WHEN i.Im_Tasa=16.0000 AND i.Im_Tipo_Factor='Tasa' THEN gri.Gri_Base_Gravable ELSE 0 END)*grd.Grd_Tipo_Cambio AS SUBTOTAL_16,
    SUM(CASE WHEN i.Im_Tasa=0.0000 AND i.Im_Tipo_Factor='Tasa' THEN gri.Gri_Base_Gravable ELSE 0 END)*grd.Grd_Tipo_Cambio AS SUBTOTAL_0,
    SUM(CASE WHEN i.Im_Tipo_Factor='Exento' THEN gri.Gri_Base_Gravable ELSE 0 END)*grd.Grd_Tipo_Cambio AS SUBTOTAL_EXENTA,
    grd.Grd_Precio_Descontado_Importe*grd.Grd_Tipo_Cambio AS SUBTOTAL_NETO
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal=s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio=grd.Gr_Folio
LEFT JOIN Gasto_Registro_Impuesto gri ON gri.Gr_Folio=grd.Gr_Folio AND gri.Grd_ID=grd.Grd_ID
LEFT JOIN Impuesto i ON i.Im_Cve_Impuesto=gri.Im_Cve_Impuesto
WHERE gr.Gr_Fecha>=:fi AND gr.Gr_Fecha<:ff AND gr.Es_Cve_Estado<>'CA' AND s.Em_Cve_Empresa=:emp
GROUP BY gr.Gr_Folio, grd.Grd_ID, grd.Grd_Tipo_Cambio, grd.Grd_Precio_Descontado_Importe
"""

# Reparto del documento entre centros de costo. GASTO_RECLASIFICACION queda fuera: su importe es un par espejo (+/-).
GASTO_REPARTO_SQL = """
SELECT gr.Gr_Folio AS FOLIO, grc.Grd_ID, grc.Cc_Cve_Centro_Costo AS CECO, grc.Grc_Importe, grc.Grc_Factor
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal=s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Control grc ON grc.Gr_Folio=gr.Gr_Folio
WHERE gr.Gr_Fecha>=:fi AND gr.Gr_Fecha<:ff AND gr.Es_Cve_Estado<>'CA' AND s.Em_Cve_Empresa=:emp
  AND ISNULL(gr.Gr_Tabla,'')<>'GASTO_RECLASIFICACION'
"""

GASTO_IMPUESTO_CLAVE_SQL = """
SELECT gr.Gr_Folio AS FOLIO, grd.Grd_ID, gri.Im_Cve_Impuesto AS CLAVE,
       SUM(gri.Gri_Importe)*grd.Grd_Tipo_Cambio AS IMPORTE
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal=s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio=grd.Gr_Folio
JOIN Gasto_Registro_Impuesto gri ON gri.Gr_Folio=grd.Gr_Folio AND gri.Grd_ID=grd.Grd_ID
WHERE gr.Gr_Fecha>=:fi AND gr.Gr_Fecha<:ff AND gr.Es_Cve_Estado<>'CA' AND s.Em_Cve_Empresa=:emp
GROUP BY gr.Gr_Folio, grd.Grd_ID, gri.Im_Cve_Impuesto, grd.Grd_Tipo_Cambio
"""

# ----------------------------------------------------------------------------------------------
# XML (CFDI) y retenciones. {origen} = tabla de Comprobante_Digital; #docs = universo del tipo.
# ----------------------------------------------------------------------------------------------
XML_SQL = """
WITH xml AS (
    SELECT d.FOLIO, cd.Cd_Timbre_UUID, cd.Cd_RFC_Emisor, cd.Cd_Monto, cd.Cd_Serie, cd.Cd_Serie_Folio,
           cd.Cd_Uso_CFDI, cd.Cd_Tipo_CFDI, CASE WHEN RTRIM(cd.Cd_Metdo_Pago_CFDI) IN ('PUE','PPD') THEN RTRIM(cd.Cd_Metdo_Pago_CFDI) WHEN RTRIM(cd.Cd_Metodo_Pago) IN ('PUE','PPD') THEN RTRIM(cd.Cd_Metodo_Pago) END AS METODO_PAGO, cd.Cd_Forma_Pago
    FROM #docs d JOIN Comprobante_Digital cd
      ON cd.Cd_Tabla='{origen}' AND cd.Cd_Documento LIKE d.FOLIO+'%' AND cd.Es_Cve_Estado='AC'
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

# Folios con varios documentos: proveedor, concepto y XML por documento (Grd_ID). Un XML cuyo Cd_Documento
# no trae el Grd_ID (14 caracteres, folio + '0001') llega con DOC_ID nulo y aplica a todo el folio.
GASTO_DOCUMENTOS_SQL = """
SELECT d.FOLIO, grd.Grd_ID AS DOC_ID, grd.Pv_Cve_Proveedor AS CLAVE_PROVEEDOR, p.Pv_R_F_C AS RFC_PROVEEDOR,
       p.Pv_Descripcion AS NOMBRE_PROVEEDOR,
       COALESCE(NULLIF(LTRIM(RTRIM(CONVERT(varchar(500), grd.Grd_Comentario))),''), CONVERT(varchar(500), d.COM)) AS CONCEPTO_GASTO
FROM #docs d JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio=d.FOLIO
LEFT JOIN Proveedor p ON p.Pv_Cve_Proveedor=grd.Pv_Cve_Proveedor
"""

GASTO_XML_DOCUMENTO_SQL = """
WITH xml AS (
    SELECT d.FOLIO, CASE WHEN LEN(RTRIM(cd.Cd_Documento))>=18 THEN SUBSTRING(cd.Cd_Documento,11,4) END AS DOC_ID,
           cd.Cd_Timbre_UUID, cd.Cd_RFC_Emisor, cd.Cd_Monto, cd.Cd_Serie, cd.Cd_Serie_Folio,
           cd.Cd_Uso_CFDI, cd.Cd_Tipo_CFDI, CASE WHEN RTRIM(cd.Cd_Metdo_Pago_CFDI) IN ('PUE','PPD') THEN RTRIM(cd.Cd_Metdo_Pago_CFDI) WHEN RTRIM(cd.Cd_Metodo_Pago) IN ('PUE','PPD') THEN RTRIM(cd.Cd_Metodo_Pago) END AS METODO_PAGO, cd.Cd_Forma_Pago
    FROM #docs d JOIN Comprobante_Digital cd
      ON cd.Cd_Tabla='GASTO_REGISTRO' AND cd.Cd_Documento LIKE d.FOLIO+'%' AND cd.Es_Cve_Estado='AC'
),
xa AS (
    SELECT FOLIO, DOC_ID, COUNT(DISTINCT Cd_Timbre_UUID) AS N_UUID, MIN(Cd_Timbre_UUID) AS UUID_UNICO, MIN(Cd_RFC_Emisor) AS RFC_EMISOR,
           MIN(Cd_Monto) AS MONTO, MIN(Cd_Serie) AS SERIE, MIN(Cd_Serie_Folio) AS SERIE_FOLIO, MIN(METODO_PAGO) AS METODO,
           MIN(Cd_Forma_Pago) AS FORMA, MIN(Cd_Tipo_CFDI) AS TIPO_CFDI
    FROM xml GROUP BY FOLIO, DOC_ID
),
uso AS (
    SELECT FOLIO, DOC_ID, COUNT(DISTINCT Cd_Uso_CFDI) AS N_USO, MIN(Cd_Uso_CFDI) AS USO FROM xml
    WHERE Cd_Uso_CFDI IS NOT NULL AND LTRIM(RTRIM(Cd_Uso_CFDI))<>'' GROUP BY FOLIO, DOC_ID
)
SELECT x.FOLIO, x.DOC_ID,
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
FROM xa x LEFT JOIN uso u ON u.FOLIO=x.FOLIO AND ISNULL(u.DOC_ID,'')=ISNULL(x.DOC_ID,'')
LEFT JOIN Uso_CFDI uc ON uc.Uc_Cve_Uso_CFDI=u.USO
"""

GASTO_RETENCIONES_SQL = """
SELECT d.FOLIO, COUNT(DISTINCT cd.Cd_Timbre_UUID) AS N, MIN(cr.Cd_Monto) AS MONTO,
       MIN(cr.Cd_Serie) AS SERIE, MIN(cr.Cd_Serie_Folio) AS FOLIO_XML
FROM #docs d
JOIN Comprobante_Digital cd ON cd.Cd_Tabla='GASTO_REGISTRO' AND cd.Cd_Documento LIKE d.FOLIO+'%' AND cd.Es_Cve_Estado='AC' AND cd.Cd_Tipo_CFDI='RETENCIONES'
LEFT JOIN Comprobante_Digital cr ON cr.Cd_Tabla='CONSTANCIA_RETENCION' AND cr.Cd_Timbre_UUID=cd.Cd_Timbre_UUID AND cr.Es_Cve_Estado='AC'
GROUP BY d.FOLIO
"""

# ----------------------------------------------------------------------------------------------
# Pagos (requiere #folios(FOLIO, Gr_Referencia) y #cxp_d(FOLIO, Cxp_Folio)). Con tablas temporales el
# optimizador de .207 baja esta consulta de ~68 s a ~1 s.
# ----------------------------------------------------------------------------------------------
PAGOS_SQL = """
WITH pagos AS (
    SELECT cd.FOLIO, pc.Pc_ID, pc.Cxp_Folio, pc.Fp_Cve_Forma_Pago, pc.Pc_Banco, pc.Pc_Cuenta_Bancaria,
           pc.Pc_Documento, pc.Pc_Tabla, pc.Pc_Referencia,
           ROW_NUMBER() OVER (PARTITION BY cd.FOLIO ORDER BY
               CASE WHEN pc.Fp_Cve_Forma_Pago IN ('0001','0002','0003') THEN 0 ELSE 1 END,
               ABS(pc.Pc_Importe*ISNULL(pc.Pc_Tipo_Cambio,1)) DESC, pc.Cxp_Folio, pc.Pc_ID) rn
    FROM #cxp_d cd JOIN Pago_CXP pc ON pc.Cxp_Folio=cd.Cxp_Folio AND pc.Es_Cve_Estado<>'CA'
),
rep AS (SELECT * FROM pagos WHERE rn=1),
formas AS (
    SELECT t.FOLIO, STUFF((SELECT ' / '+x.Fp_Descripcion FROM (SELECT DISTINCT p.FOLIO, fp.Fp_Descripcion FROM pagos p JOIN Forma_Pago fp ON fp.Fp_Cve_Forma_Pago=p.Fp_Cve_Forma_Pago) x
        WHERE x.FOLIO=t.FOLIO ORDER BY x.Fp_Descripcion FOR XML PATH('')),1,3,'') AS FORMA_PAGO
    FROM (SELECT DISTINCT FOLIO FROM pagos) t
),
monto AS (
    SELECT cd.FOLIO, SUM(pc.Pc_Importe*ISNULL(pc.Pc_Tipo_Cambio,1)) AS MONTO_COBRADO
    FROM #cxp_d cd JOIN Pago_CXP pc ON pc.Cxp_Folio=cd.Cxp_Folio AND pc.Es_Cve_Estado<>'CA' GROUP BY cd.FOLIO
)
SELECT f.FOLIO, f.Gr_Referencia AS REFERENCIA,
  fm.FORMA_PAGO,
  r.Fp_Cve_Forma_Pago AS FP_CVE,
  COALESCE(NULLIF(LTRIM(RTRIM(r.Pc_Banco)),''), bn.Bn_Descripcion) AS BANCO,
  COALESCE(NULLIF(LTRIM(RTRIM(r.Pc_Cuenta_Bancaria)),''), bc.Bc_Cuenta) AS CUENTA_BANCARIA,
  ch.Ch_Fecha AS FECHA_CHEQUE,
  COALESCE(ch.Ch_Folio, NULLIF(LTRIM(RTRIM(r.Pc_Documento)),'')) AS FOLIO_PAGO,
  COALESCE(NULLIF(LTRIM(RTRIM(r.Pc_Referencia)),''), NULLIF(LTRIM(RTRIM(ch.Ch_Referencia)),'')) AS NO_CHEQUE_TRANSF,
  m.MONTO_COBRADO
FROM #folios f
LEFT JOIN rep r ON r.FOLIO=f.FOLIO
LEFT JOIN formas fm ON fm.FOLIO=f.FOLIO
LEFT JOIN Anticipo_CXP an ON r.Pc_Tabla='ANTICIPO_CXP' AND an.An_Folio=r.Pc_Documento
LEFT JOIN Cheque ch ON ch.Ch_Folio = CASE WHEN r.Pc_Tabla='Cheque' THEN r.Pc_Documento
                                          WHEN r.Pc_Tabla='ANTICIPO_CXP' AND an.An_Tabla='CHEQUE' THEN an.An_Documento END
LEFT JOIN Banco_Cuenta bc ON bc.Bc_Cve_Banco_Cuenta=COALESCE(ch.Bc_Cve_Banco_Cuenta, an.Bc_Cve_Banco_Cuenta)
LEFT JOIN Banco bn ON bn.Bn_Cve_Banco=bc.Bn_Cve_Banco
LEFT JOIN monto m ON m.FOLIO=f.FOLIO
"""

# ----------------------------------------------------------------------------------------------
# Compras, indirectos, NC de proveedor y CxP: plantillas por tipo (ver documentos.py)
# ----------------------------------------------------------------------------------------------
DOC_SETUP = """
SELECT d.FOLIO, d.REF, d.COM INTO #docs FROM (
    SELECT c.{p}_Folio AS FOLIO, MAX(c.{p}_Referencia) AS REF, MAX(CONVERT(varchar(500), c.{p}_Comentario)) AS COM
    FROM {tabla} c JOIN Sucursal s ON s.Sc_Cve_Sucursal=c.Sc_Cve_Sucursal
    WHERE c.Es_Cve_Estado<>'CA' AND c.{p}_Fecha>=:fi AND c.{p}_Fecha<:ff AND s.Em_Cve_Empresa=:emp {filtro_doc}
    GROUP BY c.{p}_Folio) d;
SELECT FOLIO, REF AS Gr_Referencia INTO #folios FROM #docs;
"""
DOC_CXP_DE_DOCUMENTO = """
SELECT DISTINCT d.FOLIO, cxp.Cxp_Folio INTO #cxp_d FROM #docs d
    JOIN Cuenta_X_Pagar cxp ON cxp.Cxp_Tabla='{cxp}' AND cxp.Cxp_Documento=d.FOLIO AND cxp.Es_Cve_Estado<>'CA';
"""
DOC_CXP_PROPIA = "SELECT FOLIO, FOLIO AS Cxp_Folio INTO #cxp_d FROM #docs;"
DOC_SIN_PAGO = "SELECT CAST(NULL AS varchar(30)) AS FOLIO, CAST(NULL AS varchar(30)) AS Cxp_Folio INTO #cxp_d WHERE 1=0;"

# K: 3 exento (0004), 2 tasa 0 (0003), 1 gravada (0001/0002 o sin impuesto)
DOC_CABECERA_SQL = """
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

DOC_IMPUESTO_SQL = """
SELECT c.{p}_Folio AS FOLIO, i.Im_Cve_Impuesto AS CLAVE, SUM(i.{imp_col}*c.{p}_Tipo_Cambio) AS IMPORTE
FROM {tabla} c JOIN #docs d ON d.FOLIO=c.{p}_Folio
JOIN {imp} i ON {imp_join}
WHERE c.Es_Cve_Estado<>'CA'
GROUP BY c.{p}_Folio, i.Im_Cve_Impuesto
"""

PROVEEDORES_SQL = "SELECT Pv_Cve_Proveedor AS CLAVE_PROVEEDOR, Pv_R_F_C AS RFC_PROVEEDOR, Pv_Descripcion AS NOMBRE_PROVEEDOR FROM Proveedor"

DOC_POLIZA_SQL = """
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

# Pólizas de documentos cuyas líneas quedan todas fuera de DOC_POLIZA_SQL (importe 0 o solo inventario/proveedores):
# se muestra la póliza sin líneas para que el documento no aparezca sin póliza.
DOC_POLIZA_SIN_LINEAS_SQL = """
SELECT DISTINCT d.FOLIO, pl.Pl_Folio AS POLIZA, pl.Pl_Fecha AS FECHA_POLIZA, pl.Pl_Tipo AS TIPO_POLIZA, pl.Pl_Numero AS NUMERO_POLIZA,
       pl.Pl_Comentario AS CONCEPTO_POLIZA
FROM #docs d
JOIN Poliza_Control plc ON plc.Pc_Tabla='{pc}' AND plc.Pc_Documento=d.FOLIO AND plc.Es_Cve_Estado<>'CA'
JOIN Poliza pl ON pl.Pl_Folio=plc.Pl_Folio AND pl.Es_Cve_Estado<>'CA'
JOIN Poliza_Detalle pd ON pd.Pl_Folio=plc.Pl_Folio AND {pol_ref}
"""
