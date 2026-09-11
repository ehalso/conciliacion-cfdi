-- v3.0 -- CXP consolidado: caso general + caso CONTROL_COMBUSTIBLE.
-- UNION ALL: las dos ramas usan una llave de match distinta.
--
-- GRANULARIDAD_CXP indica como interpretar CXP_MONEDA_ORIGINAL:
--   'documento'              -> match exacto para este Grd_ID, usar tal cual.
--   'referencia_consolidada' -> total de TODA la referencia semanal
--                                (repetido en cada folio que la comparte).
--                                NUNCA sumar por folio; comparar/usar 1 vez
--                                por REFERENCIA.
--
-- Fix 2026-08-04: GASTO_REFERENCIA_TOTAL debe sumar TODOS los folios que
-- comparten (Grd_Referencia, Pv_Cve_Proveedor), sin restringir por fecha ni
-- por Gr_Tabla -- los folios "tardios" (Gr_Tabla vacio) suelen caer el mes
-- siguiente. Restringir esa suma a enero + CONTROL_COMBUSTIBLE rompe el match.

WITH cxp_general AS (
    SELECT
        gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
        grd.Grd_ID,
        gr.Gr_Genera_Cxp,
        gr.Gr_Tabla                                                  AS ORIGEN,
        grd.Mn_Cve_Moneda,
        grd.Grd_Precio_Neto_Importe                                  AS GASTO_MONEDA_ORIGINAL,
        cxp.Cxp_Precio_Neto_Importe                                  AS CXP_MONEDA_ORIGINAL,
        CAST(NULL AS money)                                          AS GASTO_REFERENCIA_TOTAL,
        CAST(NULL AS nvarchar(50))                                   AS REFERENCIA,
        'documento'                                                  AS GRANULARIDAD_CXP
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
    LEFT JOIN Cuenta_X_Pagar cxp
        ON cxp.Cxp_Tabla = 'Gasto_Registro:' + gr.Gr_Folio
       AND cxp.Cxp_Documento = grd.Grd_ID
    WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = '0001'
      AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO', 'CONTROL_COMBUSTIBLE')
),
combustible_folios_enero AS (
    SELECT
        gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
        grd.Grd_ID,
        gr.Gr_Genera_Cxp,
        gr.Gr_Tabla                 AS ORIGEN,
        grd.Mn_Cve_Moneda,
        grd.Grd_Precio_Neto_Importe AS GASTO_MONEDA_ORIGINAL,
        grd.Grd_Referencia,
        grd.Pv_Cve_Proveedor
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
    WHERE gr.Gr_Tabla = 'CONTROL_COMBUSTIBLE'
      AND gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = '0001'
),
referencias_combustible AS (
    SELECT DISTINCT Grd_Referencia, Pv_Cve_Proveedor
    FROM combustible_folios_enero
),
combustible_gasto_total_ref AS (
    -- Total real por referencia: TODOS los folios que la comparten, sin
    -- restringir fecha ni Gr_Tabla (incluye los folios tardios de febrero).
    SELECT grd.Grd_Referencia, grd.Pv_Cve_Proveedor,
           SUM(grd.Grd_Precio_Neto_Importe) AS GASTO_REFERENCIA_TOTAL
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
    JOIN referencias_combustible rc
        ON rc.Grd_Referencia = grd.Grd_Referencia
       AND rc.Pv_Cve_Proveedor = grd.Pv_Cve_Proveedor
    WHERE gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = '0001'
    GROUP BY grd.Grd_Referencia, grd.Pv_Cve_Proveedor
),
combustible_cxp_ref AS (
    SELECT Cxp_Referencia, Pv_Cve_Proveedor,
           SUM(Cxp_Precio_Neto_Importe) AS CXP_REFERENCIA_TOTAL
    FROM Cuenta_X_Pagar
    WHERE Cxp_Tabla = 'Cuenta_X_Pagar'
    GROUP BY Cxp_Referencia, Pv_Cve_Proveedor
),
cxp_combustible AS (
    SELECT
        cf.FOLIO, cf.Grd_ID, cf.Gr_Genera_Cxp, cf.ORIGEN, cf.Mn_Cve_Moneda,
        cf.GASTO_MONEDA_ORIGINAL,
        ccr.CXP_REFERENCIA_TOTAL AS CXP_MONEDA_ORIGINAL,
        gtr.GASTO_REFERENCIA_TOTAL,
        cf.Grd_Referencia        AS REFERENCIA,
        'referencia_consolidada' AS GRANULARIDAD_CXP
    FROM combustible_folios_enero cf
    LEFT JOIN combustible_cxp_ref ccr
        ON ccr.Cxp_Referencia = cf.Grd_Referencia AND ccr.Pv_Cve_Proveedor = cf.Pv_Cve_Proveedor
    LEFT JOIN combustible_gasto_total_ref gtr
        ON gtr.Grd_Referencia = cf.Grd_Referencia AND gtr.Pv_Cve_Proveedor = cf.Pv_Cve_Proveedor
)
SELECT * FROM cxp_general
UNION ALL
SELECT * FROM cxp_combustible
