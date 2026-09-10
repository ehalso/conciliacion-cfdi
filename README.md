# Conciliación CFDI ↔ mpro (Trivasa)

Conciliación automatizada entre los CFDI timbrados ante el SAT (bodega
`raw_sat` en Postgres) y los registros contables de Management Pro / mpro
(SQL Server), para poder responder, periodo a periodo: **¿qué documentos de
mpro corresponden a cada CFDI, y el importe contabilizado (cargo/abono en
póliza) cuadra con el importe fiscal del CFDI?**

Alcance actual: **CFDI recibidos** (primer semestre 2026, nivel 1 a nivel
3, 99.36%) y **emitidos** (100%, factura/nota de crédito/retenciones) al
día. **Retención**: dos conceptos con mecánica de conciliación distinta
(arrendamiento/honorarios vs. intereses a prestamista — ver
[`docs/hallazgos.md`](docs/hallazgos.md) puntos 28-29) y un cruce
independiente contra el SAT que encontró 29 constancias timbradas que el
ERP nunca registró — ver [`docs/pendientes.md`](docs/pendientes.md) y
[`docs/emitidos_retenciones.md`](docs/emitidos_retenciones.md).

**Consolidación 2026-09-10**: este repo unificó varios proyectos hermanos
que respondían la misma pregunta por separado —
`~/proyectos/conciliacion-master/adjuntar-xml` (→ `recibidos/nivel_documento/`),
`conciliacion-emitidos` (ya portado, retirado) y `layout-gastos` (→
`layout_gastos_poliza/`). Se retiró también
`~/proyectos/layout-contabilidad/layout-gastos-streamlit-claude`, superado
por `streamlit-reportes` (el deployment real de producción). `funcionales-
auditoria` (reportes RPTRV79, dominio de auditoría, no de conciliación)
pasó a su propio repo, `ehalso/reportes-mpro`. Backup completo de las
carpetas originales en `~/backups/consolidacion-conciliacion-2026-09-10.zip`.

## Acceso a las bases

Conexión **directa** a las tres bases de Trivasa — Postgres (`raw_sat`) y
los dos SQL Server de mpro (`.205`/`.207`) — vía `src/bridge_client.py`
(SQLAlchemy: `psycopg2`/`pymssql`), solo lectura (`_guard_readonly` valida
que cada SQL sea un único `SELECT`/`WITH`, sin palabras clave de
escritura). Credenciales por variable de entorno o `.env` local
(gitignored) — copiar `.env.example` y llenar usuario/password de cada
target (host/puerto/base no son secreto, van hardcodeados). Detalle
completo, incluidos los tres targets y la decisión 205 vs 207, en
[`docs/arquitectura.md`](docs/arquitectura.md).

**Método deprecado**: antes de tener red directa a la LAN de Trivasa, este
repo pasaba por una API puente HTTP de solo lectura
(`https://reportesweb.frento.com.mx/query`, mantenida en `ctunlinux`).
`bridge_client.py` conservó el mismo contrato (`run_query(target, sql) ->
{"columns", "rows", ...}`) al migrar a conexión directa, así que ningún
extractor cambió una sola línea — el modo bridge queda documentado como
fallback histórico (recuperable del historial de git de ese archivo) para
el caso de que una sesión futura vuelva a correr sin ruta de red directa.

## Estructura (2026-09-10 — reorganizado por pregunta de negocio, no por sesión)

Cada dominio (recibidos/emitidos/retención) se concilia desde **dos ángulos
independientes y complementarios**, no un método único:

- **`nivel_documento`** — ¿el documento que capturó/originó el CFDI en mpro
  trae el mismo importe? (compara contra la tabla propia del módulo —
  `Compra_Encabezado`, `Factura_Encabezado`, etc. — nunca contra la póliza).
- **`nivel_poliza`** — ¿lo que se **contabilizó** en `Poliza_Detalle`
  (Cargo/Abono real) cuadra contra el CFDI? Un nivel más profundo: el
  documento puede estar perfecto y la póliza no aislarlo bien (ver
  `docs/hallazgos.md` puntos 28/30 para un caso real, FACTURA/VENTA).

