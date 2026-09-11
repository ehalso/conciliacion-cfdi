# Hito v0.2 — v0.1 + Cargo/Abono/Cuenta contable, validado origen por origen

Punto de partida: v0.1 (una fila por `Gasto_Registro_Documento`, todos los orígenes de
`Gr_Tabla` incluidos). v0.2 agrega el cruce contra póliza y cuenta contable **solo para
el importe (subtotal)**, sin impuestos, con reglas distintas por origen — pedido
explícito del usuario, validado uno por uno contra datos reales de enero 2026 antes de
darlo por bueno.

## Reglas por origen

- **`CONSUMO_INTERNO` / `GASTO_REGISTRO_NOMINA`**: Cargo/Abono/Cuenta quedan **vacíos**
  a propósito — no se intenta ningún join de póliza (pedido explícito del usuario).
- **`GASTO_RECLASIFICACION`**: no tiene póliza propia (`Poliza_Control` da 0 filas para
  estos folios). El cargo/abono real vive directo en `Gasto_Registro_Documento`: cada
  folio trae N filas "Reclasificación de gastos (Cargos)" (importe positivo) + las
  mismas N en espejo "(Abonos)" (importe negativo), cada una con su propio
  `Tg_Cve_Tipo_Gasto` → `Tipo_Gasto.Tg_Cuenta_Contable`. **100% de comprobación** (212/212).
- **Todo lo demás** (`(vacío)`, `VIAJE`, `ORDEN_COMPRA`, `CONTROL_COMBUSTIBLE`): join
  normal contra `Poliza_Detalle` vía `Poliza_Control` (`Pd_Referencia = Gr_Folio`).
  `Pd_Tipo=1` es Cargo; `Pd_Tipo=2` solo cuenta como Abono si la cuenta es de grupo raíz
  `'F'` (Gastos) — reclasificación dentro de una póliza real. Esto excluye impuestos
  porque las líneas de IVA no tienen `Pd_Referencia` poblado (agregado a nivel póliza).

## Validación: Cargo − Abono debe igualar el Importe

Resultado final, origen por origen (enero 2026, 1,624 filas donde aplica comprobación):

| Origen | n | % comprobación |
|---|---|---|
| `(vacío)` | 610 | 99.18% (605/610) |
| `CONTROL_COMBUSTIBLE` | 384 | 100.00% |
| `GASTO_RECLASIFICACION` | 212 | 100.00% |
| `ORDEN_COMPRA` | 72 | 100.00% |
| `VIAJE` | 346 | 100.00% |
| `CONSUMO_INTERNO` / `GASTO_REGISTRO_NOMINA` | 2,970 / 2,250 | N/A (sin join, por diseño) |

Solo **5 de 1,624 filas** (0.3%) no cuadran. Se llegó a este resultado corrigiendo dos
bugs reales encontrados en el camino (ver abajo); no se "forzó" el resultado.

## Bug 1 — duplicación de filas por el join de `Comprobante_Digital` (afecta también v0.1)

Primer intento: `(vacío)` 74.71%, `VIAJE` 76.28%, `ORDEN_COMPRA` 91.67% — con
discrepancias enormes (ej. cargo el doble del importe). Causa raíz:

```sql
LEFT JOIN Comprobante_Digital cd
    ON cd.Cd_Tabla = 'GASTO_REGISTRO'
   AND cd.Cd_Documento LIKE gr.Gr_Folio + grd.Grd_ID + '%'
```

El `LIKE ... + '%'` no es único: para el folio `23-0006650` / `Grd_ID 0001` hay **dos**
filas en `Comprobante_Digital` que matchean el mismo prefijo (`23-00066500001` y
`23-000665000010001`, dos UUID distintos), así que el join duplica la fila base
completa — y al sumar Cargo/Abono por `Grd_ID` en la comprobación, el cargo real queda
contado 2 veces. **Esto también existe en `layout_gastos_v0_1.py`** (mismo patrón de
join) — no se corrigió ahí todavía porque no rompió su validación contra el Excel (la
duplicación es rara, 15 grupos en todo enero), pero es el mismo bug latente.

Fix en v0.2: cambiar el `LEFT JOIN ... LIKE` por un `OUTER APPLY (SELECT TOP 1 ... ORDER
BY Cd_Documento)`, que garantiza como máximo 1 fila de comprobante por `Grd_ID` sin
alterar el grano de la fila base. Tras el fix: `ORDEN_COMPRA` y `VIAJE` llegan a 100%,
`(vacío)` sube a 99.18%.

## Bug 2 — fan-out del cargo/abono en folios con 2+ `Grd_ID` (corregido)

`Poliza_Detalle.Pd_Referencia` solo referencia el `Gr_Folio`, nunca el `Grd_ID`
específico — no hay forma de saber a qué documento dentro de un folio multi-documento
corresponde cada línea de póliza; es un dato a nivel folio, no por documento. El primer
intento agregaba el cargo/abono por folio y hacía `merge(..., on="folio")`, lo que
duplicaba el cargo-total-del-folio en **cada** `Grd_ID` de ese folio (106 de 1,412
folios "normales", 7.5%, concentrados en `(vacío)` y `VIAJE` — exactamente los dos
peores antes del fix).

Fix: para folios con un solo `Grd_ID`, merge 1:1 normal. Para folios con 2+ `Grd_ID`,
el cargo/abono/cuenta se pega solo al **último** `Grd_ID` del folio (los demás quedan en
0, marcados con `cargo_abono_a_nivel_folio=True`), y la comprobación para esos folios se
hace a **nivel folio completo** (suma de Importe de todos sus `Grd_ID`) en vez de por
fila — porque el dato de póliza genuinamente no baja a ese nivel de detalle.

