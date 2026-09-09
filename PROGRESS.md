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

**El método vigente es `baseline_universal.py`, no `main.py` ni
`reconciliacion_por_origen.py`.** Para CFDI recibidos, suma el cargo de
TODOS los documentos con los que un CFDI aparece etiquetado en
`Comprobante_Digital` (sin importar el origen/módulo de mpro) y compara esa
suma contra la base fiscal del CFDI. Tras la sesión de investigación folio por
folio del 2026-09-09/10, el chequeo ya no es una sola comparación sino una
**cascada de vías de cuadre**, cada una con su etiqueta en el reporte.

Resultado en vivo, **todo H1 2026**:

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

**Lo primero que hay que leer para retomar es
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

## Qué método usar para seguir — y por qué

1. **`baseline_universal.py`** (el método actual, agregado, todos los
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
tres documentos de referencia que hay que mantener al día:

- **`README.md`** — estado general, un párrafo por frente de trabajo.
- **`docs/pendientes.md`** — el documento más detallado: qué falta y por
  qué, con evidencia y ejemplos reales, organizado por origen/tema.
- **`docs/hallazgos.md`** — bitácora numerada de bugs y patrones
  confirmados con evidencia (queries, ejemplos reales) — el historial
  técnico completo, en orden cronológico.

## Siguiente paso más obvio

1. **Subir a GitHub el trabajo del 2026-09-09/10** (quedó pedido
   explícitamente que NO se hiciera push esa noche): incluye la corrección del
   punto 16 de `hallazgos.md`, que estaba mal, y tres hallazgos de
   estructura/calidad de dato que valen para `trivasa-context` — ver la lista
   en `docs/investigacion_pendientes.md`, Parte 4.
2. **Familia nómina (IMSS/INFONAVIT: 20 CFDI, $10.3M)** — es el 85% del monto
   pendiente. Para cuadrarla hay que separar cuota patronal de obrera y
   repartir la póliza consolidada de provisión entre los CFDI que la componen.
   Alternativa más barata: conciliarla **en agregado** (todos los CFDI del IMSS
   del mes contra el total provisionado).
3. **Extender el chequeo al lado del abono/pago.** Todo lo de arriba sigue
   siendo un chequeo de UN SOLO LADO (cargo). El doble chequeo existe solo para
   COMPRA (`baseline_conciliacion.py`).
4. **Correr emitidos y retención** con el mismo método — ya está desbloqueado.
