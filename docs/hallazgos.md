# Hallazgos y bugs reales

Todo lo que sigue está confirmado con datos en vivo (no es teoría ni
supuesto) — cada punto indica cómo se validó.

## 1. `cfdi:Impuestos` aparece más de una vez en el XML

Cada `Concepto` dentro de un CFDI trae su propio nodo `cfdi:Impuestos`
(vacío, sin totales) además del nodo a nivel `Comprobante` (el que trae
`TotalImpuestosTrasladados`/`TotalImpuestosRetenidos`). Buscar con XPath
recursivo (`.//cfdi:Impuestos`) agarra el primero que encuentra — casi
siempre uno de Concepto, vacío — y da IVA = 0 sistemáticamente.

**Fix** (`src/cfdi_parser.py`): buscar solo como hijo directo del nodo
Comprobante (`comprobante.find("cfdi:Impuestos", ns)`), nunca recursivo.

## 2. El campo `iva` de `raw_sat.cfdi_recibidos` no está neteado

Validado empíricamente (periodo 2026-08): `iva` en el warehouse SAT
equivale a `TotalImpuestosTrasladados` tal cual del XML, **sin restar**
`TotalImpuestosRetenidos`. En CFDIs con retención (ISR/IVA retenido en
servicios), comparar contra un IVA neteado daba una diferencia exacta al
importe retenido. `src/extract_mpro.py` replica el mismo criterio (usa
`total_impuestos_trasladados`, guarda `total_impuestos_retenidos` aparte
en `retenciones_mpro` para no perder la información).

## 3. `Comprobante_Digital.Cd_Documento` no es el folio real

Trae el folio real (`XX-NNNNNNN`, 10 caracteres) **más un sufijo de 4 a 8
caracteres** (identifica el sub-documento/línea dentro del folio) que
`Poliza_Control.Pc_Documento` no lleva. Sin truncar, el join a
`Poliza_Control` no encuentra nada (100% `SIN_POLIZA` en la primera
corrida). Confirmado en los 6 orígenes trabajados, incluyendo los dos
formatos de longitud que usa Gasto_Registro (14 y 18 caracteres — ambos
truncan al mismo folio real de 10).

**Fix**: `documento_real = documento[:10]` antes de cualquier join contra
`Poliza_Control`.

Este bug ya estaba documentado para Gasto_Registro específicamente en el
proyecto `layout-gastos`; aquí se confirmó que generaliza a Compra,
Cuenta_x_Pagar, Cheque, Nota_Credito_Proveedor y Compra_Indirecto.

## 4. Una póliza consolida varios documentos del mismo origen

Después de arreglar el truncado, seguía sin cuadrar nada (0% en Compra).
Causa: `Poliza_Control → Poliza → Poliza_Detalle` unido solo por
`Pl_Folio` trae **todas** las líneas de esa póliza, y una póliza puede
agrupar varios documentos del mismo origen del mismo día. Ejemplo real:
folio de Compra `07-0010712` — el join naive daba cargo = abono =
$2,587,197.95 (una sola póliza con 15+ líneas, de las cuales solo una,
$926,073.00, era de este documento).

**Fix**: agregar `AND Poliza_Detalle.Pd_Referencia = Poliza_Control.Pc_Documento`
a la condición del JOIN — aísla justo las líneas de ese documento. Mismo
método que `layout-gastos` ya usaba para Gasto_Registro, generalizado aquí.

## 5. El cargo aislado por `Pd_Referencia` cuadra contra el SUBTOTAL, no el total

Para Compra: con el fix anterior, el cargo seguía sin cuadrar contra el
total del CFDI — pero sí cuadraba **exacto** contra el subtotal
(ejemplo real: cargo $926,073.00 × 1.16 = $1,074,244.68 = total del CFDI
exacto). El cargo se postea a una cuenta de inventario (`1140.010.006.002`
en el ejemplo) sin IVA; el IVA se registra en otra línea/cuenta que no
lleva la misma referencia.

Validación amplia: de 770 documentos de Compra, 635 (82.5%) cuadran contra
subtotal con tolerancia $1, contra 0% contra total. El mismo patrón se
probó para los demás orígenes con resultado mixto — ver
`resultados_2026-02.md` para el detalle por origen (Cuenta_x_Pagar y
Gasto_Registro mejoran con subtotal; Nota_Credito_Proveedor en realidad
cuadra mejor contra total, no contra subtotal).

## 6. Cheque: los CFDI que liga son mayormente tipo P, con Subtotal=Total=$0

De 663 CFDI ligados a Cheque en febrero 2026, 654 son tipo `P` (Recibo
Electrónico de Pago / REP). Por diseño del SAT, un REP trae
`SubTotal=Total=$0.00` — el monto real de cada pago vive en el nodo
`Complemento de Pagos` (elementos `Pago`/`DoctoRelacionado`), que este
pipeline no parsea (solo lee los campos estándar del Comprobante). Esto
también se confirmó para `Cd_Monto` del lado mpro: también sale $0 para
estos CFDI, así que no hay ningún campo ya extraído contra el cual
comparar el monto del pago vía CFDI.

**Implicación práctica**: Cheque no se puede reconciliar comparando contra
el total/subtotal del CFDI — estructuralmente no tiene sentido. El método
válido (heredado de `poliza-explor`, ya validado por el equipo antes de
este proyecto) es amount-matching directo:
`ABS(Poliza_Detalle.Pd_Importe - Cheque.Ch_Importe) <= 1`, sin pasar por
el CFDI en absoluto. `extract_poliza_cheque()` implementa esto: si
encuentra una póliza así, ya se considera cuadrado.

## 7. Gasto_Registro: un folio puede tener muchas líneas de Cargo por centro de costo

Ejemplo real: folio `01-0035149`, concepto "CUOTAS AL IMSS" — una sola
fila en `Comprobante_Digital` (un solo CFDI), pero **decenas** de líneas
de Cargo en `Poliza_Detalle` con el mismo `Pd_Referencia`, una por centro
de costo, sumando $1.9M contra un subtotal de CFDI de solo $895,904.63 (más
del doble). El `GROUP BY Pd_Referencia` ya suma correctamente todas esas
líneas — el problema no es de agregación, es que el gasto contabilizado
cubre un alcance más amplio (todos los centros de costo de la cuota IMSS
del periodo) que lo que representa un solo CFDI.

Este es el mismo patrón ya resuelto en `layout-gastos` para
`GASTO_REGISTRO_NOMINA` (grano correcto: FOLIO × Centro de Costo ×
Concepto, no FOLIO solo) — **no está aplicado todavía en este repo**, ver
`pendientes.md`.

## 8. Nota_Credito_Proveedor: notas partidas en dos documentos

Ejemplo real: documentos `01-0000786` (cargo=abono=$229,912.00) y
`01-0000787` (cargo=abono=$172,434.00) — ninguno cuadra por separado
contra ningún CFDI, pero sumados dan $402,346.00, exactamente el total de
un CFDI. Apunta a una nota de crédito aplicada en dos partes/aplicaciones
distintas que generan dos documentos de mpro. No se investigó más a
fondo — solo 15 documentos en el periodo, bajo impacto, pero el patrón es
real y hay que tenerlo en cuenta antes de confiar en el cuadre
documento-por-documento de este origen.

## 9. `raw_sat.cfdi_emitidos` tiene un hueco de carga

Confirmado 2026-09-07: la tabla solo tiene cargados septiembre y
noviembre 2025 (13,208 filas, un solo batch cargado el 2026-09-02, XML por
XML vía `archivo_origen`). Nada de octubre/diciembre 2025 ni de 2026.
`raw_sat.cfdi_recibidos`, en cambio, sí está al corriente (enero a
septiembre 2026). No es un problema de este pipeline — es un hueco del
ingest/ELT que corre en `ctunlinux` (Claude Code). Bloquea por completo la
conciliación de emitidos hasta que se complete la carga — ver
`pendientes.md` para el texto exacto que se le pasó a Esteban para pedirlo.

Actualización 2026-09-07 (mismo día): un nuevo batch agregó 2026-01
completo — ver punto 12 y `pendientes.md` para el estado actualizado.

## 10. `raw_sat.cfdi_retencion` SÍ está completo — el hueco estaba del lado mpro (RESUELTO, ver punto 12)

A diferencia de emitidos, `cfdi_retencion` está bien cargado (2016-12 a
2026-07, mes a mes, sin huecos). El problema era que ninguno de los 15 CFDI
de retención de febrero 2026 (retenciones de ISR por arrendamiento, clave
16, emitidas por Trivasa) aparecía en `Comprobante_Digital` de 207, y
tampoco en la tabla dedicada `Constancia_Retencion` de mpro (esa tabla
tiene datos históricos pero ninguno en febrero 2026 — su patrón de meses
con carga, ene/may/sep, no coincide con estos CFDIs mensuales). En 205,
`Comprobante_Digital.Cd_Tabla` sí incluye un valor `CONSTANCIA_RETENCION`,
pero tampoco ahí aparecieron los UUIDs probados en ese momento. **Resuelto
parcialmente el mismo día** probando con enero 2026 (mes con datos) — ver
punto 12 para la cifra real de cobertura (36%, no el 100% que se reportó
primero).

## 11. 205 vs 207: mismo esquema, distinto avance

Ver el detalle completo en `docs/arquitectura.md` — resumen: 205 va
ligeramente atrás en `Poliza` (menos filas, fecha máxima más vieja) pero
la conciliación por origen corrida contra ambas para febrero 2026 dio
resultados prácticamente idénticos (mismos porcentajes, 2–8 documentos de
diferencia por origen). Confirmado por Esteban: 207 es la fuente de
verdad; 205 se usa temporalmente mientras 207 está en desarrollo.

