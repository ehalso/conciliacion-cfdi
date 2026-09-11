-- Columnas 43, 47-52 del layout: Fecha Factura, XML RFC EMISOR, XML MONTO,
-- XML SERIE, XML FOLIO, XML METODO PAGO, XML FORMA PAGO.
-- Fuente: Comprobante_Digital, mismo match que UUID/etapa6 (Cd_Documento
-- LIKE folio+'%', Cd_Tabla='GASTO_REGISTRO', Es_Cve_Estado='AC').
--
-- Notas de columnas confirmadas con datos reales (2026-08-07):
--  - Cd_Serie_Folio (no Cd_Factura, casi vacia: 2/95,561) es XML FOLIO --
--    mismo campo ya usado en etapa6_columnas_1_18.sql para NUMERO_FACTURA
--    (columna 18 del layout, mismo dato con nombre distinto).
--  - Metodo de pago: COALESCE(Cd_Metdo_Pago_CFDI, Cd_Metodo_Pago) --
--    ambas traen el mismo valor cuando estan pobladas (80,640/80,640
--    coinciden 100%), pero Cd_Metdo_Pago_CFDI cubre 12,471 filas mas.
--
-- Grano: 1 fila/folio, mismo dedup por UUID distinto que uuid_factura.sql
-- (si 2+ documentos con datos distintos, 'VARIOS').

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
    SELECT
        f.FOLIO,
        cd.Cd_Timbre_UUID,
        cd.Cd_Timbre_Fecha,
        cd.Cd_RFC_Emisor,
        cd.Cd_Monto,
        cd.Cd_Serie,
        cd.Cd_Serie_Folio,
        COALESCE(cd.Cd_Metdo_Pago_CFDI, cd.Cd_Metodo_Pago) AS METODO_PAGO,
        cd.Cd_Forma_Pago
    FROM folios f
    JOIN Comprobante_Digital cd
        ON cd.Cd_Tabla = 'GASTO_REGISTRO'
       AND cd.Cd_Documento LIKE f.Gr_Folio + '%'
       AND cd.Es_Cve_Estado = 'AC'
),
xml_agg AS (
    SELECT
        FOLIO,
        COUNT(DISTINCT Cd_Timbre_UUID) AS N_UUID,
        MIN(Cd_Timbre_Fecha) AS FECHA_FACTURA_UNICA,
        MIN(Cd_RFC_Emisor)   AS RFC_EMISOR_UNICO,
        MIN(Cd_Monto)        AS MONTO_UNICO,
        MIN(Cd_Serie)        AS SERIE_UNICA,
        MIN(Cd_Serie_Folio)  AS SERIE_FOLIO_UNICO,
        MIN(METODO_PAGO)     AS METODO_PAGO_UNICO,
        MIN(Cd_Forma_Pago)   AS FORMA_PAGO_UNICA
    FROM xml
    GROUP BY FOLIO
)
SELECT
    f.FOLIO,
    CASE WHEN xa.N_UUID >= 2 THEN 'VARIOS' ELSE CONVERT(varchar(19), xa.FECHA_FACTURA_UNICA, 120) END AS FECHA_FACTURA,
    CASE WHEN xa.N_UUID >= 2 THEN 'VARIOS' ELSE xa.RFC_EMISOR_UNICO END   AS XML_RFC_EMISOR,
    CASE WHEN xa.N_UUID >= 2 THEN NULL ELSE xa.MONTO_UNICO END            AS XML_MONTO,
    CASE WHEN xa.N_UUID >= 2 THEN 'VARIOS' ELSE xa.SERIE_UNICA END        AS XML_SERIE,
    CASE WHEN xa.N_UUID >= 2 THEN 'VARIOS' ELSE xa.SERIE_FOLIO_UNICO END  AS XML_FOLIO,
    CASE WHEN xa.N_UUID >= 2 THEN 'VARIOS' ELSE xa.METODO_PAGO_UNICO END  AS XML_METODO_PAGO,
    CASE WHEN xa.N_UUID >= 2 THEN 'VARIOS' ELSE xa.FORMA_PAGO_UNICA END   AS XML_FORMA_PAGO
FROM folios f
LEFT JOIN xml_agg xa ON xa.FOLIO = f.FOLIO
