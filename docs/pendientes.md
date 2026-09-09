# Pendientes

Estado al 2026-09-09 (actualizado el mismo día): `Poliza_Control` **volvió
a responder** (estaba caída desde 2026-09-07, ver `hallazgos.md` punto 13)
— desbloquea todo el trabajo de nivel 3 pendiente (emitido, retención,
Compra_Indirecto). También se validó un **método de doble chequeo
(cargo+abono)** para COMPRA — ver sección nueva abajo, es el trabajo de
mayor impacto de esta sesión.

## Método de doble chequeo (cargo + abono) — validado para COMPRA, 81.8%

Hasta ahora el pipeline solo comparaba el **cargo** (posteado bajo el folio
de compra) contra subtotal-o-total del CFDI. Se encontró y validó en vivo
(2026-09-09, 713 CFDI de COMPRA, feb-2026) un segundo chequeo independiente
usando el **abono**:

- **CARGO**: `Pd_Referencia` = folio de compra (`Comprobante_Digital.Cd_Documento`
  truncado a 10) → debe igualar el **Subtotal** del CFDI.
- **ABONO**: `Pd_Referencia` = **Serie+Folio del propio CFDI**
  (`Cd_Serie`+`Cd_Serie_Folio` de `Comprobante_Digital` — columnas que ya
  existen, no hace falta parsear el XML), normalizado (sin ceros a la
  izquierda, ignorando el prefijo manual "Fact: " que a veces trunca el
  campo `Pd_Referencia`, límite 15 caracteres) → debe igualar el **Total**.

Con los dos chequeos juntos: **583/713 (81.8%) conciliados** (cargo 88.4%,
abono 89.6% por separado). Implementado en `baseline_conciliacion.py`
(nuevo script, reusa `extract_poliza_por_origen` para el cargo). Nota: el
IVA se postea como una sola línea consolidada por día/póliza, no por
documento — no es verificable por CFDI individual, se deja fuera del
chequeo automatizado a propósito.

**Corrección aplicada (2026-09-09): documento duplicado por CFDI.** Un
mismo CFDI puede quedar etiquetado con más de un `Cd_Documento` bajo el
mismo origen en `Comprobante_Digital` (50/713 CFDI de COMPRA en feb-2026)
— normalmente una etiqueta real y una "fantasma" con cargo $0 (renglón
vacío o mal capturado). El script ahora se queda, por UUID, con el folio
cuyo cargo está más cerca del subtotal del CFDI, en vez de tomar el
primero en orden arbitrario. Esto subió el resultado de 578→583/713
(81.1%→81.8%). Ver `baseline_conciliacion.py::calcular()`.

**De los 130 sin cuadrar, causas confirmadas:**

- **Patrón "liquidación directa" (≈43 casos, proveedor GLM/Gas LP de
  Mérida y probablemente otros pagados de contado)**: la póliza de COMPRA
  se **cancela** (`Es_Cve_Estado='CA'`) y el pago se vuelve a capturar
  directo en el módulo **Cheque** — el abono nunca se recontabiliza en
  COMPRA. El cargo sí cuadra; falta buscar el abono también en Cheque para
  estos casos. Pendiente: confirmar en qué otros proveedores se repite.