## 12. Retención SÍ mapea a mpro — pero solo para una parte de los CFDI (corregido 2026-09-08)

Confirmado en vivo 2026-09-07 que el mapeo SAT → mpro para retención
**existe y funciona** vía `Comprobante_Digital.Cd_Tabla='CONSTANCIA_RETENCION'`
— eso sigue siendo cierto. Lo que estaba mal en la primera versión de este
hallazgo (2026-09-07) era la cifra de cobertura: se reportó "47 filas para
45 UUIDs, prácticamente 1-a-1" a partir de un query de "duplicados" que en
realidad estaba contando TODOS los UUID con `Cd_Tabla='CONSTANCIA_RETENCION'`
de la historia completa de la tabla, no solo los 45 de enero 2026 — dio la
impresión falsa de cobertura casi total.

**Cifra correcta, re-verificada 2026-09-08** contra los 45 CFDI de
retención de enero 2026: de 45 UUIDs, solo **31 (69%) tienen alguna fila**
en `Comprobante_Digital`, y de esos, solo **16 (36% del total) tienen la
fila `CONSTANCIA_RETENCION`** con el folio y monto reales (los otros 15 de
los 31 solo tienen el stub en `GASTO_REGISTRO` con `Cd_Monto=0`, sin
ninguna fila que traiga el monto real). **14 de 45 (31%) no tienen absolutamente
ninguna fila** en `Comprobante_Digital` bajo ningún `Cd_Tabla`.

Detalle de lo que sí sigue validado para los 16 que sí aparecen:

- **Filtrar por fecha en `Comprobante_Digital` requiere `Cd_Timbre_Fecha`**,
  no `Cd_Fecha` (esa columna no existe en la tabla — confirmado vía
  `INFORMATION_SCHEMA.COLUMNS`). Un filtro por columna inexistente no
  tira error de SQL en este bridge, tira `HTTP 502` genérico — fácil de
  confundir con una caída real del servidor.
- `Cd_Documento` (truncado a 10 caracteres, ej. `01-0000787`) coincide
  1-a-1 con `Constancia_Retencion.Cr_Folio`, y `Cd_Monto` = `Cr_Importe` =
  `monto_total_operacion`/`monto_total_gravado` del CFDI del SAT (no el
  monto retenido — ese vive en `Cr_Importe` menos lo que calcule
  `Constancia_Retencion_Detalle`, no validado a fondo todavía).
- De los que sí tienen `Cd_Tabla='CONSTANCIA_RETENCION'`, todos aparecen
  también con `Cd_Tabla='GASTO_REGISTRO'` y `Cd_Monto=0` — mismo patrón
  "stub en cero" que Cheque/REP (punto 6).

**Pendiente real, sin resolver**: por qué 29 de 45 CFDI de retención de
enero (64%) no llegan a `Constancia_Retencion` — ¿un proceso distinto los
registra en otro lado de mpro, o de verdad no se están registrando
contablemente? Antes de invertir más tiempo explorando a ciegas, vale la
pena la pregunta directa a alguien de Trivasa que conozca el proceso.
Para el 36% que sí mapea, sigue pendiente además llegar de `Cd_Documento`/
`Cr_Folio` hasta `Poliza_Control` para el cargo/abono real — bloqueado por
la caída de esa tabla específica (ver punto 13).

## 13. `Poliza_Control` cayó (HTTP 502) en ambos targets, 2026-09-07

Confirmado en vivo: `SELECT TOP 3 ... FROM Poliza_Control` sin ningún
filtro falla con `HTTP 502` de forma persistente (probado 5+ veces con
reintentos y esperas, en 205 y en 207), mientras que en el mismo momento
`Comprobante_Digital`, `Poliza`, `Poliza_Detalle`, `Poliza_Configuracion` y
`Cheque` responden con normalidad, y `SELECT 1` contra los tres targets
del bridge (`postgres_dw`, `mssql_205`, `mssql_207`) funciona bien. Es una
falla aislada a esa tabla específica (lock, reindexado, o efecto
colateral de la carga de ingest que corrió el mismo día) — no algo
resoluble desde este repo. Bloquea todo trabajo de nivel 3 (documento →
póliza) tanto para emitidos como para el resto de retención, no solo
para lo nuevo — recibidos ya construido no se ve afectado porque no
vuelve a consultar esta tabla en cada corrida salvo que se re-ejecute.

## 14. Baseline universal: sumar el cargo de TODOS los orígenes por CFDI, no elegir "el" documento

Pedido explícito de Esteban 2026-09-09: en vez de conciliar un origen a la
vez exigiendo que UN documento cuadre exacto (`baseline_conciliacion.py`),
sumar el cargo de TODOS los documentos con los que un CFDI aparece
etiquetado en `Comprobante_Digital` — sin importar el origen — y comparar
esa suma contra el Subtotal. Implementado en `baseline_universal.py`.
Resultado en vivo, CFDI recibidos feb-2026: **1,351/1,500 (90.1%)** del
universo con valor monetario real ya cuadra en agregado (cifra final,
tras el fix de Gasto_Registro del punto 15 — la primera corrida, con el
Gasto_Registro por-origen viejo, daba 87.0%). Las combinaciones cruzadas
de orígenes (COMPRA+COMPRA_INDIRECTO, GASTO_REGISTRO+CUENTA_X_PAGAR,
COMPRA+FACTURA) cuadran al 100% — confirma que el problema real de fondo
era exigir 1 documento = 1 CFDI, no un hueco de datos. Es un chequeo de UN
SOLO LADO (cargo=subtotal); no exige que el abono/pago también cuadre.
Detalle completo, tabla por combinación de orígenes y motivación completa
en `pendientes.md`.

## 15. Gasto_Registro: la llave granular correcta es `(Gr_Folio, Grd_ID)`, sumando TODOS los `Grc_ID` — no `(Gr_Folio, Grd_ID, Grc_ID)`

