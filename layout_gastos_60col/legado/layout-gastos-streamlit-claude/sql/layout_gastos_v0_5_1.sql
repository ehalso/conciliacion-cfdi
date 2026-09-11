-- ============================================================================
-- Layout de gastos - v0.5.1 (SQL puro + atribucion por documento via Gasto_Registro_Control)
-- ============================================================================
-- Extiende v0.5 (ver layout_gastos_v0_5.sql para el detalle de los casos especiales
-- 1-6, que aqui se mantienen identicos): agrega el mismo mecanismo de v0.4.2 para
-- repartir el Cargo/Abono de un folio multi-documento ENTRE sus documentos, en vez de
-- concentrarlo todo en el ultimo. Pedido explicito del usuario: "si hacemos la v5.1
-- para usar el detalle de grc_id? estamos perdiendo granularidad y no creo que
-- complique mucho el sql".
--
-- Mecanismo (identico al validado en Python, docs/13-14): dentro de un mismo
-- (folio, centro_costo), Gasto_Registro_Control (agrupado por documento) y
-- Poliza_Detalle (via Pd_Centro_Costo) se emparejan ordenando AMBOS lados por VALOR
-- (no por orden de creacion -- verificado que el orden de insercion NO siempre
-- coincide, docs/14) y usando ROW_NUMBER() para parear posicion a posicion:
--   - Conteo de documentos IGUAL en ambos lados -> emparejamiento EXACTO por valor.
--   - Conteo DISTINTO pero datos en ambos lados -> reparto PROPORCIONAL por
--     Grc_Importe (la poliza combino 2+ documentos en 1 linea, o viceversa).
--   - Sin centro de costo, o centro que no aparece en Gasto_Registro_Control -> cae al
--     respaldo de v0.5 (agregado por folio, pegado al ultimo documento).
--
-- Lo que NO se incluyo (para no acercarse a la complejidad de v0.4.2): la salvaguarda
-- de "verificar cuadre por documento y re-enrutar si falla". Se omite a proposito --
-- una vez que se empareja por VALOR (no por orden de insercion), los casos que
-- necesitaban esa salvaguarda en Python (ej. folio de depreciacion 01-0035004, 642
-- lineas / 77 centros) YA CUADRABAN EXACTO sin ella (ver docs/14, seccion final) -- la
-- salvaguarda solo importaba cuando se emparejaba por orden de insercion, no por valor.
--
-- RENDIMIENTO (docs/18): la primera version de este archivo usaba CTEs para TODO,
-- incluyendo "poliza_linea" y "grc" -- referenciadas 5 y 3 veces respectivamente mas
-- abajo. SQL Server NO materializa las CTEs (son macros que se re-expanden en cada
-- referencia), asi que el JOIN pesado de poliza (Gasto_Registro + Poliza_Control +
-- Poliza + Poliza_Detalle + arbol recursivo de cuentas) se recalculaba 5 VECES por
-- consulta -- 14 minutos para un anio completo. Fix: materializar grupo_arbol, base,
-- poliza_linea y grc en tablas #temporales (se calculan UNA vez) con indices, y dejar
-- el resto (conteo, los ROW_NUMBER, el reparto proporcional) como CTEs normales, ya que
-- corren sobre las #temporales (baratas de re-leer) en vez de sobre los JOINs
-- originales.
--
-- Parametros: @Empresa, @FechaInicio, @FechaFin (formato DATE, ej. '2026-01-01').
-- ============================================================================

SET NOCOUNT ON;

DECLARE @Empresa NVARCHAR(10) = '0001';
DECLARE @FechaInicio DATE = '2026-01-01';
DECLARE @FechaFin DATE = '2026-01-31';          -- inclusive (se usa < @FechaFin+1 abajo)

IF OBJECT_ID('tempdb..#grupo_arbol') IS NOT NULL DROP TABLE #grupo_arbol;
IF OBJECT_ID('tempdb..#base') IS NOT NULL DROP TABLE #base;
IF OBJECT_ID('tempdb..#grc') IS NOT NULL DROP TABLE #grc;
IF OBJECT_ID('tempdb..#poliza_linea') IS NOT NULL DROP TABLE #poliza_linea;

