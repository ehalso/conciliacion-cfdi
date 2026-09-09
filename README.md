# Conciliación CFDI ↔ mpro (Trivasa)

Conciliación automatizada entre los CFDI timbrados ante el SAT (bodega
`raw_sat` en Postgres) y los registros contables de Management Pro / mpro
(SQL Server), para poder responder, periodo a periodo: **¿qué documentos de
mpro corresponden a cada CFDI, y el importe contabilizado (cargo/abono en
póliza) cuadra con el importe fiscal del CFDI?**

Alcance actual: **CFDI recibidos** (primer semestre 2026, nivel 1 a nivel
3) con avances en **emitidos** (nivel 1 validado para enero 2026) y
**retención** (mapeo a mpro ya encontrado) — ver
[`docs/pendientes.md`](docs/pendientes.md).

## Arquitectura

Conexión **directa** (SQLAlchemy + psycopg2/pymssql) a las tres bases de
Trivasa — `postgres_dw` (raw_sat) y los dos SQL Server de mpro
(`mssql_205`/`mssql_207`) — vía `src/bridge_client.py`, con guard de solo
lectura del lado cliente (un único `SELECT`/`WITH`, nunca `commit()`).

Hasta el 2026-09-09 esta sesión no tenía ruta de red a la LAN de Trivasa y
todo pasaba por una API HTTP puente mantenida en `ctunlinux`
(`https://reportesweb.frento.com.mx/query`) — historia completa, y el
fallback si algún día vuelve a hacer falta, en
[`docs/arquitectura.md`](docs/arquitectura.md).

## Quickstart

```bash
pip install -r requirements.txt

# Credenciales de conexión directa: copiar .env.example a .env y llenar
# usuario/password de cada target (host/puerto/base ya van hardcodeados
# en src/bridge_client.py — no son secreto). .env nunca se versiona.
cp .env.example .env

# Conciliación base (nivel CFDI): SAT vs mpro, un periodo o varios
python3 main.py --periodo 2026-02
python3 main.py --periodos 2026-01,2026-02,2026-03 --salida output/conciliacion_Q1.xlsx

# Igual pero para emitidos (solo 2026-01 tiene datos completos por ahora)
python3 main.py --tipo emitido --periodo 2026-01

# Conciliación a nivel póliza/cuenta contable (piloto, vía Poliza_Detalle_Comprobante)
python3 poliza_reconciliation.py --periodo 2026-01

# Conciliación distinguida por origen de documento en mpro (Compra, Gasto_Registro,
# Cuenta_x_Pagar, Cheque, Nota_Credito_Proveedor, Compra_Indirecto) — el nivel de
# detalle más profundo, con cuadre documento-a-documento Y cuadre agregado por origen
python3 reconciliacion_por_origen.py --periodo 2026-02

# Baseline conciliados/pendientes (doble chequeo cargo=subtotal Y abono=total,
# via Serie+Folio del CFDI) — por ahora validado para origen COMPRA
python3 baseline_conciliacion.py --periodo 2026-02 --origen COMPRA

# Baseline UNIVERSAL (todos los origenes a la vez, chequeo agregado de un
# solo lado: cargo=subtotal, sumando TODOS los documentos con los que un
# CFDI aparece etiquetado en mpro, sin importar el origen)
python3 baseline_universal.py --periodo 2026-02

# Reporte interactivo (Streamlit) sobre el baseline universal
streamlit run streamlit_app_conciliacion.py --server.port 8507
```

Cada script imprime su avance y termina escribiendo un `.xlsx` en `output/`
(no versionado — ver `.gitignore`) con hojas de resumen y detalle, semaforeado
por color.

## GUI de revisión

Dos formas de revisar la conciliación sin abrir el `.xlsx`, con datos
en vivo (consultan la base directo, no un snapshot):

- **`streamlit_app_conciliacion.py`** — reporte interactivo sobre el
  baseline universal: selector de periodo(s), filtros por origen/RFC/
  proveedor, KPIs, tablas de conciliados/pendientes con descarga a Excel,
  y gráficas por vía de cuadre / motivo pendiente. Ver Quickstart arriba.
- Un dashboard más viejo (Artifact HTML, publicado desde Cowork) con
  totales y % de cuadre por origen — es un **snapshot estático** de los
  datos de este README (no consulta la base en vivo); se regenera
  pidiéndole a Cowork que lo actualice.

## Estructura del repo

```
src/
  bridge_client.py            Conexión directa a las 3 bases (SQLAlchemy, guard de solo lectura)
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
  reconcile.py                  Cruce SAT vs mpro a nivel CFDI + clasificación
  report.py                     Reporte .xlsx (colores por estatus)

main.py                        CLI: conciliación base (nivel CFDI)
poliza_reconciliation.py       CLI: conciliación a nivel póliza (piloto, origen-agnóstico)
reconciliacion_por_origen.py   CLI: conciliación por origen de documento (el más completo)
streamlit_app_conciliacion.py  Reporte interactivo sobre baseline_universal.calcular()

docs/
  arquitectura.md              Conexión directa a las 3 bases, historia de la bridge, mssql_205 vs mssql_207
  metodologia.md                Cómo se define "cuadra": base, tolerancias, nivel documento vs agregado
  hallazgos.md                  Bugs y patrones reales encontrados (con evidencia)
  resultados_2026-02.md         Resultados concretos, febrero 2026 recibidos
  pendientes.md                 Qué falta y por qué (emitido, retención, orígenes sin resolver)
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
  repartido entre sucursales…).
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
- 🟡 Emitidos: ingest ya trajo enero 2026 completo (6,500 CFDI) — nivel 1
  corrido y validado (99.8% OK), censo de origen hecho (FACTURA,
  NOTA_CREDITO, COMPROBANTE_PAGO, TRASLADO). Falta el resto del histórico
  y el nivel 3 (documento → póliza) — ya desbloqueado, ver abajo.
- 🟡 Retención: el mapeo a mpro que antes no aparecía **ya se encontró**
  (`Comprobante_Digital.Cd_Tabla='CONSTANCIA_RETENCION'`) pero solo cubre
  el 36% de los CFDI de enero 2026 (16 de 45) — el resto no tiene ninguna
  fila en mpro, causa sin resolver. Ver `pendientes.md`.
- ✅ `Poliza_Control` **volvió a responder** (2026-09-09) — estuvo caída
  desde 2026-09-07. Desbloquea todo el trabajo de nivel 3 pendiente
  (emitidos, retención). Ver `hallazgos.md` punto 13.
- 🔧 Mientras 207 (la base "buena") está en desarrollo, el pipeline corre
  contra 205 (`src/config.py:MPRO_TARGET`), acotado a enero–junio 2026.

## Continuidad — para retomar el trabajo en otra sesión

Ver [`PROGRESS.md`](PROGRESS.md): estado actual, método validado, pendientes
por origen con lo ya investigado de cada uno, y cómo seguir. Es el punto de
entrada pensado para que otra sesión de Claude Code retome el trabajo sin
tener que releer todo el historial.
