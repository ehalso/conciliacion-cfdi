-- ============================================================================
-- Layout de Gastos v0.3 -- Detalle de Cargo/Abono por cuenta contable y
-- centro de costo. Esta es la query que se sirve en FlexMonster (sin
-- logica de comprobacion -- eso vive aparte, en Python, solo para uso
-- interno de validacion).
--
-- Que responde: "para cada gasto (folio), que movimientos contables reales
-- generó (que cuenta, que centro de costo, cuanto de Cargo, cuanto de
-- Abono)". Una fila por combinacion folio + cuenta + centro de costo.
-- ============================================================================

SELECT
    -- Folio de display, como lo ve el usuario en MPRO: sucursal (4 digitos,
    -- convencion interna) + folio (7 digitos). Ojo: el dato crudo en la
    -- base (Gasto_Registro.Gr_Folio) usa sucursal de 2 digitos, no 4 --
    -- por eso se reconstruye aqui.
    gr.Sc_Cve_Sucursal + '-' + RIGHT('0000000' + gr.Gr_Folio, 7) AS FOLIO,

    -- Cuenta contable del movimiento y su descripcion legible.
    pd.Cc_Cve_Cuenta_Contable AS CUENTA,
    cc.Cc_Descripcion AS CUENTA_DESCRIPCION,

    -- Centro de costo del movimiento. IMPORTANTE: es obligatorio agrupar por
    -- esto, no es un detalle opcional. Algunas reclasificaciones mueven un
    -- gasto de un centro de costo a otro usando la MISMA cuenta contable en
    -- Cargo y Abono -- sin este campo, esas dos lineas se mezclarian en una
    -- sola fila y parecerian cancelarse solas, ocultando el movimiento real.
    pd.Pd_Centro_Costo AS CENTRO_COSTO,
    cco.Cc_Descripcion AS CENTRO_COSTO_DESCRIPCION,

    -- Pd_Tipo en la tabla origen es 1=Cargo, 2=Abono, en la misma columna
    -- (Pd_Importe). Se separan en dos columnas para que el consumidor del
    -- reporte no tenga que interpretar el codigo 1/2.
    SUM(CASE WHEN pd.Pd_Tipo = 1 THEN pd.Pd_Importe ELSE 0 END) AS CARGO,
    SUM(CASE WHEN pd.Pd_Tipo = 2 THEN pd.Pd_Importe ELSE 0 END) AS ABONO

FROM Gasto_Registro gr

    -- Gasto_Registro no guarda a que empresa pertenece directamente -- se
    -- obtiene subiendo a su sucursal.
    JOIN Sucursal s
        ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal

    -- Poliza_Control es la tabla puente: dice que poliza contable
    -- corresponde a este folio de gasto. Pc_Tabla='GASTO_REGISTRO' filtra
    -- porque esta misma tabla puente tambien liga polizas de otros modulos
    -- del ERP (ventas, nomina, etc.).
    JOIN Poliza_Control plc
        ON plc.Pc_Tabla = 'GASTO_REGISTRO'
       AND plc.Pc_Documento = gr.Gr_Folio   -- comparacion de texto simple:
                                              -- Gr_Folio ya guarda el folio
                                              -- completo como string
                                              -- ('SS-FFFFFFF'), no hace
                                              -- falta convertir nada.
       AND plc.Es_Cve_Estado <> 'CA'         -- 'CA' = cancelada. Se filtra
                                              -- aqui Y en Poliza (mas abajo)
                                              -- porque son dos tablas
                                              -- independientes, cada una
                                              -- con su propio estado.

    -- Cabecera de la poliza contable (fecha, estado). Se necesita solo para
    -- poder filtrar su Es_Cve_Estado.
    JOIN Poliza pl
        ON pl.Pl_Folio = plc.Pl_Folio

    -- Las lineas reales de la poliza: aqui vive el Cargo/Abono/Cuenta.
    JOIN Poliza_Detalle pd
        ON pd.Pl_Folio = plc.Pl_Folio
       AND pd.Pd_Referencia = gr.Gr_Folio    -- una misma poliza puede
                                              -- agrupar varios folios de
                                              -- gasto en un solo asiento
                                              -- (posteo por lote) --
                                              -- Pd_Referencia aisla solo
                                              -- las lineas de ESTE folio.

    -- Catalogos, solo para traer la descripcion legible.
    LEFT JOIN Cuenta_Contable cc
        ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable
    LEFT JOIN Centro_Costo cco
        ON cco.Cc_Cve_Centro_Costo = pd.Pd_Centro_Costo

WHERE gr.Gr_Fecha >= :fecha_ini
  AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND pl.Es_Cve_Estado <> 'CA'

  -- Estos dos origenes de gasto no generan poliza por decision de negocio
  -- (Consumo Interno y Nomina se contabilizan por otro mecanismo, ajeno a
  -- este reporte) -- se excluyen para no traer filas vacias sin sentido.
  AND ISNULL(gr.Gr_Tabla, '') NOT IN ('GASTO_REGISTRO_NOMINA', 'CONSUMO_INTERNO')

GROUP BY
    gr.Sc_Cve_Sucursal, gr.Gr_Folio,
    pd.Cc_Cve_Cuenta_Contable, cc.Cc_Descripcion,
    pd.Pd_Centro_Costo, cco.Cc_Descripcion
