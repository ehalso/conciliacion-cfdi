# Hito v0.5.1 — atribución por documento en la versión SQL

Pedido explícito del usuario: *"si hacemos la v5.1 para usar el detalle de grc_id?
estamos perdiendo granularidad y no creo que complique mucho el sql"*, tras ver que v0.5
concentraba el Cargo/Abono de un folio multi-documento en un solo documento (ejemplo:
3 folios de TOKA "COMISIÓN VALES DE DESPENSA", 6-7 documentos de $0.01 cada uno, con el
Cargo total solo visible en el último documento del folio).

## Mecanismo

Igual al validado en Python (v0.4.2, docs/13-14), pero **sin la salvaguarda de
re-enrutado**: se verificó que no hace falta una vez que el emparejamiento es por VALOR
(ordenando ambos lados — `Gasto_Registro_Control` y `Poliza_Detalle` — por importe, no
por orden de creación). Los casos que en Python necesitaban la salvaguarda (folio de
depreciación `01-0035004`, 642 líneas / 77 centros; `01-0034938`) ya cuadraban exacto
solo con el cambio a orden por valor — la salvaguarda solo importaba cuando se
emparejaba por orden de inserción.

Tres métodos, igual que v0.4.2:
1. **Exacto**: mismo conteo de documentos en ambos lados dentro de `(folio,
   centro_costo)` → emparejamiento por valor vía `ROW_NUMBER()`.
2. **Proporcional**: conteo distinto pero datos en ambos lados → reparto por
   `Grc_Importe`.
3. **Respaldo** (igual que v0.5): sin centro de costo, o centro que no aparece en
   `Gasto_Registro_Control` → agregado por folio, pegado al último documento.

## Validación de granularidad (folio TOKA)

| Documento | v0.5 (folio completo) | v0.5.1 (por documento) |
|---|---|---|
| `01-0034734` Grd 0001-0006 | `None` | $0.01 c/u |
| `01-0034734` Grd 0007 | $0.07 (todo el folio) | $0.01 |

## Costo: rendimiento (y por qué, y cómo se resolvió)

Primer intento: 22s para enero 2026, pero **14 minutos 14 segundos para todo 2025**. El
usuario preguntó por qué era tan lento comparado con v0.4.2 (Python, ~51s para el mismo
año) — la respuesta reveló la causa real: `poliza_linea` y `grc` eran CTEs referenciadas
5 y 3 veces respectivamente más abajo en la consulta. **SQL Server no materializa las
CTEs** (son macros que se re-expanden en cada referencia), así que el JOIN pesado de
póliza (`Gasto_Registro` + `Poliza_Control` + `Poliza` + `Poliza_Detalle` + árbol
recursivo de cuentas) se recalculaba 5 veces por consulta. v0.4.2 (Python) no tiene este
problema porque cada tabla se consulta una sola vez y el resto del emparejamiento corre
en memoria con pandas.

**Fix**: materializar `grupo_arbol`, `base`, `grc` y `poliza_linea` en tablas `#temporales`
(se calculan una sola vez, con índice) en vez de CTEs — el resto (conteo, `ROW_NUMBER`,
reparto proporcional) se queda como CTEs normales porque ya corren sobre las
`#temporales` (baratas de releer), no sobre los JOINs originales.

| Periodo | v0.5 | v0.5.1 (CTEs) | v0.5.1 (#temp, final) |
|---|---|---|---|
| Enero 2026 | ~3s | ~19s | **~5s** |
| 2025 completo | **22s** | 14 min 14s | **24s** |

~35x más rápido tras el fix, mismo resultado de comprobación exacto en las tres versiones
(15 de 15,047 filas sin cuadrar en 2025, todas de redondeo) — la granularidad adicional
no cambia los totales, solo el desglose por documento dentro de folios multi-documento.
Con este fix, v0.5.1 es prácticamente tan rápido como v0.5 y ya no hace falta elegir
entre velocidad y granularidad.
