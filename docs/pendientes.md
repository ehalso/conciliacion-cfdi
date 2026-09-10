# Pendientes

> **Actualización 2026-09-10**: la conciliación pasó de 90.1% a **99.36% en
> todo H1 2026** tras la revisión folio por folio de los pendientes. Casi todo
> lo que este documento describe como pendiente ya está resuelto o
> reclasificado — ver
> [`investigacion_pendientes.md`](investigacion_pendientes.md), que es el
> documento vigente sobre el tema. Lo de abajo se conserva como historial de
> cómo se veía el problema antes.

Estado al 2026-09-09 (actualizado el mismo día): `Poliza_Control` **volvió
a responder** (estaba caída desde 2026-09-07, ver `hallazgos.md` punto 13)
— desbloquea todo el trabajo de nivel 3 pendiente (emitido, retención,
Compra_Indirecto). También se validó un **método de doble chequeo
(cargo+abono)** para COMPRA, y más tarde el mismo día un **baseline
UNIVERSAL** que suma el cargo de todos los orígenes por CFDI — es el
método de mayor impacto y el que se usa actualmente (**90.1%**, tras
corregir la llave granular de Gasto_Registro). Ver
[`PROGRESS.md`](../PROGRESS.md) en la raíz del repo para un resumen
orientado a retomar el trabajo.

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
monetario real (1,500 CFDI), **1,351 (90.1%)** ya cuadran en agregado —
muy por encima del techo por-origen-individual (cifra actualizada
2026-09-09 tras corregir la llave granular de GASTO_REGISTRO, ver
subsección propia abajo; la primera corrida, sin ese fix, daba 87.0%):

| Combinación de orígenes | n CFDI | % cuadra |
|---|---:|---:|
| COMPRA (solo) | 701 | 94.3% |
| GASTO_REGISTRO (solo) | 699 | 89.4% |
| CUENTA_X_PAGAR (solo) | 33 | 54.5% |
| GASTO_REGISTRO + CUENTA_X_PAGAR | 29 | **100%** |
| NOTA_CREDITO_PROVEEDOR (solo) | 13 | 0% |
| CHEQUE (solo, vía pago directo) | 11 | 45.5% |
| COMPRA + COMPRA_INDIRECTO | 6 | **100%** |
| COMPRA + FACTURA | 4 | **100%** |
| COMPRA + GASTO_REGISTRO | 2 | **100%** |
| ANTICIPO_CXP + NOTA_CREDITO | 1 | **100%** |
| FACTURA (solo) | 1 | 0% |

Dos lecturas importantes:

- **Las combinaciones cruzadas cuadran al 100%** — confirma que sumar en
  vez de elegir "el" documento resuelve de raíz el problema de CFDI
  repartidos entre orígenes, sin necesitar lógica especial por caso.
- **Gasto_Registro sube de ~37% (método viejo, `reconciliacion_por_origen.py`)
  a 89.4%** — 82.8% solo por usar el filtro robusto de cuentas-de-orden
  (`Pl_Configuracion`) en vez del filtro de texto frágil, y de ahí a 89.4%
  corrigiendo la llave granular (ver subsección dedicada abajo). Sin portar
  ninguno de los patrones específicos ya documentados (CONSUMO_INTERNO,
  reversiones, GASTO_RECLASIFICACION, NOMINA) — sugiere que buena parte de
  esa deuda técnica ya está resuelta "gratis" por el cambio de método; los
  patrones específicos seguramente explican una porción del resto.
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

**Pendiente**: de los 149 sin cuadrar (actualizado 2026-09-09, tras el fix
de llave granular), investigar dirigido por origen:

| Origen (pendientes) | n |
|---|---:|
| GASTO_REGISTRO | 74 |
| COMPRA | 40 |
| CUENTA_X_PAGAR | 15 |
| NOTA_CREDITO_PROVEEDOR | 13 |
| CHEQUE | 6 |
| FACTURA | 1 |

Candidatos por origen: los patrones ya conocidos de Gasto_Registro
(CONSUMO_INTERNO, reversiones, NOMINA, y los cinco patrones de la
subsección siguiente — folio-agrupa-CFDI, arrendamiento financiero,
captura duplicada de `Grc_Importe`, CFDI de gobierno repartido entre
sucursales), y una versión con signo para NOTA_CREDITO_PROVEEDOR.

## Gasto_Registro — llave granular corregida (2026-09-09): folio+Grd_ID, no folio truncado a 10

Pedido explícito de Esteban: confirmar que las pólizas canceladas (`CA`)
estuvieran filtradas, y corregir la lógica de folio granular de
Gasto_Registro para ver cómo quedaba el % de conciliación. Dos hallazgos
en el camino, uno de confirmación y uno de corrección real:

