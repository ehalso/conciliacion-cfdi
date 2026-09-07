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

## 10. `raw_sat.cfdi_retencion` SÍ está completo — el hueco está del lado mpro

A diferencia de emitidos, `cfdi_retencion` está bien cargado (2016-12 a
2026-07, mes a mes, sin huecos). El problema es que ninguno de los 15 CFDI
de retención de febrero 2026 (retenciones de ISR por arrendamiento, clave
16, emitidas por Trivasa) aparece en `Comprobante_Digital` de 207, y
tampoco en la tabla dedicada `Constancia_Retencion` de mpro (esa tabla
tiene datos históricos pero ninguno en febrero 2026 — su patrón de meses
con carga, ene/may/sep, no coincide con estos CFDIs mensuales). En 205,
`Comprobante_Digital.Cd_Tabla` sí incluye un valor `CONSTANCIA_RETENCION`,
pero tampoco ahí aparecieron los UUIDs probados. Sigue sin resolverse cuál
es la tabla/proceso correcto en mpro para este tipo de retención — ver
`pendientes.md`.

## 11. 205 vs 207: mismo esquema, distinto avance

Ver el detalle completo en `docs/arquitectura.md` — resumen: 205 va
ligeramente atrás en `Poliza` (menos filas, fecha máxima más vieja) pero
la conciliación por origen corrida contra ambas para febrero 2026 dio
resultados prácticamente idénticos (mismos porcentajes, 2–8 documentos de
diferencia por origen). Confirmado por Esteban: 207 es la fuente de
verdad; 205 se usa temporalmente mientras 207 está en desarrollo.
