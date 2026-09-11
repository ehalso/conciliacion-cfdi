-- Etapa 6 -- Bloque de proveedor, cobro/pago y comprobante de pago (columnas 1-18
-- del layout de 60 columnas). Grano: 1 fila por FOLIO (Gasto_Registro), igual
-- convencion que v3.0 (CXP) y v5.0 (Impuestos).
--
-- Fix 2026-08-06 (v2): cxp_docs_combustible ya NO filtra por f.ORIGEN=
-- 'CONTROL_COMBUSTIBLE' -- esa etiqueta (Gr_Tabla) puede venir vacia en
-- folios "tardios" que en la practica SI son combustible (mismo proveedor,
-- misma referencia semanal J8XXXXX), y con el filtro original quedaban sin
-- pago encontrado por error de clasificacion, no por falta de dato
-- (confirmado: 25/25 folios con Gr_Tabla vacio y proveedor
-- CONTROL INTEGRAL DE COMBUSTIBLES SI tenian match via referencia
-- consolidada). Ahora se intenta el match por documento (cxp_docs_general)
-- Y por referencia consolidada (cxp_docs_combustible) para TODOS los
-- folios, sin importar Gr_Tabla -- el UNION ALL + de-dup por FOLIO en
-- pagos/pago_repr ya maneja el caso de que ambos caminos encuentren algo
-- (no deberia pasar en la practica, pero no se asume).
--
-- Notas de diseno (detalle completo en
-- docs/etapa6_bloque_1_18_proveedor_pago_cierre.md):
--
--  - PROVEEDOR (4-6) y MONEDA (3) salen directo de Gasto_Registro_Documento
--    (grd.Pv_Cve_Proveedor, grd.Mn_Cve_Moneda) -- NO requieren CXP, por eso
--    tambien estan pobladas para folios con Gr_Genera_Cxp='NO'. Moneda es
--    siempre uniforme dentro de un folio (verificado 1425/1425, enero 2026);
--    Proveedor casi siempre lo es (1406/1425 con 1 solo proveedor), pero un
--    folio puede tener documentos de mas de un proveedor -- se resuelve
--    tomando el proveedor del documento (Grd_ID) de mayor importe neto,
--    marcado con PROVEEDOR_MULTIPLE='SI' cuando aplica.
--  - Columnas de PAGO (7-10, 12-16) dependen de Cuenta_X_Pagar/Pago_CXP con
--    match Cxp_Documento=Grd_ID (caso general) O match por referencia
--    consolidada (caso combustible, detectado por dato real, no por
--    etiqueta Gr_Tabla -- ver fix arriba).
--  - Un folio puede tener varios pagos (Pago_CXP) por Cxp_Folio -- se agrega
--    con SUM() para Monto Cobrado (16, patron ya validado en
--    check_monto_cxp*.py de la etapa CXP) y se elige 1 pago representativo
--    para los campos descriptivos (Banco/Cuenta/Cheque/Fecha), priorizando
--    forma de pago con instrumento bancario real (Fp_Cve_Forma_Pago IN
--    0001/0002/0003, en vez de movimientos contables como AN/DA/NCP) y
--    mayor importe absoluto.
--  - CFDI Comprobante de pago (10) = Pago_Cxp_Comprobante.Pcc_Timbre_UUID,
--    confirmado como el "camino de gastos via pago" en la exploracion previa
--    consulta_xmls_gastos (wiki personal, ver .md de cierre). Deduplicado
--    por UUID distinto (nunca por conteo de filas); 'VARIOS' si 2+ reales,
--    mismo patron que v_uuid_por_folio.sql (etapa v2.1).
--  - Tipo de comprobante (17) y Numero de factura (18) reusan el match ya
--    validado en v2.1 (Comprobante_Digital, Cd_Documento LIKE folio+'%',
--    Cd_Tabla='GASTO_REGISTRO', Es_Cve_Estado='AC'), mismo dedup por UUID
--    distinto y mismo criterio 'VARIOS' si 2+.
--  - FACTURA_REF (11): gap, sin fuente identificada tras exploracion
--    razonable -- placeholder NULL. Ver .md de cierre para el detalle de lo
--    que se investigo (Pago_Cxp_Comprobante.Pcc_Numero_Factura: 0% poblado;
--    Comprobante_Digital.Cd_Tipo_Relacion_UUID: candidato semantico pero
--    <1% poblado y sin confirmacion de negocio).

