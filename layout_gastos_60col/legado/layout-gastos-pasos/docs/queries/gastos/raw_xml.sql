-- Filas crudas de Comprobante_Digital. Sin COUNT DISTINCT, sin 'VARIOS' --
-- eso es Python (reglas_negocio.resolver_xml).
SELECT
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
    cd.Cd_Timbre_UUID, cd.Cd_Timbre_Fecha, cd.Cd_Tipo_CFDI,
    cd.Cd_Serie, cd.Cd_Serie_Folio, cd.Cd_RFC_Emisor, cd.Cd_Monto,
    COALESCE(cd.Cd_Metdo_Pago_CFDI, cd.Cd_Metodo_Pago) AS METODO_PAGO,
    cd.Cd_Forma_Pago, cd.Cd_Uso_CFDI
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Comprobante_Digital cd
    ON cd.Cd_Tabla = 'GASTO_REGISTRO'
   AND cd.Cd_Documento LIKE gr.Gr_Folio + '%'
   AND cd.Es_Cve_Estado = 'AC'
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
