# Recibidos — cruce independiente contra el SAT (pendiente)

Carpeta reservada, aún sin construir (2026-09-10). El equivalente para
recibidos de lo que `retencion/cruce_sat/retencion_reconciliation.py` ya
hace para retención: comparar `raw_sat.cfdi_recibidos` (fuente
**independiente** — el XML que el PAC deja en el share del SAT, cargado a
Postgres sin pasar por el ERP) contra `Comprobante_Digital`, para detectar
un CFDI recibido que el ERP nunca registró en ningún módulo.

Por qué vale la pena: todo lo que hoy existe del lado recibido
(`recibidos/nivel_documento/`, `recibidos/nivel_poliza/`) parte de
`Comprobante_Digital` — es decir, de lo que el ERP **dice que tiene**. Ninguno
de los dos puede ver, por construcción, un CFDI que llegó del proveedor y
nunca se capturó en ningún lado. `raw_sat.cfdi_recibidos` sí tiene cobertura
completa de 2026 (ver `docs/hallazgos.md`), así que el cruce ya es viable
con los datos que hay — solo falta escribirlo, siguiendo el mismo patrón
que `retencion_reconciliation.py`.
