-- ============================================================================
-- Layout de gastos - v0.5 (version SQL pura, sin post-proceso en Python/pandas)
-- ============================================================================
-- Punto de partida: ContabilidadRepository.cs / QueryAuditoria2.0.sql (query de otro
-- programador que intento este mismo reporte antes) -- se conserva su estructura y
-- estilo general, pero se simplifico el lado de poliza y se le agregaron los casos
-- especiales que encontramos al construir v0.1-v0.4.2 en Python (ver docs/09 a /16).
--
-- Por que es MAS SIMPLE que v0.4.2 (Python): a proposito. v0.4.2 usa
-- Gasto_Registro_Control + ROW_NUMBER por valor + reparto proporcional + una
-- salvaguarda de re-enrutado para atribuir Cargo/Abono a nivel de DOCUMENTO individual
-- (Grd_ID) con 99.96% de exactitud. Eso no es "SQL simple" -- es dificil de mantener
-- para un programador que no vivio todo el proceso de descubrimiento. v0.5 vuelve a
-- atribuir a nivel de FOLIO COMPLETO (como v0.2): el Cargo/Abono de la poliza se pega
-- al ULTIMO Grd_ID del folio (evita duplicar al sumar), sin intentar repartir entre
-- documentos de un folio multi-documento. Esto es EXACTAMENTE lo que ya hacia el query
-- de referencia (ahi ni siquiera se intentaba evitar la duplicacion -- el join cruzaba
-- CADA documento contra TODAS las lineas de poliza del folio).
--
-- Efecto esperado (no cierra el gap al 100%, a proposito -- pedido explicito del
-- usuario): para folios de un solo documento (la gran mayoria), el resultado es
-- identico a v0.4.2. Para folios multi-documento, el Cargo/Abono queda concentrado en
-- el ultimo documento en vez de repartido -- mismo comportamiento que v0.2/v0.3 antes
-- del hallazgo de Gasto_Registro_Control.
--
-- Casos especiales HARDCODEADOS aqui (aprendidos en v0.1 a v0.4.2):
--   1. CONSUMO_INTERNO / GASTO_REGISTRO_NOMINA (Gr_Tabla): Cargo/Abono/Cuenta en NULL a
--      proposito -- no se intenta ningun join de poliza (docs/12).
--   2. GASTO_RECLASIFICACION (Gr_Tabla): no tiene poliza real (Poliza_Control da 0 filas
--      para estos folios). Cargo/Abono salen del SIGNO de Grd_Precio_Descontado_Importe
--      (positivo=Cargo, negativo=Abono) y la cuenta de Tipo_Gasto.Tg_Cuenta_Contable
--      (docs/12).
--   3. Abono (Pd_Tipo=2) solo cuenta si la cuenta es de raiz 'F' (Gastos) en el arbol de
--      Grupo_Cuenta_Contable, O si no tiene grupo asignado y el codigo empieza con '6',
--      O si su descripcion es "Gastos a cuenta de costo estandar" (familia de costeo
--      estandar 2120.010.xxx, sufijo .002 -- el sufijo .001 "Provision de costo
--      estandar" es la contrapartida/pasivo, correctamente excluida) (docs/12, /16).
--   4. Reversiones contables reales: si el Importe del folio completo (sumado por
--      documento) es <= -$1 (una reversion/saldo), se usa SOLO el Abono -- el Cargo de
--      esos folios se pone en 0 porque cae en una cuenta de Provision/Pasivo por pagar,
--      no es un gasto real (docs/15).
--   5. El join a Comprobante_Digital usa OUTER APPLY TOP 1 (no un LEFT JOIN...LIKE
--      simple) porque un documento puede matchear 2+ UUID con el patron LIKE usado en
--      el query de referencia, duplicando la fila (docs/12).
--   6. NO se usa Poliza_Detalle_Comprobante (aunque el query de referencia si la usa):
--      se investigo y esa tabla liga UUID de COMPLEMENTO DE PAGO a lineas de poliza de
--      PAGO, no el UUID del CFDI original a la poliza de REGISTRO del gasto -- no sirve
--      para esta atribucion (se probo con folio 01-0034739: la misma linea de poliza
--      aparecia ligada a los 9 UUID de sus 9 documentos por igual).
--
-- Parametros: @Empresa, @FechaInicio, @FechaFin (formato DATE, ej. '2026-01-01').
-- Uso: reemplazar las DECLARE de abajo, o pegar el bloque completo tras un
-- CREATE OR ALTER FUNCTION / VIEW segun lo necesite el programador que lo reciba.
-- ============================================================================

DECLARE @Empresa NVARCHAR(10) = '0001';
DECLARE @FechaInicio DATE = '2026-01-01';
DECLARE @FechaFin DATE = '2026-01-31';          -- inclusive (se usa < @FechaFin+1 abajo)

WITH grupo_arbol AS (
    -- arbol de Grupo_Cuenta_Contable, para resolver la raiz (F=Gastos) de cada cuenta
    SELECT Gcc_Cve_Grupo_Cuenta_Contable, Gcc_Padre, Gcc_Cve_Grupo_Cuenta_Contable AS Raiz
    FROM Grupo_Cuenta_Contable
    WHERE Gcc_Padre = '0' OR Gcc_Padre = '' OR Gcc_Padre IS NULL
    UNION ALL
    SELECT g.Gcc_Cve_Grupo_Cuenta_Contable, g.Gcc_Padre, t.Raiz
    FROM Grupo_Cuenta_Contable g
    JOIN grupo_arbol t ON g.Gcc_Padre = t.Gcc_Cve_Grupo_Cuenta_Contable
),

base AS (
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
    FROM Gasto_Registro gr
    INNER JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = gr.Gr_Folio
    INNER JOIN Sucursal sc ON sc.Sc_Cve_Sucursal = gr.Sc_Cve_Sucursal
    LEFT JOIN Proveedor pv ON pv.Pv_Cve_Proveedor = grd.Pv_Cve_Proveedor
    LEFT JOIN Tipo_Gasto tg ON tg.Tg_Cve_Tipo_Gasto = grd.Tg_Cve_Tipo_Gasto
    OUTER APPLY (
        -- caso especial 5: TOP 1 en vez de LEFT JOIN...LIKE (evita duplicar la fila)
        SELECT TOP 1 Cd_Documento, Cd_Timbre_UUID
        FROM Comprobante_Digital
        WHERE Cd_Tabla = 'GASTO_REGISTRO'
          AND Cd_Documento LIKE gr.Gr_Folio + grd.Grd_ID + '%'
        ORDER BY Cd_Documento
    ) cd
    WHERE sc.Em_Cve_Empresa = @Empresa
      AND gr.Es_Cve_Estado <> 'CA'
      AND gr.Gr_Fecha >= @FechaInicio
      AND gr.Gr_Fecha < DATEADD(DAY, 1, @FechaFin)
),

poliza_agg AS (
    -- Cargo/Abono agregado a nivel FOLIO COMPLETO (no por documento) + cuenta contable.
    -- Casos especiales 1 y 3 aplicados aqui.
    SELECT
        gr.Gr_Folio                                                          AS Folio,
        pd.Cc_Cve_Cuenta_Contable                                            AS CuentaContable,
        cc.Cc_Descripcion                                                    AS DescripcionCuenta,
        SUM(CASE WHEN pd.Pd_Tipo = 1 THEN pd.Pd_Importe ELSE 0 END)         AS Cargo,
        SUM(CASE WHEN pd.Pd_Tipo = 2 THEN pd.Pd_Importe ELSE 0 END)         AS Abono
    FROM Gasto_Registro gr
    INNER JOIN Poliza_Control pc
        ON pc.Pc_Tabla = 'GASTO_REGISTRO' AND pc.Pc_Documento = gr.Gr_Folio AND pc.Es_Cve_Estado <> 'CA'
    INNER JOIN Poliza pl ON pl.Pl_Folio = pc.Pl_Folio AND pl.Es_Cve_Estado <> 'CA'
    INNER JOIN Poliza_Detalle pd ON pd.Pl_Folio = pc.Pl_Folio AND pd.Pd_Referencia = gr.Gr_Folio
    LEFT JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable
    LEFT JOIN grupo_arbol ga ON ga.Gcc_Cve_Grupo_Cuenta_Contable = cc.Cc_Grupo_Cuenta_Contable
    INNER JOIN Sucursal sc ON sc.Sc_Cve_Sucursal = gr.Sc_Cve_Sucursal
    WHERE sc.Em_Cve_Empresa = @Empresa
      AND gr.Es_Cve_Estado <> 'CA'
      AND gr.Gr_Fecha >= @FechaInicio
      AND gr.Gr_Fecha < DATEADD(DAY, 1, @FechaFin)
      -- caso especial 1: estos dos origenes no tienen join de poliza en absoluto
      AND gr.Gr_Tabla NOT IN ('CONSUMO_INTERNO', 'GASTO_REGISTRO_NOMINA')
      -- caso especial 2: GASTO_RECLASIFICACION no tiene poliza real, se calcula aparte
      AND gr.Gr_Tabla <> 'GASTO_RECLASIFICACION'
      -- caso especial 3: regla de inclusion de Abono
      AND (
            pd.Pd_Tipo = 1
         OR (pd.Pd_Tipo = 2 AND ga.Raiz = 'F')
         OR (pd.Pd_Tipo = 2 AND ga.Raiz IS NULL AND LEFT(pd.Cc_Cve_Cuenta_Contable, 1) = '6')
         OR (pd.Pd_Tipo = 2 AND ga.Raiz IS NULL
             AND LOWER(cc.Cc_Descripcion) LIKE '%gastos a cuenta de costo estandar%')
          )
    GROUP BY gr.Gr_Folio, pd.Cc_Cve_Cuenta_Contable, cc.Cc_Descripcion
),

importe_folio AS (
    -- Importe total del folio (sumado por documento) -- para detectar reversiones (caso 4)
    SELECT Folio, SUM(Importe) AS ImporteFolio
    FROM base
    WHERE Origen NOT IN ('CONSUMO_INTERNO', 'GASTO_REGISTRO_NOMINA', 'GASTO_RECLASIFICACION')
    GROUP BY Folio
),

ultimo_documento AS (
    -- el Cargo/Abono del folio se pega SOLO a este documento, para no duplicar al sumar
    SELECT Folio, MAX(Grd_ID) AS Grd_ID
    FROM base
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
        ELSE p.CuentaContable
    END AS CuentaContable,
    CASE
        WHEN b.Origen IN ('CONSUMO_INTERNO', 'GASTO_REGISTRO_NOMINA', 'GASTO_RECLASIFICACION') THEN NULL
        ELSE p.DescripcionCuenta
    END AS DescripcionCuenta,
    CASE
        WHEN b.Origen IN ('CONSUMO_INTERNO', 'GASTO_REGISTRO_NOMINA') THEN NULL
        WHEN b.Origen = 'GASTO_RECLASIFICACION' THEN CASE WHEN b.Importe > 0 THEN b.Importe ELSE 0 END
        WHEN imf.ImporteFolio <= -1 THEN 0                            -- caso especial 4
        ELSE p.Cargo
    END AS Cargo,
    CASE
        WHEN b.Origen IN ('CONSUMO_INTERNO', 'GASTO_REGISTRO_NOMINA') THEN NULL
        WHEN b.Origen = 'GASTO_RECLASIFICACION' THEN CASE WHEN b.Importe < 0 THEN -b.Importe ELSE 0 END
        ELSE p.Abono
    END AS Abono
FROM base b
LEFT JOIN ultimo_documento ud ON ud.Folio = b.Folio AND ud.Grd_ID = b.Grd_ID
LEFT JOIN poliza_agg p ON p.Folio = b.Folio AND ud.Grd_ID IS NOT NULL   -- solo en el ultimo documento
LEFT JOIN importe_folio imf ON imf.Folio = b.Folio
ORDER BY b.Folio, b.Grd_ID, CuentaContable;
