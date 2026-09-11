# Hito v0.4 — reparto proporcional + salvaguarda de cuadre por documento

Origen del cambio: el usuario revisó en MPRO (drill-down real: "Origen de la Póliza" /
"Detalle de Póliza" / "Factura de gastos por partida", folio `01-0034739`) y pidió
minimizar el uso de `folio_completo` (el respaldo de v0.3) "a menos que sea sumamente
necesario para el cuadre".

## Hallazgo: la póliza a veces combina documentos idénticos en una sola línea

Folio `01-0034739` (9 documentos de renta de equipo): dos de sus documentos (Grd `0004` y
`0005`, ambos $42,767.65, mismo centro de costo `000501`) generan **una sola línea** de
póliza de $85,535.30 (la suma de los dos). Eso rompía el emparejamiento posicional 1 a 1
de v0.3 (2 documentos vs. 1 línea de póliza → conteo desigual → todo caía a
`folio_completo`).

Verificado a nivel de todo enero 2026: de 6,867 grupos `(folio, centro_costo)` con datos
en ambos lados, 6,540 tienen conteo igual (método v0.3) y **327 (4.8%) tienen conteo
distinto pero datos en ambos lados** — candidatos a un reparto mejor que el respaldo total.

## Regla nueva: reparto proporcional

Cuando el conteo no coincide para un `(folio, centro_costo)` pero ambos lados tienen
datos, el total de la línea de póliza se reparte entre los documentos de
`Gasto_Registro_Control` de ese grupo, en proporción a `Grc_Importe` de cada uno. Sigue
siendo una atribución exacta a nivel de grupo (la suma da exacto), solo que el reparto
interno entre documentos es proporcional en vez de posicional. Nuevo método:
`centro_costo_proporcional`.

`folio_completo` (respaldo real) queda solo para: líneas de póliza sin
`Pd_Centro_Costo` en absoluto (mayormente Abono), o centros de costo que no aparecen del
todo en `Gasto_Registro_Control` para ese folio.

## Salvaguarda: verificar el cuadre por documento antes de confiar en el reparto

Al aplicar el reparto proporcional a folios MUY grandes (ej. `01-0035004`, depreciación:
642 líneas de póliza repartidas en 77+ centros de costo para solo 8 documentos), el folio
completo cuadraba exacto ($0.08 de diferencia en $2.43M) pero **3 de sus 8 documentos**
quedaban con diferencias de $1,400 a $5,000 — ruido de redondeo acumulado de repartir un
mismo documento en decenas de grupos independientes, no un error de datos.

Fix: después de atribuir por centro de costo (exacto o proporcional), se verifica
Cargo − Abono == Importe **por documento**. Si algún documento de un folio no cuadra
(tolerancia $0.50), **todo ese folio** se re-enruta a `folio_completo` (se descarta la
atribución fina para ese folio completo y se usa el método de respaldo, ya validado a
nivel folio) — mejor perder precisión por documento en ese caso raro que mostrar un
número ligeramente incorrecto.

## Resultado (enero 2026)

| Versión | Folios en `folio_completo` | De esos, con 2+ documentos (riesgo real de mala atribución) |
|---|---|---|
| v0.2 | 106 (todo folio multi-documento) | 106 |
| v0.3 | 64 | 11 |
| **v0.4** | **5** | **1** (el de depreciación, genuinamente necesario) |

Validación por origen (igual o mejor que v0.3): `(vacío)` 99.47%, `CONTROL_COMBUSTIBLE`
100%, `GASTO_RECLASIFICACION` 100%, `ORDEN_COMPRA` 100%, `VIAJE` 100%. Mismas 4
discrepancias de siempre (los 3 casos de reclasificación manual + 1 de redondeo de
$0.59) — nada nuevo, nada oculto.

Totales de Cargo ($30,333,274.96) y Abono ($4,410,411.35) idénticos a v0.2/v0.3 (mismo
universo de datos).

## Nota: columna `origen`

Se confirmó que `origen` (`Gr_Tabla`) sigue presente en el dataframe y en el reporte —
no se perdió en ningún punto del pipeline de v0.2/v0.3/v0.4. Puede que no fuera visible
en pantalla por estar más a la derecha en la tabla (requiere scroll horizontal), o por
estar ordenando la tabla por `cuenta_registro` ascendente (los `None` suben al tope,
dando la impresión de que "nada tiene datos" cuando en realidad son las mismas filas ya
conocidas sin atribución -- `01-0034855` genuinamente sin postear, `01-0035004` con todo
pegado al último documento).