Corrección 2026-09-09, pedida explícitamente por Esteban ("corrige el
parser y la lógica de folio granular"). `Comprobante_Digital.Cd_Documento`
para `Cd_Tabla='GASTO_REGISTRO'` trae el folio (10 caracteres) más un
sufijo — la hipótesis inicial (y también la de una sesión hermana en
`trivasa-context`, ver `calidad-de-datos.md` sección "Comprobante_Digital
— cuatro gotchas") es que ese sufijo puede ser de 4 caracteres (`Grd_ID`,
formato de 14 en total) o de 8 (`Grd_ID`+`Grc_ID`, formato de 18) según el
caso. **Lo que se verificó en vivo aquí, y que no estaba confirmado en
ningún lado antes**: los 4 caracteres extra del formato de 18 **no
distinguen nada** — nunca hay más de un `Cd_Documento` completo distinto
por `(Gr_Folio, Grd_ID)` (los primeros 14 caracteres), sin importar cuántas
líneas de `Grc_ID` (prorrateo por centro de costo) tenga
`Gasto_Registro_Control` para esa combinación.

El cargo real que corresponde a un CFDI es la **suma de TODOS los
`Grc_Importe`** de `Gasto_Registro_Control` para `(Gr_Folio, Grd_ID)` —
verificado exacto contra el cargo realmente posteado en `Poliza_Detalle`
(vía `Pd_Referencia = Gr_Folio`, ya sabiendo — ver punto 4 y el hallazgo
paralelo de `layout-gastos` — que `Poliza_Detalle` no guarda `Grd_ID`
explícito, solo el folio). Dos ejemplos confirmados exactos:

```
folio 01-0027091, Grd_ID 0001, 4 líneas de Grc_ID (prorrateo CeCo)
  suma Grc_Importe = $2,746.64  ==  cargo Poliza_Detalle = $2,746.64

folio 01-0035252, 2 Grd_ID distintos (2 CFDI en el mismo folio)
  Grd_ID 0001: Grc_Importe = $2,168.05  -> 1a línea de Poliza_Detalle
  Grd_ID 0002: Grc_Importe = $1,518.69  -> 2a línea de Poliza_Detalle
```

**Vuelta en falso, útil de documentar**: la primera implementación de este
fix asumió la llave de 18 caracteres SIEMPRE (folio+Grd_ID+Grc_ID) y
buscaba el `Grc_Importe` de ESE renglón exacto — el % de conciliación
**bajó** en vez de subir (87.0% → 82.7-83.3%), porque 433 de 1,211
documentos GASTO_REGISTRO de feb-2026 traen el formato corto (14
caracteres) y quedaban sin cargo encontrado. Corregido usando
`documento[:14]` como llave y sumando todos los `Grc_ID`. Ver
`extract_gasto_registro.py`.

Nota de alcance: `layout-gastos` (proyecto hermano en `trivasa-context`,
ver `layout-gastos-ceco-cont-1.md`) ya sabía que "no existe llave real
entre `Grc_ID` y `Poliza_Detalle`" y por eso usa *rank-pairing* a nivel
`(FOLIO, CECO, TIPO_GASTO)` en vez de aislar líneas individuales. Este
hallazgo no resuelve esa ambigüedad del lado de `Poliza_Detalle` — la
evita, calculando el cargo directo desde `Gasto_Registro_Control` (que sí
tiene llave limpia hacia el CFDI) sin necesitar volver a `Poliza_Detalle`
línea por línea. Para el propósito de este repo (cuadrar cargo contra
CFDI) es suficiente; no es una respuesta al problema más general que
enfrenta `layout-gastos`.

**De regalo**: se confirmó también que las pólizas canceladas (`CA`) no
afectan este método (`Gasto_Registro_Control` no tiene `Pl_Folio` ni
`Es_Cve_Estado`, es independiente de qué póliza materializó el motor), y
que `extract_poliza_por_origen.py` ya filtraba `Es_Cve_Estado <> 'CA'`
desde antes para el resto de los orígenes (COMPRA, CUENTA_X_PAGAR,
NOTA_CREDITO_PROVEEDOR, COMPRA_INDIRECTO, CHEQUE) — no era necesario
corregir nada ahí.

## 16. ~~Gasto_Registro: `Grc_Importe` duplicado entre folios~~ — **CORREGIDO 2026-09-10: era conversión de moneda, no un error**

> ⚠️ **Este punto estaba mal.** Lo que sigue es el texto original, conservado
> porque la corrección enseña algo: el importe idéntico de BRIGGS EQUIPMENT
> **no** era captura duplicada, era el mismo importe en **dólares** convertido
> con el mismo tipo de cambio. Los 5 CFDI son de **USD 2,615.00** cada uno y
> `Grd_Tipo_Cambio` = 17.2315 en todos: 2,615.00 × 17.2315 = **45,060.3725**.
> El "importe repetido" se repite porque el importe en dólares y el tipo de
> cambio se repiten — es la misma renta mensual de montacargas facturada por
> unidad. Los 8 CFDI de BRIGGS de feb-2026 ya cuadran exacto con el fix de
> moneda (ver punto 20). **Lección**: antes de reportar un error de captura del
> cliente, descartar que el CFDI esté en moneda extranjera y que no haya doble
> conteo propio (ver punto 24). El "patrón simétrico del lado del abono" que
> describe el texto de abajo tampoco era duplicación: son la cuenta de la divisa
> y su cuenta complementaria en pesos, que suman el pasivo correcto — **ver punto
> 26**.
>
> Texto original, incorrecto:

Caso confirmado 2026-09-09, proveedor BRIGGS EQUIPMENT (renta de
montacargas): 5 CFDI independientes de $2,615.00 cada uno (unidades
U-1269 a U-1272 y U-1275, folios `05-0178783/784/786/831/832`, todos
capturados el 2026-02-11) tienen en `Gasto_Registro_Control.Grc_Importe`
**exactamente el mismo importe, $45,060.3725** — pese a ser folios,
proveedores-CFDI y centros de costo (`Cc_Cve_Centro_Costo`: `000455` x3,
`000227`, `000055`) distintos. Confirmado que el problema está en el dato
de origen, no en cómo se generó la póliza: el renglón de la configuración
que genera el cargo (`0450` / renglón `0010`, "CARGO A GASTOS MINA") es
`SUM(ABS(Gasto_Registro_Control.Grc_Importe))` — simplemente suma lo que
ya esté en la tabla, y $45,060.3725 ya estaba mal ahí ANTES de generarse
la póliza (que además la materializó fielmente: `Poliza_Detalle` trae ese
mismo importe repetido en los 5 renglones).

Patrón simétrico del lado del abono, misma póliza (`0000478228`): las
referencias `A370838`-`A370845` (que sí coinciden con `Grd_Referencia` de
estos folios) aparecen **dos veces** cada una en `Poliza_Detalle` — una
vez con su importe correcto (~$3,033.40 / ~$1,740.00, coincide con
`Grd_Precio_Neto_Importe`) y otra vez con un importe mucho mayor
($49,236.63 o $28,242.81) repetido idéntico entre varias referencias
distintas.

Hipótesis (no confirmada, no hace falta para el propósito de este repo):
error de captura por lote — al registrar varias facturas del mismo
proveedor el mismo día, algún campo de importe se copió/pegó igual en
varios renglones en vez de capturarse individualmente. **No es algo que
la reconciliación pueda "arreglar" prorrateando** — el importe correcto
por folio SÍ existe en `Gasto_Registro_Documento.Grd_Precio_Descontado_Importe`
($2,615.00 en los 5 casos), pero el importe REALMENTE contabilizado en
póliza es el erróneo. Vale la pena reportarlo a quien mantiene la captura
de Gasto_Registro en mpro — es un hallazgo de calidad de dato del cliente,
no un bug de este pipeline.

## 17. CFDI de arrendamiento financiero: Gasto_Registro solo captura el interés, no el capital

Confirmado 2026-09-09, proveedor START BANREGIO SOFOM (arrendadora). El
CFDI `070FE9DB-1FEE-4CD8-893F-7FEC13C70DAD` (mensualidad 23/48 de un
arrendamiento financiero, Subtotal $60,044.90) solo tiene un documento
relacionado en mpro: GASTO_REGISTRO folio `01-0035117`, con comentario
*"INTERES ARRENDAMIENTO FINANCIERO 23/48"* y cargo de solo **$14,540.09**
(el interés). La diferencia, ~$45,504.81 (la porción de capital de la
mensualidad), no pasa por Gasto_Registro — presumiblemente reduce un
pasivo por arrendamiento financiero en otro módulo/póliza que este
pipeline no rastrea todavía. Al menos 2 CFDI de este mismo proveedor
confirmados con el patrón (`070FE9DB...` y `C3D0C835...`, ambos con
diferencia idéntica de -$45,504.81) — candidato fuerte para explicar más
casos entre los pendientes de Gasto_Registro de proveedores financieros
(START BANREGIO, CATERPILLAR CREDITO también aparece con una diferencia
grande similar en los pendientes, sin confirmar todavía si es el mismo
patrón).

**Confirmado 2026-09-09 (segunda ronda)**: CATERPILLAR CREDITO **sí** es
el mismo patrón. CFDI `25C19AC9-0CA1-48E8-9D23-69D670FCCF7A` (Subtotal
$322,530.44, pendiente por -$190,127.59) liga al folio `01-0035173`,
comentario *"ARRENDAMIENTO FINANCIERO U1238 Y U1232 10/60"* — dos
`Grd_ID` (0001/0002, uno por unidad), cada uno capturando solo la porción
de interés. Confirma que el patrón de arrendamiento financiero no es
exclusivo de START BANREGIO — cualquier proveedor de leasing en los
pendientes de Gasto_Registro es candidato.

## 18. `implocal:ImpuestosLocales` — complemento de impuestos locales que mpro suma al "Importe", no al "Impuesto"

Confirmado 2026-09-09. El complemento SAT `implocal:ImpuestosLocales`
(namespace `http://www.sat.gob.mx/implocal`) declara impuestos
estatales/municipales (ej. ISH — Impuesto Sobre Hospedaje) que el SAT NO
incluye en `cfdi:Impuestos/@TotalImpuestosTrasladados` a nivel
Comprobante. mpro, al capturar el gasto en Gasto_Registro, **suma este
traslado local dentro del "Importe"/base del gasto, no del impuesto** —
confirmado exacto en dos CFDI: SubTotal($2,074.69) + local($93.36) =
Importe mpro($2,168.05); SubTotal($1,453.29) + local($65.40) = Importe
mpro($1,518.69). El valor resultante no aparece literal en ningún lado del
XML — hay que sumar dos campos separados para reproducirlo. Confirmado
también que afecta un porcentaje bajo pero no despreciable: 14 de 759
CFDI de GASTO_REGISTRO en feb-2026 (1.8%) traen este complemento con
traslado > $0. Implementado en `cfdi_parser.py`
(`CfdiAmounts.impuestos_locales_trasladados/retenidos`, propiedad
`base_mpro`) y aplicado como ajuste al Subtotal en
`baseline_universal.py` solo para CFDI de GASTO_REGISTRO.

## 19. CFDI de impuesto estatal (ISN) repartido entre MUCHOS folios de Gasto_Registro — uno por sucursal — pero solo UNO queda etiquetado en `Comprobante_Digital`

Confirmado 2026-09-09, retomando el drill-down de Gasto_Registro por
mayor impacto en $. El pendiente más grande del periodo (CFDI
`A95D6C54-7570-4F5C-8FCF-E1BBD02CFEA1`, emisor `SHA840512SX1` —
"SECRETARIA DE ADMINISTRACION Y FINANZAS", entidad de gobierno estatal;
Subtotal $397,161.00, cargo agregado encontrado solo $131,430.58,
diferencia -$265,730.42) resultó ser un CFDI de **ISN (Impuesto Sobre
Nómina)**, que Trivasa captura **por sucursal**, un folio de
`Gasto_Registro` por sucursal, cada uno con su propio `Gr_Comentario`
("ISN SOBRE NOMINA TRIVASA SA DE CV"). El único documento etiquetado en
`Comprobante_Digital` para este UUID es `05-017698000010001` (folio
`05-0176980`, sucursal `0005`) — ese folio por sí solo captura
$131,430.58, exactamente el `cargo_agregado` que reportaba el pendiente.

El resto del CFDI **sí existe en mpro**, solo que repartido en otros
folios de `Gasto_Registro` con el mismo comentario, uno por sucursal, sin
ninguna fila propia en `Comprobante_Digital` que los ligue a este UUID.
Sumando los folios activos (`Es_Cve_Estado='AP'`, cada sucursal tiene
también un folio cancelado `CA` gemelo — mismo patrón de par
cancelada/activa ya documentado) con el mismo comentario y periodo:

```
01-0034984 (suc 0001)   $43,853.16
02-0000842 (suc 0002)    $1,764.43
05-0176980 (suc 0005)  $131,430.58   <- el único etiquetado en Comprobante_Digital
07-0082454 (suc 0007)   $83,409.86
08-0001590 (suc 0008)    $3,514.26
09-0001803 (suc 0009)    $4,686.63
11-0005584 (suc 0011)    $1,343.36
13-0001278 (suc 0013)    $1,355.54
14-0000418 (suc 0014)    $1,946.36
18-0001302 (suc 0018)    $3,342.39
22-0015214 (suc 0022)   $27,221.85
23-0006905 (suc 0023)   $17,770.74
25-0000013 (suc 0025)   $75,521.68
---------------------------------
SUMA                   $397,160.85   ==  Subtotal CFDI $397,161.00 (diferencia $0.15, redondeo)
```

Match exacto. Este es un patrón **inverso** al de "folio agrupa varios
CFDI" (punto 15/pendientes.md): aquí es **un CFDI el que se reparte entre
varios folios**, y el proceso de adjuntar XML en mpro solo alcanza a
etiquetar uno de ellos en `Comprobante_Digital` — probablemente porque
adjunta el XML una sola vez, a la primera captura, sin replicarlo a las
demás sucursales que comparten la misma factura de gobierno. No es un
bug de este pipeline ni de la fórmula de póliza — es una limitación del
proceso de captura/adjuntado de XML en mpro para facturas de gobierno que
cubren varias sucursales a la vez.

**No es fácil de generalizar como fix automático**: la única señal para
agrupar los folios hermanos es texto libre en `Gr_Comentario` (aquí
"ISN SOBRE NOMINA TRIVASA SA DE CV", fecha y sucursal) — no hay una
referencia estructurada que los ligue entre sí ni con el CFDI. Candidato
razonable para heurística futura: mismo `Gr_Comentario` (normalizado) +
misma `Gr_Fecha` + `Es_Cve_Estado='AP'`, pero no se implementó — riesgo de
falsos positivos con otros conceptos de "provisión" que usan el mismo
patrón de comentario a una escala mucho mayor (probado con un caso
similar de "PREVISION SOCIAL" mensual, descartado como explicación de
otro pendiente — suma cientos de miles a millones de pesos, no
comparable en magnitud al CFDI que se intentaba explicar; no se confirmó
que sea el mismo mecanismo).


## 20. El CFDI viene en su moneda original y la póliza en MXN — hay que convertir con el tipo de cambio del documento

Confirmado 2026-09-09/10. `raw_sat.cfdi_recibidos.subtotal`/`.total` están en
la **moneda original del CFDI** (mismo criterio que
`Comprobante_Digital.Cd_Monto`, ya documentado en `trivasa-context`), mientras
que `Poliza_Detalle` y `Gasto_Registro_Control` postean **siempre en MXN**.
Comparar cargo contra subtotal sin convertir da una diferencia que es
exactamente el tipo de cambio: **43 de los 149 pendientes de feb-2026 eran CFDI
en USD**, todos con ratio cargo/subtotal entre 15 y 20.

El factor correcto es el del **propio documento de mpro**, no uno de mercado ni
el `Cd_Tipo_Cambio` de `Comprobante_Digital` (que en varios casos difiere del
que se usó para postear: CADECO 17.2698 real vs 17.6900 en
`Comprobante_Digital`). Cada tabla de origen trae su par
`Mn_Cve_Moneda` / `Xx_Tipo_Cambio`:

| Origen | Tabla | Tipo de cambio |
|---|---|---|
| COMPRA | `Compra_Encabezado` | `Co_Tipo_Cambio` |
| COMPRA_INDIRECTO | `Compra_Indirecto` | `Ci_Tipo_Cambio` |
| CUENTA_X_PAGAR | `Cuenta_X_Pagar` | `Cxp_Tipo_Cambio` |
| NOTA_CREDITO_PROVEEDOR | `Nota_Credito_Proveedor` | `Nc_Tipo_Cambio` |
| CHEQUE | `Cheque` | `Ch_Tipo_Cambio` (⚠️ sin columna de moneda) |
| FACTURA | `Factura_Encabezado` | `Fc_Tipo_Cambio` |
| GASTO_REGISTRO | `Gasto_Registro_Documento` | `Grd_Tipo_Cambio` |

`Cheque` es el único que **no tiene** `Mn_Cve_Moneda`; pedirla devuelve
`HTTP 502` genérico, no un error de SQL. Implementado en
`src/extract_moneda.py`.

## 21. El `Descuento` del CFDI no existe en `raw_sat` — y mpro postea el importe NETO

Confirmado 2026-09-10, el hallazgo que más pendientes explicó (33 de feb-2026).
`raw_sat.cfdi_recibidos` **no tiene columna de descuento**: su `subtotal` es el
bruto, antes del atributo `Descuento` del nodo `cfdi:Comprobante`. mpro captura
y postea el importe neto, así que todo CFDI con descuento quedaba pendiente
aunque estuviera perfectamente contabilizado:

```
AT&T COMUNICACIONES   12,472.32 - 12,120.64 =    351.68 = cargo real
AGENCIA COMERCIALIZ. 118,205.26 - 70,215.11 = 47,990.15 = cargo real
G3M                    4,449.96 -  1,557.49 =  2,892.47 = cargo real
AUTO PARTES Y MAS     12,901.65 -  1,290.17 = 11,611.48 = cargo real
```

Hay que leerlo del XML (`Cd_XML`). `cfdi_parser.py` ya lo extraía; lo que
faltaba era restarlo en `base_mpro`.

## 22. El IEPS trasladado se suma a la BASE del gasto, igual que los impuestos locales

Confirmado 2026-09-10 (12 pendientes de feb-2026). El IEPS (clave `003` del
catálogo del SAT: combustibles, refrescos, botanas, telecomunicaciones) no es
acreditable, así que mpro lo manda al gasto — exactamente el mismo tratamiento
que el complemento `implocal` del punto 18:

```
CADENA COMERCIAL OXXO   100.11 + IEPS 3.63 = 103.74 = Grc_Importe
SUPER SAN FRANCISCO     143.73 + IEPS 4.37 = 148.10 = Grc_Importe
GO MART YUC             109.26 + IEPS 8.74 = 118.00 = Grc_Importe
TELMEX          (528.55 - 65.00 desc) + 9.73 = 473.28 = Grc_Importe
```

⚠️ `raw_sat.cfdi_recibidos.iva` **no sirve** para detectarlo: trae
`TotalImpuestosTrasladados`, que mezcla IVA con IEPS, y en varios casos ni
siquiera coincide con la suma de los traslados (OXXO: `iva` = 8.76 pero
`TotalImpuestosTrasladados` = 12.39). Hay que leer los `cfdi:Traslado` con
`Impuesto="003"` del nodo `Impuestos` de nivel Comprobante.

Con esto, la base comparable queda:

```
base = (SubTotal - Descuento + IEPS + impuestos_locales) x tipo_de_cambio_del_documento
```

## 23. Las cuentas de orden se identifican por la RAÍZ de la cuenta, no por el texto de la configuración

Confirmado 2026-09-10 (14 pendientes, 13 de ellos con ratio exactamente 2.0).
El filtro `Pc_Descripcion NOT LIKE '%CUENTAS DE ORDEN%'` deja pasar tres de las
cinco redacciones que usa el catálogo — `(CTS ORDEN)`, `( CUENTA DE ORDEN)`,
`(CUENT ORDEN)` — y por eso CUENTA_X_PAGAR (config `0360`) y
NOTA_CREDITO_PROVEEDOR (`0235`/`0352`) contaban el cargo **dos veces**.

En `Cuenta_Contable`, las cuentas de orden son exactamente las de **raíz de 5
dígitos**: `10100`–`10600`, grupo `E.*` (`Cc_Acumula` = `E.A` Valores Ajenos,
`E.B` Valores Contingentes, `E.C` De Control). Las cuentas reales tienen raíz
de 4 dígitos (`1110`, `1140`, `2110`, `6100`…). El filtro robusto:

```sql
AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '10[1-6]00%'
```

## 24. Los dos formatos de `Cd_Documento` duplican el cargo si se deduplica por el documento completo

Confirmado 2026-09-10. Siete CFDI de feb-2026 mostraban exactamente **2× su
importe**; parecían capturados dos veces en mpro y eran **doble conteo
nuestro**. El mismo `(Gr_Folio, Grd_ID)` tiene dos filas en
`Comprobante_Digital`, una en formato de 14 caracteres y otra en el de 18, con
el mismo UUID y el mismo monto — el gotcha que `layout-gastos` ya documentó en
`trivasa-context`:

```
05-01784220001      (14)  05E5388C-…  9,373.96
05-017842200010001  (18)  05E5388C-…  9,373.96   <- la misma captura
```

`baseline_universal.py` deduplicaba por el `documento` completo, que no colapsa
los dos formatos. Corregido deduplicando por `documento[:14]`, la llave
granular real (punto 15).

## 25. Vías de cuadre legítimas más allá de "cargo = base del CFDI"

Confirmado 2026-09-10 revisando folio por folio los 149 pendientes. Un CFDI
puede estar perfectamente contabilizado sin que el cargo iguale su base,
porque el tratamiento contable correcto es otro. Las nueve vías validadas
(implementadas en `baseline_universal.py`, cada una etiquetada en la columna
"Vía de cuadre" del reporte):

1. **Nota de crédito = total.** Reduce el adeudo con IVA incluido. Dos
   configuraciones vivas: `0451` (DEVOLUCION) deja el importe del lado del
   cargo a proveedores; `0350` (BONIFICACION) solo deja abonos con referencia
   (inventario + IVA) y su cargo va sin referencia, así que el cargo aislado
   sale en cero y hay que usar el abono.
2. **IVA no acreditable**: mpro manda el IVA al gasto (gasolina, abarrotes) y
   el importe contabilizado es el total del CFDI.
3. **Capturado en el documento**: `Grd_Precio_Neto_Importe` = base del CFDI
   pero el gasto distribuido es menor porque mpro aplicó un descuento propio
   (cuotas IMSS: la parte obrera no es gasto de la empresa).
4. **Arrendamiento financiero**: solo el interés pasa por Gasto_Registro; el
   capital amortiza el pasivo `2130.*`. La póliza de pago junta las dos piezas
   y **abona al banco el total del CFDI**. Se sigue la cadena
   `Grd_Referencia`/`Cxp_Referencia` → `Poliza_Detalle.Pd_Referencia`. Si el
   CFDI ampara varias unidades hay una póliza de pago por unidad y hay que
   sumarlas (CATERPILLAR: 211,890.64 + 158,917.98 = 370,808.62).
5. **Gasto repartido entre folios hermanos**: una factura capturada como varios
   folios, uno por sucursal, con solo uno etiquetado (ISN, punto 19).
6. **El CFDI cubre el folio completo**: todos los renglones del folio son del
   CFDI pero solo uno quedó etiquetado.
7. **Capturado en un renglón del folio**: el folio mezcla conceptos y uno de
   sus renglones es exactamente este CFDI.
8. **Cheque que liquida varias facturas**: el importe del cheque = suma de los
   CFDI etiquetados (excluyendo el REP que ampara el cheque completo).
9. **Capturado en el documento de origen**: `Xx_Precio_Neto_Importe` del
   documento = base o total, aunque el cargo no se pueda aislar en la póliza.

**Criterio descartado por permisivo**: `Pago_Cxp_Comprobante` liga pagos con el
UUID del CFDI y `Pcc_Monto` trae su total — cubre **1,407 de 1,500 CFDI
(93.8%)** del universo de febrero. Aceptarlo como vía de cuadre habría
"conciliado" casi todo de un plumazo, incluidos los CFDI mal capturados (un
CFDI contabilizado dos veces también tiene su pago correcto). Queda como
herramienta de investigación, no de cuadre.

Resultado con las nueve vías, H1 2026 completo: **9,511 / 9,572 (99.36%)**.
Detalle completo, evidencia por caso y clasificación del residual en
[`investigacion_pendientes.md`](investigacion_pendientes.md).

## 26. Pasivo en moneda extranjera: mpro lo parte en dos cuentas (la de la divisa y una "complementaria" en pesos) que SUMAN la valuación en MXN

Confirmado 2026-09-10 al verificar la retractación del punto 16. La póliza
`0000478228` (BRIGGS EQUIPMENT) parecía tener cada referencia de proveedor
**duplicada** en `Poliza_Detalle`: una vez con un importe chico y otra con uno
mucho mayor. No es duplicación — son **cuentas distintas**, y las dos filas
suman el pasivo correcto en pesos:

| Cuenta | Descripción | `A370839` | `A370838` |
|---|---|---:|---:|
| `2110.001.001.002` | Proveedor Nacional Dollar | 3,033.40 | 1,740.00 |
| `2110.001.001.004` | Proveedor Nacional **complementaria** Dollar | 49,236.63 | 28,242.81 |
| | **suma = importe USD × 17.2315** | **52,270.03** | **29,982.81** |

Es decir: la cuenta base guarda el importe **tal cual en la divisa** (USD
3,033.40 = 2,615.00 × 1.16) y la "complementaria" guarda la **diferencia en
pesos**, de modo que la suma de ambas es la valuación en MXN al tipo de cambio
del documento. El catálogo tiene **9 cuentas** con este rol — no es un caso
aislado:

```
1110.003.001.008.003  Banco Monex Cta.20252455 (Usd Cta Complementaria)
1110.003.001.008.005  Banco Monex Cta.20252455 (Eur Cta Complementaria)
2110.001.001.004      Proveedor Nacional complementaria Dollar
2110.001.001.005      Proveedor Nacional complementaria Euro
2110.001.002.003      Proveedores Extranjero Complementaria Dollar
2110.001.002.004      Proveedores Extranjero Complementaria Euro
2130.001.005.001.002  SITSA Metso Num Econ 445 complementaria Dollar
2230.001.005.001.002  SITSA Metso Num Econ 445 complementaria Dollar
2230.001.005.001.004  SITSA NUM ECON COMPLEMENTARIA DOLLAR
```

**Consecuencia para cualquier lectura del abono**: al conciliar el lado del
pago de un CFDI en moneda extranjera hay que **sumar la cuenta y su
complementaria**. Tomar solo la base da el importe en divisa (no en pesos);
tomar solo la complementaria da un número sin significado propio; y tratar los
dos renglones como duplicados —el error del punto 16 original— borra la mitad
del pasivo. Esto todavía **no** está implementado en el baseline: el chequeo
actual es de un solo lado (cargo), así que no lo toca; hay que incorporarlo
cuando se extienda el doble chequeo cargo+abono a los orígenes en USD/EUR.

## 27. Migración de la bridge HTTP a conexión directa a BD, y primer reporte Streamlit

2026-09-09. Esta sesión, que hasta ahora no tenía ruta de red hacia
la LAN de Trivasa (de ahí la bridge HTTP documentada en `docs/arquitectura.md`
y usada por `src/bridge_client.py` desde el inicio del proyecto), pasó a
correr con acceso directo — confirmado con una conexión TCP real a los tres
targets (`192.168.117.205:1433`, `192.168.117.207:1433`,
`192.168.117.14:5433`, esta última con `ping` mostrando ~98ms de latencia vía
VPN).

`src/bridge_client.py` se reescribió para conectar directo por SQLAlchemy
(`psycopg2` para `postgres_dw`, `pymssql` para `mssql_205`/`mssql_207`) en vez
de HTTP, **conservando el mismo contrato** (`run_query(target, sql) ->
{"columns", "rows", "row_count", "truncated"}`) — los ~10 extractores que lo
importan no cambiaron una sola línea. Se agregó un guard de solo lectura del
lado cliente (`_guard_readonly`: un único `SELECT`/`WITH`, sin palabras clave
de escritura), espejo del `sql_guard.py` que antes vivía del lado servidor de
la bridge. Credenciales: `.env` local (gitignored, ver `.env.example`) con
`PG_USER`/`PG_PASSWORD` y `MSSQL_205_USER`/`PASSWORD`/`MSSQL_207_USER`/
`PASSWORD` — las de SQL Server no estaban en Infisical (solo las de Postgres,
proyecto `Trivasa`, rol `ealcocer_ro`), Esteban las dio directo en el chat y
se guardaron tanto en el `.env` local como en Infisical (mismo proyecto,
claves `MSSQL_205_USER/PASSWORD`, `MSSQL_207_USER/PASSWORD`) para no perderlas.

**Validado, no solo asumido**: correr `baseline_universal.py --periodo
2026-02` completo contra la conexión directa dio exactamente el mismo
resultado ya documentado (1,492/1,500 CFDI, 99.5%) que contra la bridge — el
cambio de transporte no alteró ningún número. El guard de solo lectura se
probó rechazando un `DELETE` y un `SELECT 1; DROP TABLE foo` (multi-statement).

De la misma sesión: primer reporte Streamlit del proyecto,
`streamlit_app_conciliacion.py` — envuelve `baseline_universal.calcular()` en
una UI con selector de periodo(s), filtros, KPIs y descarga a Excel, sin
duplicar la lógica de conciliación. Validado con `streamlit.testing.v1.AppTest`
contra datos en vivo (multi-periodo, filtro por origen, búsqueda de texto,
las tres sin excepción) antes de considerarlo listo para `streamlit run`.

## 28. Primer intento de nivel 3 para EMITIDOS (`baseline_universal_emitido.py`) — FACTURA no aísla por documento, NOTA_CREDITO sí

2026-09-10. Arranque del trabajo de emitidos pedido explícitamente por
Esteban ("extiende baseline universal", ver `PROGRESS.md` punto 4 de la
sesión anterior). Exploración directa a `mssql_205` (sin pasar por ninguna
API — conexión SQL directa vía `bridge_client.py`, igual que el resto del
repo). Censo de origen ya conocido (`docs/pendientes.md`): FACTURA, NOTA_CREDITO,
COMPROBANTE_PAGO/TRASLADO (estos dos últimos, complementos sin valor, mismo
tratamiento que recibidos).

**`Comprobante_Digital.Cd_Tabla='FACTURA'` no tiene módulo homónimo en
`Poliza_Control`** — no existe `Pc_Tabla='FACTURA'`; se contabiliza bajo
`Pc_Tabla='VENTA'`. `Cd_Tabla='NOTA_CREDITO'` sí es homónimo directo
(`Pc_Tabla='NOTA_CREDITO'` = `Nc_Folio`) — verificado con fecha (`Poliza.
Pl_Fecha` = `Nota_Credito.Nc_Fecha` = `Cd_Timbre_Fecha`, mismo día, en 8/8 de
una muestra de enero 2026) y **confiable**.

**Corrección a media sesión, casi documentada mal**: el primer intento probó
`Poliza_Control WHERE Pc_Documento = '<Fc_Folio>'` y sí devolvió filas
`Pc_Tabla='VENTA'` — parecía confirmar que el folio era el mismo valor
directamente. Es un **falso positivo por reciclaje de folio**: la serie
`XX-NNNNNNN` de `Venta_Encabezado.Vn_Folio` es independiente de la de
`Factura_Encabezado.Fc_Folio`, y ambas reciclan el mismo rango de números en
años distintos. Se detectó cruzando `Poliza.Pl_Fecha` contra `Factura_
Encabezado.Fc_Fecha`: para una muestra de 8 FACTURA de enero 2026, TODOS los
matches por texto directo traían pólizas de 2018-2025, sin relación con la
fecha real de la factura (ejemplo: `Cd_Documento='02-0019715'`,
`Cd_Timbre_Fecha=2026-01-02`, pero el "match" en `Poliza_Control` traía
`Pl_Fecha=2020-01-11`). **Lección para cualquier exploración futura de
folios de mpro: validar SIEMPRE la fecha del match, no solo el string** —
recibidos no tuvo este problema (o no se detectó), pero emitidos sí, al
menos para el módulo VENTA.

La cadena real, verificada con fecha: `Factura_Encabezado.Fc_Folio` (=
`Cd_Documento`, siempre 10 caracteres exactos, sin sufijo — a diferencia de
recibidos no hace falta truncar) -> `Venta_Encabezado.Fc_Folio` (una factura
puede consolidar VARIAS ventas/tickets — hasta 382 `Vn_Folio` distintos para
una sola factura en enero 2026; el caso típico, 93.5% de 2,201 facturas con
al menos un match, es 1 factura = 1 venta) -> `Vn_Folio` =
`Poliza_Control.Pc_Documento` bajo `Pc_Tabla='VENTA'`, exigiendo además
`ABS(DATEDIFF(day, Poliza.Pl_Fecha, Venta_Encabezado.Vn_Fecha)) <= 3` (el
mismo reciclaje de folio aplica un nivel más abajo, a `Vn_Folio`).
Implementado en `extract_poliza_factura()` (`src/extract_poliza_por_origen.py`).

**VENTA postea DOS pólizas separadas por documento** (censo real, enero
2026, `Poliza_Configuracion.Pc_Descripcion`):

- `VENTAS 2019 EN ADELANTE` — la de INGRESO: Cargo a Clientes (`1120.xxx`) =
  Total del CFDI (con IVA); Abono a Ventas (`4100.xxx`, ≈ subtotal) + IVA
  Trasladado (`2160.xxx`, ≈ iva). Es la que importa para conciliar.
- `COSTO DE VENTA 2018 EN ADELANTE` — la de COSTO: Cargo a Costo de Venta
  (`5100.xxx`) = Abono a Inventario (`1140.xxx`) — el costo del producto
  vendido, sin relación con el importe fiscal del CFDI. Hay que excluirla
  (`extract_poliza_por_origen()` ahora acepta `excluir_descripcion` para
  esto) para no sumar costo+ingreso en un solo número sin sentido.

**Hallazgo grave para el método**: de las dos, la que SÍ aísla el documento
por `Pd_Referencia` de forma consistente es la de COSTO DE VENTA — la de
INGRESO casi nunca trae `Pd_Referencia` al documento individual (verificado
caso por caso, ej. `Vn_Folio='05-0271923'`: la póliza de costo trae la línea
con `Pd_Referencia` exacto, la póliza de ingreso activa de la misma fecha
tiene CERO líneas con esa referencia). Aparenta postearse consolidada por
sucursal/día sin trazabilidad a documento individual, para la inmensa
mayoría de las ventas. **Resultado real, enero 2026, con la cadena
corregida**: de 2,191 FACTURA, solo 19 documentos encuentran algún cargo/abono
aislado (excluyendo costo de venta), y de esos solo 13 cuadran contra el
Total — **0.6% de cobertura**. NOTA_CREDITO, en cambio, con el match directo
confiable, arrancó en 33.5% con el mismo patrón dual cargo/abono vs total
usado para `NOTA_CREDITO_PROVEEDOR` en recibidos — pero **subió a 99.5%**
tras el fix descrito en el punto 29 (abajo): el 33.5% inicial no era ruido
real, era el mismo problema del punto 3 (dos pólizas mezcladas bajo el mismo
`Pd_Referencia`) aplicado a NOTA_CREDITO.

**No resuelto — candidato principal para la siguiente sesión**: no se
encontró ninguna columna/tabla que ligue la póliza de INGRESO de VENTA a su
documento de forma confiable. Se probaron sin éxito: `Pd_Referencia` =
`Fc_Folio` (folio reciclado, descartado), `Pd_Referencia` = `Vn_Folio` (casi
vacío), `Poliza_Detalle_Comprobante` (nivel 2, liga UUID directo — SÍ
encuentra huella para 2,377/6,500 UUIDs de enero, pero el `suma_abono`
agregado mezcla la cuenta de Clientes (`1120.xxx`) con la de Ventas
(`4100.xxx`) para el 87% de esos casos — sugiere que el anexo también etiqueta
la póliza de COBRANZA/pago del cliente con el mismo UUID del CFDI de venta,
no solo la de reconocimiento de ingreso; sin separar ambas pólizas por
`Pl_Configuracion`, el nivel 2 tampoco sirve para cuadrar contra el Total —
0% de cuadre directo probado). Antes de seguir explorando a ciegas, vale la
pena la misma recomendación que para retención (`docs/pendientes.md`):
preguntar directo a alguien de Trivasa cómo se referencia el documento en la
póliza de ingreso de VENTA — el patrón de "consolidado por sucursal/día sin
referencia" es consistente con un negocio de alto volumen (POS/mostrador),
donde quizás la conciliación real vive a otro nivel (agregado por
sucursal/día contra la suma de CFDI del mismo corte), no por documento
individual.

## 29. NOTA_CREDITO (emitidos): separar por cuenta contable sube el cuadre de 33.5% a 99.5%

2026-09-10, misma sesión que el punto 28. Protocolo de diagnóstico estándar
(ver skill `trivasa-comprobacion`): aislar los pendientes en su propio
conjunto y buscar patrones antes de investigar caso por caso. El primer
intento de NOTA_CREDITO (sumar TODO el `Cargo`/`Abono` por `Pd_Referencia`,
igual que el método genérico de `extract_poliza_por_origen`) daba 33.5%
(63/188) — pero los pendientes mostraban un patrón clarísimo al calcular
`monto_agregado / total`: un cluster limpio en **0.862** (= 1/1.16, el factor
del IVA — es decir, `monto_agregado` caía EXACTO en el subtotal, no el
total) y otro cluster disperso entre **1.2 y 1.65** (con valores idénticos
repetidos entre UUIDs *distintos* — señal de que se estaba sumando algo
ajeno al CFDI, no ruido de redondeo).

**Censo real por configuración** (`Poliza_Configuracion.Pc_Descripcion`,
enero 2026, `Pd_Tipo=1` agrupado por raíz de cuenta):

| Config | Cargo `4200.xxx` | Cargo `2140.xxx` | Cargo `2160.xxx` | Abono `5100.xxx` | Abono `2140.xxx` |
|---|---:|---:|---:|---:|---:|
| BONIFICACION (22 docs) | $15,251.71 | — | — | — | — |
| DEVOL C/REF (98-102 docs) | $2,033,891.11 | $1,296,132.74 | — | $1,296,132.74 | — |
| DEVOL S/REF (4-7 docs) | $23,482.26 | $15,117.55 | — | $15,117.55 | — |
| DIRECTA (64 docs) | — | $1,864,123.13 | $298,259.45 | — | $2,162,383.18 |

Drill-down de un folio real (`05-0013517`, config DEVOL C/REF, CFDI
subtotal=10,344.96, total=12,000.15): `Cargo 4200.001.001.001 = 10,344.96`
(exacto = subtotal) + `Cargo 2140.001.005 = 4,326.24` (sin relación con el
IVA de este CFDI, 1,655.19) + `Abono 5100.001.001.002 = 4,326.24` (misma
cifra que el segundo cargo — reversión de costo de venta por la devolución
física de mercancía, autobalanceada, cero relación con el importe fiscal).
El método genérico sumaba los dos Cargos (10,344.96+4,326.24=14,671.20) —
de ahí el cluster de ratios dispersos (1.2-1.65: la proporción entre "ruido
de costo" e "importe real" varía por documento, por eso no era un factor
constante).

**Fix**: separar el `Cargo` por cuenta al extraer — `cargo_4200` (cuenta
`4200%`, Devoluciones sobre Ventas) vs `cargo_resto` (todo lo demás).
Comparar `cargo_4200` contra el **Subtotal** (cubre BONIFICACION/DEVOL
C-S REF) y `cargo_resto` contra el **Total** (cubre DIRECTA, que nunca usa
la cuenta 4200 y por eso no se contamina). Implementado en
`extract_poliza_nota_credito()` (`src/extract_poliza_por_origen.py`).
Drill-down de DIRECTA confirmó el patrón limpio, sin necesidad de fix (5/5
folios de muestra: `Cargo 2140 (=subtotal) + Cargo 2160 (=iva) = Abono 2140
(sub-cuenta distinta) = Total`, exacto al centavo).

**Resultado**: NOTA_CREDITO pasa de 33.5% a **99.5% (187/188)**. El único
pendiente residual (`9ED9C67A-...`) es una BONIFICACION donde la línea de
devolución se capturó por error en la cuenta `8200` en vez de `4200` — un
caso aislado de mala captura (n=1), no un patrón — se deja como pendiente
real, no se fuerza una regla para un solo caso (mismo criterio que otros
"errores de captura reales" ya documentados en este repo, ej. BRIGGS
EQUIPMENT punto 16).

## 30. Conciliación de emitidos y retenciones — proyecto hermano portado y validado en vivo (100% documento↔CFDI, 29 retenciones faltantes en el ERP)

2026-09-10, misma sesión. Esteban le pasó a otra sesión de Claude Code
("cowork") la documentación de un proyecto hermano ya maduro,
`~/proyectos/conciliacion-master/conciliacion-emitidos` (metodología propia,
no la de este repo — ver su `docs/metodologia.md`/`esquema-datos.md`, no
duplicados aquí). Esa sesión de cowork lo adaptó en su propio sandbox, pero
el commit quedó local (push bloqueado por la restricción de proxy de sesión,
ya documentada en `PROGRESS.md` — el fix conocido es el MCP de GitHub, no
`git push` crudo) y no se pudo recuperar directo — Esteban rescató a mano el
`.md` de resumen que esa sesión había producido.

**Hallazgo metodológico central, que faltaba en este repo**: del lado
emitido, **el CFDI se genera DESDE el documento de mpro** (al revés que
recibidos, donde el CFDI llega de fuera y mpro lo captura). Por eso la
relación CFDI↔documento es **1:1 estricta**, nunca N:M, y comparar el CFDI
contra el documento que lo originó (no contra la póliza contable) es la
validación correcta y más fundamental — no es circular. Esto es justo la
pregunta que `baseline_universal_emitido.py` (nivel 3, vía póliza) no
contesta para FACTURA, y por una razón distinta (ver punto 28): son dos
preguntas legítimas y complementarias, no la misma.

En vez de confiar en los números rescatados sin más, se re-implementó la
metodología completa **en este repo**, con `bridge_client` (conexión SQL
directa, ya el patrón de este repo desde el punto 27) — dos scripts nuevos:

- **`conciliacion_emitidos_documento.py`** (equivalente al reporte 01 del
  proyecto original): factura/nota de crédito/constancia de retención/gasto-
  retención vs su documento fuente en mpro.
- **`cruce_sat_retenciones.py`** (equivalente al reporte 04): cruce
  independiente contra `raw_sat.cfdi_retencion` — detecta un CFDI timbrado
  que el ERP nunca registró (invisible para el primero, por construcción).

**Aceleración real, no solo copiada del proyecto original**: ningún XML se
parsea en este puerto. FACTURA/NOTA_CREDITO/CONSTANCIA_RETENCION usan
`Comprobante_Digital.Cd_Monto` directo (ya es el importe comparable — el
proyecto original lo midió, aquí se reconfirmó en la corrida). GASTO_REGISTRO
con retención (`Cd_Monto=0` por diseño del SAT) usa
`raw_sat.cfdi_retencion.monto_total_operacion` — columna ya parseada desde
la ingesta (mejora de `consulta-xmls` del 2026-09-10, la misma sesión que
agregó `descuento`/`ieps_trasladado`/`impuestos_locales_*` a
`cfdi_recibidos`/`cfdi_emitidos`, ver `trivasa-context/docs/proyectos/
conciliacion-cfdi/PROGRESS.md`) — en vez de bajar y parsear `Cd_XML`.
`raw_sat.cfdi_retencion` tiene cobertura histórica completa (2016-2026), así
que esta aceleración no le cuesta cobertura a ningún periodo.

**Resultado, corrido en vivo contra `mssql_205`, H1 2026 — coincide EXACTO
con lo rescatado de la sesión de cowork**:

| Periodo | Universo | Conciliables (sin cancelados) | Concilian | % |
|---|---:|---:|---:|---:|
| 2026-01 | 2,479 | 2,429 | 2,429 | 100.00% |
| 2026-02 | 2,240 | 2,209 | 2,209 | 100.00% |
| 2026-03 | 2,505 | 2,450 | 2,450 | 100.00% |
| 2026-04 | 2,529 | 2,486 | 2,486 | 100.00% |
| 2026-05 | 2,450 | 2,410 | 2,410 | 100.00% |
| 2026-06 | 2,624 | 2,570 | 2,570 | 100.00% |
| **H1** | **14,827** | **14,554** | **14,554** | **100.00%** |

Y el cruce contra el SAT (`cruce_sat_retenciones.py --periodos 2026-01,...,
2026-06`), también exacto contra lo rescatado:

| Periodo | Timbradas (SAT) | En el ERP | Faltantes | Monto de operación | ISR faltante |
|---|---:|---:|---:|---:|---:|
| 2026-01 | 45 | 31 | 14 | $282,291.65 | $56,458.35 |
| 2026-02 | 15 | 0 | 15 | $254,305.39 | $50,861.10 |
| 2026-03..06 | 76 | 76 | 0 | — | — |
| **H1** | **136** | **107** | **29** | **$536,597.04** | **$107,319.45** |

**Lectura**: del lado emitido, el importe **no es el problema** (100% por
construcción, confirmado). El problema real de negocio son **29 constancias
de retención de intereses, timbradas ante el SAT y nunca registradas en el
ERP** ($536,597.04, $107,319.45 de ISR) — dos lotes (22 de enero, 26 de
febrero), mismo mecanismo, mismo tipo de retención (`CveRetenc 16`,
intereses a prestamistas), acreedores casi todos repetidos. No se repite en
marzo-junio. Ver `docs/pendientes.md` para la recomendación de siguiente
paso (llevarlo a Contabilidad, y correr el mismo cruce sobre meses
posteriores a junio cuando estén disponibles).

**Pendiente, no portado esta sesión** (documentado en el proyecto original,
sección "Qué falta"): el reporte 02/03 de cobranza (REP) — parcialidades
cobradas sin timbrar y REP timbrados por duplicado. El proyecto original ya
lo tiene medido (96.18% de facturas con cobranza conciliada, enero 2026) —
portarlo con el mismo patrón es el siguiente paso natural de este frente.
**Nota 2026-09-10**: esta migración se descubrió en paralelo, por dos
sesiones distintas trabajando el mismo día/día siguiente — ambas
coincidieron en el mismo hallazgo (conexión directa disponible) por
caminos separados. Ver `docs/arquitectura.md` para el estado final,
unificado, de esta transición (bridge HTTP documentada ahí como fallback
histórico, ya no como el camino primario).

## 31. Retención: el XML de mpro NO es un CFDI normal — y el hueco de cobertura es estacional (ene/may/sep), no aleatorio

**Corrección 2026-09-10 (ver punto 29): la lectura "estacional (ene/may/sep),
no aleatorio" de este punto mezclaba dos conceptos distintos de retención sin
darse cuenta.** El patrón trimestral SÍ es real, pero solo aplica al grupo de
`cve_retenc=14` (arrendamiento/honorarios) — el grupo recurrente de 15
CFDI/mes (`cve_retenc=16`, intereses a prestamista) **nunca** usa
`CONSTANCIA_RETENCION`, en ningún mes, así que no tiene sentido hablar de
"estacionalidad" para ese grupo. Sección conservada tal cual se escribió esa
noche; ver punto 29 para el diagnóstico correcto y completo.

Arranque del frente de retención (2026-09-09/10). Dos hallazgos, uno de
método y uno de negocio:

**El `Cd_XML` de una fila `CONSTANCIA_RETENCION` es un "Comprobante de
Retenciones e Información de Pagos"** (root `retenciones:Retenciones`,
namespace `.../esquemas/retencionpago/2`), un schema totalmente distinto al
de un CFDI normal — sin los atributos `SubTotal`/`Total`/
`TipoDeComprobante` que `cfdi_parser.parse_cfdi` busca. **`parse_cfdi` no
lo rechaza**: como no encuentra el nodo `Comprobante` cae de vuelta al
root (pensado para tolerar el caso normal en que el root ya ES el
Comprobante) y los atributos que busca simplemente no existen ahí —
regresa `subtotal=0`/`total=0` en silencio en vez de lanzar `ValueError`.
Por eso `extract_mpro_por_uuids`/`parse_cfdi` (el camino que usan
recibido/emitido) **no sirve para retención**. En su lugar, la columna
nativa `Cd_Monto` de `Comprobante_Digital` ya trae el importe correcto sin
parsear nada — confirmado exacto contra `monto_total_operacion` del SAT en
2 UUID de enero 2026 (51,574.00 y 20,000.00 exactos). Implementado en
`src/extract_retencion.py` / `retencion_reconciliation.py` (nuevos,
nivel 1: existencia + cuadre de `monto_total_operacion`, sin trazar
todavía hasta `Poliza_Control`).

