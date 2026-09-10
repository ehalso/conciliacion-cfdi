-- v2.4 -- Impuestos por CECO + Cargo/Abono de poliza, ambos usando el
-- centro de costo de Gasto_Registro_Control (NO Poliza_Detalle.Pd_Centro_Costo).
-- Confirmado con datos reales (folio 01-0035004, 2026-08-07): el set de
-- centros y sus montos coinciden EXACTO entre Gasto_Registro_Control y
-- Poliza_Detalle.Pd_Centro_Costo -- la unica diferencia son las lineas de
-- Abono en cuentas de balance (Depreciacion Acumulada, Amortizaciones...)
-- que no llevan centro de costo, y que de todos modos ya excluye el
-- filtro '6xxx' del caso general. Union segura.
--
-- Cargo/Abono de poliza es a nivel FOLIO completo (Pd_Referencia solo
-- llega a Gr_Folio, no a Grd_ID) -- se prorratea por centro usando el
-- PESO del Grc_Importe total del folio (no el factor por documento, que
-- es para impuestos, que si estan a nivel Grd_ID).

WITH centro_factor_doc AS (
    SELECT
        grc.Gr_Folio, grc.Grd_ID, grc.Cc_Cve_Centro_Costo,
        CAST(SUM(grc.Grc_Factor) AS FLOAT) / NULLIF(CAST(tot.factor_total AS FLOAT), 0) AS FACTOR_NORMALIZADO
    FROM Gasto_Registro_Control grc
    JOIN (
        SELECT Gr_Folio, Grd_ID, SUM(Grc_Factor) AS factor_total
        FROM Gasto_Registro_Control GROUP BY Gr_Folio, Grd_ID
    ) tot ON tot.Gr_Folio = grc.Gr_Folio AND tot.Grd_ID = grc.Grd_ID
    GROUP BY grc.Gr_Folio, grc.Grd_ID, grc.Cc_Cve_Centro_Costo, tot.factor_total
),
centro_peso_folio AS (
    SELECT
        grc.Gr_Folio, grc.Cc_Cve_Centro_Costo,
        CAST(SUM(grc.Grc_Importe) AS FLOAT) / NULLIF(CAST(tot.importe_total AS FLOAT), 0) AS PESO_FOLIO
    FROM Gasto_Registro_Control grc
    JOIN (
        SELECT Gr_Folio, SUM(Grc_Importe) AS importe_total
        FROM Gasto_Registro_Control GROUP BY Gr_Folio
    ) tot ON tot.Gr_Folio = grc.Gr_Folio
    GROUP BY grc.Gr_Folio, grc.Cc_Cve_Centro_Costo, tot.importe_total
),
doc_impuestos AS (
    SELECT
        grd.Gr_Folio, grd.Grd_ID,
        SUM(gri.Gri_Importe) AS TOTAL_IMPUESTO_DOC
    FROM Gasto_Registro_Documento grd
    LEFT JOIN Gasto_Registro_Impuesto gri ON gri.Gr_Folio = grd.Gr_Folio AND gri.Grd_ID = grd.Grd_ID
    GROUP BY grd.Gr_Folio, grd.Grd_ID
),
poliza_folio AS (
    SELECT
        gr.Gr_Folio,
        SUM(CASE WHEN pd.Pd_Tipo = 1 THEN pd.Pd_Importe ELSE 0 END) AS CARGO,
        SUM(CASE WHEN pd.Pd_Tipo = 2 AND LEFT(pd.Cc_Cve_Cuenta_Contable, 1) = '6'
                 THEN pd.Pd_Importe ELSE 0 END) AS ABONO
    FROM Gasto_Registro gr
    JOIN Poliza_Control plc
        ON plc.Pc_Tabla = 'GASTO_REGISTRO' AND plc.Pc_Documento = gr.Gr_Folio AND plc.Es_Cve_Estado <> 'CA'
    JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio AND pl.Es_Cve_Estado <> 'CA'
    JOIN Poliza_Detalle pd ON pd.Pl_Folio = plc.Pl_Folio AND pd.Pd_Referencia = gr.Gr_Folio
    GROUP BY gr.Gr_Folio
)
SELECT
    gr.Gr_Folio AS FOLIO,
    cfd.Cc_Cve_Centro_Costo AS CENTRO_COSTO,
    SUM(di.TOTAL_IMPUESTO_DOC * cfd.FACTOR_NORMALIZADO) AS IMPUESTO_CECO,
    MAX(cpf.PESO_FOLIO) * MAX(pf.CARGO) AS CARGO_CECO,
    MAX(cpf.PESO_FOLIO) * MAX(pf.ABONO) AS ABONO_CECO
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN centro_factor_doc cfd ON cfd.Gr_Folio = gr.Gr_Folio
JOIN doc_impuestos di ON di.Gr_Folio = cfd.Gr_Folio AND di.Grd_ID = cfd.Grd_ID
LEFT JOIN centro_peso_folio cpf ON cpf.Gr_Folio = gr.Gr_Folio AND cpf.Cc_Cve_Centro_Costo = cfd.Cc_Cve_Centro_Costo
LEFT JOIN poliza_folio pf ON pf.Gr_Folio = gr.Gr_Folio
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
GROUP BY gr.Gr_Folio, cfd.Cc_Cve_Centro_Costo
