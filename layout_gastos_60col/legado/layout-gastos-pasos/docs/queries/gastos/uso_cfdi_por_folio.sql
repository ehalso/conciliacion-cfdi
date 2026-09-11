-- Columnas 44-45 del layout (sin el JOIN al catalogo -- ese se resuelve en
-- pandas, ver paso10_concepto_uso_cfdi.py). Solo trae la clave cruda.
-- El JOIN a Uso_CFDI dentro de un 4to CTE anidado daba error de columna
-- invalida en pymssql/FreeTDS (bug del driver, no de SQL Server -- el
-- mismo JOIN funciona bien fuera de CTEs anidados, confirmado con prueba
-- minima). Se separa el join del catalogo a Python para evitarlo.

WITH folios AS (
    SELECT
        gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
        gr.Gr_Folio, gr.Gr_Comentario
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = '0001'
      AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
),
uso_cfdi AS (
    SELECT f.FOLIO, cd.Cd_Uso_CFDI
    FROM folios f
    JOIN Comprobante_Digital cd
        ON cd.Cd_Tabla = 'GASTO_REGISTRO'
       AND cd.Cd_Documento LIKE f.Gr_Folio + '%'
       AND cd.Es_Cve_Estado = 'AC'
),
uso_cfdi_agg AS (
    SELECT FOLIO,
           COUNT(DISTINCT Cd_Uso_CFDI) AS N_USO_CFDI,
           MIN(Cd_Uso_CFDI) AS USO_CFDI_UNICO
    FROM uso_cfdi
    WHERE Cd_Uso_CFDI IS NOT NULL AND LTRIM(RTRIM(Cd_Uso_CFDI)) <> ''
    GROUP BY FOLIO
)
SELECT
    f.FOLIO,
    f.Gr_Comentario AS CONCEPTO_GASTO,
    CASE WHEN ua.N_USO_CFDI >= 2 THEN 'VARIOS' ELSE ua.USO_CFDI_UNICO END AS CLAVE_USO_BIEN_SERVICIO
FROM folios f
LEFT JOIN uso_cfdi_agg ua ON ua.FOLIO = f.FOLIO