**El hueco de cobertura reportado en el punto 12 (36%, solo enero 2026) no
es representativo del semestre — es estacional.** Corriendo el nuevo
script para los 6 meses de H1 2026:

| Periodo | Total SAT | Conciliado | Stub Gasto_Registro ($0) | Sin ninguna fila |
|---|---:|---:|---:|---:|
| 2026-01 | 45 | 16 ($812,237.00) | 15 ($254,305.39) | 14 ($282,291.65) |
| 2026-02 | 15 | 0 | 0 | 15 ($254,305.39) |
| 2026-03 | 15 | 0 | 15 ($254,305.39) | 0 |
| 2026-04 | 15 | 0 | 15 ($254,305.39) | 0 |
| 2026-05 | 31 | 16 ($992,799.00) | 15 ($254,305.39) | 0 |
| 2026-06 | 15 | 0 | 15 ($254,305.39) | 0 |
| **H1** | **136** | **32 (23.5%)** | **75** | **29** |

Dos patrones separados, no uno:

- **Un grupo recurrente de 15 CFDI/mes, siempre por el mismo monto total
  exacto ($254,305.39)** — casi seguro una renta fija mensual con 15
  arrendadores. Este grupo **nunca** llega a `CONSTANCIA_RETENCION` en
  ningún mes del semestre, ni siquiera en enero/mayo — solo alterna entre
  "stub en `GASTO_REGISTRO` con `Cd_Monto=0`" (mar/abr/may/jun) y "ninguna
  fila en absoluto" (feb). Candidato fuerte a ser el pendiente real,
  estructural, de retención — vale la pena la misma pregunta directa a
  Trivasa que ya sugería `PROGRESS.md`.
