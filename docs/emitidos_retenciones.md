# Conciliación de CFDI emitidos y retenciones (H1 2026)

Metodología del proyecto hermano `~/proyectos/conciliacion-master/
conciliacion-emitidos` (Esteban, 2026-09-10 — ver su `docs/metodologia.md`
y `docs/esquema-datos.md`, no repetidos aquí), **implementada y validada en
vivo en este repo** el mismo día: `conciliacion_emitidos_documento.py`
(reporte 01, documento↔CFDI) y `retencion_reconciliation.py` (reporte 04,
cruce independiente contra el SAT). Conexión directa por LAN
(`bridge_client.py`, sin bridge HTTP — ese patrón quedó atrás desde
`docs/arquitectura.md`).

**Diferencia clave sobre el proyecto original: aquí no se parsea XML en
ningún caso.** El original bajaba y parseaba `Comprobante_Digital.Cd_XML`
para los 5 módulos. Aquí:

- FACTURA/NOTA_CREDITO/CONSTANCIA_RETENCION usan `Cd_Monto` directo (ya es
  el importe comparable — medido en el proyecto original).
- GASTO_REGISTRO con retención (`Cd_Monto=0` por diseño) usa
  `raw_sat.cfdi_retencion.monto_total_operacion`, ya parseado desde la
  ingesta (`consulta-xmls`, mejora del 2026-09-10) — cobertura histórica
  completa, sin volver a tocar el XML.

Los números de abajo se corrieron en vivo con este método y coinciden
EXACTO con los del proyecto original (mismo dato, dos caminos distintos) —
ver `docs/hallazgos.md` para el detalle de la validación.

## Resultado

### Reporte 01 — CFDI emitidos (factura, nota de crédito, retenciones) vs mpro

| Periodo | Universo | Conciliables (sin cancelados) | Concilian | % |
|---|---:|---:|---:|---:|
| 2026-01 | 2,479 | 2,429 | 2,429 | **100.00%** |
| 2026-02 | 2,240 | 2,209 | 2,209 | **100.00%** |
| 2026-03 | 2,505 | 2,450 | 2,450 | **100.00%** |
| 2026-04 | 2,529 | 2,486 | 2,486 | **100.00%** |
| 2026-05 | 2,450 | 2,410 | 2,410 | **100.00%** |
| 2026-06 | 2,624 | 2,570 | 2,570 | **100.00%** |
| **H1** | **14,827** | **14,554** | **14,554** | **100.00%** |

Confirma la conclusión de la investigación original: **el lado emitido no
tiene problema de importes**, por construcción — el CFDI se genera desde el
documento de mpro (factura, nota de crédito), así que no puede diferir. Los
`AMBOS_CANCELADOS` (273 en el semestre) son cancelaciones consistentes en
ambos lados, no descuadres.

Script: `conciliacion_emitidos_documento.py --periodo YYYY-MM` (o
`--periodos 2026-01,...,2026-06`).

### Reporte 04 — cruce independiente contra el SAT (raw_sat.cfdi_retencion)

A diferencia del reporte 01 (que compara mpro consigo mismo: el `Cd_XML`
que guarda contra el documento que lo originó), este cruce usa una fuente
**independiente**: los XML que el PAC deja en el share del SAT, cargados a
Postgres sin pasar por el ERP. Puede detectar un comprobante que se timbró
pero el ERP nunca registró — invisible para el reporte 01 por construcción.

`raw_sat.cfdi_retencion` tiene cobertura histórica completa (2016-2026), a
diferencia de `cfdi_emitidos` (solo hasta enero 2026, backfill pendiente)
— por eso este cruce sí se puede correr sobre todo H1 2026 ya mismo.

**Hallazgo — 29 constancias de retención timbradas que el ERP no tiene, dos
meses distintos, mismo patrón:**

