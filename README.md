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

## Arquitectura en dos partes

Este proyecto se construyó dividido a propósito entre dos agentes:

- **Claude Code** (corriendo en la máquina `ctunlinux` de Esteban) construyó
  y mantiene **únicamente** una API puente de solo lectura
  (`https://reportesweb.frento.com.mx/query`) que expone tres bases de
  datos de Esteban sin que este repo necesite credenciales de base de datos
  directas.
- **Este repo / Cowork** hace *todo* lo demás: extracción, parseo de XML,
  lógica de conciliación, reportes .xlsx.

Detalle completo en [`docs/arquitectura.md`](docs/arquitectura.md).

## Quickstart

```bash
pip install -r requirements.txt

# El token de la bridge API NO se versiona. Se lee de:
#   - variable de entorno QUERY_API_TOKEN, o
#   - archivo en QUERY_API_TOKEN_FILE (default: /home/claude/.query_api_token)
export QUERY_API_TOKEN="..."

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
```

Cada script imprime su avance y termina escribiendo un `.xlsx` en `output/`
(no versionado — ver `.gitignore`) con hojas de resumen y detalle, semaforeado
por color.

## GUI de revisión

Hay un dashboard (Artifact HTML, publicado desde Cowork) para revisar la
conciliación sin abrir el `.xlsx`: totales y % de cuadre por origen, y
tabla de detalle documento-por-documento (recibido) o CFDI-por-CFDI
(emitido, retención), con búsqueda, filtros y orden por columna. Es un
snapshot estático de los datos de este README (no consulta la bridge en
vivo) — se regenera pidiéndole a Cowork que lo actualice con datos más
recientes.

## Estructura del repo

```
src/
  bridge_client.py            Cliente HTTP de la bridge API (auth, reintentos)
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

docs/
  arquitectura.md              Bridge API, split Cowork/Claude Code, mssql_205 vs mssql_207
  metodologia.md                Cómo se define "cuadra": base, tolerancias, nivel documento vs agregado
  hallazgos.md                  Bugs y patrones reales encontrados (con evidencia)
  resultados_2026-02.md         Resultados concretos, febrero 2026 recibidos
  pendientes.md                 Qué falta y por qué (emitido, retención, orígenes sin resolver)
```

## Estado (2026-09-09, actualizado el mismo día)

- ✅ Conciliación base nivel CFDI (recibidos): corrida y validada para
  ene/feb/ago 2026 y Q1 2026, ~99% OK.
- ✅ Censo de orígenes de documento en mpro para recibidos (qué módulos
  hay que reconciliar y cuánto $ representa cada uno).
- ✅ **Método de doble chequeo (cargo + abono) validado para COMPRA**:
  cargo (folio de compra) = Subtotal, Y abono (Serie+Folio del propio
  CFDI) = Total → **578/713 (81.1%) conciliados** para febrero 2026. Ver
  `baseline_conciliacion.py` y `pendientes.md`.
- ✅ Reconciliación por origen (Compra, Cheque, Cuenta_x_Pagar) con cuadre
  agregado 90–97% para febrero 2026.
- ⚠️ Gasto_Registro: cobertura real todavía baja (~37%) — requiere lógica
  adicional, ver `pendientes.md`.
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
