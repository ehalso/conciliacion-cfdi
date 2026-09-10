# Pendientes

Documento vigente de trabajo pendiente, por frente. El detalle técnico de
cómo se llegó al estado actual del lado recibido (fixes, cascada de reglas
de cuadre, cifras paso a paso) vive en
[`hallazgos.md`](hallazgos.md) puntos 20-26 y 34 — no se repite aquí.

## Recibidos — 99.36% H1 2026, quedan 61 CFDI sin cuadrar

Estado actual y desglose por familia: ver `hallazgos.md` punto 34. De ahí,
lo genuinamente accionable:

- **Extender el doble chequeo a cargo+abono** en todos los orígenes (hoy
  solo se verifica el cargo) — sigue pendiente.
- **Créditos bancarios (11 CFDI, $1.6M)**: requiere la tabla de amortización
  del contrato para separar interés devengado de interés facturado — dato
  fuera de este pipeline.
- **CONAGUA (4 CFDI, $12,187)**: captura parcial real confirmada (solo
  actualización + recargos, no los derechos de agua). Vale la pena
  preguntar a Trivasa si es intencional.
- **Cheque `01-0060062`** (FABRICA DE IMPLEMENTOS, 3 CFDI de feb-2026): la
  etiqueta apunta a un folio de cheque de enero 2024 — parece un error de
  captura, vale la pena confirmar el folio correcto.
- Nómina (IMSS/INFONAVIT, 20 CFDI, $10.3M) y los residuales de agencia
  aduanal/otros: **no requieren trabajo** — confirmado con Esteban
  (2026-09-10) que son errores de captura reales o límites de alcance, no
  un hueco de método.

## Emitidos

**Documento↔CFDI: resuelto, 100%** (14,554/14,554 conciliables, H1 2026).
Scripts: `conciliacion_emitidos_documento.py`, `retencion_reconciliation.py`.
Ver `docs/hallazgos.md` punto 30.

**Hallazgo real de negocio, ya identificado, falta llevarlo a Contabilidad**:
29 constancias de retención de intereses (`CveRetenc 16`) timbradas ante el
SAT que el ERP nunca registró — $536,597.04, $107,319.45 de ISR (14 de
enero, 15 de febrero, nada en marzo-junio). Correr
`retencion_reconciliation.py` sobre julio en adelante cuando esos meses
estén disponibles, para ver si el patrón sigue.

**Nivel 3 (vía póliza contable)**:

- NOTA_CREDITO: resuelto, 99.5% (187/188).
- FACTURA: **sin método funcional (0.6%, 13/2,191)** — la póliza de
  INGRESO de VENTA casi nunca aísla el documento por `Pd_Referencia`.
  Hipótesis sin confirmar: la venta se postea consolidada por
  sucursal/día (negocio POS/mostrador), no por CFDI individual —
  pendiente real, candidato para preguntar directo a Trivasa.

**Cobranza (REP)**: no portado todavía. El proyecto hermano
(`conciliacion-emitidos`) ya mide 96.18% de facturas con cobranza
conciliada (enero 2026) y encontró parcialidades cobradas sin timbrar y REP
timbrados por duplicado — portar con el mismo patrón (`bridge_client`, sin
XML) es el siguiente paso natural.

**Ingest incompleto**: `raw_sat.cfdi_emitidos` solo cubre 2026-01 completo;
falta el resto de 2025/2026 para igualar el rango de recibidos.

## Retención

Dos conceptos con comportamiento distinto (`cve_retenc` 14 vs 16, ver
`docs/hallazgos.md` punto 28):

- `cve=14` (arrendamiento/honorarios): 100% cuando se busca en el mes
  correcto — resuelto.
- `cve=16` (intereses, mensual): el link vía `Comprobante_Digital` falla
  por dos motivos (omisión de etiquetado, o CFDI sustituido sin re-ligar
  vía `CfdiRetenRelacionados`), aunque el gasto **sí está bien capturado**
  en `Gasto_Registro`. Pendientes reales, en orden de prioridad:
  1. Matchear por RFC receptor → `Gasto_Registro_Documento` del mismo mes
     como *fallback* cuando `Comprobante_Digital` no tenga fila para el
     UUID.
  2. Seguir `CfdiRetenRelacionados` cuando el UUID directo no aparezca en
     `Comprobante_Digital`.
  3. Nivel 3: trazar `folio_constancia`/`Gr_Folio` hasta `Poliza_Control`
     (ya no bloqueado — solo falta escribir el extractor, mismo patrón que
     `extract_poliza_por_origen.py`).
  4. Preguntar directamente a Trivasa por qué el lote de febrero (cve=16)
     nunca se etiquetó.

## Nota sobre alcance temporal

Mientras el pipeline corre contra `mssql_205` (ver `arquitectura.md`), el
alcance de fechas acordado con Esteban es **enero–junio 2026**. No se ha
confirmado cobertura de 205 fuera de ese rango — antes de correr un periodo
fuera de H1 2026, validar cobertura de mes (mismo chequeo que se hizo para
confirmar H1: contar filas por mes en `Poliza` y `Comprobante_Digital`).
