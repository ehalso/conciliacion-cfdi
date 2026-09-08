# Pendientes

Estado al 2026-09-07 (actualizado el mismo día): el ingest de Claude Code
avanzó y **desbloqueó parcialmente emitido y retención** — ver el detalle
de cada uno abajo. Sigue habiendo trabajo real por delante en ambos antes
de llegar al mismo nivel de profundidad que recibido (nivel 3, por origen).

## Emitidos: ingest parcial — nivel 1 corrido y validado, nivel 3 bloqueado por infraestructura

`raw_sat.cfdi_emitidos` ya no está congelado en sep/nov 2025: un nuevo
batch (2026-09-07) agregó **2026-01 completo** (6,500 CFDI). 2026-02 solo
trae 2 filas (carga a medias, en curso) y no hay nada de octubre/diciembre
2025 ni de marzo–agosto 2026 todavía — el ingest sigue sin ponerse al día
por completo (recibidos ya llega a septiembre 2026).

Con lo que ya hay, nivel 1 (`main.py --tipo emitido --periodo 2026-01`) da
**6,489/6,500 = 99.8% OK** — prácticamente el mismo nivel de conciliación
que recibidos. Censo de origen (`Comprobante_Digital.Cd_Tabla` para esos
UUIDs):

| origen | n_cfdi | monto_total |
|---|---:|---:|
| FACTURA | 2,191 | $62,346,811.72 |
| NOTA_CREDITO | 189 | $4,566,869.25 |
| COMPROBANTE_PAGO | 544 | $0.00 |
| TRASLADO | 3,565 | $0.00 |

`COMPROBANTE_PAGO` y `TRASLADO` en $0 son el mismo patrón ya documentado
para Cheque/recibidos (REP tipo P y Carta Porte respectivamente — ver
`hallazgos.md` puntos 6 y el nuevo punto 12).

**Bloqueado ahora mismo**: pasar a nivel 3 (trazar FACTURA/NOTA_CREDITO
hasta su póliza, cargo/abono real) requiere `Poliza_Control`, y esa tabla
específica está devolviendo `HTTP 502` en la bridge para **ambos**
targets (205 y 207) desde el 2026-09-07 — confirmado con `SELECT TOP 3`
sin ningún filtro, mientras que `Comprobante_Digital`, `Poliza`,
`Poliza_Detalle`, `Poliza_Configuracion` y `Cheque` sí responden con
normalidad. Parece un problema puntual de esa tabla (lock, reindexado, o
algo relacionado con la carga que acaba de correr) — no algo resoluble
desde este repo. Vale la pena que Esteban le pida a Claude Code que
revise el estado de `Poliza_Control` en `ctunlinux`/el bridge.

Pendiente, una vez que Poliza_Control vuelva a responder: escribir el
extractor de nivel 3 para FACTURA/NOTA_CREDITO (mismo patrón que
`extract_poliza_por_origen.py`: folio truncado a 10 caracteres,
`Pd_Referencia` para aislar el documento dentro de la póliza, exclusión de
cuentas de orden). Completar también el resto de 2025/2026 en el ingest
para tener el mismo rango de fechas que recibidos.

## Retención: mapeo a mpro encontrado, pero solo cubre ~36% de los CFDI (corregido 2026-09-08)

El mapeo SAT → mpro para retención existe y funciona vía
`Comprobante_Digital.Cd_Tabla = 'CONSTANCIA_RETENCION'` — lo que antes
fallaba (investigación previa a 2026-09-07) era que las pruebas se
hicieron sobre febrero 2026 (mes sin datos) y sin considerar que
`Comprobante_Digital` se indexa por `Cd_Timbre_Fecha`, no por una columna
`Cd_Fecha` que no existe.

**Corrección importante (2026-09-08)**: el primer reporte de este hallazgo
(2026-09-07) decía cobertura casi total ("47 filas para 45 UUIDs") — esa
cifra estaba mal calculada (contaba UUIDs de toda la historia de la tabla,
no solo enero 2026). La cifra real, re-verificada con los 45 CFDI de
retención de enero 2026: **solo 16 de 45 (36%) tienen la fila
`CONSTANCIA_RETENCION`** con folio y monto reales (ese folio sí coincide
1-a-1 con `Constancia_Retencion.Cr_Folio` y el monto es exacto). Otros 15
de 45 (33%) solo tienen un stub en `GASTO_REGISTRO` con `Cd_Monto=0` (sin
monto real en ningún lado). Los **14 restantes (31%) no tienen ninguna
fila** en `Comprobante_Digital`.

**Pendiente real, sin resolver**: por qué el 64% de los CFDI de retención
no llega a `Constancia_Retencion`. No investigado a fondo — antes de
seguir explorando a ciegas, vale la pena preguntarle directamente a
alguien de Trivasa que conozca el proceso de retención de arrendamiento:
¿hay más de un proceso/vía para registrar la retención en mpro, o
simplemente no se está registrando contablemente en la mayoría de los
casos?

Para el 36% que sí mapea, sigue pendiente además trazar `Cd_Documento`/
`Cr_Folio` hasta `Poliza_Control` para llegar al cargo/abono contable
real — bloqueado por la misma caída de `Poliza_Control` descrita arriba
para emitidos.

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
