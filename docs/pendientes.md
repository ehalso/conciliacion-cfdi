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
- **Cheque `01-0060062`** (FABRICA DE IMPLEMENTOS MINEROS, RFC FIM700102AU6):
  confirmado en vivo 2026-09-11 — son **8 CFDI en total** (no solo los 3 de
  feb-2026), fechados 2024-01-11, 2024-09-03, 2025-11-06 (×2), 2026-01-30,
  2026-02-23, 2026-02-24, 2026-02-25, que suman **$60,395.38** contra un
  cheque de **$626,916.82** (2024-01-15, "ANTICIPO C/F A987 T.C 16.9898 BIEN
  O SERVICIO" — anticipo en USD). Póliza real del cheque: `Pl_Folio
  0000395288` (activa; hay una cancelada idéntica, `0000367538`) — ninguna
  liga a estos 8 CFDI por `Pd_Referencia`. Sigue sin resolver: no se
  confirmó el folio correcto ni si es un error de captura o un anticipo que
  se va aplicando (sin método propio para ese patrón — ver el caso análogo
  de `ANTICIPO_CXP` en la línea de abajo).
  **Pista de Esteban para investigar la relación real (2026-09-11, sin
  confirmar todavía)**: para el UUID `E12E90BC-4C4A-5BF0-B01F-A406D28F7F99`
  (uno de los 8, CFDI `01-00600620007`, 2026-02-24, $6,234.98), la liga
  correcta pasaría por la **`Pl_Folio 476319`** (póliza del 2026-02-25) — no
  por las pólizas del propio cheque (`395288`/`367538`) que hoy usa
  `extract_poliza_cheque()`. Falta seguir esta pista: qué hay en `Pl_Folio
  476319` (revisado en esta sesión: aparece como `Pc_Tabla='PAGO_CXP'`,
  `Pc_Documento` `01-0095069...`/`07-0015318...`, con renglones de
  `DEVOLUCION` y referencia `2007587` — ninguno de esos folios calza a
  simple vista con el cheque `01-0060062` ni con el CFDI; falta entender el
  mecanismo que sí los conecta, quizá vía `Aplicacion_Nota_Credito_Compra`/
  `Aplicacion_Indirecto` u otra tabla de aplicación de anticipo/nota de
  crédito de proveedor — exploradas en esta sesión sin encontrar la liga
  directa).
- **`ANTICIPO_CXP` sin método de cargo propio** (confirmado 2026-09-11, CFDI
  `6CDC03DF...`, feb-2026): el origen no está en `FUENTES`/`IMPORTE_DOCUMENTO`
  de ningún extractor, así que el genérico nunca lo cuadra aunque el
  documento sí exista y sea real — ej. anticipo real a Triturados de
  Valladolid (`Anticipo_CXP` folio `01-0005881`, $180,000, pagado por
  cheque) aplicado solo parcialmente contra un CFDI de $77,384.98. Mismo
  patrón de fondo que el cheque `01-0060062` de arriba: un anticipo grande
  que se va aplicando contra varios CFDI chicos, sin que el pipeline sepa
  sumarlos ni aislar la aplicación parcial correcta.
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