## Actualización — Grc_ID no identifica un documento, identifica una sub-línea

El usuario señaló que `Grc_ID` "es como cada Grd_ID se reparte entre distintos centros
de costo" -- y tenía razón en que no lo estábamos usando bien. `Grc_ID` no distingue
documentos distintos: distingue **sub-líneas dentro del mismo documento y mismo centro
de costo** (ej. folio `01-0035004`, `Grd_ID 0004` tiene **15 `Grc_ID` distintos** solo
en el centro `000027` -- probablemente uno por activo fijo). Contar filas de `Grc_ID`
crudas como si fueran "documentos" inflaba el conteo (`n_grc`) y mandaba a reparto
proporcional grupos que en realidad tenían el MISMO número de documentos que líneas de
`Poliza_Detalle` -- 85 de 127 grupos del folio `01-0035004` caían en este caso.

Fix: `Gasto_Registro_Control` se colapsa a 1 fila por `(folio, centro_costo, Grd_ID)`
(sumando `Grc_Importe`) antes de contar o emparejar. Efecto en todo enero 2026:
`centro_costo_proporcional` bajó de 239 a **18 filas** (la mayoría de los grupos que
antes parecían tener conteo desigual en realidad coincidían exacto una vez agrupados
por documento).

**Esto reveló un límite real del método posicional por orden de creación**: incluso con
conteo igual, el orden de la póliza no siempre corresponde al orden de `Grd_ID`
(confirmado en `01-0034938` y en `01-0035004`).

## Actualización final — emparejar por VALOR, no por orden de creación

El usuario insistió en revisar la relación Mov (Pd_ID) ↔ `Grc_ID` con más cuidado, lo que
llevó a la causa raíz real: dentro de un `(folio, centro_costo)`, la línea de póliza que
corresponde a un documento **no está en la misma posición de creación**, pero **sí tiene
el mismo importe exacto**. Ejemplo verificado (folio `01-0035004`, centro `000103`, 8
documentos / 8 líneas de póliza):

| Documento | Importe | Cuenta contable (por valor) |
|---|---|---|
| `Grd 0001` | $2,287.08 | `...009.001` Edificio y Planta |
| `Grd 0002` | $714.91 | `...009.002` Mob y Eqpo Oficina |
| `Grd 0003` | **$59,495.92** | `...009.005` **Maquinaria y Equipo** (5ª cuenta, no la 3ª) |
| `Grd 0004` | $1,750.44 | `...009.003` Equipo de Computo |
| `Grd 0005` | $4,692.41 | `...009.004` Equipo de Transporte |
| `Grd 0006` | $252.90 | `...009.006` Equipo de Comunicación |

`Grd_ID 0003` (el documento más grande) no cae en la 3ª línea de póliza por orden de
creación — cae en la 5ª, porque corresponde a la cuenta "Maquinaria y Equipo". El importe
coincide exacto; la posición de inserción no.

**Fix definitivo**: dentro de cada grupo `(folio, centro_costo)` con conteo igual de
documentos, en vez de emparejar por rango de creación (`Pd_ID` vs `Grd_ID`/`Grc_ID`), se
ordenan ambos lados por **importe** y se emparejan por esa posición. Cuando los valores
son distintos, esto es inequívoco; cuando son idénticos (documentos fungibles, ej. varios
peajes iguales), el orden no importa porque cualquier asignación da el mismo resultado.

### Resultado final

| Métrica | v0.4 (posicional) | v0.4 (por valor) |
|---|---|---|
| Folios en `folio_completo` | 6 | **4** |
| De esos, con 2+ documentos | 2 | **0** |

**Cero folios con ambigüedad real de múltiples documentos** en todo enero 2026 — los 4
folios restantes en `folio_completo` son de un solo documento (los 3 casos de
reclasificación manual + 1 de redondeo, ya conocidos y decididos). El folio de
depreciación (`01-0035004`, 642 líneas / 77 centros / 8 documentos) y `01-0034938` ahora
cuadran exacto por documento (diferencias de centavos, ruido de redondeo normal).
