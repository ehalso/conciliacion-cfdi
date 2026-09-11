# Legado — layout de gastos de 60 columnas (requerimiento original de Contabilidad)

Rescatado el 2026-09-11 desde `~/backups/` (nunca antes revisado a fondo, solo usado como
"imita este reporte"). Alcance: **solo `GASTO_REGISTRO`, 5 orígenes normales — excluye
`CONSUMO_INTERNO` y `GASTO_REGISTRO_NOMINA` a propósito**, tal como lo pide
`layout-gastos-streamlit-claude/docs/00_requerimiento.md` (transcripción del Word
`Requerimiento_de_Reportes_de_Contabilidad_auditoria_V2.docx`, auditoría externa trimestral
con Bates y Asociados). Es un alcance **distinto** al de `../../layout_gastos_poliza/`
(CECO, 6-7 orígenes, incluye nómina/consumo interno) — no uno subconjunto del otro.

## Los tres orígenes, en orden de relevancia

### 1. `layout-gastos-streamlit-claude/` — de `~/backups/consolidacion-conciliacion-2026-09-10.zip`

Proyecto que **llegó a producción real** (`explore.frento.com.mx`, systemd) y fue
**retirado a propósito** en septiembre 2026, reemplazado por CONT-1/CONT-2 (decisión de
alcance: CECO en vez de 60 columnas — no fue abandono por falla técnica).

Dos líneas de iteración documentadas en `CHANGELOG.md`/`docs/`:
- **v1 → v1.1** (jul 2026, Python/pandas): `scripts/layout_gastos_v1.py` — cabecera +
  póliza en 2 queries, unidas con **merge posicional** (no rank-pairing). Reconciliación
  Cargo-Abono vs. Subtotal Neto: **+0.89%** sobre enero 2025 (partió de -35.7%, 5
  correcciones documentadas en `docs/03_hito_v1.md`). Esta es la versión que quedó "viva"
  en producción.
- **v0.1 → v0.5.1** (jul 2026, exploración posterior a v1.1, nunca promovida a
  producción): reescritura a **SQL puro** buscando granularidad por documento
  (`Grc_ID`) en vez de por folio. `docs/18_hito_v0_5_1_granularidad.md` documenta el
  hallazgo más valioso: **`ROW_NUMBER()` ordenando por VALOR (no por orden de inserción)
  en ambos lados** (`Gasto_Registro_Control` y `Poliza_Detalle`) hace innecesaria la
  salvaguarda de "re-enrutado" que sí hacía falta en la versión Python — y con `#temporales`
  en vez de CTEs repetidas, corre ~35x más rápido (24s vs. 14 min para todo 2025).

`data/*.parquet` — caché de enero 2025 contra la BD que usaban entonces (no es `.205`
actual). Útil solo para entender la forma de los datos, no para validar nada de hoy
(gitignored, no se versiona — ver raíz del repo).

### 2. `layout-gastos-pasos/` — de `~/backups/layout-contabilidad-legacy-2026-09-10.zip`

Segunda vuelta **independiente** (ago 2026, no reusó v1.1), organizada como `paso1`...`paso15`
+ `docs/queries/gastos/*.sql` — cada bloque de columnas validado por separado con su propio
SQL y % de cobertura, documentado en `docs/cierre_1_56_enero2026.md`:

| Columnas | Bloque | Cobertura (ago 2026, sin fixes de calidad de dato posteriores) | Query |
|---|---|---:|---|
| 1-18 | Identidad/proveedor/pago | 91.8%-100% | `etapa6_columnas_1_18.sql` |
| 19-40 | Impuestos por tasa/retenciones | 100% | `v5_impuestos_layout.sql` |
| 41-52 | UUID/XML/método de pago | 92.8%-94% | `uuid_factura.sql`, `xml_detalle.sql` |
| 44-46 | Concepto/Uso CFDI | 91.7%-100% | `uso_cfdi_por_folio.sql` |
| 53-56 | Póliza descriptiva | 99.3%-99.4% | `poliza_descriptiva.sql` |
| 57-60 | Cuenta/Cargo/Abono | 100% | `v03_detalle_cuenta_centro_costo.sql` (mismo ancestro de CONT-1/2) |

**Nunca unió los bloques** — se topó con el mismo choque de grano header(1 fila/folio)↔
póliza(N filas/folio) que v1.1 ya había resuelto con merge posicional, sin reusarlo.

⚠️ **Estos % son anteriores a los fixes de calidad de dato de agosto-septiembre 2026** que
ya conocemos por `../../layout_gastos_poliza/PROGRESS.md`: moneda del CFDI sin convertir,
dedup de formato 14/18 de `Comprobante_Digital`, retenciones con monto en fila hermana
(`CONSTANCIA_RETENCION`), `implocal`/IEPS mezclado en la base en vez del impuesto, cuentas
de orden por raíz. **Nada de eso está aplicado aquí — hay que re-auditar, no solo re-correr.**

Nota: los `.csv`/`.py` sueltos en la raíz de este directorio son *outputs* de validación de
cada paso, no solo código — quedan aquí como evidencia histórica (gitignored).

### 3. `aaron_query/` — de `~/backups/layout-contabilidad-legacy-2026-09-10.zip` (dentro de `layout_gastos/`)

Implementación **C#/.NET independiente** del mismo reporte completo, hecha por un
programador externo. Útil como referencia de negocio para diferenciar decisiones de
diseño (dónde coincide confirma el diseño, dónde diverge hay que decidir cuál es correcto)
— no para reusar código directamente (stack distinto).

## Gaps permanentes (confirmados 2 veces, de forma independiente — dato inexistente, no bug)

`FACTURA_REF` (0% en ambos intentos), `Descuento`/`Descuento global`, `Concepto gasto`,
`Clave/Descripción de Uso de bien o servicio`. Documentar como pendiente de Contabilidad,
no perseguir más con SQL.

## Siguiente paso (ver conversación con Claude, 2026-09-11)

Re-auditar bloque por bloque (tabla de arriba) contra los gotchas de calidad de dato ya
conocidos, sobre datos actuales (`.205`), partiendo de la técnica de merge posicional /
`ROW_NUMBER()` por valor de v0.5.1 — no reinventar el emparejamiento de grano.
