# Emitidos — cruce independiente contra el SAT (pendiente)

Carpeta reservada, aún sin construir (2026-09-10). El equivalente para
FACTURA/NOTA_CREDITO de lo que `retencion/cruce_sat/retencion_reconciliation.py`
ya hace para las constancias de retención: comparar `raw_sat.cfdi_emitidos`
(fuente **independiente** del ERP) contra `Comprobante_Digital`, para
detectar un CFDI emitido que se timbró y el ERP nunca registró.

Por qué no está construido todavía: `raw_sat.cfdi_emitidos` solo tiene
backfill hasta enero 2026 (ver `docs/emitidos_retenciones.md`) — correrlo
para febrero-junio daría ceros que parecen hallazgo pero son el backfill
pendiente, no un hueco real. En cuanto el backfill avance, este cruce es
directo (mismo patrón que `retencion_reconciliation.py`, solo cambia la
tabla origen y que FACTURA/NOTA_CREDITO no tienen el gotcha de "fila
hermana" que sí tienen las retenciones).
