-- Filas crudas a nivel documento (Grd_ID). Sin agregar, sin decidir nada --
-- eso vive en Python (reglas_negocio.resolver_proveedor / resolver_referencia).
SELECT
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
    grd.Grd_ID, grd.Mn_Cve_Moneda, grd.Pv_Cve_Proveedor,
    grd.Grd_Precio_Neto_Importe, grd.Grd_Referencia
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = gr.Gr_Folio
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