- **Un grupo adicional, solo en enero (30 CFDI) y mayo (16 CFDI)**, que
  coincide exactamente con el patrón ya documentado en el punto 10 de que
  la tabla `Constancia_Retencion` de mpro solo carga datos en
  **ene/may/sep** (confirmado ahí para 2026, dato histórico). De este
  grupo adicional, en enero 16/30 sí mapean bien (los 14 restantes quedan
  `SIN_MAPEO_MPRO`) y en mayo los 16 mapean 100%. Confirma que la carga de
  `Constancia_Retencion`/`Comprobante_Digital` para retención es
  **trimestral por diseño**, no un hueco aleatorio del 64% — el % real de
  cualquier mes individual depende de si cae en un mes de carga o no.

**Pendiente**: (1) preguntar a Trivasa por qué el grupo recurrente de 15
nunca llega a `Constancia_Retencion`; (2) para julio-septiembre (fuera del
rango H1 vigente, ver nota de alcance temporal), septiembre debería ser el
próximo mes de carga trimestral — útil para confirmar el patrón con un
tercer punto de datos; (3) nivel 3 (trazar `folio_constancia` hasta
`Poliza_Control` para el cargo/abono real) sigue bloqueado por lo mismo que
emitidos — no se ha escrito el extractor todavía (ahora si desbloqueado
por la vuelta de `Poliza_Control`, ver punto 13).

