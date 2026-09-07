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
el mismo día** probando con enero 2026 (mes con datos) — ver punto 12.

## 11. 205 vs 207: mismo esquema, distinto avance

Ver el detalle completo en `docs/arquitectura.md` — resumen: 205 va
ligeramente atrás en `Poliza` (menos filas, fecha máxima más vieja) pero
la conciliación por origen corrida contra ambas para febrero 2026 dio
resultados prácticamente idénticos (mismos porcentajes, 2–8 documentos de
diferencia por origen). Confirmado por Esteban: 207 es la fuente de
verdad; 205 se usa temporalmente mientras 207 está en desarrollo.

## 12. Retención SÍ mapea a mpro — vía `Comprobante_Digital.Cd_Tabla='CONSTANCIA_RETENCION'`

Confirmado en vivo 2026-09-07 con los 45 CFDI de retención de enero 2026
(periodo con datos completos, a diferencia de febrero, mes usado en la
investigación anterior y que resultó estar vacío del lado mpro por
casualidad, no por falta de mapeo). Dos hallazgos:

- **Filtrar por fecha en `Comprobante_Digital` requiere `Cd_Timbre_Fecha`**,
  no `Cd_Fecha` (esa columna no existe en la tabla — confirmado vía
  `INFORMATION_SCHEMA.COLUMNS`). Un filtro por columna inexistente no
  tira error de SQL en este bridge, tira `HTTP 502` genérico — fácil de
  confundir con una caída real del servidor.
- Con la fecha correcta, `Cd_RFC_Emisor='TRI970922TL2'` +
  `Cd_Tabla='CONSTANCIA_RETENCION'` trae exactamente los folios de
  retención. `Cd_Documento` (truncado a 10 caracteres, ej.
  `01-0000787`) coincide 1-a-1 con `Constancia_Retencion.Cr_Folio`, y
  `Cd_Monto` = `Cr_Importe` = `monto_total_operacion`/`monto_total_gravado`
  del CFDI del SAT (no el monto retenido — ese vive en
  `Cr_Importe` menos lo que calcule `Constancia_Retencion_Detalle`, no
  validado a fondo todavía).
- Cada UUID de retención aparece **también** una segunda vez en
  `Comprobante_Digital` con `Cd_Tabla='GASTO_REGISTRO'` y `Cd_Monto=0`
  — mismo patrón "stub en cero" que Cheque/REP (punto 6): la retención se
  liga al gasto de renta correspondiente sin duplicar el importe ahí.
- La tabla dedicada `Constancia_Retencion` en sí (no vía
  `Comprobante_Digital`) trae menos folios que CFDI del SAT hay en el
  mes (16 folios en enero 2026 contra 45 CFDI) — no se explica todavía
  por qué; una hipótesis es que solo los que generan CxP
  (`Cr_Genera_Cxp='SI'`) obtienen fila propia, pero no se confirmó con
  suficiente muestra.

Pendiente: llegar de `Cd_Documento`/`Cr_Folio` hasta `Poliza_Control` para
el cargo/abono real — bloqueado por la caída de esa tabla específica (ver
punto 13).

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
