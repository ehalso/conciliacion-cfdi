# Hito v0.3 — atribución exacta por documento vía centro de costo

Origen del cambio: en v0.2, los folios con 2+ documentos (`Grd_ID`) mostraban Cargo/Abono
solo en el último documento del folio (`cuenta_registro`/`cargo` en `None` para los
demás) — porque `Poliza_Detalle.Pd_Referencia` solo referencia el folio, nunca el
documento específico. El usuario preguntó si agrupar por Centro de Costo (CECO) en vez
de Cuenta Contable resolvería los vacíos.

**Respuesta corregida en el camino**: agrupar por CECO no lo resuelve — el problema no es
qué campo se muestra, sino que ninguno de los dos (cuenta contable, CECO) identifica el
documento por sí solo (ver ejemplo real folio `05-0176298`: 10 documentos de peaje, las
10 líneas de póliza comparten la MISMA cuenta Y el MISMO centro de costo). Pero el
usuario señaló que existe una tabla que desglosa cada `Grd_ID` a nivel CECO, y ahí sí
coinciden los importes contra la póliza — **tenía razón**: `Gasto_Registro_Control`
(`Gr_Folio + Grd_ID + Cc_Cve_Centro_Costo + Grc_Importe`), tabla que v0.1/v0.2 no usaban.

## El hallazgo: emparejamiento posicional exacto

Verificado con datos reales (folio `13-0001279`, 76 líneas; folio `05-0176298`, 10
documentos): dentro de un mismo `(folio, centro_costo)`, las líneas de
`Gasto_Registro_Control` (ordenadas por `Grd_ID`) y las de `Poliza_Detalle` (ordenadas por
`Pd_ID`, que también trae `Pd_Centro_Costo`) coinciden **posición a posición** con
diferencia $0.00 — se generan en el mismo orden en MPRO. Eso da una atribución
`Grd_ID` ↔ línea de póliza exacta, sin adivinar.

Cobertura: 1,615 de 1,620 documentos "normales" de enero 2026 (99.7%) tienen desglose en
`Gasto_Registro_Control`. Del lado de la póliza: 7,714 de 7,973 líneas Pd_Tipo (96.7%,
casi todo el Cargo) traen `Pd_Centro_Costo` poblado; el Abono (`Pd_Tipo=2`) casi nunca lo
trae (212 de 259 líneas sin centro, 82%) — para esas se usa el método de respaldo de v0.2
(atribuir al folio completo / último documento).

## Regla nueva

1. Líneas de `Poliza_Detalle` **con** `Pd_Centro_Costo`: se emparejan con
   `Gasto_Registro_Control` por posición dentro de `(folio, centro_costo)`. Si el conteo
   de líneas no coincide en algún grupo específico (raro), ese grupo cae al método de
   respaldo en vez de forzar un emparejamiento dudoso.
2. Líneas **sin** `Pd_Centro_Costo` (mayormente Abono) y los grupos con conteo desigual:
   método de respaldo de v0.2 — se agregan por folio y se pegan al último documento.

## Validación (enero 2026, corregida para no mezclar niveles)

Primer intento de `validar()` dio un resultado **peor** que v0.2 (83% en `(vacío)`,
diferencias de millones de pesos) — bug: cuando un folio tenía algunos documentos con
atribución exacta y el residual de respaldo en el último, se comparaban por separado
(documento vs. folio) sin que ninguno de los dos viera el total real. Fix: si un folio
tiene **alguna** línea de respaldo, **todo el folio** se valida a nivel folio completo
(igual que v0.2); solo los folios enteramente resueltos por centro de costo se validan
documento por documento.

Resultado final:

| Origen | % comprobación | vs. v0.2 |
|---|---|---|
| `(vacío)` | 99.45% | 99.18% |
| `CONTROL_COMBUSTIBLE` | 100% | 100% |
| `GASTO_RECLASIFICACION` | 100% | 100% |
| `ORDEN_COMPRA` | 100% | 100% |
| `VIAJE` | 100% | 100% |

Quedan **4 discrepancias** (de 1,793 filas aplicables) — exactamente las mismas 3
reclasificaciones manuales de v0.2 (`01-0034998`, `01-0034999`, `05-0181359`, sin cambios
en la decisión: se dejan marcadas) más 1 caso de ruido de redondeo ($0.59). El caso de
redondeo de v0.2 (`01-0035149`, -$0.65) **se resolvió solo** con la atribución exacta.

Totales de Cargo ($30,333,274.96) y Abono ($4,410,411.35) idénticos a v0.2 (mismo universo
de datos, solo mejor atribuido) — pero **1,595 de 1,611 documentos** (99%) ahora tienen
Cargo/Cuenta atribuidos de forma exacta, contra 1,411 en v0.2 (88%). Se eliminó la gran
mayoría de los "None" que mostraba el reporte.

## Columna nueva: `metodo_atribucion`

Visible en el reporte para transparencia: `centro_costo` (atribución exacta),
`folio_completo` (respaldo, folio multi-documento sin cobertura de centro de costo),
`reclasificacion` (mecanismo de `GASTO_RECLASIFICACION`), `sin_join` (CONSUMO_INTERNO /
GASTO_REGISTRO_NOMINA), `sin_poliza` (documento sin ninguna línea de póliza encontrada).
