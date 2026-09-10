# PROGRESS — para retomar el trabajo en otra sesión

> Punto de entrada pensado para que otra sesión de Claude Code (u otro
> agente) pueda continuar este proyecto sin releer todo el historial de
> conversación. Si algo de aquí queda desactualizado, corregirlo en el
> mismo commit que cambie el código — es más valioso que esté al día que
> completo.

> **Reorganización 2026-09-10**: los scripts de este PROGRESS se movieron a
> carpetas por dominio × nivel (`recibidos/nivel_documento/`,
> `recibidos/nivel_poliza/`, `emitidos/nivel_documento/`,
> `emitidos/nivel_poliza/`, `retencion/cruce_sat/`,
> `layout_gastos_poliza/`) — ver el mapa completo y el porqué en
> `README.md`. Este documento no repite esa estructura, solo referencia los
> scripts por su nombre; si un comando no corre, buscar el archivo en el
> árbol de `README.md` antes de asumir que se perdió. También se
> consolidaron aquí los proyectos hermanos `adjuntar-xml` y
> `conciliacion-emitidos` (retirados tras portarse), y `funcionales-
> auditoria` pasó a su propio repo, `ehalso/reportes-mpro`.

## Qué es este proyecto

Conciliación automatizada entre CFDI (facturas electrónicas) recibidos
por Trivasa, timbrados ante el SAT, y sus registros contables en
Management Pro / mpro (ERP en SQL Server). La pregunta de negocio: **¿qué
documentos de mpro corresponden a cada CFDI, y el importe contabilizado
cuadra con el importe fiscal del CFDI?**