**CA ya estaba filtrado.** `extract_poliza_por_origen.py` ya trae
`AND p.Es_Cve_Estado <> 'CA'` en las dos queries que arma (la genérica por
origen y la de CHEQUE) — COMPRA, CUENTA_X_PAGAR, NOTA_CREDITO_PROVEEDOR,
COMPRA_INDIRECTO y CHEQUE ya excluían canceladas desde antes de esta
sesión. Para GASTO_REGISTRO no aplica: el nuevo método (abajo) no pasa por
`Poliza_Detalle`, así que no depende de qué póliza materializó el motor.

**La llave granular correcta es `(Gr_Folio, Grd_ID)`, sumando TODOS los
`Grc_ID`.** El primer intento asumió que `Comprobante_Digital.Cd_Documento`
traía folio(10)+Grd_ID(4)+Grc_ID(4) = 18 caracteres siempre, y que había
que aislar el `Grc_Importe` de ESE `Grc_ID` exacto. Verificado en vivo que
es **incorrecto**: `Cd_Documento` para este origen tiene dos formatos,
14 caracteres (folio+Grd_ID, sin sufijo de Grc_ID) o 18 (con un sufijo que
resultó ser irrelevante — nunca hay más de un `Cd_Documento` distinto por
`(folio, Grd_ID)`, sin importar cuántos `Grc_ID` tenga ese renglón en
`Gasto_Registro_Control`). El cargo correcto es la **suma de TODOS los
`Grc_Importe`** de esa llave — verificado exacto contra el cargo realmente
posteado en `Poliza_Detalle` (vía `extract_poliza_por_origen`, que sí lee
`Poliza_Detalle`), incluyendo un folio con 8 renglones de prorrateo por
centro de costo: suma control $2,746.64 = cargo póliza $2,746.64 (folio
`01-0027091`). Ver `extract_gasto_registro.py` (docstring actualizado con
el detalle completo) y `hallazgos.md` puntos 14-15.

Con la hipótesis equivocada (18 caracteres siempre), el % **bajó** de
87.0% a 82.7-83.3% en vez de subir — 433 de 1,211 documentos GASTO_REGISTRO
de feb-2026 tienen el formato de 14 caracteres y quedaban sin cargo
encontrado (`None` → 0.0). Con la llave corregida: **89.4%** para
GASTO_REGISTRO solo (era 82.8% con el método anterior a esta sesión), y
**90.1%** el agregado universal completo (era 87.0%).

**Bug adicional corregido en el camino**: el `drop_duplicates` inicial de
`baseline_universal.py::calcular()` deduplicaba por `documento_real`
(folio truncado a 10) para **todos** los orígenes por igual — correcto
para colapsar folios "fantasma" duplicados en la mayoría de los orígenes,
pero incorrecto para GASTO_REGISTRO: colapsaba de más los `Grd_ID`
legítimos de un mismo folio. Se corrigió para que el dedup sea
origin-aware (dedup por `documento` completo solo para GASTO_REGISTRO) —
ver `ORIGEN_GRANULAR` en `baseline_universal.py`.

### Cinco patrones encontrados en los pendientes de Gasto_Registro (drill-down manual, dos rondas)

- **Arrendamiento financiero (leasing) — solo se captura el interés.**
  CFDI de START BANREGIO SOFOM (renta de mensualidad de arrendamiento
  financiero): `Gasto_Registro_Documento` solo trae el renglón de
  **interés** (ej. $14,540.09 de un CFDI con Subtotal $60,044.90) — la
  porción de capital/amortización (~$45,504.81) no pasa por
  Gasto_Registro, presumiblemente reduce un pasivo en otro módulo no
  rastreado por este pipeline. Al menos 2 CFDI confirmados de este
  proveedor con el mismo patrón; probablemente más entre los pendientes.
  **Confirmado 2026-09-09 que no es exclusivo de START BANREGIO**:
  CATERPILLAR CREDITO (pendiente de -$190,127.59) es el mismo patrón —
  folio `01-0035173`, comentario "ARRENDAMIENTO FINANCIERO U1238 Y U1232
  10/60", 2 `Grd_ID` (uno por unidad) capturando solo interés. Cualquier
  proveedor de leasing/arrendadora en los pendientes es candidato a este
  mismo patrón.
