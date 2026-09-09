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

## Estado actual (2026-09-09) — leer esto primero

**El método vigente es `baseline_universal.py`, no `main.py` ni
`reconciliacion_por_origen.py`.** Para CFDI recibidos, suma el cargo de
TODOS los documentos con los que un CFDI aparece etiquetado en
`Comprobante_Digital` (sin importar el origen/módulo de mpro) y compara
esa suma contra el Subtotal del CFDI — en vez de exigir que un solo
documento cuadre exacto. Resultado en vivo, feb-2026:

```
Universo monetario en mpro: 1,500   Conciliados: 1,351 (90.1%)   Pendientes: 149
```

```bash
python3 baseline_universal.py --periodo 2026-02
```

Pendientes por origen (149 total):

| Origen | n pendientes | Qué se sabe |
|---|---:|---|
| GASTO_REGISTRO | 74 | Ver `docs/pendientes.md` — 3 patrones nuevos confirmados (arrendamiento financiero, captura duplicada de `Grc_Importe`, folio-agrupa-CFDI) más los ya conocidos de `layout-gastos` (CONSUMO_INTERNO, reversiones, NOMINA) sin portar |
| COMPRA | 40 | Sin drill-down dirigido esta sesión — candidatos: patrón GLM/liquidación directa vía Cheque, documento duplicado sin match (ver `docs/pendientes.md`) |
| CUENTA_X_PAGAR | 15 | Sin investigar caso por caso — `extract_poliza_por_origen()` no encuentra póliza en absoluto para estos |
| NOTA_CREDITO_PROVEEDOR | 13 | 0% de cuadre — el chequeo actual no maneja signo (una nota de crédito reduce el cargo, no lo iguala) |
| CHEQUE | 6 | Vía pago directo (liquidación sin pasar por COMPRA/GASTO_REGISTRO) |
| FACTURA | 1 | Volumen mínimo, no investigado |

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

De los 149 pendientes, **COMPRA (40 casos)** es el origen con más volumen
sin ningún drill-down dirigido esta sesión — aplicar el mismo patrón de
trabajo que se usó para Gasto_Registro (tomar CFDI concretos, revisar
documentos relacionados y configuración de póliza) es probablemente el
siguiente paso de mayor impacto. Después, extender el chequeo de signo a
NOTA_CREDITO_PROVEEDOR (0% de cuadre, causa ya diagnosticada — solo falta
implementar la lógica de reversión).
