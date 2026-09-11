# Ajuste final v0.4.2 — reversiones contables reales (Importe negativo)

Origen: el usuario preguntó "si trajéramos solo Abono o solo Cargo, ¿no cuadraría ya
bien?" para los folios de reclasificación manual (`01-0034998`, `01-0034999`,
`05-0181359`). La respuesta es sí — y se encontró **por qué**, generalizándolo a todo
2025 y 2026 en vez de a los 3 folios puntuales.

## El patrón (verificado, no supuesto)

Para estos 3 folios: la póliza trae Cargo **y** Abono, casi iguales entre sí (netean a
~0). El Importe de cabecera viene negativo. Se probó primero excluir el Cargo por
**nombre de cuenta** (`Provision de costo estandar`, `...por pagar`) — pero eso rompía
**59 folios de Importe positivo** que usan esas mismas cuentas legítimamente (costeo
estándar: la expensa se reconoce contra una cuenta "Provision", es normal).

El patrón real no es la cuenta — es la **combinación a nivel folio**: `Importe ≤ -$1`
**y** `|Cargo − Abono| ≤ $1`. Verificado en 71 folios de 2025+2026: en todos, el Abono
por sí solo ya es igual al Importe (con signo). Esto no es coincidencia: es una garantía
de partida doble — una reversión contable real siempre tiene Cargo == Abono == monto
revertido, porque se está deshaciendo una póliza anterior (se revierte el pasivo/provisión
del lado Cargo Y se revierte el gasto del lado Abono, por el mismo monto).

## Fix

Regla final, simplificada a partir de la pregunta del usuario ("¿no sería más simple
decir que si el Importe es negativo, hay que traer su Abono en lugar de su Cargo?"):
cuando `Importe_folio ≤ -$1`, se pone en **0 el Cargo** de ese folio (se deja el Abono,
que es el lado real de Gastos). Resultado: `Cargo − Abono = −Abono ≈ Importe`. Columna
nueva `ajuste_reversion` (booleana) marca qué filas recibieron este ajuste, para
transparencia.

Un primer intento agregó la condición extra `|Cargo − Abono| ≤ $1` (pensando que hacía
falta confirmar que de verdad se cancelaban) — pero se verificó que es innecesaria: de
84 folios con `Importe ≤ -$1` en 2025+2026, la condición extra solo cubría 71; la regla
simple (solo el signo del Importe) cubre 83 de los 84 sin ningún falso positivo, porque
nunca toca folios de Importe positivo.

## Validación

| Periodo | Discrepancias antes | Discrepancias después |
|---|---|---|
| Enero 2026 | 4 (3 reclas + 1 redondeo) | **1** (solo redondeo, $0.59) |
| 2025 completo | 75 (68 reclas + 7 redondeo) | **10** (3 filas de 1 solo folio sin póliza + 7 redondeo) |

Los únicos 3 residuales de "Reclasificación" que quedan son las 3 filas de
`05-0164271` (Importe -$108,302.59 total) — verificado que este folio **no tiene ninguna
línea de póliza en absoluto** (Cargo=Abono=0), así que no hay nada que repartir; se deja
correctamente marcado como una discrepancia real (falta capturar la póliza en MPRO), no
un error del reporte.

## Por qué no se intentó por nombre de cuenta

Se investigó primero filtrar Cargo excluyendo cuentas con "provision" o "por pagar" en la
descripción. Se encontraron 126 folios con esas cuentas en el lado Cargo en todo el
periodo — pero **59 tenían Importe positivo** (folios normales de costeo estándar donde
esa cuenta SÍ es el gasto real). Aplicar la regla por nombre de cuenta habría roto esos
59 folios. La regla final (por combinación Importe+neto a nivel folio) no tiene ese
riesgo porque nunca toca folios de Importe positivo.