Un efecto colateral de este fix requirió un segundo ajuste: cuando el folio multi-`Grd_ID`
además tiene 2+ cuentas contables distintas en su póliza (común en nómina/depreciación
repartida en varios centros de costo), la fila "último `Grd_ID`" se repite una vez por
cuenta — y el "importe" (que es un dato por documento, no por línea de póliza) se
duplicaba también al sumarlo por folio. Se corrigió deduplicando `importe` por
`(folio, Grd_ID)` antes de sumarlo a nivel folio, sin tocar la suma de Cargo/Abono (que sí
debe sumar todas las líneas de póliza).

## Casos que NO cuadran — pendientes de confirmar con el usuario

Tras los dos fixes, quedan **5 filas** sin cuadrar en todo enero 2026:

**2 son ruido de redondeo** (diferencia menor a $1, mismo patrón de centavos que v0.1):
`01-0035149` (−$0.65) y `01-0034667` (−$0.59).

**3 son un patrón real y sistemático, no ruido** — folios de origen `(vacío)` (manual),
con `Importe` **negativo** y comentario explícito de reclasificación/ajuste:

| Folio | Importe | Cargo | Abono | Comentario |
|---|---|---|---|---|
| `01-0034998` | −$125,086.88 | $125,086.88 | $125,086.85 | RECLA PRIMA DE ANTIGÜEDAD GASTO REAL ENERO 2026 |
| `01-0034999` | −$118,946.84 | $118,946.84 | $118,946.65 | RECLA PRIMA DE VACACIONAL GASTO REAL ENERO 2026 |
| `05-0181359` | −$3,395,052.95 | $3,395,052.95 | $3,395,052.95 | SALDO RENTA MAQ-EQ TRANSPORTE 2025 |

En los tres, la póliza SÍ trae Cargo y Abono a la vez (como en `GASTO_RECLASIFICACION`,
contradice la expectativa de "o cargo o abono" para gasto normal) y el `Importe` viene
en negativo — son reclasificaciones/ajustes hechos a mano con una póliza real (no con el
mecanismo de pares de `GASTO_RECLASIFICACION`). En los tres, Cargo = Abono (neto = 0,
igual que una reclasificación real) pero el `Importe` de cabecera es el monto completo en
negativo — la comprobación actual (`Cargo − Abono == Importe`) no tiene forma de cuadrar
con esa convención de signos.

**Nota sobre `05-0181359`**: en un primer intento, Cargo ($3,395,052.95) y Abono
($1,948,646.94) no cuadraban entre sí — faltaba la línea de Abono de la cuenta
`6200.001.007.016` ($1,446,406.01, "Renta Maq-Eq transp PM Res Nac"). Causa: esa cuenta
**no tiene `Cc_Grupo_Cuenta_Contable` asignado** en el catálogo (`Cuenta_Contable`), a
diferencia de sus cuentas hermanas del mismo folio (`6300.001.007.016`, `1140.020...016`,
mismo concepto, mismo tipo de cuenta) que sí resuelven a raíz `'F'` (Gastos). Se confirmó
que es un hueco aislado del catálogo (única cuenta con prefijo `6xxx` sin grupo entre
todas las líneas Abono de gasto de enero 2026 — el resto de cuentas sin grupo son
pasivo/capital, `2xxx`/`3xxx`, correctamente excluidas). Decisión del usuario: agregar un
fallback en el query (cuenta `6xxx` sin grupo → tratar como Gastos) en vez de corregir el
catálogo real — con eso, Cargo = Abono exacto y el folio queda en el mismo patrón que los
otros dos. **Pendiente separado**: Contabilidad podría querer corregir el catálogo real
(asignar grupo a `6200.001.007.016`) para que futuros reportes no dependan del fallback.

**No se intentó "arreglar" estos 3 casos ajustando la regla de negocio** — son
manuales, poco frecuentes (3 de 1,624), y la forma correcta de tratarlos (¿tratarlos como
`GASTO_RECLASIFICACION`? ¿comparar contra `|Importe|` en vez de `Importe`? ¿marcarlos
aparte?) es una decisión de negocio, no algo que se deba asumir. Quedan señalados en el
reporte (columna futura, pendiente) para que el usuario los revise antes de cerrar v0.2.

## Actualización — decisiones y cierre

- **Los 3 folios de reclasificación manual** (`01-0034998`, `01-0034999`, `05-0181359`):
  decisión del usuario: **dejarlos marcados como no cuadrados**, sin ajustar la regla de
  validación. Quedan visibles en la pestaña "Comprobación" del reporte para que
  Contabilidad los revise caso por caso.
- **Bug 1 también se corrigió en `layout_gastos_v0_1.py`** (mismo fix, `OUTER APPLY TOP
  1`). Efecto real: v0.1 estaba sobre-contando IMPORTE por ~$158,838.85 en enero 2026 (15
  filas duplicadas de 7,058) porque el join viejo (`LEFT JOIN ... LIKE`) duplicaba la fila
  para documentos con 2 UUID de CFDI que matcheaban el mismo prefijo. Tras el fix, v0.1
  vuelve a coincidir exacto con el Excel de referencia (7,043 filas, IMPORTE
  $39,469,269.50) — los números "más altos" observados en una validación anterior de la
  app en vivo no eran datos nuevos entrando a la BD, eran este bug.
- v0.2 cableado en `streamlit_app.py` como tercera opción del radio "Versión del reporte",
  con pestañas Reporte / Comprobación / Documentación (la de Comprobación expone el
  resumen por origen y las filas que no cuadran). Validado con `AppTest` sin excepciones
  en las 3 versiones (v0.1, v0.2, v1.1) antes de desplegar.
