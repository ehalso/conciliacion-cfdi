-- ============================================================================
-- Layout de Gastos -- Detalle de Cargo/Abono por CUENTA CONTABLE, sin
-- Centro de Costo. Misma base que v03_detalle_cuenta_centro_costo.sql,
-- quitando Pd_Centro_Costo del SELECT/GROUP BY -- la hipotesis es que los
-- folios de "reparto corporativo" (1 documento, 80+ centros de costo, misma
-- cuenta contable) colapsan aqui a 1-2 filas por folio.
--
-- OJO: si un folio reparte el mismo Cargo entre varias CUENTAS distintas
-- (no solo centros de costo), este nivel seguira teniendo varias filas --
-- eso es correcto, no es el mismo problema que con centro de costo.
-- ============================================================================

SELECT
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
    pd.Cc_Cve_Cuenta_Contable AS CUENTA,
    cc.Cc_Descripcion AS CUENTA_DESCRIPCION,
    SUM(CASE WHEN pd.Pd_Tipo = 1 THEN pd.Pd_Importe ELSE 0 END) AS CARGO,
    SUM(CASE WHEN pd.Pd_Tipo = 2 THEN pd.Pd_Importe ELSE 0 END) AS ABONO

FROM Gasto_Registro gr
    JOIN Sucursal s
        ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    JOIN Poliza_Control plc
        ON plc.Pc_Tabla = 'GASTO_REGISTRO'
       AND plc.Pc_Documento = gr.Gr_Folio
       AND plc.Es_Cve_Estado <> 'CA'
    JOIN Poliza pl
        ON pl.Pl_Folio = plc.Pl_Folio
    JOIN Poliza_Detalle pd
        ON pd.Pl_Folio = plc.Pl_Folio
       AND pd.Pd_Referencia = gr.Gr_Folio
    LEFT JOIN Cuenta_Contable cc
        ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable

WHERE gr.Gr_Fecha >= :fecha_ini
  AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND pl.Es_Cve_Estado <> 'CA'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')

GROUP BY
    gr.Sc_Cve_Sucursal, gr.Gr_Folio,
    pd.Cc_Cve_Cuenta_Contable, cc.Cc_Descripcion