| Periodo | Timbradas (SAT) | En el ERP | Faltantes | Monto de operación | ISR faltante |
|---|---:|---:|---:|---:|---:|
| 2026-01 | 45 | 31 | **14** | $282,291.65 | $56,458.35 |
| 2026-02 | 15 | 0 | **15** | $254,305.39 | $50,861.10 |
| 2026-03..06 | 76 | 76 | 0 | — | — |
| **H1** | **136** | **107** | **29** | **$536,597.04** | **$107,319.45** |

Los 14 de enero replican exactamente el hallazgo de la investigación
original (mismos UUID, mismo monto, todos timbrados el 22 de enero entre
12:28 y 14:11). **Los 15 de febrero son un hallazgo nuevo**, no visto en la
investigación original porque esa sesión no llegó a correr el reporte 04
sobre febrero — mismo mecanismo exacto: mismo tipo de retención (`CveRetenc
16`, intereses), casi los mismos acreedores (BLANCA LEONOR MENDEZ AVILES,
GONZALO JOSE ESCALANTE ALCOCER, RUYLUZ ALCOCER ROSADO, y dos más), un solo
lote timbrado el mismo día (26 de febrero, 11:30–12:22).

**Lectura:** no es un incidente aislado de enero — es un patrón que se
repitió en febrero y no en marzo-junio. Sugiere un problema recurrente
(pero no mensual) del proceso de timbrado de retenciones de intereses que
no siempre se refleja en el ERP. Vale la pena preguntar en Contabilidad si
hay una causa común (ej. un proceso manual que a veces se salta el paso de
registrar en mpro) y correr este mismo cruce sobre meses posteriores a
junio para ver si el patrón sigue.

Script: `retencion_reconciliation.py --periodos 2026-01,...,2026-06`

**Nota de consolidación (2026-09-10):** este cruce se construyó dos veces en
paralelo, por dos sesiones distintas el mismo día (una lo llamó "reporte 04
de emitidos"/`cruce_sat_retenciones.py`, la otra "retención nivel 1"/
`retencion_reconciliation.py`) — ambas llegaron exacto a los mismos 29
faltantes por caminos independientes. Se quedó `retencion_reconciliation.py`
porque separa un tercer estatus más útil que un simple faltante/no-faltante:
`STUB_GASTO_REGISTRO_SIN_MONTO` (75 en H1, $1,271,526.95) — CFDI de
retención de intereses que SÍ tienen fila en `Comprobante_Digital`
(`GASTO_REGISTRO`) pero con `Cd_Monto=0` por diseño de esa columna, no por
un hueco real: el importe correcto vive en `Gasto_Registro_Documento.
Grd_Precio_Descontado_Importe`, y el reporte 01 de arriba ya confirma que
esos documentos conciliar al 100% contra `raw_sat.cfdi_retencion` cuando sí
existen. Solo `SIN_MAPEO_MPRO` (los 29 de la tabla de arriba) es el hueco
real — **no confundir los 75 `STUB` con faltantes**, son casos ya resueltos
por otra vía.

## Qué falta (siguiente paso natural)

1. **Reporte 02/03 — cobranza (REP) y drill-down.** La investigación
   original encontró en su lado dos hallazgos de cobranza (parcialidades
   cobradas sin timbrar, REP timbrados por duplicado) que valen la pena
   replicar aquí — pendiente de implementar `conciliacion_cobranza.py`
   siguiendo la misma metodología (`DoctoRelacionado` → factura → CxC →
   `Pago_CXC`, cierre de universo 24 meses atrás + hasta hoy).
2. **Reporte 04 para FACTURA/NOTA_CREDITO.** `raw_sat.cfdi_emitidos` solo
   tiene backfill hasta enero 2026 — no vale la pena correrlo para
   feb-jun hasta que el backfill avance (ver el mismo gotcha documentado en
   la investigación original).
3. **Confirmar contra `.207`** antes de convertir cualquiera de estas
   cifras en un ajuste contable o reporte a Contabilidad — este pipeline,
   como el de recibidos, corre contra `mssql_205` (no productiva).