WITH folios AS (
    SELECT
        gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,
        gr.Gr_Folio, gr.Sc_Cve_Sucursal, gr.Gr_Fecha, gr.Gr_Genera_Cxp,
        gr.Gr_Tabla AS ORIGEN
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = '0001'
      AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')
),
doc_rank AS (
    SELECT
        f.FOLIO, grd.Grd_ID, grd.Mn_Cve_Moneda, grd.Pv_Cve_Proveedor,
        ROW_NUMBER() OVER (PARTITION BY f.FOLIO ORDER BY grd.Grd_Precio_Neto_Importe DESC, grd.Grd_ID) AS rn
    FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = f.Gr_Folio
),
n_proveedores AS (
    SELECT f.FOLIO, COUNT(DISTINCT grd.Pv_Cve_Proveedor) AS n_proveedores
    FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = f.Gr_Folio
    GROUP BY f.FOLIO
),
proveedor_repr AS (
    SELECT d.FOLIO, d.Pv_Cve_Proveedor, d.Mn_Cve_Moneda,
           CASE WHEN np.n_proveedores > 1 THEN 'SI' ELSE 'NO' END AS PROVEEDOR_MULTIPLE
    FROM doc_rank d
    JOIN n_proveedores np ON np.FOLIO = d.FOLIO
    WHERE d.rn = 1
),
cxp_docs_general AS (
    -- Caso general: match por documento (Cxp_Documento=Grd_ID). Se intenta
    -- para TODOS los folios (ya no se excluye combustible aqui).
    SELECT DISTINCT f.FOLIO, cxp.Cxp_Folio
    FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = f.Gr_Folio
    JOIN Cuenta_X_Pagar cxp
        ON cxp.Cxp_Tabla = 'Gasto_Registro:' + f.Gr_Folio
       AND cxp.Cxp_Documento = grd.Grd_ID
),
cxp_docs_referencia AS (
    -- Caso referencia consolidada: match por (Grd_Referencia,
    -- Pv_Cve_Proveedor). Se intenta para TODOS los folios con
    -- Grd_Referencia real -- no restringido a un proveedor de combustible
    -- fijo, porque ZFB_Proveedor_Combustible confirma que hay varios
    -- proveedores de combustible reales por sucursal/tipo (0000000021,
    -- 0000000506, 0000000156, 0000003475). Sin restringir fecha sobre
    -- Cuenta_X_Pagar.
    --
    -- Fix 2026-08-06 (v3, CRITICO): excluir Grd_Referencia NULL/vacio.
    -- Confirmado con datos reales: folios con Grd_Referencia en blanco y
    -- Pv_Cve_Proveedor='0000000000' (PROVEEDORES VARIOS, placeholder
    -- generico) hacian match contra CENTENARES de Cxp_Folio no
    -- relacionados (misma condicion "referencia vacia + proveedor
    -- generico" compartida por anos de historial, 2017-2025) -- fan-out
    -- masivo. Se investigo si existia una tabla intermedia mas robusta
    -- (Control_Combustible, Comprobacion_Gasto) -- ninguna aplica:
    -- Control_Combustible no tiene filas para estos folios (es bitacora
    -- operativa, no facturacion) y Comprobacion_Gasto esta vacia (modulo
    -- no usado). Confirmado con datos reales que Cxp_Referencia duplica
    -- literalmente Cxp_Documento en estos casos (ambos 'J869202') -- el
    -- texto de la referencia es el unico ancla real que existe en el
    -- sistema para este mecanismo, exigir que no este vacio es la
    -- defensa correcta.
    SELECT DISTINCT f.FOLIO, cxp.Cxp_Folio
    FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = f.Gr_Folio
    JOIN Cuenta_X_Pagar cxp
        ON cxp.Cxp_Tabla = 'Cuenta_X_Pagar'
       AND cxp.Cxp_Referencia = grd.Grd_Referencia
       AND cxp.Pv_Cve_Proveedor = grd.Pv_Cve_Proveedor
    WHERE grd.Grd_Referencia IS NOT NULL AND LTRIM(RTRIM(grd.Grd_Referencia)) <> ''
),
cxp_docs AS (
    SELECT * FROM cxp_docs_general
    UNION
    SELECT * FROM cxp_docs_referencia
),
pagos AS (
    SELECT cd.FOLIO, cd.Cxp_Folio, pc.Pc_ID, pc.Fp_Cve_Forma_Pago,
           pc.Pc_Banco, pc.Pc_Cuenta_Bancaria, pc.Pc_Documento, pc.Pc_Tabla,
           ROW_NUMBER() OVER (
               PARTITION BY cd.FOLIO
               ORDER BY CASE WHEN pc.Fp_Cve_Forma_Pago IN ('0001','0002','0003') THEN 0 ELSE 1 END,
                        ABS(pc.Pc_Importe) DESC, pc.Pc_ID
           ) AS rn
    FROM cxp_docs cd
    JOIN Pago_CXP pc ON pc.Cxp_Folio = cd.Cxp_Folio
),
pago_repr AS (
    SELECT p.FOLIO, p.Fp_Cve_Forma_Pago, p.Pc_Banco, p.Pc_Cuenta_Bancaria,
           p.Pc_Documento, p.Pc_Tabla
    FROM pagos p WHERE p.rn = 1
),
cheque_repr AS (
    SELECT pr.FOLIO, ch.Ch_Fecha, ch.Ch_Folio
    FROM pago_repr pr
    LEFT JOIN Cheque ch ON ch.Ch_Folio = pr.Pc_Documento AND pr.Pc_Tabla = 'Cheque'
),
monto_cobrado AS (
    SELECT cd.FOLIO, SUM(pc.Pc_Importe) AS MONTO_COBRADO
    FROM cxp_docs cd
    JOIN Pago_CXP pc ON pc.Cxp_Folio = cd.Cxp_Folio
    GROUP BY cd.FOLIO
),
comprobante_pago AS (
    SELECT cd.FOLIO,
           COUNT(DISTINCT pcc.Pcc_Timbre_UUID) AS N_UUID_PAGO,
           MIN(pcc.Pcc_Timbre_UUID) AS UUID_PAGO_UNICO
    FROM cxp_docs cd
    JOIN Pago_Cxp_Comprobante pcc ON pcc.Cxp_Folio = cd.Cxp_Folio
    GROUP BY cd.FOLIO
),
xml AS (
    SELECT f.FOLIO, cd.Cd_Timbre_UUID, cd.Cd_Tipo_CFDI, cd.Cd_Serie_Folio
    FROM folios f
    JOIN Comprobante_Digital cd
        ON cd.Cd_Tabla = 'GASTO_REGISTRO'
       AND cd.Cd_Documento LIKE f.Gr_Folio + '%'
       AND cd.Es_Cve_Estado = 'AC'
),
xml_agg AS (
    SELECT FOLIO,
           COUNT(DISTINCT Cd_Timbre_UUID) AS N_UUID_XML,
           MIN(Cd_Tipo_CFDI) AS TIPO_CFDI_UNICO,
           MIN(Cd_Serie_Folio) AS SERIE_FOLIO_UNICO
    FROM xml
    GROUP BY FOLIO
)
SELECT
    f.FOLIO,
    f.ORIGEN,
    f.Gr_Fecha                                                          AS FECHA,
    p.Mn_Cve_Moneda                                                     AS MONEDA,
    p.Pv_Cve_Proveedor                                                  AS CLAVE_PROVEEDOR,
    prov.Pv_R_F_C                                                       AS RFC_PROVEEDOR,
    prov.Pv_Descripcion                                                 AS NOMBRE_PROVEEDOR,
    p.PROVEEDOR_MULTIPLE,
    CASE WHEN pr.Fp_Cve_Forma_Pago = '0001' THEN 'SI'
         WHEN pr.Fp_Cve_Forma_Pago IS NULL THEN NULL ELSE 'NO' END       AS COBRADO_EFECTIVO,
    CASE WHEN pr.Fp_Cve_Forma_Pago IN ('0002','0003') THEN 'SI'
         WHEN pr.Fp_Cve_Forma_Pago IS NULL THEN NULL ELSE 'NO' END       AS COBRADO_CHEQUE_TRANSFERENCIA,
    CASE WHEN pr.Fp_Cve_Forma_Pago = '0002' THEN 'SI'
         WHEN pr.Fp_Cve_Forma_Pago IS NULL THEN NULL ELSE 'NO' END       AS CHEQUE,
    CASE WHEN cp.N_UUID_PAGO >= 2 THEN 'VARIOS' ELSE cp.UUID_PAGO_UNICO END AS CFDI_COMPROBANTE_PAGO,
    CAST(NULL AS nvarchar(50))                                          AS FACTURA_REF,
    pr.Pc_Banco                                                         AS BANCO,
    pr.Pc_Cuenta_Bancaria                                               AS CUENTA_BANCARIA,
    ch.Ch_Fecha                                                         AS FECHA_CHEQUE,
    ch.Ch_Folio                                                         AS NO_CHEQUE_TRANSF,
    mc.MONTO_COBRADO,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS'
         WHEN xa.TIPO_CFDI_UNICO = 'I' THEN 'Ingreso'
         WHEN xa.TIPO_CFDI_UNICO = 'E' THEN 'Egreso'
         WHEN xa.TIPO_CFDI_UNICO = 'D' THEN 'Diario'
         ELSE NULL END                                                  AS TIPO_COMPROBANTE,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS' ELSE xa.SERIE_FOLIO_UNICO END AS NUMERO_FACTURA
FROM folios f
LEFT JOIN proveedor_repr p   ON p.FOLIO = f.FOLIO
LEFT JOIN Proveedor prov     ON prov.Pv_Cve_Proveedor = p.Pv_Cve_Proveedor
LEFT JOIN pago_repr pr       ON pr.FOLIO = f.FOLIO
LEFT JOIN cheque_repr ch     ON ch.FOLIO = f.FOLIO
LEFT JOIN monto_cobrado mc   ON mc.FOLIO = f.FOLIO
LEFT JOIN comprobante_pago cp ON cp.FOLIO = f.FOLIO
LEFT JOIN xml_agg xa         ON xa.FOLIO = f.FOLIO
ORDER BY f.FOLIO
