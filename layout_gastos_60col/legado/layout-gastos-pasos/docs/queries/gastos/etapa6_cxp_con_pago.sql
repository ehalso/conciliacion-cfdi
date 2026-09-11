-- Etapa 6 -- extension de etapa6_cxp_con_folio.sql, encadenando hasta
-- Pago_CXP y Cheque. Explota deliberadamente (multiples filas por FOLIO
-- posibles, tanto por multiples Cxp_Folio en combustible como por
-- multiples Pc_ID de pago) -- de-duplicar en Python con el mismo
-- criterio de prioridad ya usado en etapa6_columnas_1_18.sql.

WITH cxp_general AS (
    SELECT
        gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
        grd.Grd_ID,
        cxp.Cxp_Folio,
        'documento' AS GRANULARIDAD_CXP
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
    JOIN Cuenta_X_Pagar cxp
        ON cxp.Cxp_Tabla = 'Gasto_Registro:' + gr.Gr_Folio
       AND cxp.Cxp_Documento = grd.Grd_ID
    WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = '0001'
      AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO', 'CONTROL_COMBUSTIBLE')
),
combustible_folios_enero AS (
    SELECT
        gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
        grd.Grd_ID, grd.Grd_Referencia, grd.Pv_Cve_Proveedor
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
    WHERE gr.Gr_Tabla = 'CONTROL_COMBUSTIBLE'
      AND gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = '0001'
),
cxp_combustible AS (
    SELECT
        cf.FOLIO, cf.Grd_ID, cxp.Cxp_Folio,
        'referencia_consolidada' AS GRANULARIDAD_CXP
    FROM combustible_folios_enero cf
    JOIN Cuenta_X_Pagar cxp
        ON cxp.Cxp_Tabla = 'Cuenta_X_Pagar'
       AND cxp.Cxp_Referencia = cf.Grd_Referencia
       AND cxp.Pv_Cve_Proveedor = cf.Pv_Cve_Proveedor
),
cxp_con_folio AS (
    SELECT * FROM cxp_general
    UNION ALL
    SELECT * FROM cxp_combustible
)
SELECT DISTINCT
    ccf.FOLIO,
    ccf.GRANULARIDAD_CXP,
    pc.Pc_ID,
    pc.Fp_Cve_Forma_Pago,
    pc.Pc_Banco,
    pc.Pc_Cuenta_Bancaria,
    pc.Pc_Documento,
    pc.Pc_Tabla,
    pc.Pc_Importe,
    pc.Pc_Fecha
FROM cxp_con_folio ccf
JOIN Pago_CXP pc ON pc.Cxp_Folio = ccf.Cxp_Folio
