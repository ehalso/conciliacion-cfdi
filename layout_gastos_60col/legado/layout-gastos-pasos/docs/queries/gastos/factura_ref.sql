-- Columna 11 del layout: FACTURA_REF. Antes gap conocido -- se identifico
-- que es Grd_Referencia (Gasto_Registro_Documento), el mismo campo usado
-- para el match de CXP por referencia consolidada (combustible). Un folio
-- puede tener varios documentos con referencias distintas -- mismo patron
-- 'VARIOS' que el resto del layout cuando N_REF_DISTINTAS >= 2.

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
ref_agg AS (
    SELECT
        f.FOLIO,
        COUNT(DISTINCT grd.Grd_Referencia) AS N_REF_DISTINTAS,
        MIN(grd.Grd_Referencia) AS REF_UNICA
    FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = f.Gr_Folio
    WHERE grd.Grd_Referencia IS NOT NULL AND LTRIM(RTRIM(grd.Grd_Referencia)) <> ''
    GROUP BY f.FOLIO
)
SELECT
    f.FOLIO,
    CASE WHEN ra.N_REF_DISTINTAS >= 2 THEN 'VARIOS' ELSE ra.REF_UNICA END AS FACTURA_REF
FROM folios f
LEFT JOIN ref_agg ra ON ra.FOLIO = f.FOLIO