## 32. Retención: dos conceptos distintos (`cve_retenc` 14 vs 16), y dos mecanismos reales — no uno — detrás de un CFDI huérfano

Diagnóstico completo 2026-09-10, corrigiendo el punto 28, hecho con acceso
**directo** a las bases (ver nota de acceso al final) en vez del bridge —
más rápido para el volumen de queries exploratorias que hicieron falta.

**Hay dos tipos de retención de ISR completamente distintos mezclados bajo
`raw_sat.cfdi_retencion`, confirmados por tasa de retención y por
`Gasto_Registro.Gr_Comentario`:**

| `cve_retenc` | Tasa (`retenido/gravado`) | Concepto real | Frecuencia | Camino de conciliación |
|---|---:|---|---|---|
| `14` | 10% exacto | Arrendamiento/honorarios | Cada ~4 meses (visto: emitido ene-2026 cubriendo sep-dic 2025; emitido may-2026 cubriendo may-ago 2026 — `Cr_Fecha_Inicial`/`Cr_Fecha_Final` de `Constancia_Retencion` lo confirman) | `Comprobante_Digital.Cd_Tabla='CONSTANCIA_RETENCION'`, **100%** cuando se busca en el mes correcto |
| `16` | 20% exacto | Intereses a prestamista/inversionista (`Gr_Comentario` literal: `INTERES PRESTAMISTA <NOMBRE> <MES> <AÑO>`) | Mensual, ~15 CFDI/mes (mismo RFC puede repetir por varios contratos/proveedores-código) | `Comprobante_Digital.Cd_Tabla='GASTO_REGISTRO'` (stub `Cd_Monto=0`, patrón ya conocido) — **`CONSTANCIA_RETENCION` NUNCA aparece para este tipo, en ningún mes de H1 2026** |