-- arbol de Grupo_Cuenta_Contable, para resolver la raiz (F=Gastos) de cada cuenta
;WITH grupo_arbol_cte AS (
    SELECT Gcc_Cve_Grupo_Cuenta_Contable, Gcc_Padre, Gcc_Cve_Grupo_Cuenta_Contable AS Raiz
    FROM Grupo_Cuenta_Contable
    WHERE Gcc_Padre = '0' OR Gcc_Padre = '' OR Gcc_Padre IS NULL
    UNION ALL
    SELECT g.Gcc_Cve_Grupo_Cuenta_Contable, g.Gcc_Padre, t.Raiz
    FROM Grupo_Cuenta_Contable g
    JOIN grupo_arbol_cte t ON g.Gcc_Padre = t.Gcc_Cve_Grupo_Cuenta_Contable
)
SELECT Gcc_Cve_Grupo_Cuenta_Contable, Raiz
INTO #grupo_arbol
FROM grupo_arbol_cte;
CREATE UNIQUE CLUSTERED INDEX ix_grupo_arbol ON #grupo_arbol(Gcc_Cve_Grupo_Cuenta_Contable);

-- grano: 1 fila por documento (Gr_Folio + Grd_ID)
SELECT
    gr.Gr_Folio                                              AS Folio,
    grd.Grd_ID                                                AS Grd_ID,
    gr.Gr_Fecha                                                AS Fecha,
    grd.Grd_Fecha                                              AS FechaDocumento,
    grd.Grd_Referencia                                        AS Referencia,
    grd.Pv_Cve_Proveedor                                      AS ClaveProveedor,
    pv.Pv_Descripcion                                         AS RazonSocial,
    grd.Grd_Comentario                                        AS Comentario,
    grd.Mn_Cve_Moneda                                         AS Moneda,
    grd.Grd_Tipo_Cambio                                       AS TipoCambio,
    grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio   AS Importe,
    grd.Grd_Impuesto_Importe * grd.Grd_Tipo_Cambio            AS Impuestos,
    grd.Grd_Precio_Neto_Importe * grd.Grd_Tipo_Cambio         AS Total,
    gr.Gr_Tabla                                               AS Origen,
    tg.Tg_Cuenta_Contable                                     AS TipoGastoCuentaContable,
    CASE WHEN cd.Cd_Documento IS NOT NULL THEN 1 ELSE 0 END   AS TieneComprobante,
    cd.Cd_Timbre_UUID                                         AS UUID
INTO #base
FROM Gasto_Registro gr
INNER JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = gr.Gr_Folio
INNER JOIN Sucursal sc ON sc.Sc_Cve_Sucursal = gr.Sc_Cve_Sucursal
LEFT JOIN Proveedor pv ON pv.Pv_Cve_Proveedor = grd.Pv_Cve_Proveedor
LEFT JOIN Tipo_Gasto tg ON tg.Tg_Cve_Tipo_Gasto = grd.Tg_Cve_Tipo_Gasto
OUTER APPLY (
    SELECT TOP 1 Cd_Documento, Cd_Timbre_UUID
    FROM Comprobante_Digital
    WHERE Cd_Tabla = 'GASTO_REGISTRO'
      AND Cd_Documento LIKE gr.Gr_Folio + grd.Grd_ID + '%'
    ORDER BY Cd_Documento
) cd
WHERE sc.Em_Cve_Empresa = @Empresa
  AND gr.Es_Cve_Estado <> 'CA'
  AND gr.Gr_Fecha >= @FechaInicio
  AND gr.Gr_Fecha < DATEADD(DAY, 1, @FechaFin);
CREATE UNIQUE CLUSTERED INDEX ix_base ON #base(Folio, Grd_ID);

-- Gasto_Registro_Control: Grc_ID NO identifica un documento, identifica una sub-linea
-- DENTRO del mismo documento y mismo centro de costo (ej. varios activos fijos de un
-- documento de depreciacion) -- se colapsa a 1 fila por (Folio, CentroCosto, Grd_ID)
-- sumando Grc_Importe antes de usarlo (docs/14).
SELECT gr.Gr_Folio AS Folio, grc.Grd_ID, grc.Cc_Cve_Centro_Costo AS CentroCosto,
       SUM(grc.Grc_Importe) AS GrcImporte
