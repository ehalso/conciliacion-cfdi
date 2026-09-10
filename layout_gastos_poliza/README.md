# Layout de gastos — reconciliación por CECO (Cargo/Abono vs Importe)

Consolidado aquí el 2026-09-10 desde `~/proyectos/conciliacion-master/layout-gastos`
(repo local, sin remote). Valida, folio por folio y centro de costo por
centro de costo, que el Cargo/Abono real posteado en `Poliza_Detalle`
cuadra contra el importe que reporta `Gasto_Registro_Control` — es la
contraparte "nivel_poliza" para Gasto_Registro, análoga a
`recibidos/nivel_poliza/` pero mucho más granular (llega a nivel línea de
póliza × cuenta contable × CECO).

Es también la fuente de desarrollo de las páginas CONT-1/CONT-2 ("Layout de
Gastos por CECO") que se copian a mano a `streamlit-reportes/contabilidad/`
para producción — ver `reportes_streamlit/layout_gastos_ceco/` en este
mismo repo para esa parte (UI), separada de la reconciliación (aquí).

Ver `PROGRESS.md` y `RESUMEN_CASOS.md` para el detalle completo de método y
casos ya resueltos — documentos largos, no repetidos en este README.

## Scripts (orden cronológico de creación, no de "etapa lógica")

`01`-`13`, numerados — ver el docstring de cada uno para su pregunta
específica. `07_reconciliacion_completa_ceco.py` es el más completo
(agrega los pasos anteriores); los scripts de más adelante (09, 12, 13)
extienden a consumo interno y nómina.

## Conexión

`connection_205_trivasadb3.py` — adaptado para leer `MSSQL_205_USER`/
`MSSQL_205_PASSWORD` del `.env` en la raíz de este repo (mismo que usa
`src/bridge_client.py`), en vez de depender de `trivasa-bi-core` (externo).