El punto 28 trataba el "hueco" de `cve=16` como si fuera el mismo fenómeno
estacional que `cve=14` (carga trimestral). Es un error de lectura: `cve=14`
de verdad solo se emite cada 4 meses (no hay hueco, no le tocaba); `cve=16`
se emite cada mes y **nunca** pasa por `CONSTANCIA_RETENCION` — su universo
de conciliación es enteramente distinto (`Gasto_Registro`, no
`Constancia_Retencion`).

### El gasto de `cve=16` SÍ está bien capturado — el problema es solo el link

Verificado en vivo, folio por folio, para los 15 CFDI de febrero 2026 (el
único mes de H1 con 0% de link en `Comprobante_Digital` para este grupo):
sumando `Gasto_Registro_Documento.Grd_Precio_Descontado_Importe` de los 15
proveedores correspondientes (mismo RFC receptor del CFDI → `Proveedor.Pv_R_F_C`
→ `Gasto_Registro_Documento.Pv_Cve_Proveedor`, mismo mes), el total da
**exacto $254,305.39** — el mismo monto, al centavo, que los 15 CFDI del
SAT. Referencias correlativas (`Grd_Referencia` `B1430`-`B1444`), mismo
comentario `INTERES PRESTAMISTA FEBRERO 2026`, capturadas el mismo día
(2026-02-05). El dinero está bien contabilizado; lo que falta es la
etiqueta digital.

