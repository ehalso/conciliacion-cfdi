-- Columnas 44-46 del layout: Concepto gasto (comentario del folio),
-- Clave Uso bien o servicio (Cd_Uso_CFDI), Descripcion Uso bien o servicio
-- (JOIN contra Uso_CFDI, catalogo real de MPRO).
--
-- Reescrito para separar el JOIN a Uso_CFDI del calculo de 'VARIOS' en dos
-- pasos -- la version anterior con el JOIN condicionado dentro del mismo
-- nivel que el CASE de conteo daba error de columna invalida en pymssql.

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
),
uso_cfdi_con_desc AS (
    -- Paso separado: el JOIN a Uso_CFDI vive aqui solo, sin mezclarse
    -- con el CASE de conteo en el mismo SELECT.
    SELECT
        ua.FOLIO,
        ua.N_USO_CFDI,
        ua.USO_CFDI_UNICO,
        uc.Uc_Descripcion
    FROM uso_cfdi_agg ua
    LEFT JOIN Uso_CFDI uc ON uc.Uc_Cve_Uso_CFDI = ua.USO_CFDI_UNICO
)
SELECT
    f.FOLIO,
    f.Gr_Comentario AS CONCEPTO_GASTO,
    CASE WHEN ud.N_USO_CFDI >= 2 THEN 'VARIOS' ELSE ud.USO_CFDI_UNICO END AS CLAVE_USO_BIEN_SERVICIO,
    CASE WHEN ud.N_USO_CFDI >= 2 THEN 'VARIOS' ELSE ud.Uc_Descripcion END AS DESCRIPCION_USO_BIEN_SERVICIO
FROM folios f
LEFT JOIN uso_cfdi_con_desc ud ON ud.FOLIO = f.FOLIO
