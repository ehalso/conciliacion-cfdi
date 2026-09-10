# PROGRESS — para retomar el trabajo en otra sesión

> Punto de entrada pensado para que otra sesión de Claude Code (u otro
> agente) pueda continuar este proyecto sin releer todo el historial de
> conversación. Si algo de aquí queda desactualizado, corregirlo en el
> mismo commit que cambie el código — es más valioso que esté al día que
> completo.

## Qué es este proyecto

Conciliación automatizada entre CFDI (facturas electrónicas) recibidos
por Trivasa, timbrados ante el SAT, y sus registros contables en
Management Pro / mpro (ERP en SQL Server). La pregunta de negocio: **¿qué
documentos de mpro corresponden a cada CFDI, y el importe contabilizado
cuadra con el importe fiscal del CFDI?**

Arquitectura en dos partes (detalle en `docs/arquitectura.md`): una API
puente de solo lectura (`https://reportesweb.frento.com.mx/query`,
mantenida en otra máquina) expone las bases de datos; este repo hace toda
la extracción, parseo y lógica de conciliación. El bridge es
**estrictamente de solo lectura** — nunca se intenta un write/DDL/DML
contra él.

## Estado actual (2026-09-10) — leer esto primero

**El método vigente para RECIBIDOS es `baseline_universal.py`, no `main.py` ni
`reconciliacion_por_origen.py`.** Para CFDI recibidos, suma el cargo de
TODOS los documentos con los que un CFDI aparece etiquetado en
`Comprobante_Digital` (sin importar el origen/módulo de mpro) y compara esa
suma contra la base fiscal del CFDI. Tras la sesión de investigación folio por
folio del 2026-09-09/10, el chequeo ya no es una sola comparación sino una
**cascada de vías de cuadre**, cada una con su etiqueta en el reporte.

Resultado en vivo, **todo H1 2026** (recibidos):

| Periodo | Universo | Conciliados | % | Pendientes |
|---|---:|---:|---:|---:|
| 2026-01 | 1,585 | 1,572 | 99.2% | 13 |
| 2026-02 | 1,500 | 1,492 | 99.5% | 8 |
| 2026-03 | 1,736 | 1,722 | 99.2% | 14 |
| 2026-04 | 1,775 | 1,771 | 99.8% | 4 |
| 2026-05 | 1,545 | 1,532 | 99.2% | 13 |
| 2026-06 | 1,431 | 1,422 | 99.4% | 9 |
| **H1** | **9,572** | **9,511** | **99.36%** | **61** |

(febrero venía en 90.1% antes de esa sesión)

```bash
python3 baseline_universal.py --periodo 2026-02
```

**Lo primero que hay que leer para retomar RECIBIDOS es
[`docs/investigacion_pendientes.md`](docs/investigacion_pendientes.md)**: trae
los hallazgos que subieron el porcentaje, las nueve vías de cuadre con su
evidencia, y la clasificación de los 61 pendientes que quedan.

Pendientes que quedan (61 en el semestre), por familia:

| Familia | CFDI | Monto | Estado |
|---|---:|---:|---|
| Nómina: IMSS | 16 | $7.88M | Estructural: el CFDI mezcla cuota patronal (gasto) y obrera (retención), y la póliza de provisión consolida varios CFDI. Requiere modelar la provisión de nómina |
| Nómina: INFONAVIT | 4 | $2.46M | Mismo mecanismo |
| Crédito bancario | 11 | $1.60M | El CFDI de intereses no coincide con el interés posteado; requiere la tabla de amortización del contrato |
| Cheque consolidado | 15 | $58K | Cheques que liquidan facturas de otros periodos (uno de 2024) — revisar si la etiqueta apunta al cheque correcto |
| Agencia aduanal | 6 | $50K | El folio agrupa el pedimento completo; el CFDI del agente es solo una parte |
| SAT | 2 | $43K | `Grc_Importe` simbólico de $0.01: el pago de impuestos no se registra como gasto |
| CONAGUA | 4 | $12K | **Captura parcial real** — solo entran actualización y recargos; los derechos no pasan por el módulo. Reportable al cliente |
| Otros | 3 | $45K | Casos sueltos |