- **Cruce con COMPRA_INDIRECTO (varios casos, ej. proveedor "Industrial de
  Alambres")**: el mismo CFDI aparece tageado en dos orígenes —
  COMPRA (la mayor parte del valor) y COMPRA_INDIRECTO (una porción
  prorrateada hacia *otras* compras, como costo de flete/maniobra). Si no
  se suman ambos orígenes, cargo y abono quedan cortos exactamente por esa
  porción.
- **Documento duplicado sin match ni con el mejor candidato (≈35 casos)**:
  tras la corrección de arriba, quedan casos donde el CFDI sí tiene más de
  un `Cd_Documento` bajo COMPRA pero ninguno de los candidatos cuadra ni
  con subtotal ni con total — sugiere que el cargo real está repartido
  entre ambos folios, o que ninguno de los dos es el correcto.
- **Errores puntuales de captura (al menos 1 caso confirmado — CFDI de
  MAQUINAS DIESEL, serie IFG-89675)**: el `Cd_Documento` apunta a un folio
  de compra sin relación con el CFDI (otro proveedor/familia, otro orden
  de magnitud). El abono sí cuadra (vía Serie+Folio) pero el cargo quedó
  capturado contra el folio equivocado. No parece sistemático — es ruido
  de captura manual, no vale la pena perseguirlo caso por caso.
- Quedan casos residuales sin causa confirmada — candidatos: más
  proveedores con el patrón GLM, o folios de compra que agrupan más de una
  línea contable sin corresponder 1 a 1 con un solo CFDI (confirmado que
  existe: ver ejemplo folio `05-0030182`, reusado en varias líneas del
  mismo día).

**Pendiente**: extender el método a los demás orígenes con mapeo
confirmado (GASTO_REGISTRO, CUENTA_X_PAGAR, NOTA_CREDITO_PROVEEDOR), y
buscar el patrón GLM también ahí.

## Baseline UNIVERSAL (todos los orígenes, chequeo agregado) — 87.0%, 2026-09-09

Pivote pedido explícitamente por Esteban: en vez de conciliar un origen a
la vez exigiendo que UN documento cuadre exacto contra el CFDI (como hace
`baseline_conciliacion.py`), sumar el cargo de **todos** los documentos con
los que un CFDI aparece etiquetado en `Comprobante_Digital` — sin importar
el origen — y comparar esa suma contra el Subtotal. Motivado por hallazgos
ya confirmados de que un mismo CFDI puede repartirse entre varios
documentos/orígenes (COMPRA+COMPRA_INDIRECTO, GASTO_REGISTRO+CUENTA_X_PAGAR,
folio duplicado dentro del mismo origen, liquidación directa vía Cheque) y
por la investigación de `trivasa-context` (`poliza-explor` /
`configuracion-polizas.md`) que confirmó que el motor de pólizas (`CT001` /
`Poliza_Configuracion`) genera el cargo con la misma fórmula
(`SUM(subtotal)`, referenciado al folio del documento) en varios orígenes,
y que el filtro robusto de "cuentas de orden" (vía `Pl_Configuracion` →
`Poliza_Configuracion.Pc_Descripcion`) generaliza sin cambios a cualquier
origen.

Implementado en `baseline_universal.py`. Validado en vivo sobre CFDI
recibidos feb-2026: de 5,563 CFDI, 5,523 tienen al menos una etiqueta en
mpro; de esos, 4,023 son complementos sin valor propio (TRASLADO/
COMPROBANTE_PAGO, Subtotal≈$0 — excluidos del cuadre). Del universo
monetario real (1,500 CFDI), **1,305 (87.0%)** ya cuadran en agregado —
muy por encima del techo por-origen-individual:

| Combinación de orígenes | n CFDI | % cuadra |
|---|---:|---:|
| COMPRA (solo) | 701 | 94.3% |
| GASTO_REGISTRO (solo) | 699 | 82.8% |
| CUENTA_X_PAGAR (solo) | 33 | 54.5% |
| GASTO_REGISTRO + CUENTA_X_PAGAR | 29 | **100%** |
| COMPRA + COMPRA_INDIRECTO | 6 | **100%** |
| COMPRA + FACTURA | 4 | **100%** |
| NOTA_CREDITO_PROVEEDOR (solo) | 13 | 0% |
| CHEQUE (solo, vía pago directo) | 11 | 45.5% |

Dos lecturas importantes:

- **Las combinaciones cruzadas cuadran al 100%** — confirma que sumar en
  vez de elegir "el" documento resuelve de raíz el problema de CFDI
  repartidos entre orígenes, sin necesitar lógica especial por caso.
- **Gasto_Registro sube de ~37% (método viejo, `reconciliacion_por_origen.py`)
  a 82.8%** solo por usar el filtro robusto de cuentas-de-orden
  (`Pl_Configuracion`) en vez del filtro de texto frágil — sin portar
  ninguno de los patrones específicos ya documentados (CONSUMO_INTERNO,
  reversiones, GASTO_RECLASIFICACION, NOMINA). Sugiere que buena parte de
  esa deuda técnica ya está resuelta "gratis" por el cambio de método; los
  patrones específicos seguramente explican una porción del 17.2% restante.
- **NOTA_CREDITO_PROVEEDOR da 0%** — consistente con el patrón de
  "documentos partidos"/signo ya documentado (`hallazgos.md` punto 8): una
  nota de crédito reduce el cargo, no lo iguala, y el chequeo actual no
  maneja signo. Pendiente aplicar la misma lógica de reversión pensada para
  Gasto_Registro.

**Límite importante**: este chequeo es de UN SOLO LADO (cargo=subtotal). No
exige que el abono/pago también cuadre — un CFDI "conciliado" aquí tiene su
compra/gasto bien reconocido contablemente, pero el pago puede seguir sin
verificar. Extender el doble chequeo (como ya existe para COMPRA vía
Serie+Folio) a los demás orígenes es el siguiente paso natural.

**Pendiente**: de los 195 sin cuadrar, investigar dirigido por combinación
de orígenes (empezando por GASTO_REGISTRO solo, 120 casos, y COMPRA solo,
40 casos) — candidatos: los patrones ya conocidos de Gasto_Registro
(CONSUMO_INTERNO, reversiones, NOMINA) y una versión con signo para
NOTA_CREDITO_PROVEEDOR.

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

**`Poliza_Control` ya responde de nuevo** (confirmado 2026-09-09, resuelto
del lado de `ctunlinux`/bridge — ver `hallazgos.md` punto 13). Sigue
pendiente escribir el extractor de nivel 3 para FACTURA/NOTA_CREDITO
(mismo patrón que `extract_poliza_por_origen.py`: folio truncado a 10
caracteres, `Pd_Referencia` para aislar el documento dentro de la póliza,
exclusión de cuentas de orden — y ya con el método de doble chequeo
cargo+abono validado esta sesión para COMPRA, ver más abajo). Completar
también el resto de 2025/2026 en el ingest para tener el mismo rango de
fechas que recibidos.

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

### Compra_Indirecto — causa del 3% confirmada (2026-09-09): no es un hueco de datos

Investigado a fondo: los 6 CFDI de febrero SÍ tienen póliza activa. El 3%
de cuadre pasa porque estos CFDI **también aparecen bajo COMPRA** (con su
propio folio de compra, ahí sí cuadran ~88-102%) — COMPRA_INDIRECTO solo
captura la porción de costo indirecto (flete/maniobra) que ese mismo CFDI
prorratea hacia *otras* órdenes de compra, nunca su importe completo.
Comparar COMPRA_INDIRECTO contra el total del CFDI compara contra dinero
que ya está resuelto (duplicado) en COMPRA. **Se debe sacar del cálculo de
% cuadre por importe de CFDI** — si se quiere validar, la comparación
correcta es que la porción prorrateada tenga póliza y sume bien, no que
iguale el CFDI completo.

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