INTO #grc
FROM Gasto_Registro gr
INNER JOIN Gasto_Registro_Control grc ON grc.Gr_Folio = gr.Gr_Folio
INNER JOIN Sucursal sc ON sc.Sc_Cve_Sucursal = gr.Sc_Cve_Sucursal
WHERE sc.Em_Cve_Empresa = @Empresa
  AND gr.Es_Cve_Estado <> 'CA'
  AND gr.Gr_Fecha >= @FechaInicio
  AND gr.Gr_Fecha < DATEADD(DAY, 1, @FechaFin)
  AND grc.Cc_Cve_Centro_Costo IS NOT NULL AND grc.Cc_Cve_Centro_Costo <> ''
GROUP BY gr.Gr_Folio, grc.Grd_ID, grc.Cc_Cve_Centro_Costo;
CREATE CLUSTERED INDEX ix_grc ON #grc(Folio, CentroCosto);

-- lineas de poliza SIN colapsar por folio (para poder repartirlas por centro de costo).
-- Mismos casos especiales 1, 2 y 3 de v0.5.
SELECT
    gr.Gr_Folio                AS Folio,
    pd.Pd_ID                   AS Pd_ID,
    pd.Pd_Centro_Costo         AS CentroCosto,
    pd.Cc_Cve_Cuenta_Contable  AS CuentaContable,
    cc.Cc_Descripcion          AS DescripcionCuenta,
    CASE WHEN pd.Pd_Tipo = 1 THEN pd.Pd_Importe ELSE 0 END AS Cargo,
    CASE WHEN pd.Pd_Tipo = 2 THEN pd.Pd_Importe ELSE 0 END AS Abono
INTO #poliza_linea
FROM Gasto_Registro gr
INNER JOIN Poliza_Control pc
    ON pc.Pc_Tabla = 'GASTO_REGISTRO' AND pc.Pc_Documento = gr.Gr_Folio AND pc.Es_Cve_Estado <> 'CA'
INNER JOIN Poliza pl ON pl.Pl_Folio = pc.Pl_Folio AND pl.Es_Cve_Estado <> 'CA'
INNER JOIN Poliza_Detalle pd ON pd.Pl_Folio = pc.Pl_Folio AND pd.Pd_Referencia = gr.Gr_Folio
LEFT JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable
LEFT JOIN #grupo_arbol ga ON ga.Gcc_Cve_Grupo_Cuenta_Contable = cc.Cc_Grupo_Cuenta_Contable
INNER JOIN Sucursal sc ON sc.Sc_Cve_Sucursal = gr.Sc_Cve_Sucursal
WHERE sc.Em_Cve_Empresa = @Empresa
  AND gr.Es_Cve_Estado <> 'CA'
  AND gr.Gr_Fecha >= @FechaInicio
  AND gr.Gr_Fecha < DATEADD(DAY, 1, @FechaFin)
  AND gr.Gr_Tabla NOT IN ('CONSUMO_INTERNO', 'GASTO_REGISTRO_NOMINA', 'GASTO_RECLASIFICACION')
  AND (
        pd.Pd_Tipo = 1
     OR (pd.Pd_Tipo = 2 AND ga.Raiz = 'F')
     OR (pd.Pd_Tipo = 2 AND ga.Raiz IS NULL AND LEFT(pd.Cc_Cve_Cuenta_Contable, 1) = '6')
     OR (pd.Pd_Tipo = 2 AND ga.Raiz IS NULL
         AND LOWER(cc.Cc_Descripcion) LIKE '%gastos a cuenta de costo estandar%')
      );
CREATE CLUSTERED INDEX ix_poliza_linea ON #poliza_linea(Folio, CentroCosto);

