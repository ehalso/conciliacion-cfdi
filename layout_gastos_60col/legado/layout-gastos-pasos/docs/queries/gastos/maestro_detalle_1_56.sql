-- Query maestra consolidada: columnas 1-18, 41-45, 47-56 del layout de
-- gastos (nivel folio, 1:1). Reemplaza 6 queries independientes
-- (etapa6_columnas_1_18, uuid_factura, xml_detalle, uso_cfdi_por_folio,
-- factura_ref, poliza_descriptiva) fusionadas en un solo round-trip.
--
-- EXCLUYE deliberadamente:
--  - 19-40 (impuestos): estructura de agregacion muy distinta (2 niveles,
--    documento->folio, via Gasto_Registro_Impuesto) -- se mantiene en
--    v5_impuestos_layout.sql, aparte.
--  - 46 (Descripcion Uso bien o servicio): JOIN a catalogo Uso_CFDI --
--    dentro de una cadena de CTEs profunda daba error de columna
--    invalida en pymssql/FreeTDS (bug de driver confirmado) -- se
--    resuelve en pandas.
--  - 22-23 (Descuento/Descuento Global): siempre 0, literal en Python.
--  - 57-60 (Cuenta/Cargo/Abono): grano distinto, aparte por diseño.

WITH folios AS (
    SELECT
        gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
        gr.Gr_Folio, gr.Sc_Cve_Sucursal, gr.Gr_Fecha, gr.Gr_Genera_Cxp,
        gr.Gr_Tabla AS ORIGEN, gr.Gr_Comentario
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = '0001'
      AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
),
documentos AS (
    -- Base compartida (proveedor/moneda/referencia) -- reusada por
    -- proveedor_repr y ref_agg, antes 2 scans separados.
    SELECT
        f.FOLIO, f.Gr_Folio,
        grd.Grd_ID, grd.Mn_Cve_Moneda, grd.Pv_Cve_Proveedor,
        grd.Grd_Precio_Neto_Importe, grd.Grd_Referencia
    FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = f.Gr_Folio
),
doc_rank AS (
    SELECT
        FOLIO, Grd_ID, Mn_Cve_Moneda, Pv_Cve_Proveedor,
        ROW_NUMBER() OVER (PARTITION BY FOLIO ORDER BY Grd_Precio_Neto_Importe DESC, Grd_ID) AS rn
    FROM documentos
),
n_proveedores AS (
    SELECT FOLIO, COUNT(DISTINCT Pv_Cve_Proveedor) AS n_proveedores
    FROM documentos
    GROUP BY FOLIO
),
proveedor_repr AS (
    SELECT d.FOLIO, d.Pv_Cve_Proveedor, d.Mn_Cve_Moneda,
           CASE WHEN np.n_proveedores > 1 THEN 'SI' ELSE 'NO' END AS PROVEEDOR_MULTIPLE
    FROM doc_rank d
    JOIN n_proveedores np ON np.FOLIO = d.FOLIO
    WHERE d.rn = 1
),
ref_agg AS (
    SELECT
        FOLIO,
        COUNT(DISTINCT Grd_Referencia) AS N_REF_DISTINTAS,
        MIN(Grd_Referencia) AS REF_UNICA
    FROM documentos
    WHERE Grd_Referencia IS NOT NULL AND LTRIM(RTRIM(Grd_Referencia)) <> ''
    GROUP BY FOLIO
),
cxp_docs_general AS (
    SELECT DISTINCT f.FOLIO, cxp.Cxp_Folio
    FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = f.Gr_Folio
    JOIN Cuenta_X_Pagar cxp
        ON cxp.Cxp_Tabla = 'Gasto_Registro:' + f.Gr_Folio
       AND cxp.Cxp_Documento = grd.Grd_ID
),
cxp_docs_referencia AS (
    SELECT DISTINCT f.FOLIO, cxp.Cxp_Folio
    FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = f.Gr_Folio
    JOIN Cuenta_X_Pagar cxp
        ON cxp.Cxp_Tabla = 'Cuenta_X_Pagar'
       AND cxp.Cxp_Referencia = grd.Grd_Referencia
       AND cxp.Pv_Cve_Proveedor = grd.Pv_Cve_Proveedor
    WHERE grd.Grd_Referencia IS NOT NULL AND LTRIM(RTRIM(grd.Grd_Referencia)) <> ''
),
cxp_docs AS (
    SELECT * FROM cxp_docs_general
    UNION
    SELECT * FROM cxp_docs_referencia
),
pagos AS (
    SELECT cd.FOLIO, cd.Cxp_Folio, pc.Pc_ID, pc.Fp_Cve_Forma_Pago,
           pc.Pc_Banco, pc.Pc_Cuenta_Bancaria, pc.Pc_Documento, pc.Pc_Tabla,
           ROW_NUMBER() OVER (
               PARTITION BY cd.FOLIO
               ORDER BY CASE WHEN pc.Fp_Cve_Forma_Pago IN ('0001','0002','0003') THEN 0 ELSE 1 END,
                        ABS(pc.Pc_Importe) DESC, pc.Pc_ID
           ) AS rn
    FROM cxp_docs cd
    JOIN Pago_CXP pc ON pc.Cxp_Folio = cd.Cxp_Folio
),
pago_repr AS (
    SELECT p.FOLIO, p.Fp_Cve_Forma_Pago, p.Pc_Banco, p.Pc_Cuenta_Bancaria,
           p.Pc_Documento, p.Pc_Tabla
    FROM pagos p WHERE p.rn = 1
),
cheque_repr AS (
    SELECT pr.FOLIO, ch.Ch_Fecha, ch.Ch_Folio
    FROM pago_repr pr
    LEFT JOIN Cheque ch ON ch.Ch_Folio = pr.Pc_Documento AND pr.Pc_Tabla = 'Cheque'
),
monto_cobrado AS (
    SELECT cd.FOLIO, SUM(pc.Pc_Importe) AS MONTO_COBRADO
    FROM cxp_docs cd
    JOIN Pago_CXP pc ON pc.Cxp_Folio = cd.Cxp_Folio
    GROUP BY cd.FOLIO
),
comprobante_pago AS (
    SELECT cd.FOLIO,
           COUNT(DISTINCT pcc.Pcc_Timbre_UUID) AS N_UUID_PAGO,
           MIN(pcc.Pcc_Timbre_UUID) AS UUID_PAGO_UNICO
    FROM cxp_docs cd
    JOIN Pago_Cxp_Comprobante pcc ON pcc.Cxp_Folio = cd.Cxp_Folio
    GROUP BY cd.FOLIO
),
xml AS (
    -- Un solo join a Comprobante_Digital, todas las columnas necesarias
    -- (antes: 3 joins separados en etapa6/uuid_factura/xml_detalle).
    SELECT
        f.FOLIO,
        cd.Cd_Timbre_UUID, cd.Cd_Timbre_Fecha, cd.Cd_Tipo_CFDI,
        cd.Cd_Serie, cd.Cd_Serie_Folio,
        cd.Cd_RFC_Emisor, cd.Cd_Monto,
        COALESCE(cd.Cd_Metdo_Pago_CFDI, cd.Cd_Metodo_Pago) AS METODO_PAGO,
        cd.Cd_Forma_Pago, cd.Cd_Uso_CFDI
    FROM folios f
    JOIN Comprobante_Digital cd
        ON cd.Cd_Tabla = 'GASTO_REGISTRO'
       AND cd.Cd_Documento LIKE f.Gr_Folio + '%'
       AND cd.Es_Cve_Estado = 'AC'
),
xml_agg AS (
    SELECT
        FOLIO,
        COUNT(DISTINCT Cd_Timbre_UUID) AS N_UUID_XML,
        MIN(Cd_Timbre_UUID)  AS UUID_UNICO,
        MIN(Cd_Timbre_Fecha) AS FECHA_FACTURA_UNICA,
        MIN(Cd_Tipo_CFDI)    AS TIPO_CFDI_UNICO,
        MIN(Cd_Serie)        AS SERIE_UNICA,
        MIN(Cd_Serie_Folio)  AS SERIE_FOLIO_UNICO,
        MIN(Cd_RFC_Emisor)   AS RFC_EMISOR_UNICO,
        MIN(Cd_Monto)        AS MONTO_UNICO,
        MIN(METODO_PAGO)     AS METODO_PAGO_UNICO,
        MIN(Cd_Forma_Pago)   AS FORMA_PAGO_UNICA,
        MIN(Cd_Uso_CFDI)     AS USO_CFDI_UNICO
    FROM xml
    GROUP BY FOLIO
),
poliza_match AS (
    SELECT
        f.FOLIO, pl.Pl_Folio, pl.Pl_Fecha, pl.Pl_Tipo, pl.Pl_Numero, pl.Pl_Comentario
    FROM folios f
    JOIN Poliza_Control plc
        ON plc.Pc_Tabla = 'GASTO_REGISTRO'
       AND plc.Pc_Documento = f.Gr_Folio
       AND plc.Es_Cve_Estado <> 'CA'
    JOIN Poliza pl
        ON pl.Pl_Folio = plc.Pl_Folio
       AND pl.Es_Cve_Estado <> 'CA'
),
poliza_agg AS (
    SELECT
        FOLIO,
        COUNT(DISTINCT Pl_Folio) AS N_POLIZAS,
        MIN(Pl_Fecha)      AS FECHA_UNICA,
        MIN(Pl_Tipo)       AS TIPO_UNICO,
        MIN(Pl_Numero)     AS NUMERO_UNICO,
        MIN(Pl_Comentario) AS COMENTARIO_UNICO
    FROM poliza_match
    GROUP BY FOLIO
)
SELECT
    f.FOLIO,
    f.ORIGEN,
    f.Gr_Fecha AS FECHA,
    f.Gr_Comentario AS CONCEPTO_GASTO,
    p.Mn_Cve_Moneda AS MONEDA,
    p.Pv_Cve_Proveedor AS CLAVE_PROVEEDOR,
    prov.Pv_R_F_C AS RFC_PROVEEDOR,
    prov.Pv_Descripcion AS NOMBRE_PROVEEDOR,
    p.PROVEEDOR_MULTIPLE,
    CASE WHEN pr.Fp_Cve_Forma_Pago = '0001' THEN 'SI'
         WHEN pr.Fp_Cve_Forma_Pago IS NULL THEN NULL ELSE 'NO' END AS COBRADO_EFECTIVO,
    CASE WHEN pr.Fp_Cve_Forma_Pago IN ('0002','0003') THEN 'SI'
         WHEN pr.Fp_Cve_Forma_Pago IS NULL THEN NULL ELSE 'NO' END AS COBRADO_CHEQUE_TRANSFERENCIA,
    CASE WHEN pr.Fp_Cve_Forma_Pago = '0002' THEN 'SI'
         WHEN pr.Fp_Cve_Forma_Pago IS NULL THEN NULL ELSE 'NO' END AS CHEQUE,
    CASE WHEN cp.N_UUID_PAGO >= 2 THEN 'VARIOS' ELSE cp.UUID_PAGO_UNICO END AS CFDI_COMPROBANTE_PAGO,
    CASE WHEN ra.N_REF_DISTINTAS >= 2 THEN 'VARIOS' ELSE ra.REF_UNICA END AS FACTURA_REF,
    pr.Pc_Banco AS BANCO,
    pr.Pc_Cuenta_Bancaria AS CUENTA_BANCARIA,
    ch.Ch_Fecha AS FECHA_CHEQUE,
    ch.Ch_Folio AS NO_CHEQUE_TRANSF,
    mc.MONTO_COBRADO,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS'
         WHEN xa.TIPO_CFDI_UNICO = 'I' THEN 'Ingreso'
         WHEN xa.TIPO_CFDI_UNICO = 'E' THEN 'Egreso'
         WHEN xa.TIPO_CFDI_UNICO = 'D' THEN 'Diario'
         ELSE NULL END AS TIPO_COMPROBANTE,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS' ELSE xa.SERIE_FOLIO_UNICO END AS NUMERO_FACTURA,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS' ELSE xa.UUID_UNICO END AS UUID,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS' ELSE LEFT(xa.UUID_UNICO, 4) END AS UUID_4,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS' ELSE CONVERT(varchar(19), xa.FECHA_FACTURA_UNICA, 120) END AS FECHA_FACTURA,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS' ELSE xa.USO_CFDI_UNICO END AS CLAVE_USO_BIEN_SERVICIO,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS' ELSE xa.RFC_EMISOR_UNICO END AS XML_RFC_EMISOR,
    CASE WHEN xa.N_UUID_XML >= 2 THEN NULL ELSE xa.MONTO_UNICO END AS XML_MONTO,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS' ELSE xa.SERIE_UNICA END AS XML_SERIE,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS' ELSE xa.SERIE_FOLIO_UNICO END AS XML_FOLIO,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS' ELSE xa.METODO_PAGO_UNICO END AS XML_METODO_PAGO,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS' ELSE xa.FORMA_PAGO_UNICA END AS XML_FORMA_PAGO,
    CASE WHEN pa.N_POLIZAS >= 2 THEN 'VARIOS' ELSE CONVERT(varchar(19), pa.FECHA_UNICA, 120) END AS FECHA_POLIZA,
    CASE WHEN pa.N_POLIZAS >= 2 THEN NULL ELSE pa.TIPO_UNICO END AS TIPO_POLIZA,
    CASE WHEN pa.N_POLIZAS >= 2 THEN 'VARIOS' ELSE pa.NUMERO_UNICO END AS NUMERO_POLIZA,
    CASE WHEN pa.N_POLIZAS >= 2 THEN 'VARIOS' ELSE pa.COMENTARIO_UNICO END AS CONCEPTO_POLIZA
FROM folios f
LEFT JOIN proveedor_repr p    ON p.FOLIO = f.FOLIO
LEFT JOIN Proveedor prov      ON prov.Pv_Cve_Proveedor = p.Pv_Cve_Proveedor
LEFT JOIN pago_repr pr        ON pr.FOLIO = f.FOLIO
LEFT JOIN cheque_repr ch      ON ch.FOLIO = f.FOLIO
LEFT JOIN monto_cobrado mc    ON mc.FOLIO = f.FOLIO
LEFT JOIN comprobante_pago cp ON cp.FOLIO = f.FOLIO
LEFT JOIN ref_agg ra          ON ra.FOLIO = f.FOLIO
LEFT JOIN xml_agg xa          ON xa.FOLIO = f.FOLIO
LEFT JOIN poliza_agg pa       ON pa.FOLIO = f.FOLIO
ORDER BY f.FOLIO