```
recibidos/
  nivel_documento/   Documento↔CFDI+impuestos (ex adjuntar-xml). 03_conciliacion_xml_vs_mpro_impuestos.py,
                     04_conciliacion_mpro_vs_xml.py (inverso: mpro sin CFDI), 05_resumen_conciliacion.py
  nivel_poliza/      Póliza↔CFDI — el método vigente. baseline_universal.py (99.36% H1),
                     baseline_conciliacion.py, reconciliacion_por_origen.py, poliza_reconciliation.py
  cruce_sat/         (pendiente) independiente de Comprobante_Digital — ver su README

emitidos/
  nivel_documento/   conciliacion_emitidos_documento.py — 100% H1 (por construcción: el
                     CFDI se genera DESDE el documento, no captura contra él)
  nivel_poliza/      baseline_universal_emitido.py — NOTA_CREDITO 99.5%, FACTURA sin método aún

retencion/
  cruce_sat/         retencion_reconciliation.py — SAT (raw_sat.cfdi_retencion, fuente
                     INDEPENDIENTE del ERP) vs Cd_Monto. Aquí vive el hallazgo real: 29
                     constancias timbradas que el ERP nunca registró ($536,597.04)

cobranza_rep/       (pendiente) REP vs Pago_CXC — ver su README

layout_gastos_poliza/  Reconciliación CECO/Gasto_Registro (Cargo-Abono vs Importe), la
                       fuente de desarrollo de las páginas CONT-1/CONT-2 de streamlit-reportes

src/                 Extractores compartidos entre los métodos de arriba (ver abajo)
reportes_streamlit/  UIs interactivas — candidatas a promover a streamlit-reportes (producción)
docs/                Metodología, hallazgos, pendientes — consolidados, no uno por dominio
```

`main.py` queda en la raíz (nivel 1, el más simple — CFDI existe y el
importe coincide, sirve para ambas direcciones vía `--tipo`) por ser
cross-cutting y ya no el punto de partida para trabajo nuevo.

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env   # llenar PG_USER/PASSWORD, MSSQL_205/207_USER/PASSWORD

# --- Recibidos ---
python3 recibidos/nivel_documento/03_conciliacion_xml_vs_mpro_impuestos.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
python3 recibidos/nivel_documento/04_conciliacion_mpro_vs_xml.py           --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
python3 recibidos/nivel_poliza/baseline_universal.py --periodo 2026-02          # método vigente, 99.36% H1

# --- Emitidos ---
python3 emitidos/nivel_documento/conciliacion_emitidos_documento.py --periodo 2026-01   # 100%
python3 emitidos/nivel_poliza/baseline_universal_emitido.py --periodo 2026-01          # NOTA_CREDITO 99.5%

# --- Retención (incluye el cruce independiente contra el SAT) ---
python3 retencion/cruce_sat/retencion_reconciliation.py --periodo 2026-01
python3 retencion/cruce_sat/retencion_reconciliation.py --periodos 2026-01,2026-02,2026-03,2026-04,2026-05,2026-06

# --- Layout de gastos por CECO ---
python3 layout_gastos_poliza/07_reconciliacion_completa_ceco.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01

# --- Nivel 1 (cross-cutting, el más simple) ---
python3 main.py --periodo 2026-02
python3 main.py --tipo emitido --periodo 2026-01
```

Cada script imprime su avance y termina escribiendo un `.xlsx`/`.csv` en
`output/` (o junto al script — no versionado, ver `.gitignore`) con hojas
de resumen y detalle, semaforeado por color.

## Reportes

- **GUI estática**: un dashboard (Artifact HTML) para revisar la
  conciliación sin abrir el `.xlsx` — totales y % de cuadre por origen, y
  tabla de detalle documento-por-documento (recibido) o CFDI-por-CFDI
  (emitido, retención), con búsqueda, filtros y orden por columna. Es un
  snapshot estático de los datos de este README — se regenera pidiendo que
  se actualice con datos más recientes.
- **Streamlit interno** (`reportes_streamlit/`): UIs en vivo sobre los
  métodos de arriba, sin duplicar lógica — candidatas a promoverse a
  `streamlit-reportes` (el deployment de producción real, Docker +
  Cloudflare Tunnel en `reportes.frento.com.mx`) cuando maduren. Correr con
  `streamlit run reportes_streamlit/streamlit_app.py` (recibidos) o
  `streamlit run reportes_streamlit/layout_gastos_ceco/streamlit_app.py`
  (CECO).

## Estructura de código compartido

```
src/
  bridge_client.py            Conexión SQL directa a los 3 targets (Postgres/SQL Server), guard de solo lectura
  config.py                   Un solo lugar para decidir contra qué SQL Server
                               correr (mssql_205 vs mssql_207 — ver docs/arquitectura.md)
  cfdi_parser.py               Parseo de CFDI 3.3/4.0 (subtotal, IVA, total, UUID)
  extract_sat.py               Lado SAT: raw_sat.cfdi_recibidos / cfdi_emitidos (Postgres)
  extract_mpro.py              Lado mpro, nivel CFDI: Comprobante_Digital + parseo de Cd_XML
  extract_origen.py            Traza cada CFDI a su(s) documento(s) de origen en mpro
                               (Comprobante_Digital.Cd_Tabla / Cd_Documento)
  extract_poliza.py            Piloto: CFDI → póliza vía Poliza_Detalle_Comprobante (agnóstico de origen)
  extract_poliza_por_origen.py Cargo/abono por documento, YA distinguido por origen,
                               vía Poliza_Control → Poliza → Poliza_Detalle
  extract_gasto_registro.py    Cargo granular para GASTO_REGISTRO (folio+Grd_ID)
  extract_detalle_lineas.py    Detalle a nivel línea de póliza/control de gasto (drill-down)
  extract_moneda.py            Moneda y tipo de cambio del documento de mpro, por origen
  extract_vias_extra.py        Vías de cuadre adicionales (arrendamiento, folios hermanos...)
  reconcile.py                  Cruce SAT vs mpro a nivel CFDI + clasificación
  report.py                     Reporte .xlsx (colores por estatus)