WITH
-- conteo de documentos (grc) vs lineas de poliza por (Folio, CentroCosto)
conteo AS (
    SELECT
        COALESCE(pc.Folio, gc.Folio) AS Folio,
        COALESCE(pc.CentroCosto, gc.CentroCosto) AS CentroCosto,
        pc.NPoliza, gc.NGrc
    FROM (
        SELECT Folio, CentroCosto, COUNT(*) AS NPoliza
        FROM #poliza_linea
        WHERE CentroCosto IS NOT NULL AND CentroCosto <> ''
        GROUP BY Folio, CentroCosto
    ) pc
    FULL OUTER JOIN (
        SELECT Folio, CentroCosto, COUNT(*) AS NGrc FROM #grc GROUP BY Folio, CentroCosto
    ) gc ON gc.Folio = pc.Folio AND gc.CentroCosto = pc.CentroCosto
),

-- emparejamiento POR VALOR (no por orden de creacion, ver docs/14) dentro de cada grupo
poliza_rank AS (
    SELECT pl.*, ROW_NUMBER() OVER (PARTITION BY pl.Folio, pl.CentroCosto ORDER BY (pl.Cargo - pl.Abono), pl.Pd_ID) AS Rn
    FROM #poliza_linea pl
    WHERE pl.CentroCosto IS NOT NULL AND pl.CentroCosto <> ''
),
grc_rank AS (
    SELECT g.*, ROW_NUMBER() OVER (PARTITION BY g.Folio, g.CentroCosto ORDER BY g.GrcImporte, g.Grd_ID) AS Rn
    FROM #grc g
),

-- metodo 1: EXACTO -- mismo conteo de documentos en ambos lados
exacta AS (
    SELECT p.Folio, r.Grd_ID, p.CuentaContable, p.DescripcionCuenta, p.Cargo, p.Abono
    FROM poliza_rank p
    JOIN conteo c ON c.Folio = p.Folio AND c.CentroCosto = p.CentroCosto AND c.NPoliza = c.NGrc
    JOIN grc_rank r ON r.Folio = p.Folio AND r.CentroCosto = p.CentroCosto AND r.Rn = p.Rn
),

-- metodo 2: PROPORCIONAL -- conteo distinto pero datos en ambos lados (ej. la poliza
-- combino 2+ documentos identicos en 1 sola linea) -- se reparte por Grc_Importe
pesos AS (
    SELECT g.Folio, g.CentroCosto, g.Grd_ID,
           g.GrcImporte * 1.0 / NULLIF(SUM(g.GrcImporte) OVER (PARTITION BY g.Folio, g.CentroCosto), 0) AS Peso
    FROM #grc g
),
proporcional AS (
    SELECT p.Folio, w.Grd_ID, p.CuentaContable, p.DescripcionCuenta,
           p.Cargo * w.Peso AS Cargo, p.Abono * w.Peso AS Abono
    FROM #poliza_linea p
    JOIN conteo c ON c.Folio = p.Folio AND c.CentroCosto = p.CentroCosto
        AND c.NPoliza IS NOT NULL AND c.NGrc IS NOT NULL AND c.NPoliza <> c.NGrc
    JOIN pesos w ON w.Folio = p.Folio AND w.CentroCosto = p.CentroCosto
),

-- metodo 3: RESPALDO (igual que v0.5) -- sin centro de costo, o centro que no aparece
-- del todo en Gasto_Registro_Control -- se agrega por folio y se pega al ultimo documento
poliza_fallback_items AS (
    SELECT Folio, CuentaContable, DescripcionCuenta, Cargo, Abono
    FROM #poliza_linea
    WHERE CentroCosto IS NULL OR CentroCosto = ''
    UNION ALL
    SELECT pl.Folio, pl.CuentaContable, pl.DescripcionCuenta, pl.Cargo, pl.Abono
    FROM #poliza_linea pl
    JOIN conteo c ON c.Folio = pl.Folio AND c.CentroCosto = pl.CentroCosto
    WHERE pl.CentroCosto IS NOT NULL AND pl.CentroCosto <> '' AND c.NGrc IS NULL
),
fallback_agg AS (
    SELECT Folio, CuentaContable, DescripcionCuenta, SUM(Cargo) AS Cargo, SUM(Abono) AS Abono
    FROM poliza_fallback_items
    GROUP BY Folio, CuentaContable, DescripcionCuenta
),
ultimo_documento AS (
    SELECT Folio, MAX(Grd_ID) AS Grd_ID FROM #base GROUP BY Folio
),
fallback AS (
    SELECT fa.Folio, ud.Grd_ID, fa.CuentaContable, fa.DescripcionCuenta, fa.Cargo, fa.Abono
    FROM fallback_agg fa
    JOIN ultimo_documento ud ON ud.Folio = fa.Folio
),