### Mecanismo 1 — omisión pura (febrero 2026)

Los 15 CFDI de febrero (timbrados 26-feb) tienen **cero filas** en
`Comprobante_Digital`, ni siquiera el stub en `$0`. No es una caída general
del proceso de etiquetado: ese mismo día se etiquetaron 72 filas
`GASTO_REGISTRO` de otros folios (y 463 filas en total, de todos los
orígenes). Comparado contra el resto de H1 (marzo/abril/mayo etiquetan el
mismo día; junio 4 días después; enero unos días después), febrero es la
única anomalía del semestre — parece un paso puntual que alguien se saltó
para este lote específico, no un proceso roto.

### Mecanismo 2 — CFDI sustituido sin re-ligar (enero 2026)

Enero trae 29 CFDI de `cve=16` en vez de los 15 recurrentes — a primera
vista parecía un "duplicado" (mismos RFC, mismos montos, timbrados 22-ene y
26-ene). **No lo es.** Bajando el XML real de uno de los "huérfanos"
(UUID `5608781C-B297-47BB-B241-845A9916CFE7`, timbrado 22-ene):

```xml
<retenciones:Periodo Ejercicio="2025" MesFin="11" MesIni="11"/>
...
<retenciones:CfdiRetenRelacionados TipoRelacion="04" UUID="95df3fd5-79f6-453d-9c68-3e59a9600d6c"/>
```

Es la retención de **noviembre 2025**, timbrada tarde (2 meses después), y
`TipoRelacion="04"` (sustitución de una retención previa) apunta al CFDI
original que reemplaza. Ese UUID original (`95DF3FD5-...`):

- **No está en `raw_sat.cfdi_retencion`** — ya no es válido ante el SAT.
- **SÍ está en `Comprobante_Digital`**, ligado al mismo folio de gasto
  (`01-0033848`, "INTERES PRESTAMISTA... NOVIEMBRE 2025"), etiquetado en
  diciembre 2025.

Es decir: el CFDI original se emitió y se ligó bien en su momento; después
se **canceló y se sustituyó** por uno nuevo (probablemente una corrección),
pero el link contable **nunca se actualizó al UUID nuevo** — se quedó
apuntando al viejo. El otro CFDI "huérfano" de enero (`FA01CC3A`, 26-ene) es
un CFDI normal de enero 2026, sin relación con nada — el que sí quedó
ligado. **Antes de tratar un CFDI de retención huérfano como "gasto no
encontrado", hay que revisar `CfdiRetenRelacionados`/`TipoRelacion` en el
XML — puede que el gasto ya esté conciliado bajo el UUID que este CFDI
sustituyó.**

### Nota de acceso: bases y XML crudos, directo (sin bridge)

Confirmado 2026-09-10 que, desde una sesión con red al segmento
`192.168.117.0/24` (VPN mesh), se puede conectar **directo** a las bases —
sin pasar por la bridge API de `ctunlinux` — con `psycopg2` (`192.168.117.14:5433`,
postgres_dw) y `pymssql`/`pyodbc` (`192.168.117.205`/`.207:1433`,
mssql_205/207). Credenciales vía Infisical (proyecto `secret-management`,
`workspaceId 2aefdbd1-389c-4fd0-bdb8-a5621af8aac1`) o el `.env` local del
repo. Mucho más rápido para exploración iterativa que el bridge (sin
límite de 502 en queries de tabla completa, sin relanzar el token cada
vez). El XML crudo de retención se navega vía SMB directo
(`smbclient //192.168.117.211/SincronizarXml`, credenciales
`SAMBA_SINCRONIZARXML_*` del mismo proyecto Infisical, env `prod`) —
`TRI970922TL2/XML RETENCIONES/{año}/{año}_{mes}/{ACCIONISTAS|INVERSIONISTAS}/`.
**Un CFDI que sustituye un periodo anterior se archiva bajo la carpeta del
periodo ORIGINAL, no la del mes en que se timbró** (el ejemplo de arriba,
timbrado enero 2026, vive en `2025/11 Noviembre 2025/INVERSIONISTAS/`) — usar
siempre el nombre exacto de `raw_sat.cfdi_retencion.archivo_origen` para
localizar el archivo, no adivinar la carpeta por fecha de timbrado.
Documentado también en `trivasa-context`
(`docs/schema/calidad-de-datos.md`, `docs/proyectos/consulta-xmls/index.md`)
para que el resto del ecosistema se beneficie.

**Pendiente**: (1) construir el matcheo por RFC+proveedor+mes+monto contra
`Gasto_Registro_Documento` como *fallback* — solo cuando `Comprobante_Digital`
no tenga ninguna fila para el UUID — para recuperar casos tipo "mecanismo 1"
sin depender del link; (2) para casos tipo "mecanismo 2", seguir la cadena
`CfdiRetenRelacionados` cuando el UUID directo no aparezca, en vez de
asumir que no hay gasto; (3) confirmar si el mecanismo 2 (sustitución sin
re-ligar) explica también los "sin constancia ligada" de `cve=14` que
reportó el punto 12 (residual de `layout-gastos`, ver
`trivasa-context/docs/schema/calidad-de-datos.md`).
