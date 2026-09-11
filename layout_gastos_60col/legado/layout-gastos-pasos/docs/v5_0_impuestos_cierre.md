# v5.0 — Impuestos por folio (Subtotal 0/16/Exenta + 13 retenciones) — cierre

**Fecha:** 2026-08-04
**Query:** `docs/queries/gastos/v5_impuestos_layout.sql`
**Script de comprobación:** `validar_impuestos_v5.py` (`.200`/TRIVASADB3)

## Qué resuelve

Clasifica cada renglón de `Gasto_Registro_Impuesto` a su columna del layout de
60 columnas — el bloque de impuestos por tasa (`Subtotal 0%`, `Subtotal 16%`,
`Subtotal exento`) y las 13 columnas de retención/IVA específico
(`26-ISR RESICO 1.25%`, `23-IVA S/ARRENDAMIENTO 10.67`, `22-IMSS PATRON`, etc.).
Cierra el bloque "territorio nuevo" del roadmap — tabla no tocada por ninguna
de las dos exploraciones previas al 2026-08-04.

## Mecanismo de clasificación

No hay configuración por proveedor ni por tipo de gasto que determine qué
retención aplica a un folio — investigado y descartado con datos reales
(`Proveedor.Pv_Grupo_Impuesto` es un catálogo genérico de ~20 impuestos
posibles por grupo, no una restricción específica; `Tipo_Gasto.Tg_Tipo`
tampoco correlaciona de forma limpia). La retención se decide manualmente al
capturar cada renglón en `Gasto_Registro_Impuesto`, con su propio
`Im_Cve_Impuesto`. La clasificación es directa:

- **Subtotal 0/16/Exenta**: por `Im_Tasa`/`Im_Tipo_Factor` del catálogo
  `Impuesto` (agregado, no por código específico — varios códigos comparten
  la misma tasa, ej. `0001`/`0002` ambos 16%).
- **13 retenciones específicas**: por `Im_Cve_Impuesto` exacto — 1 código = 1
  columna del layout.
- **`Descuento`/`Descuento Global`**: sin resolver, `0` explícito. Ni
  siquiera el reporte de producción del programador externo los resolvió
  (hardcodeados en 0 ahí también) — territorio pendiente de investigación
  aparte.

## La validación correcta (y la que NO lo era)

Primer intento (`v4b`): exigir que `Subtotal_0 + Subtotal_16 + Subtotal_Exenta
= Grd_Precio_Descontado_Importe` (el subtotal completo del documento). Esto
es **incorrecto** para pagos financieros con retención de ISR (intereses,
dividendos) — confirmado con drill-down del folio `0001-0034764` (interés de
arrendamiento financiero): la póliza contable registra el monto completo
correctamente, pero el IVA solo se calcula sobre una porción de la base
(exclusión del componente inflacionario, mecanismo fiscal mexicano) — la
base gravable capturada nunca cubre el 100% del subtotal por diseño, no por
dato faltante.

**Validación correcta**: `SUM(Gri_Importe)` de todos los renglones de
impuesto de un folio debe cuadrar contra `Grd_Impuesto_Importe` (el monto de
impuesto ya validado como correcto contra la baseline v0.1). Esto no exige
nada sobre la base gravable — solo confirma que la suma de columnas
individuales del layout reconstruye exacto el total de impuesto documentado.

## Fan-out por documentos múltiples (Grd_ID)

Un folio puede tener más de un `Grd_ID` con montos distintos (ver también
`Z_Grd_Multiple='SI'`, folio `0001-0034986` con 2 documentos). Agregar
directo a nivel folio sin pasar primero por una agregación a nivel documento
duplica filas al cruzar contra la baseline (detectado: 1,425 → 1,706 filas
en un intento intermedio). Fix: CTE de dos niveles
(`doc_impuestos` a nivel `Grd_ID` → `SELECT` final agregado por `FOLIO`).
El script de comprobación incluye `assert df["FOLIO"].is_unique` inmediato
tras leer el resultado del SQL, para detectar cualquier fan-out futuro sin
depender de notar conteos raros a simple vista.

## Resultados

| Corrida | Servidor | Rango | Folios | Cuadran | % |
|---|---|---|---|---|---|
| Enero 2026 | `.200` (TRIVASADB3) | 2026-01-01 a 2026-02-01 | 1,425 | 1,425 | **100.0%** |

Desglose por origen: `CONTROL_COMBUSTIBLE` 384/384, `GASTO_DIRECTO` 610/610,
`GASTO_RECLASIFICACION` 13/13, `ORDEN_COMPRA` 72/72, `VIAJE` 346/346 — 100%
en los 5 orígenes.

## Pendiente

- `Descuento`/`Descuento Global`: sin origen identificado, 0 explícito.
- Validar contra `.207` (producción) y semestre completo, como se hizo con
  v3.0 CXP — no corrido todavía para impuestos.
- `RETENCIONES_IVA`/`RETENCIONES_ISR` (columnas agregadas del layout)
  incluyen códigos sin columna individual dedicada (`0024`, `0016`, `0017`,
  `0009`, `0010`) — confirmar con el requerimiento original si el agregado
  debe ser solo suma de las 13 columnas explícitas o todo lo retenido exista
  o no columna propia.
- `Constancia_Retencion_Detalle` apareció en la búsqueda de tablas con
  `Im_Cve_Impuesto` (ver hallazgos) — no explorada, podría ser relevante para
  DIOT/constancias fiscales relacionadas a estas mismas retenciones.

## Véase también

- [Roadmap layout completo](roadmap_layout_completo.md)
- `docs/v3_0_cxp_completo_cierre.md` — mismo patrón de cierre para el bloque de CXP.
