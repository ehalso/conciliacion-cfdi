-- Filas crudas de comprobante de pago (Pago_Cxp_Comprobante). Mismo
-- cxp_docs que raw_pagos.sql -- se repite aqui porque es una tabla
-- distinta, no vale la pena forzarlas al mismo SELECT.
WITH folios AS (
    SELECT
        gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
        gr.Gr_Folio
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = '0001'
      AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
),
cxp_docs AS (
    SELECT DISTINCT f.FOLIO, cxp.Cxp_Folio
    FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = f.Gr_Folio
    JOIN Cuenta_X_Pagar cxp
        ON cxp.Cxp_Tabla = 'Gasto_Registro:' + f.Gr_Folio
       AND cxp.Cxp_Documento = grd.Grd_ID
    UNION
    SELECT DISTINCT f.FOLIO, cxp.Cxp_Folio
    FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = f.Gr_Folio
    JOIN Cuenta_X_Pagar cxp
        ON cxp.Cxp_Tabla = 'Cuenta_X_Pagar'
       AND cxp.Cxp_Referencia = grd.Grd_Referencia
       AND cxp.Pv_Cve_Proveedor = grd.Pv_Cve_Proveedor
    WHERE grd.Grd_Referencia IS NOT NULL AND LTRIM(RTRIM(grd.Grd_Referencia)) <> ''
)
SELECT cd.FOLIO, cd.Cxp_Folio, pcc.Pcc_Timbre_UUID
FROM cxp_docs cd
JOIN Pago_Cxp_Comprobante pcc ON pcc.Cxp_Folio = cd.Cxp_Folio