detalle AS (
    SELECT Folio, Grd_ID, CuentaContable, DescripcionCuenta, Cargo, Abono FROM exacta
    UNION ALL
    SELECT Folio, Grd_ID, CuentaContable, DescripcionCuenta, Cargo, Abono FROM proporcional
    UNION ALL
    SELECT Folio, Grd_ID, CuentaContable, DescripcionCuenta, Cargo, Abono FROM fallback
),

-- puede haber 2+ filas de detalle por (Folio,Grd_ID,Cuenta) si el emparejamiento por
-- valor coincidio en mas de un grupo de centro de costo con la misma cuenta -- se suman
detalle_agg AS (
    SELECT Folio, Grd_ID, CuentaContable, DescripcionCuenta, SUM(Cargo) AS Cargo, SUM(Abono) AS Abono
    FROM detalle
    GROUP BY Folio, Grd_ID, CuentaContable, DescripcionCuenta
),

importe_folio AS (
    -- Importe total del folio (sumado por documento) -- para detectar reversiones (caso 4)
    SELECT Folio, SUM(Importe) AS ImporteFolio
    FROM #base
    WHERE Origen NOT IN ('CONSUMO_INTERNO', 'GASTO_REGISTRO_NOMINA', 'GASTO_RECLASIFICACION')
    GROUP BY Folio
)

SELECT
    b.Folio,
    b.Grd_ID,
    b.Fecha,
    b.FechaDocumento,
    b.Referencia,
    b.ClaveProveedor,
    b.RazonSocial,
    b.Comentario,
    b.Moneda,
    b.TipoCambio,
    b.Importe,
    b.Impuestos,
    b.Total,
    b.Origen,
    b.TieneComprobante,
    b.UUID,
    CASE
        WHEN b.Origen IN ('CONSUMO_INTERNO', 'GASTO_REGISTRO_NOMINA') THEN NULL
        WHEN b.Origen = 'GASTO_RECLASIFICACION' THEN b.TipoGastoCuentaContable
        ELSE d.CuentaContable
    END AS CuentaContable,
    CASE
        WHEN b.Origen IN ('CONSUMO_INTERNO', 'GASTO_REGISTRO_NOMINA', 'GASTO_RECLASIFICACION') THEN NULL
        ELSE d.DescripcionCuenta
    END AS DescripcionCuenta,
    CASE
        WHEN b.Origen IN ('CONSUMO_INTERNO', 'GASTO_REGISTRO_NOMINA') THEN NULL
        WHEN b.Origen = 'GASTO_RECLASIFICACION' THEN CASE WHEN b.Importe > 0 THEN b.Importe ELSE 0 END
        WHEN imf.ImporteFolio <= -1 THEN 0                            -- caso especial 4
        ELSE d.Cargo
    END AS Cargo,
    CASE
        WHEN b.Origen IN ('CONSUMO_INTERNO', 'GASTO_REGISTRO_NOMINA') THEN NULL
        WHEN b.Origen = 'GASTO_RECLASIFICACION' THEN CASE WHEN b.Importe < 0 THEN -b.Importe ELSE 0 END
        ELSE d.Abono
    END AS Abono
FROM #base b
LEFT JOIN detalle_agg d ON d.Folio = b.Folio AND d.Grd_ID = b.Grd_ID
LEFT JOIN importe_folio imf ON imf.Folio = b.Folio
ORDER BY b.Folio, b.Grd_ID, CuentaContable;

DROP TABLE #grupo_arbol;
DROP TABLE #base;
DROP TABLE #grc;
DROP TABLE #poliza_linea;
