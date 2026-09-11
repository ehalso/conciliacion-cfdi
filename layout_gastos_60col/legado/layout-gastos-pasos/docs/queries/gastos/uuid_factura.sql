-- Columnas 41-42 del layout: UUID (de Comprobante_Digital, XML de factura)
-- y UUID_4 (primeros 4 caracteres del UUID). Misma logica de match y de
-- dedup ya validada en etapa6_columnas_1_18.sql (CTE xml/xml_agg) --
-- COUNT(DISTINCT Cd_Timbre_UUID), no COUNT(*) crudo, porque un folio puede
-- tener el mismo UUID repetido en mas de una fila sin ser "Varios" real
-- (confirmado con check_uuid_por_folio.py, folios como 0005-0190741).

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
xml AS (
    SELECT f.FOLIO, cd.Cd_Timbre_UUID
    FROM folios f
    JOIN Comprobante_Digital cd
        ON cd.Cd_Tabla = 'GASTO_REGISTRO'
       AND cd.Cd_Documento LIKE f.Gr_Folio + '%'
       AND cd.Es_Cve_Estado = 'AC'
),
xml_agg AS (
    SELECT FOLIO,
           COUNT(DISTINCT Cd_Timbre_UUID) AS N_UUID_XML,
           MIN(Cd_Timbre_UUID)            AS UUID_UNICO
    FROM xml
    GROUP BY FOLIO
)
SELECT
    f.FOLIO,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS' ELSE xa.UUID_UNICO END AS UUID,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS' ELSE LEFT(xa.UUID_UNICO, 4) END AS UUID_4
FROM folios f
LEFT JOIN xml_agg xa ON xa.FOLIO = f.FOLIO
