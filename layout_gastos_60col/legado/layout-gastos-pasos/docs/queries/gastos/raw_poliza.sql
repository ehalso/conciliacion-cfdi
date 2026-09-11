-- Filas crudas de Poliza. Sin 'VARIOS' -- eso es Python
-- (reglas_negocio.resolver_poliza).
SELECT
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
    pl.Pl_Folio, pl.Pl_Fecha, pl.Pl_Tipo, pl.Pl_Numero, pl.Pl_Comentario
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
   AND plc.Es_Cve_Estado <> 'CA'
JOIN Poliza pl
    ON pl.Pl_Folio = plc.Pl_Folio
   AND pl.Es_Cve_Estado <> 'CA'
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
