# Ajuste v0.4.2 — cuenta "Gastos a cuenta de costo estandar" faltante del lado Abono

Origen: el usuario mostró en MPRO la póliza real del folio `05-0164271` (el último caso
sin explicación que quedaba tras el fix de reversiones) — **sí tenía póliza completa**
(3 líneas, sumas iguales $108,302.59), pero nuestro reporte mostraba Cargo=Abono=0 para
ese folio.

## Causa

El filtro de Abono solo incluía `Pd_Tipo=2` cuando la cuenta era raíz `'F'` (Gastos) o,
como fallback, cuando no tenía grupo asignado y empezaba con `'6'` (ver
`docs/12_hito_v0_2.md`). La cuenta real de este folio, `2120.010.002.011.002 "Gastos a
cuenta de costo estandar"`, no tiene grupo asignado (root NULL) y empieza con `'2'`, no
`'6'` — quedaba fuera de ambas reglas, aunque es un gasto real (es la familia dual de
costeo estándar: sufijo `.001` = "Provision de costo estandar" -contrapartida/pasivo-,
sufijo `.002` = "Gastos a cuenta de costo estandar" -el gasto real-, ya documentado en
`docs/15`).

## Verificación de alcance antes de aplicar el fix

Se contaron todas las líneas de Abono con raíz NULL y prefijo distinto de `'6'` en
2025+2026: 2,590 líneas / 1,821 folios / $86.8M. Casi todas están **correctamente**
excluidas hoy (préstamos a terceros, arrendamientos Banregio/Bancomer/Caterpillar,
proveedores, cuentas de empleados, fondos fijos) — **solo 2 líneas** ($108,302.59, ambas
del folio `05-0164271`) son "Gastos a cuenta de costo estandar". El fix se acotó
exactamente a esa descripción de cuenta para no arrastrar nada de lo demás.

## Fix

Se agregó un tercer fallback a la regla de Abono en `POLIZA_SQL`: incluir `Pd_Tipo=2`
cuando la cuenta no tiene grupo asignado (root NULL) **y** su descripción contiene
"gastos a cuenta de costo estandar" (sin distinguir mayúsculas). Aplicado en
`layout_gastos_v0_4_1.py` y `layout_gastos_v0_4_2.py` (es un bug de la regla de inclusión
de Abono, no específico de las reversiones).

## Resultado

| Periodo | Discrepancias antes | Discrepancias después |
|---|---|---|
| 2025 completo | 10 (7 redondeo + 3 filas de `05-0164271`) | **7** (solo redondeo) |

**0 discrepancias sin explicación automática en todo 2025** — el 100% de lo que no cuadra
(7 de 18,046 filas, 99.96%) es ruido de redondeo menor a $1.

## Nota sobre cómo se encontró el bug

Al investigar por qué una consulta de diagnóstico daba 0 filas cuando debía dar 2, se
encontró que la consulta usaba `NOT (A OR B)` con `A` comparando contra `NULL`
(`ga.raiz = 'F'` cuando `ga.raiz IS NULL`) — en lógica de tres valores de SQL,
`NULL OR FALSE = NULL` y `NOT NULL = NULL`, no `TRUE`, así que la fila se excluía
silenciosamente. La regla real en producción (`POLIZA_SQL`, sin el `NOT` envolvente)
tiene el mismo problema estructural con `NULL`, que es precisamente la causa original del
bug (las filas de Abono con cuenta sin grupo asignado nunca calificaban con
certeza lógica bajo la regla vieja).