main.py                        CLI: conciliación base (nivel CFDI, ambas direcciones)

investigacion/
  dump_contexto.py             Dump de contexto de los pendientes para investigación
  triage.py                    Batería de relaciones numéricas candidatas

docs/
  arquitectura.md              Conexión directa a las 3 bases, bridge HTTP deprecada, mssql_205 vs mssql_207
  metodologia.md                Cómo se define "cuadra": base, tolerancias, nivel documento vs agregado
  hallazgos.md                  Bugs y patrones reales encontrados (con evidencia)
  resultados_2026-02.md         Resultados concretos, febrero 2026 recibidos
  pendientes.md                 Qué falta y por qué (emitido, retención, orígenes sin resolver)
  investigacion_pendientes.md   Investigación folio por folio que llevó a 99.36%
  emitidos_retenciones.md       Conciliación de emitidos y retenciones (100%) + hallazgo SAT
```

## Estado (2026-09-10)

- ✅ Conciliación base nivel CFDI (recibidos): corrida y validada para
  ene/feb/ago 2026 y Q1 2026, ~99% OK.
- ✅ Censo de orígenes de documento en mpro para recibidos (qué módulos
  hay que reconciliar y cuánto $ representa cada uno).
- ✅ **Método de doble chequeo (cargo + abono) validado para COMPRA**:
  cargo (folio de compra) = Subtotal, Y abono (Serie+Folio del propio
  CFDI) = Total → **583/713 (81.8%) conciliados** para febrero 2026 (tras
  corregir la selección de documento cuando un CFDI queda etiquetado dos
  veces bajo el mismo origen). Ver `baseline_conciliacion.py` y
  `pendientes.md`.
- ✅ Reconciliación por origen (Compra, Cheque, Cuenta_x_Pagar) con cuadre
  agregado 90–97% para febrero 2026.
- ✅ **Conciliación al 99.36% en todo H1 2026** (9,511 de 9,572 CFDI con valor
  monetario). Por mes: ene 99.2%, feb 99.5%, mar 99.2%, abr 99.8%, may 99.2%,
  jun 99.4%. Febrero venía en 90.1% antes de la sesión de investigación folio
  por folio del 2026-09-09/10 — el detalle completo de qué lo subió, con la
  evidencia de cada hallazgo y la clasificación de los 61 pendientes que
  quedan, está en [`docs/investigacion_pendientes.md`](docs/investigacion_pendientes.md).
  Lo que más pesó: convertir el CFDI a MXN con el tipo de cambio del documento,
  restar el `Descuento` (que `raw_sat` no guarda), sumar el IEPS a la base,
  identificar las cuentas de orden por la raíz de la cuenta, y una cascada de
  vías de cuadre para tratamientos contables legítimos (arrendamiento
  financiero, nota de crédito contra total, IVA no acreditable, gasto
  repartido entre sucursales…). El `Descuento`/IEPS/impuestos locales ya no
  se re-parsean del XML de mpro en cada corrida: `raw_sat.cfdi_recibidos`/
  `cfdi_emitidos` los trae parseados desde la ingesta (`baseline_universal.py`
  los lee directo con `ajustes_desde_sat()`).
- ✅ **Baseline UNIVERSAL (todos los orígenes, chequeo agregado de un solo
  lado)** — *hito del 2026-09-09, superado por el punto anterior; se deja
  porque explica de dónde salió el método*: sumando el cargo de TODOS los
  documentos con los que un CFDI aparece etiquetado en mpro (sin importar el
  origen) y comparando contra el Subtotal, **1,351/1,500 (90.1%)** de los CFDI
  recibidos con valor real de febrero 2026 ya cuadran — resuelve de raíz los casos de CFDI repartidos
  entre varios documentos/orígenes (COMPRA+COMPRA_INDIRECTO,
  GASTO_REGISTRO+CUENTA_X_PAGAR, liquidación directa vía Cheque). No exige
  que el abono también cuadre (ver `baseline_universal.py` y
  `pendientes.md`).
- ✅ **Gasto_Registro corregido (2026-09-09): llave granular folio+Grd_ID,
  no el folio truncado a 10**. Pasó de 37% (método viejo por-documento) a
  **89.4%** con el chequeo agregado universal, en dos pasos: (1) el filtro
  robusto de cuentas-de-orden vía `Pl_Configuracion` (82.8%), y (2) la
  llave granular vía `Gasto_Registro_Control` — sumando `Grc_Importe` por
  `(Gr_Folio, Grd_ID)` en vez de sumar toda la póliza referenciando el
  folio truncado — más el ajuste por el complemento `implocal:
  ImpuestosLocales` (89.4%). Detalle completo, incluida una vuelta en
  falso (una hipótesis de llave `folio+Grd_ID+Grc_ID` que resultó
  incorrecta y causó una regresión temporal), en `hallazgos.md` puntos
  14-15 y `pendientes.md`. Confirmado que las pólizas canceladas (`CA`) ya
  estaban filtradas desde antes en `extract_poliza_por_origen.py` para
  todos los demás orígenes.
- ✅ Compra_Indirecto: causa del 3% ya diagnosticada (no es un hueco de
  datos — son CFDI duplicados con COMPRA, donde ya cuadran; ver
  `pendientes.md`), pendiente decidir tratamiento.
- ✅ **Emitidos y retenciones (2026-09-10): conciliación al 100% en todo H1
  2026** (14,554/14,554 CFDI conciliables — factura, nota de crédito,
  retenciones). Del lado emitido no hay problema de importes: el CFDI se
  genera desde el documento de mpro, así que no puede diferir. El hallazgo
  real está en el cruce independiente contra el SAT
  (`retencion_reconciliation.py`): **29 constancias de retención por
  $536,597.04 ($107,319.45 de ISR) que el SAT tiene timbradas y el ERP
  nunca registró** — 14 en enero, 15 más en febrero. Detalle completo en
  [`docs/emitidos_retenciones.md`](docs/emitidos_retenciones.md).
  Pendiente: reporte de cobranza (REP) y correr el cruce SAT más allá de
  junio.
- ✅ **Retención recibida por Trivasa (nivel 1, H1 2026): dos conceptos
  distintos bajo el mismo `cve_retenc`** — arrendamiento/honorarios (10%,
  cada ~4 meses, concilia 100% vía `CONSTANCIA_RETENCION`) vs. intereses a
  prestamista (20%, mensual, nunca usa `CONSTANCIA_RETENCION` — concilia
  vía `Gasto_Registro`). Los CFDI "huérfanos" de este segundo tipo tienen
  dos mecanismos reales, no uno: omisión de etiquetado, o CFDI sustituido
  (`CfdiRetenRelacionados`) sin re-ligar el link contable al UUID nuevo.
  Detalle completo en `docs/hallazgos.md` puntos 28-29.
- ✅ `Poliza_Control` **volvió a responder** (2026-09-09) — estuvo caída
  desde 2026-09-07. Desbloquea todo el trabajo de nivel 3 pendiente
  (emitidos, retención). Ver `hallazgos.md` punto 13.
- 🔧 Mientras 207 (la base "buena") está en desarrollo, el pipeline corre
  contra 205 (`src/config.py:MPRO_TARGET`), acotado a enero–junio 2026.

## Continuidad — para retomar el trabajo en otra sesión

Ver [`PROGRESS.md`](PROGRESS.md): estado actual, método validado, pendientes
por origen con lo ya investigado de cada uno, y cómo seguir. Es el punto de
entrada pensado para que otra sesión retome el trabajo sin tener que releer
todo el historial.
