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

## 16. Gasto_Registro: `Grc_Importe` puede venir duplicado idéntico entre folios/CFDI sin relación — error real de captura, no de método

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