## EMITIDOS y RETENCIONES (nuevo, 2026-09-10) — 100% de conciliación + hallazgo SAT

Portado del proyecto hermano `~/proyectos/conciliacion-master/
conciliacion-emitidos` (documentación subida por Esteban), sin parsear XML
(usa `Cd_Monto` directo + `raw_sat.cfdi_retencion` ya parseado desde la
ingesta — ver `docs/hallazgos.md` punto 30). **`conciliacion_emitidos_
documento.py`** da 100.00% en los 6 meses de H1 2026 (14,554/14,554 CFDI de
factura, nota de crédito y retenciones). Esto confirma que el lado emitido
no tiene problema de importes por construcción.

El hallazgo real está en **`cruce_sat_retenciones.py`** (cruce independiente
contra `raw_sat.cfdi_retencion`, que no pasa por el ERP): **29 constancias
de retención por $536,597.04 ($107,319.45 de ISR) que el SAT tiene timbradas
y el ERP nunca registró** — 14 en enero (ya conocidas), 15 más en febrero
(hallazgo nuevo). Ver [`docs/emitidos_retenciones.md`](docs/emitidos_retenciones.md).

Pendiente en este frente: reporte de cobranza (REP, `Pago_CXC`/`DoctoRelacionado`)
y correr el cruce SAT sobre meses posteriores a junio.

## Qué método usar para seguir — y por qué

1. **`baseline_universal.py`** (recibidos, el método actual, agregado, todos los
   orígenes) — usar esto para cualquier pregunta de "¿cuánto cuadra en
   total" o "¿qué le falta a este CFDI". Es un chequeo de **un solo
   lado**: cargo=subtotal. No exige que el abono/pago también cuadre.
2. **`baseline_conciliacion.py`** — método de doble chequeo (cargo+abono)
   pero solo para COMPRA (81.8%). Útil como referencia de qué se necesita
   para verificar también el lado del pago, pendiente extender a los
   demás orígenes.
3. **`reconciliacion_por_origen.py`** y **`main.py`** — métodos más viejos,
   por-origen o solo a nivel CFDI. Ya no son el punto de partida para
   trabajo nuevo, pero el código de extracción que usan
   (`extract_poliza_por_origen.py`, `extract_origen.py`) sigue siendo la
   base de `baseline_universal.py`.
4. **`conciliacion_emitidos_documento.py`** (emitidos, factura/NC/retenciones) y
   **`cruce_sat_retenciones.py`** (cruce independiente SAT vs ERP) — el
   frente nuevo. Ver docs/emitidos_retenciones.md.

**Patrón de trabajo que ha funcionado bien esta sesión** (drill-down
dirigido por Esteban): para cada origen con pendientes, tomar 1-2 CFDI
concretos, mostrar sus documentos relacionados en mpro
(`extract_origen.extract_origenes_por_uuids`), su póliza real
(`Poliza_Control` → `Poliza` → `Poliza_Detalle`), y — cuando algo no
cuadra — revisar la `Poliza_Configuracion`/`Poliza_Configuracion_Detalle`
que la generó (`Poliza.Pl_Configuracion` → fórmulas de Cargo/Abono/
Referencia) para distinguir un **bug de nuestro método** de un **error
real de datos en mpro**. Repetir esto por origen es más productivo que
intentar una regla general de entrada.

## Constricciones que hay que seguir respetando

- **Bridge de solo lectura** — nunca escribir/DDL/DML contra
  `mssql_205`/`mssql_207`/`postgres_dw`.
- **Token de la bridge API**: solo en `/home/claude/.query_api_token`
  (chmod 600) o `QUERY_API_TOKEN` env var — nunca en memoria, nunca en el
  repo (`.gitignore` ya lo excluye).
- **`.gitignore`** excluye `output/`, `*.xlsx`, `*.parquet`,
  `.query_api_token`, `*.token` — no versionar salidas ni credenciales.
- **Push**: usar el MCP de GitHub (`mcp__Repo_Privado__push_files` o
  equivalente) — `git push` crudo está bloqueado por una restricción de
  proxy a nivel de sesión.