- **CFDI de gobierno repartido entre varios folios, uno por sucursal —
  solo uno queda etiquetado en `Comprobante_Digital`.** El pendiente de
  mayor impacto del periodo (CFDI de "SECRETARIA DE ADMINISTRACION Y
  FINANZAS", Subtotal $397,161.00, cargo encontrado solo $131,430.58):
  es un CFDI de ISN (Impuesto Sobre Nómina) que Trivasa captura en un
  folio de Gasto_Registro **por sucursal** (13 sucursales, mismo
  `Gr_Comentario` "ISN SOBRE NOMINA TRIVASA SA DE CV"), pero mpro solo
  adjuntó el XML/UUID a UNO de esos folios. Sumando los 13 folios activos
  de todas las sucursales, el total cuadra exacto ($397,160.85 vs
  $397,161.00 del CFDI) — el dinero sí está capturado en mpro, solo que
  repartido y sin ligar de vuelta al CFDI. No hay una llave estructurada
  para reagrupar los folios hermanos (solo texto libre en
  `Gr_Comentario` + fecha + sucursal) — ver `hallazgos.md` punto 19 para
  el detalle completo y la heurística candidata (no implementada, riesgo
  de falsos positivos con otros "provisión" a otra escala). Candidato
  fuerte para explicar otros pendientes grandes de proveedores tipo
  gobierno/organismos que facturan consolidado (IMSS también aparece con
  una diferencia grande, -$110,642.93, pero **no se confirmó** el mismo
  mecanismo — el concepto que se intentó cruzar, "PREVISION SOCIAL", opera
  a una escala de cientos de miles/millones de pesos por sucursal/mes, no
  comparable, así que sigue sin explicación confirmada).
- **Captura duplicada de `Grc_Importe` — error real de datos, no de
  método.** Caso BRIGGS EQUIPMENT (renta de montacargas, 5 CFDI
  independientes de $2,615.00 cada uno, folios `05-0178783/784/786/831/832`
  del 2026-02-11): los 5 `Gasto_Registro_Control.Grc_Importe` traen
  **exactamente el mismo importe, $45,060.3725**, pese a ser folios,
  proveedores-CFDI y centros de costo distintos — y ese mismo valor es el
  que terminó posteado en `Poliza_Detalle` (confirmado que el problema
  está en la captura, no en cómo se generó la póliza — ver
  `hallazgos.md` punto 16 para el detalle de la configuración
  revisada, `0450`). Un patrón simétrico aparece del lado del abono de la
  misma póliza (referencias `A370838`-`A370845` duplicadas con dos
  totales grandes repetidos, $49,236.63 y $28,242.81, además de sus
  montos correctos). Parece un error de captura por lote (copy-paste) al
  registrar varias facturas del mismo proveedor el mismo día — vale la
  pena reportarlo a quien mantiene la captura de Gasto_Registro en mpro,
  no es algo que este pipeline pueda "arreglar" prorrateando.
- **Folio agrupa más de un CFDI** (ya documentado en sesiones previas,
  confirmado que sigue siendo la causa más común): un folio de
  Gasto_Registro con varios `Grd_ID` reparte varios CFDI distintos — ya
  resuelto por la llave granular de arriba, pero sigue explicando
  pendientes cuando el CFDI en cuestión no tiene ninguna etiqueta propia
  bien formada.

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

## Retención: dos conceptos distintos (`cve_retenc` 14 vs 16) — cada uno con su propio camino de conciliación (actualizado 2026-09-10, ver `hallazgos.md` punto 28)

**Corrección 2026-09-10**: la primera pasada (2026-09-09) trató el hueco de
cobertura como un solo fenómeno "estacional" — estaba mal. `raw_sat.cfdi_retencion`
mezcla dos tipos de retención de ISR con comportamiento completamente
distinto, diferenciados por `cve_retenc`:

| `cve_retenc` | Tasa | Concepto | Frecuencia | Camino de conciliación |
|---|---:|---|---|---|
| `14` | 10% | Arrendamiento/honorarios | Cada ~4 meses (así se emite, no es un hueco) | `Comprobante_Digital.Cd_Tabla='CONSTANCIA_RETENCION'`, 100% cuando se busca en el mes correcto |
| `16` | 20% | Intereses a prestamista/inversionista | Mensual, ~15 CFDI/mes | `Comprobante_Digital.Cd_Tabla='GASTO_REGISTRO'` (stub) — **`CONSTANCIA_RETENCION` nunca aparece para este tipo** |

**Implementado**: `src/extract_retencion.py` + `retencion_reconciliation.py`
(nivel 1 — existencia + cuadre de `monto_total_operacion` contra
`Comprobante_Digital.Cd_Monto`, sin parsear XML — el XML de mpro para este
origen NO es un CFDI normal, ver `hallazgos.md` punto 27 para el detalle).
Esta implementación cubre bien `cve=14`; para `cve=16` solo detecta
"conciliado si hay `CONSTANCIA_RETENCION`" — que nunca pasa, así que hoy
reporta a este grupo siempre como pendiente aunque el gasto esté bien
capturado (ver abajo).

```bash
python3 retencion_reconciliation.py --periodo 2026-01
```

**Corrida en vivo para los 6 meses de H1 2026** (sin separar por `cve_retenc`
— cifra agregada, `hallazgos.md` punto 27/28):

| Periodo | Total SAT | Conciliado (CONSTANCIA_RETENCION) | Stub Gasto_Registro ($0) | Sin ninguna fila |
|---|---:|---:|---:|---:|
| 2026-01 | 45 | 16 | 15 | 14 |
| 2026-02 | 15 | 0 | 0 | 15 |
| 2026-03 | 15 | 0 | 15 | 0 |
| 2026-04 | 15 | 0 | 15 | 0 |
| 2026-05 | 31 | 16 | 15 | 0 |
| 2026-06 | 15 | 0 | 15 | 0 |
| **H1** | **136** | **32 (23.5%)** | **75** | **29** |

Los 32 "conciliado" son enteramente `cve=14` (100% de ese grupo, en los
meses en que de verdad se emite — enero y mayo). Los 75 "stub" y 29 "sin
ninguna fila" son enteramente `cve=16` — y **el gasto detrás de esos 104 SÍ
está bien capturado** en `Gasto_Registro` (verificado exacto: los 15 CFDI de
febrero, el único mes con 0% de link, suman $254,305.39 contra
`Gasto_Registro_Documento` — al centavo). El problema no es contable, es que
`Comprobante_Digital` no siempre liga el CFDI al folio, por dos motivos
reales y distintos (ver punto 28 completo):

1. **Omisión pura** (febrero 2026): nunca se generó el link, ni el stub en
   $0, para un lote de 15 CFDI — confirmado que el proceso de etiquetado sí
   corría ese día para otros folios, así que es un paso puntual saltado, no
   una caída general.
2. **CFDI sustituido sin re-ligar** (un caso confirmado, enero 2026): el
   CFDI trae `CfdiRetenRelacionados TipoRelacion="04"` (sustituye una
   retención previa cancelada) — el link en `Comprobante_Digital` se quedó
   apuntando al UUID viejo/cancelado, nunca se actualizó al nuevo. El gasto
   ya estaba bien conciliado bajo el UUID anterior; solo la referencia
   fiscal quedó desactualizada.

**Pendientes reales, en orden de prioridad**:

1. **Extender el método**: para `cve=16`, matchear por RFC receptor →
   `Proveedor.Pv_R_F_C` → `Gasto_Registro_Documento` del mismo mes (comparar
   `monto_total_operacion` contra `Grd_Precio_Descontado_Importe`) como
   *fallback* cuando `Comprobante_Digital` no tenga ninguna fila para el
   UUID — recuperaría el mecanismo 1 (omisión) sin depender del link.
2. Para el mecanismo 2 (sustitución), seguir `CfdiRetenRelacionados` cuando
   el UUID directo no aparezca en `Comprobante_Digital`, antes de reportar
   "gasto no encontrado" — puede que ya esté conciliado bajo el UUID
   sustituido.
3. Nivel 3: trazar `folio_constancia`/`Gr_Folio` hasta `Poliza_Control` para
   el cargo/abono contable real — ya no bloqueado (`Poliza_Control` volvió a
   responder, punto 13), solo falta escribir el extractor (mismo patrón que
   `extract_poliza_por_origen.py`).
4. Preguntar directamente a alguien de Trivasa por qué el lote de febrero
   (cve=16) nunca se etiquetó — para confirmar que es error humano puntual y
   no un proceso paralelo sin documentar.

## Pendiente dentro de recibido — mejoras al alcance ya construido

### Gasto_Registro — actualizado a 89.4% (ver sección dedicada arriba); patrones específicos de `layout-gastos` siguen sin portar

Nota: esta sección describe el estado de `reconciliacion_por_origen.py`
(el método por-documento antiguo, 37%). El método vigente
(`baseline_universal.py`, agregado + llave granular) ya llega a **89.4%**
para este origen sin portar nada de lo de abajo — ver la sección "Gasto_Registro
— llave granular corregida" más arriba para el detalle completo del fix
2026-09-09. Lo de abajo sigue siendo relevante como candidato para explicar
parte de los 74 pendientes restantes.

El proyecto `layout-gastos` (fuera de este repo, en
`trivasa-context/docs/proyectos/layout-gastos/`) ya documentó y validó
varios patrones específicos de este origen que **no están portados
todavía** a `reconciliacion_por_origen.py` ni a `baseline_universal.py`:

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