Conexión **directa** (SQLAlchemy vía `src/bridge_client.py`, credenciales en
`.env` local) a las tres bases de Trivasa — Postgres `raw_sat` y los dos SQL
Server de mpro — detalle en `docs/arquitectura.md`. Es **estrictamente de
solo lectura** (`_guard_readonly` valida cada SQL) — nunca se intenta un
write/DDL/DML. El modo anterior, una API puente HTTP
(`https://reportesweb.frento.com.mx/query`), queda deprecado como fallback
histórico — `bridge_client.py` conservó el mismo contrato así que ningún
extractor cambió al migrar.

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
python3 recibidos/nivel_poliza/baseline_universal.py --periodo 2026-02
```

**Lo primero que hay que leer para retomar RECIBIDOS es
[`docs/investigacion_pendientes.md`](docs/investigacion_pendientes.md)**: trae
los hallazgos que subieron el porcentaje, las nueve vías de cuadre con su
evidencia, y la clasificación de los 61 pendientes que quedan.

Pendientes que quedan (61 en el semestre), por familia:

| Familia | CFDI | Monto | Estado |
|---|---:|---:|---|
| Nómina: IMSS | 16 | $7.88M | **No filtrar del universo, no crear una vía de cuadre dedicada — confirmado con Esteban 2026-09-10: son errores de captura reales, no un patrón estructural a modelar.** Se les aplica exactamente la misma Regla 1 (cargo=subtotal) que a cualquier otro CFDI del universo, sin excepción ni regla especial — si no cuadra por ahí, se queda como no conciliado, y eso es correcto. El ratio cargo/subtotal no es una proporción fija (0.14-0.48 en el análisis original de H1; 0.88-0.94 en una muestra de 5/6 de febrero, un sexto en ~0.50) — esa variabilidad es la señal de que es error de captura, no una fórmula patronal/obrera consistente que valga la pena modelar como regla propia |
| Nómina: INFONAVIT | 4 | $2.46M | Mismo mecanismo — misma instrucción: no filtrar, no regla especial |
| Crédito bancario | 11 | $1.60M | El CFDI de intereses no coincide con el interés posteado; requiere la tabla de amortización del contrato |
| Cheque consolidado | 15 | $58K | Cheques que liquidan facturas de otros periodos (uno de 2024) — revisar si la etiqueta apunta al cheque correcto |
| Agencia aduanal | 6 | $50K | El folio agrupa el pedimento completo; el CFDI del agente es solo una parte |
| SAT | 2 | $43K | `Grc_Importe` simbólico de $0.01: el pago de impuestos no se registra como gasto |
| CONAGUA | 4 | $12K | **Captura parcial real** — solo entran actualización y recargos; los derechos no pasan por el módulo. Reportable al cliente |
| Otros | 3 | $45K | Casos sueltos |

## Rendimiento (2026-09-10): `nivel_documento` sin XML, `baseline_universal.py` con menos consultas — paralelizar queda pendiente

`recibidos/nivel_documento/conciliacion_xml_lib.py` (reportes `03_`/`04_`/
`05_`) dejó de parsear `Cd_XML` — lee `raw_sat.cfdi_recibidos` (10 columnas
nuevas pedidas al ELT el mismo día: `ret_iva`/`ret_isr`, complemento Pagos,
ValesDeDespensa, etc.), validado idéntico contra el pipeline viejo salvo un
gap de backfill real (18 UUID). Se agregó estatus dedicado `SIN_RAW_SAT_
CANCELADO`/`SIN_RAW_SAT_PENDIENTE` para no confundir ese hueco con un
descuadre — **ojo con la regla exacta** (solo aplica si TODOS los UUID del
grupo faltan, no si falta uno solo — ver el detalle de por qué en el punto
34 de abajo, casi se tapó un hallazgo real). De paso se encontró que
`raw_sat.iva` es solo IVA (no el total de impuestos trasladados) —
documentado en `trivasa-context/docs/schema/calidad-de-datos.md`.

`baseline_universal.py` (nivel_poliza) bajó de 143 a 125 consultas por
corrida fusionando dos pares de consultas redundantes (misma tabla, mismo
folio, columnas distintas). Instrumentando `bridge_client.run_query` se
confirmó que el ~95% del tiempo de una corrida (118s) es esperar
respuestas secuenciales de `mssql_205` (~900ms/consulta) — **paralelizar
los lotes de consulta (son independientes entre sí) es el siguiente paso
obvio de rendimiento y NO está hecho todavía**; medir primero cuántas
conexiones concurrentes tolera `.205`. Detalle completo, números exactos y
qué se descartó en `docs/hallazgos.md` puntos 34-35.

## EMITIDOS y RETENCIONES (nuevo, 2026-09-10) — 100% de conciliación + hallazgo SAT

Portado del proyecto hermano `~/proyectos/conciliacion-master/
conciliacion-emitidos` (documentación subida por Esteban), sin parsear XML
(usa `Cd_Monto` directo + `raw_sat.cfdi_retencion` ya parseado desde la
ingesta — ver `docs/hallazgos.md` punto 30). **`conciliacion_emitidos_
documento.py`** da 100.00% en los 6 meses de H1 2026 (14,554/14,554 CFDI de
factura, nota de crédito y retenciones). Esto confirma que el lado emitido
no tiene problema de importes por construcción.

El hallazgo real está en **`retencion_reconciliation.py`** (cruce independiente
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
   **`retencion_reconciliation.py`** (cruce independiente SAT vs ERP) — el
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

- **Solo lectura contra las bases** — nunca escribir/DDL/DML contra
  `mssql_205`/`mssql_207`/`postgres_dw` (`_guard_readonly` en
  `bridge_client.py` lo valida por texto, pero no reemplaza el criterio).
- **Credenciales**: `.env` local (gitignored, plantilla en `.env.example`)
  o variables de entorno — nunca hardcodeadas, nunca en el repo. El token
  de la bridge HTTP deprecada (`QUERY_API_TOKEN`) ya no hace falta salvo
  que una sesión futura vuelva a correr sin ruta de red directa.
- **`.gitignore`** excluye `.env`, `output/`, `*.xlsx`, `*.parquet`,
  `.query_api_token`, `*.token` — no versionar salidas ni credenciales.
- **Push**: `git push` directo funciona si la sesión lo corre
  interactivamente (el usuario lo autoriza); si el propio agente lo intenta
  automatizado puede quedar bloqueado por el clasificador de auto mode —
  en ese caso pedirle al usuario que lo corra él (`! git push ...`).
- **Alcance temporal**: mientras el pipeline corre contra `mssql_205`
  (`src/config.py:MPRO_TARGET`), el rango acordado con Esteban es
  **enero–junio 2026**. No correr fuera de ese rango sin antes validar
  cobertura de mes (mismo chequeo que se hizo para confirmar H1: contar
  filas por mes en `Poliza` y `Comprobante_Digital`).
- **Repo hermano `ehalso/trivasa-context`**: documentación de estructura,
  esquemas y calidad de datos de TODO mpro, mantenida por otras sesiones
  además de esta. Revisarlo antes de investigar un patrón nuevo — es
  común que ya esté documentado ahí (`docs/schema/calidad-de-datos.md`,
  `docs/proyectos/poliza-explor/`, `docs/proyectos/layout-gastos/`,
  `docs/proyectos/conciliacion-cfdi/` — la entrada de este mismo proyecto).
  Actualizarlo con hallazgos genéricos de estructura/esquema/calidad de
  dato (no específicos de este proyecto de conciliación) para que el
  resto del ecosistema se beneficie.

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

## Retención — nivel 1 construido y corrido para H1 2026, dos conceptos distintos identificados (2026-09-09/10)

**Nuevo**: `src/extract_retencion.py` + `retencion_reconciliation.py` —
nivel 1 (existencia + cuadre de `monto_total_operacion` SAT vs `Cd_Monto`
mpro, sin parsear XML: el XML de retención en mpro NO es un CFDI normal,
ver `docs/hallazgos.md` punto 28).

**Hay dos tipos de retención de ISR completamente distintos bajo el mismo
`cve_retenc`** (`hallazgos.md` punto 29): `cve_retenc=14` (arrendamiento/
honorarios, 10%, se emite cada ~4 meses, concilia 100% vía
`CONSTANCIA_RETENCION`) y `cve_retenc=16` (intereses a prestamista, 20%,
mensual, **nunca** pasa por `CONSTANCIA_RETENCION`). Para `cve=16` el gasto
SÍ está bien capturado en `Gasto_Registro` (verificado exacto, folio por
folio) — lo que falta es solo el *link* en `Comprobante_Digital`, por dos
mecanismos reales y distintos: omisión pura (un lote de 15 CFDI de febrero
nunca se etiquetó) y CFDI sustituido sin re-ligar (`CfdiRetenRelacionados`
apuntando a un UUID viejo/cancelado). Detalle completo en `docs/pendientes.md`
(sección Retención) y `docs/hallazgos.md` puntos 28-29.

Siguiente paso natural para retención: (1) construir el fallback por RFC+
proveedor+mes+monto contra `Gasto_Registro_Documento` para `cve=16` (recupera
el mecanismo de omisión sin depender del link), (2) seguir
`CfdiRetenRelacionados` para el mecanismo de sustitución, (3) nivel 3 — trazar hasta `Poliza_Control` para el
cargo/abono real de lo que sí concilia.

## Siguiente paso más obvio

1. **Familia nómina (IMSS/INFONAVIT: 20 CFDI, $10.3M)** — es el 85% del monto
   pendiente de recibidos. **Confirmado con Esteban 2026-09-10: NO conciliar
   en agregado, NO modelar la separación patronal/obrera, y NO filtrarlos del
   universo** — se les aplica la misma Regla 1 (cargo=subtotal) que a
   cualquier otro CFDI, sin ninguna vía de cuadre dedicada. Son errores de
   captura reales; que la lógica estándar los deje como no conciliados es el
   comportamiento correcto. La variabilidad del ratio cargo/subtotal entre
   distintos CFDI de la misma familia (0.14-0.48 en el análisis original de
   H1; 0.88-0.94 en una muestra de febrero) es la señal de que no hay una
   proporción fija que valga la pena modelar como regla propia.
2. **Extender el chequeo al lado del abono/pago** (recibidos). Todo lo de
   arriba sigue siendo un chequeo de UN SOLO LADO (cargo). El doble chequeo
   existe solo para COMPRA (`baseline_conciliacion.py`).
3. **Reporte de cobranza para emitidos** (REP vs `Pago_CXC`/`DoctoRelacionado`),
   portando la metodología del proyecto hermano
   (`~/proyectos/conciliacion-master/conciliacion-emitidos`, reportes 02/03,
   ya con 96.18% medido ahí).
4. **Correr `retencion_reconciliation.py` sobre meses posteriores a junio** para
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
6. **Retención**: nivel 1 y nivel 3 (`retencion/nivel_poliza/baseline_retencion.py`,
   2026-09-10) ya construidos y corridos — nivel 3 es granular por CFDI
   (mismo método que `baseline_universal.py`: ubicar cada UUID en
   `Comprobante_Digital`, sumar su cargo real vía `Gasto_Registro_Control`,
   comparar contra `monto_total_operacion`), deliberadamente NO al 100%
   (35.6% en los 3 periodos probados: nov-2025 6.7%, ene-2026 100%,
   feb-2026 0%) — sirve para exponer errores reales, no para promediarlos.
   Pendiente:
   (a) fallback por RFC+proveedor+mes+monto contra `Gasto_Registro_Documento`
   para recuperar el mecanismo de omisión de `cve=16` sin depender del link;
   (b) **pedirle al ELT que agregue `CfdiRetenRelacionados` (UUID
   relacionado + `TipoRelacion`) como columna nueva de
   `raw_sat.cfdi_retencion`**, en vez de parsear el XML en vivo por cada
   pendiente — confirmado en vivo 2026-09-10 que el mecanismo de sustitución
   es sistemático (13 de 15 CFDI de retención de intereses de noviembre 2025
   se re-timbraron en bloque el 22-ene-2026, y `Comprobante_Digital` se
   quedó apuntando al UUID viejo/invalidado en cada caso). Con esa columna
   ya ingerida, `baseline_retencion.py` podría reintentar cada pendiente
   `SIN_MAPEO` contra el UUID relacionado antes de reportarlo como error, y
   el mismo campo serviría para el hub de Streamlit (`retencion_cruce_sat.py`
   del PR #1) para mostrar "sustituido, ver UUID X" en vez de "no encontrado".
7. Tres hallazgos de estructura/calidad de dato de la sesión de recibidos
   (2026-09-09/10) que valen para `trivasa-context` — ver la lista en
   `docs/investigacion_pendientes.md`, Parte 4 (ya subidos ahí).
8. **Paralelizar las consultas batched de `baseline_universal.py`** (y de
   los extractores que llama) — hoy son secuenciales y ~900ms/consulta ×
   125 consultas es prácticamente todo el tiempo de una corrida (ver
   `docs/hallazgos.md` punto 35). Medir antes cuántas conexiones
   concurrentes tolera `mssql_205` sin degradarse; probable candidato:
   `ThreadPoolExecutor` sobre `bridge_client.run_query`, o paralelizar cada
   loop de lotes por origen dentro de cada extractor.
9. Backfill en `raw_sat.cfdi_recibidos` de los 15 UUID de enero 2026 que
   siguen vigentes (`AC`) en mpro pero no tienen match ahí — no son
   cancelados, es un gap real de cobertura del ELT/mount (ver
   `docs/hallazgos.md` punto 34).