- **Alcance temporal**: mientras el pipeline corre contra `mssql_205`
  (`src/config.py:MPRO_TARGET`), el rango acordado con Esteban es
  **enero–junio 2026**. No correr fuera de ese rango sin antes validar
  cobertura de mes (mismo chequeo que se hizo para confirmar H1: contar
  filas por mes en `Poliza` y `Comprobante_Digital`).
- **Repo hermano `ehalso/trivasa-context`** (clonado en `/tmp/` en
  sesiones de Cowork, o donde corresponda): documentación de estructura,
  esquemas y calidad de datos de TODO mpro, mantenida por otras sesiones
  además de esta. Revisarlo antes de investigar un patrón nuevo — es
  común que ya esté documentado ahí (`docs/schema/calidad-de-datos.md`,
  `docs/proyectos/poliza-explor/`, `docs/proyectos/layout-gastos/`).
  Actualizarlo con hallazgos genéricos de estructura/esquema/calidad de
  dato (no específicos de este proyecto de conciliación) para que el
  resto del ecosistema de sesiones se beneficie.

## Dónde está cada cosa

Ver `README.md` para la estructura completa del repo y quickstart. Los
documentos de referencia que hay que mantener al día:

- **`README.md`** — estado general, un párrafo por frente de trabajo.
- **`docs/pendientes.md`** — historial de cómo se veía el problema de
  recibidos antes de la investigación folio por folio (documento
  superado, se conserva por contexto).
- **`docs/investigacion_pendientes.md`** — el documento vigente sobre
  recibidos: método, vías de cuadre, clasificación de pendientes.
- **`docs/hallazgos.md`** — bitácora numerada de bugs y patrones
  confirmados con evidencia (queries, ejemplos reales) — el historial
  técnico completo, en orden cronológico.
- **`docs/emitidos_retenciones.md`** — conciliación de emitidos y
  retenciones, y el hallazgo del cruce contra el SAT.

## Siguiente paso más obvio

1. **Familia nómina (IMSS/INFONAVIT: 20 CFDI, $10.3M)** — es el 85% del monto
   pendiente de recibidos. Para cuadrarla hay que separar cuota patronal de obrera y
   repartir la póliza consolidada de provisión entre los CFDI que la componen.
   Alternativa más barata: conciliarla **en agregado** (todos los CFDI del IMSS
   del mes contra el total provisionado).
2. **Extender el chequeo al lado del abono/pago** (recibidos). Todo lo de arriba sigue
   siendo un chequeo de UN SOLO LADO (cargo). El doble chequeo existe solo para
   COMPRA (`baseline_conciliacion.py`).
3. **Reporte de cobranza para emitidos** (REP vs `Pago_CXC`/`DoctoRelacionado`),
   portando la metodología del proyecto hermano
   (`~/proyectos/conciliacion-master/conciliacion-emitidos`, reportes 02/03,
   ya con 96.18% medido ahí).
4. **Correr `cruce_sat_retenciones.py` sobre meses posteriores a junio** para
   ver si el patrón de retenciones faltantes sigue.
5. **Emitidos, nivel 3 vía póliza (rama `emitido`, worktree
   `reconciliacion-cowork_emitido`): arrancado 2026-09-10**
   (`baseline_universal_emitido.py`). **NOTA_CREDITO ya es un resultado
   confiable: 99.5% (187/188)** — separar el Cargo por cuenta contable
   (devolución de mercancía vs reversión de costo de venta, ver
   `docs/hallazgos.md` punto 29) resolvió lo que parecía ruido. **FACTURA
   sigue sin método nivel 3 funcional** (0.6%, el 92% del universo
   monetario) — la póliza de ingreso de VENTA no aísla el documento por
   `Pd_Referencia` como sí hacen recibidos y NOTA_CREDITO; ver
   `docs/hallazgos.md` punto 28 y `docs/pendientes.md` sección Emitidos para
   el detalle completo y la recomendación (preguntar a Trivasa cómo se
   referencia el documento en esa póliza, o probar un chequeo agregado por
   sucursal/día en vez de por CFDI). Distinto de los puntos 3-4 arriba
   (pregunta "¿cuadra la póliza contable?", no "¿cuadra el documento?").
