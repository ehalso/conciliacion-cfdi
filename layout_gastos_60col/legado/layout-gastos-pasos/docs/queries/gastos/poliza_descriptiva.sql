-- Columnas 53-56 del layout: Fecha de poliza, Tipo de poliza, Numero de
-- poliza, Concepto de poliza. Fuente: Poliza, via Poliza_Control (mismo
-- link ya validado en etapa4/etapa6: Pc_Tabla='GASTO_REGISTRO',
-- Pc_Documento=Gr_Folio, ambos con Es_Cve_Estado <> 'CA').
--
-- Un folio podria tener mas de una poliza asociada (igual riesgo que
-- Cargo/Abono) -- se detecta con COUNT(DISTINCT Pl_Folio) y se marca
-- 'VARIOS' si aplica, mismo patron que UUID/XML.

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
poliza_match AS (
    SELECT
        f.FOLIO,
        pl.Pl_Folio,
        pl.Pl_Fecha,
        pl.Pl_Tipo,
        pl.Pl_Numero,
        pl.Pl_Comentario
    FROM folios f
    JOIN Poliza_Control plc
        ON plc.Pc_Tabla = 'GASTO_REGISTRO'
       AND plc.Pc_Documento = f.Gr_Folio
       AND plc.Es_Cve_Estado <> 'CA'
    JOIN Poliza pl
        ON pl.Pl_Folio = plc.Pl_Folio
       AND pl.Es_Cve_Estado <> 'CA'
),
poliza_agg AS (
    SELECT
        FOLIO,
        COUNT(DISTINCT Pl_Folio) AS N_POLIZAS,
        MIN(Pl_Fecha)      AS FECHA_UNICA,
        MIN(Pl_Tipo)       AS TIPO_UNICO,
        MIN(Pl_Numero)     AS NUMERO_UNICO,
        MIN(Pl_Comentario) AS COMENTARIO_UNICO
    FROM poliza_match
    GROUP BY FOLIO
)
SELECT
    f.FOLIO,
    CASE WHEN pa.N_POLIZAS >= 2 THEN 'VARIOS' ELSE CONVERT(varchar(19), pa.FECHA_UNICA, 120) END AS FECHA_POLIZA,
    CASE WHEN pa.N_POLIZAS >= 2 THEN NULL ELSE pa.TIPO_UNICO END      AS TIPO_POLIZA,
    CASE WHEN pa.N_POLIZAS >= 2 THEN 'VARIOS' ELSE pa.NUMERO_UNICO END AS NUMERO_POLIZA,
    CASE WHEN pa.N_POLIZAS >= 2 THEN 'VARIOS' ELSE pa.COMENTARIO_UNICO END AS CONCEPTO_POLIZA
FROM folios f
LEFT JOIN poliza_agg pa ON pa.FOLIO = f.FOLIO
