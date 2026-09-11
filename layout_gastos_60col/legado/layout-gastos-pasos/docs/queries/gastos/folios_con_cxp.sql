-- Indicador por FOLIO: tiene o no una Cuenta_X_Pagar relacionada.
-- Reusa la misma logica de match ya validada en etapa6_columnas_1_18.sql
-- (documento + referencia consolidada, con el fix de Grd_Referencia no
-- vacio) -- PERO solo hasta Cuenta_X_Pagar, sin llegar a Pago_CXP.
-- Util para separar el universo antes de reconciliar pagos.

WITH folios AS (
    SELECT
        gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
        gr.Gr_Folio, gr.Gr_Genera_Cxp, gr.Gr_Tabla AS ORIGEN
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = '0001'
      AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
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
)
SELECT
    f.FOLIO, f.ORIGEN, f.Gr_Genera_Cxp,
    COUNT(cd.Cxp_Folio) AS N_CXP_FOLIOS
FROM folios f
LEFT JOIN cxp_docs cd ON cd.FOLIO = f.FOLIO
GROUP BY f.FOLIO, f.ORIGEN, f.Gr_Genera_Cxp
