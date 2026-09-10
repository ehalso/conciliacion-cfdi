# ref/ — scripts de referencia (no numerados)

Scripts que ya no forman parte de la secuencia numerada activa de
`layout-gastos/` (`01_`, `02_`, `03_`...), pero se conservan como referencia
porque documentan hallazgos válidos de la exploración de conciliación
Cargo/Abono a nivel centro de costo (CECO). Adaptados originalmente de
`layout-contabilidad/layout_gastos/` (ver ese repo para el historial
completo de iteración).

Conexión por defecto: `.205`/`TRIVASADB3` (`connection_205_trivasadb3.py`),
igual que el resto del proyecto — ver skill `trivasa-sql-exploracion`.

## Scripts

### `reconciliacion_cargo_abono_ceco.py`
Reconcilia Cargo/Abono real de `Poliza_Detalle` a nivel **folio × cuenta
contable × centro de costo** (`Pd_Centro_Costo`, el campo real de la
póliza, no derivado de `Grc_ID`). Es la query más validada del proyecto
histórico (99.96%, enero-junio `.207`, layout-contabilidad). Corrida en
esta exploración: **100.00%** enero 2026, **99.98%** enero-marzo 2026
(universo sin `CONSUMO_INTERNO`/`GASTO_REGISTRO_NOMINA`).
Query: `queries/v03_detalle_cuenta_centro_costo.sql` (la misma que se
sirve en FlexMonster).

### `reconciliacion_impuestos_poliza_ceco.py`
Reconcilia Impuesto + Cargo/Abono a nivel **folio**, usando el centro de
costo de `Gasto_Registro_Control` (`Grc_ID`) en vez de `Pd_Centro_Costo`.
El Impuesto se prorratea por `Grc_Factor` a nivel documento (dato nuevo,
no viene en el script anterior); el Cargo/Abono se prorratea por el peso
de `Grc_Importe` (no es el valor real por CECO de la póliza — ver
`03_reconciliacion_grc_importe_vs_poliza_ceco.py` en el directorio padre
para esa comparación directa). Resultado: **99.79%** enero 2026,
**99.74%** enero-marzo 2026.
Query: `queries/v_impuestos_y_poliza_por_ceco.sql` (v2.4).

## Diferencia clave entre los 3 cruces de la exploración (incluye el `03_` activo)

| | Grano real | Cuenta contable | Qué valida |
|---|---|---|---|
| `reconciliacion_cargo_abono_ceco.py` (aquí) | folio × cuenta × CECO real de póliza | ✅ sí | que el detalle no pierde dinero al desagregar (rollup a folio) |
| `reconciliacion_impuestos_poliza_ceco.py` (aquí) | folio (rollup, CECO de `Grc_ID`) | ❌ no | que Cargo prorrateado + Impuesto prorrateado reproducen el folio — el valor real es el Impuesto, el Cargo es estimado |
| `../03_reconciliacion_grc_importe_vs_poliza_ceco.py` (activo, antes `05_`) | folio × CECO, sin prorrateo | ❌ no (`Gasto_Registro_Control` no tiene columna de cuenta contable) | si el reparto por centro de costo de `Grc_ID` coincide literalmente con lo posteado en la póliza — la prueba más estricta, 98.09%/97.56% |

## Pendiente

No se encontró la tabla real que resuelve la cuenta contable a partir de
tipo de gasto × centro de costo (`Tipo_Gasto.Tg_Cuenta_Contable` solo está
poblado en 56/249 tipos de gasto — no sirve como mapeo directo). Sin esa
tabla, no se puede colapsar `reconciliacion_impuestos_poliza_ceco.py` ni
`03_reconciliacion_grc_importe_vs_poliza_ceco.py` a nivel cuenta contable.
