# Pendientes

Estado al 2026-09-07, confirmado con Esteban: **por ahora solo recibido**.
Emitido y retención quedan pausados hasta resolver lo de abajo.

## Bloqueado — necesita trabajo fuera de este repo

### Emitidos: falta ingest en `raw_sat.cfdi_emitidos`

`raw_sat.cfdi_emitidos` solo tiene cargados septiembre y noviembre 2025
(13,208 CFDI, un solo batch del 2026-09-02). No hay nada de octubre/diciembre
2025 ni de 2026 — ningún periodo reciente se puede reconciliar. Esto es un
hueco del ingest/ELT que corre en `ctunlinux` (dominio de Claude Code, no
de este repo). Texto ya entregado a Esteban para pedírselo a Claude Code:

> Necesito que completes la carga de `raw_sat.cfdi_emitidos` (Postgres,
> esquema `raw_sat`, mismas columnas que `cfdi_recibidos`: uuid,
> fecha_emision, rfc_emisor, nombre_emisor, rfc_receptor, direccion,
> tipo_comprobante, subtotal, iva, total, uso_cfdi, metodo_pago,
> forma_pago, periodo, archivo_origen, fecha_carga). Ahora mismo solo
> tiene sep y nov 2025 (13,208 XML, batch del 2026-09-02) — falta todo lo
> demás: el resto de 2025 y todo 2026 hasta la fecha (recibidos ya llega
> a septiembre 2026, emitidos debería llegar al mismo punto). Necesito
> que: 1) revises qué carpeta/fuente usa el job de ingest de emitidos y
> confirmes si ya tiene disponibles los XML de los meses faltantes, 2)
> corras la carga para esos periodos con el mismo criterio/schema que ya
> usa recibidos, y 3) lo dejes corriendo de forma recurrente (igual que
> recibidos), para que no se vuelva a quedar atrás.

Una vez cargado, el trabajo de este lado es directo: `raw_sat.cfdi_emitidos`
tiene el mismo esquema que `cfdi_recibidos`, así que `extract_sat.py` se
puede generalizar con un parámetro de tabla en vez de escribir un
extractor nuevo. El lado mpro (orígenes esperables: VENTA, VENTAS_TRIV,
NOTA_CREDITO, CUENTA_X_COBRAR, PAGO_CXC, RECIBO_PAGO, ANTICIPO_CXC,
DEPURACION_CXC — vistos en el censo de `Poliza_Control.Pc_Tabla`, nunca
explorados a fondo) sí es trabajo nuevo de este repo.

### Retención: mapeo a mpro no resuelto

A diferencia de emitidos, `raw_sat.cfdi_retencion` SÍ está completo
(2016-12 a 2026-07, sin huecos). El problema es del lado mpro: los 15 CFDI
de retención de febrero 2026 (ISR por arrendamiento, clave 16, emitidos
por Trivasa a personas físicas) no aparecen en `Comprobante_Digital` de
207, ni en la tabla dedicada `Constancia_Retencion` (que sí existe pero no
tiene datos de febrero 2026 — su patrón histórico, ene/may/sep, no
coincide con estos CFDI mensuales). En 205, `Comprobante_Digital.Cd_Tabla`
sí trae un valor `CONSTANCIA_RETENCION`, pero tampoco ahí aparecieron los
UUIDs probados.

Este dominio no tiene ninguna investigación previa reutilizable (a
diferencia de recibidos, que se apoyó mucho en `layout-gastos` y
`poliza-explor`). Antes de seguir explorando a ciegas, vale la pena
preguntarle directamente a alguien de Trivasa que conozca el proceso de
retención de arrendamiento: ¿se registra en mpro en absoluto, o es un
proceso externo (PAC/timbrado directo) que nunca toca `Comprobante_Digital`?

## Pendiente dentro de recibido — mejoras al alcance ya construido

### Gasto_Registro — el bloque más grande sin resolver ($22–24M, ~37% cuadre agregado)

El proyecto `layout-gastos` (fuera de este repo, en
`trivasa-context/docs/proyectos/layout-gastos/`) ya documentó y validó
varios patrones específicos de este origen que **no están portados
todavía** a `reconciliacion_por_origen.py`:

- **CONSUMO_INTERNO** (patrón de doble póliza): excluir vía
  `Poliza_Configuracion.Pc_Descripcion`, pero el filtro actual
  (`NOT LIKE '%CUENTAS DE ORDEN%'`) no atrapa las variantes de texto "CTS
  ORDEN" / "CUENTA ORDEN" que también usa este origen específico.
- **Reversiones**: cuando el importe del folio es ≤ -$1, hay que comparar
  contra Abono, no Cargo.
- **GASTO_RECLASIFICACION**: lógica por signo (no tiene una póliza "real"
  propia, se identifica por el signo de cada línea).
- **GASTO_REGISTRO_NOMINA**: el grano correcto no es folio solo, es folio ×
  centro de costo × concepto (ver `hallazgos.md` punto 7, ejemplo real de
  CUOTAS AL IMSS con cargo 2x el subtotal por sumar todos los centros de
  costo).

Portar esta lógica es el trabajo de mayor impacto disponible ahora mismo
(es el origen con más $ sin resolver).

### Compra_Indirecto — bajo volumen, método propio ya documentado

Solo 8 documentos, $253K. `poliza-explor` ya documenta un método propio
(Cargo = `SUM(Ci_Precio_Descontado_Importe)` por `Ci_Folio`, excluyendo el
par de cuentas de orden) que no se ha aplicado aquí — se usó el método
genérico (Pd_Referencia) y dio 3% de cuadre. Barato de arreglar por el
volumen tan chico.

### Cuenta_x_Pagar — 29-33 documentos sin ninguna póliza encontrada

$527K en documentos donde `extract_poliza_por_origen()` no encontró
ninguna línea con `Pd_Referencia` coincidente. No investigado caso por
caso todavía — podría ser el mismo patrón de sufijo/truncado (poco
probable, ya se valida en los otros 51 documentos del mismo origen) o un
patrón de negocio distinto (documentos aplicados de otra forma).

### Nota_Credito_Proveedor — documentos partidos

Ver `hallazgos.md` punto 8 (ejemplo real: dos documentos que suman
exacto el total de un CFDI, pero no cuadran por separado). Bajo volumen
(15 documentos) — vale la pena confirmar el patrón con más muestra antes
de escribir una regla.

### FACTURA, ANTICIPO_CXP, NOTA_CREDITO, COMPROBANTE_PAGO — no trabajados

Volumen mínimo en febrero 2026 (5, 1, 1 y 6 documentos respectivamente) —
quedaron fuera de `ORIGENES_A_RECONCILIAR` en `reconciliacion_por_origen.py`
a propósito, priorizando los 6 orígenes con volumen relevante. Agregarlos
es directo (mismo patrón que los demás) cuando se quiera cerrar el 100%
del censo.

## Nota sobre alcance temporal

Mientras el pipeline corre contra `mssql_205` (ver `arquitectura.md`), el
alcance de fechas acordado con Esteban es **enero–junio 2026**. No se ha
confirmado cobertura de 205 fuera de ese rango — antes de correr un
periodo fuera de H1 2026, validar cobertura de mes (mismo chequeo que se
hizo para confirmar H1: contar filas por mes en `Poliza` y
`Comprobante_Digital`).
