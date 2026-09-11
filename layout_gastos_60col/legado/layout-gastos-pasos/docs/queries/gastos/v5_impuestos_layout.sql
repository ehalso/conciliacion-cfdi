-- v5.0 -- Clasificacion final de impuestos por folio para el layout de gastos.
-- Fix 2026-08-04: agregacion en DOS niveles (documento -> folio) para evitar
-- fan-out cuando un folio tiene varios Grd_ID con montos distintos.
-- Fix 2026-08-07: TODAS las columnas monetarias multiplicadas por
-- Grd_Tipo_Cambio -- la version anterior traia todo en moneda ORIGINAL,
-- sin convertir. Paso desapercibido porque la validacion interna
-- (Subtotal + IVA + Retenciones = Total) es consistente consigo misma
-- en cualquier moneda -- solo se detecto al comparar TOTAL contra el
-- baseline (que si convierte, via paso2) en un folio USD
-- (0005-0175047: TOTAL sin convertir 3,201.60 vs baseline 57,496.57 MXN).

WITH doc_impuestos AS (
    SELECT
        gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
        grd.Grd_ID,
        grd.Grd_Tipo_Cambio,
        grd.Grd_Precio_Descontado_Importe,
        grd.Grd_Precio_Neto_Importe,
        grd.Grd_Impuesto_Importe,
        SUM(CASE WHEN i.Im_Tasa = 16.0000 AND i.Im_Tipo_Factor = 'Tasa'
                 THEN gri.Gri_Base_Gravable ELSE 0 END)                AS SUBTOTAL_16,
        SUM(CASE WHEN i.Im_Tasa = 0.0000 AND i.Im_Tipo_Factor = 'Tasa'
                 THEN gri.Gri_Base_Gravable ELSE 0 END)                AS SUBTOTAL_0,
        SUM(CASE WHEN i.Im_Tipo_Factor = 'Exento'
                 THEN gri.Gri_Base_Gravable ELSE 0 END)                AS SUBTOTAL_EXENTA,
        SUM(CASE WHEN i.Im_Cve_Impuesto = '0026' THEN gri.Gri_Importe ELSE 0 END) AS ISR_RESICO_1_25,
        SUM(CASE WHEN i.Im_Cve_Impuesto = '0023' THEN gri.Gri_Importe ELSE 0 END) AS IVA_ARRENDAMIENTO_10_67,
        SUM(CASE WHEN i.Im_Cve_Impuesto = '0022' THEN gri.Gri_Importe ELSE 0 END) AS IMSS_PATRON,
        SUM(CASE WHEN i.Im_Cve_Impuesto = '0018' THEN gri.Gri_Importe ELSE 0 END) AS IVA_HONORARIOS_10_67,
        SUM(CASE WHEN i.Im_Cve_Impuesto = '0015' THEN gri.Gri_Importe ELSE 0 END) AS IVA_FLETES_4_PROVEEDOR,
        SUM(CASE WHEN i.Im_Cve_Impuesto = '0014' THEN gri.Gri_Importe ELSE 0 END) AS ISR_INTERESES_20,
        SUM(CASE WHEN i.Im_Cve_Impuesto = '0013' THEN gri.Gri_Importe ELSE 0 END) AS ISR_DIVIDENDOS_10,
        SUM(CASE WHEN i.Im_Cve_Impuesto = '0012' THEN gri.Gri_Importe ELSE 0 END) AS ISR_ARRENDAMIENTOS_10,
        SUM(CASE WHEN i.Im_Cve_Impuesto = '0011' THEN gri.Gri_Importe ELSE 0 END) AS ISR_HONORARIOS_10,
        SUM(CASE WHEN i.Im_Cve_Impuesto = '0005' THEN gri.Gri_Importe ELSE 0 END) AS IVA_IMPORTACION,
        SUM(CASE WHEN i.Im_Cve_Impuesto = '0003' THEN gri.Gri_Importe ELSE 0 END) AS IVA_ACREDITABLE_0,
        SUM(CASE WHEN i.Im_Cve_Impuesto = '0002' THEN gri.Gri_Importe ELSE 0 END) AS IVA_ACREDITABLE_16_VARIABLE,
        SUM(CASE WHEN i.Im_Cve_Impuesto = '0001' THEN gri.Gri_Importe ELSE 0 END) AS IVA_ACREDITABLE_16,
        SUM(CASE WHEN i.Im_Cve_Impuesto IN ('0023','0018','0015','0024','0016','0017')
                 THEN gri.Gri_Importe ELSE 0 END)                      AS RETENCIONES_IVA,
        SUM(CASE WHEN i.Im_Cve_Impuesto IN ('0026','0014','0013','0012','0011','0009','0010')
                 THEN gri.Gri_Importe ELSE 0 END)                      AS RETENCIONES_ISR,
        SUM(gri.Gri_Importe)                                           AS SUMA_GRI_IMPORTE_DOC
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
    LEFT JOIN Gasto_Registro_Impuesto gri ON gri.Gr_Folio = grd.Gr_Folio AND gri.Grd_ID = grd.Grd_ID
    LEFT JOIN Impuesto i ON i.Im_Cve_Impuesto = gri.Im_Cve_Impuesto
    WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = '0001'
      AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
    GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, grd.Grd_ID, grd.Grd_Tipo_Cambio,
             grd.Grd_Precio_Descontado_Importe, grd.Grd_Precio_Neto_Importe, grd.Grd_Impuesto_Importe
)
SELECT
    FOLIO,
    SUM(SUBTOTAL_16 * Grd_Tipo_Cambio)                    AS SUBTOTAL_16,
    SUM(SUBTOTAL_0 * Grd_Tipo_Cambio)                     AS SUBTOTAL_0,
    SUM(SUBTOTAL_EXENTA * Grd_Tipo_Cambio)                AS SUBTOTAL_EXENTA,
    CAST(0 AS money)                                      AS DESCUENTO,
    CAST(0 AS money)                                      AS DESCUENTO_GLOBAL,
    SUM(Grd_Precio_Descontado_Importe * Grd_Tipo_Cambio)  AS SUBTOTAL_NETO,
    SUM(Grd_Precio_Neto_Importe * Grd_Tipo_Cambio)        AS TOTAL,
    SUM(ISR_RESICO_1_25 * Grd_Tipo_Cambio)                AS ISR_RESICO_1_25,
    SUM(IVA_ARRENDAMIENTO_10_67 * Grd_Tipo_Cambio)        AS IVA_ARRENDAMIENTO_10_67,
    SUM(IMSS_PATRON * Grd_Tipo_Cambio)                    AS IMSS_PATRON,
    SUM(IVA_HONORARIOS_10_67 * Grd_Tipo_Cambio)           AS IVA_HONORARIOS_10_67,
    SUM(IVA_FLETES_4_PROVEEDOR * Grd_Tipo_Cambio)         AS IVA_FLETES_4_PROVEEDOR,
    SUM(ISR_INTERESES_20 * Grd_Tipo_Cambio)               AS ISR_INTERESES_20,
    SUM(ISR_DIVIDENDOS_10 * Grd_Tipo_Cambio)              AS ISR_DIVIDENDOS_10,
    SUM(ISR_ARRENDAMIENTOS_10 * Grd_Tipo_Cambio)          AS ISR_ARRENDAMIENTOS_10,
    SUM(ISR_HONORARIOS_10 * Grd_Tipo_Cambio)              AS ISR_HONORARIOS_10,
    SUM(IVA_IMPORTACION * Grd_Tipo_Cambio)                AS IVA_IMPORTACION,
    SUM(IVA_ACREDITABLE_0 * Grd_Tipo_Cambio)              AS IVA_ACREDITABLE_0,
    SUM(IVA_ACREDITABLE_16_VARIABLE * Grd_Tipo_Cambio)    AS IVA_ACREDITABLE_16_VARIABLE,
    SUM(IVA_ACREDITABLE_16 * Grd_Tipo_Cambio)             AS IVA_ACREDITABLE_16,
    SUM(RETENCIONES_IVA * Grd_Tipo_Cambio)                AS RETENCIONES_IVA,
    SUM(RETENCIONES_ISR * Grd_Tipo_Cambio)                AS RETENCIONES_ISR,
    SUM(Grd_Impuesto_Importe * Grd_Tipo_Cambio)           AS IMPUESTO_IMPORTE_DOCUMENTO,
    SUM(SUMA_GRI_IMPORTE_DOC * Grd_Tipo_Cambio)           AS SUMA_GRI_IMPORTE
FROM doc_impuestos
GROUP BY FOLIO
