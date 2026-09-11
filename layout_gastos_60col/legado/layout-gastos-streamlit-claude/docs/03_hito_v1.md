# Hito v1 — extracción funcionando y validada contra enero 2025

## Qué se construyó

- `scripts/db.py`: conexión compartida a `TRIVASADB3` (reutiliza `connection_200_trivasadb3.py`
  de la raíz del repo).
- `scripts/layout_gastos_v1.py`: extracción en dos consultas (`extract_header` +
  `extract_poliza`) que se combinan en pandas (`extract_base_view`), más
  `group_by_cuenta_contable` para la vista 2 (agrupada) que pide el Word.

## Por qué dos consultas y no un solo JOIN

La primera versión unía todo en un solo SQL (cabecera de pago/factura + detalle de póliza) y el
`Cargo` salía multiplicado: `Pago_CXP` puede tener más de una fila por `Cxp_Folio` (pagos
parciales), y al cruzarla con `Poliza_Detalle` en el mismo JOIN, cada línea de póliza se repetía
una vez por cada pago. Separar en dos consultas por grano (cabecera a nivel `Grd_ID`, póliza a
nivel `Pd_ID`) y unir por `Operacion (ID)` en pandas evita el producto cartesiano.

## Cinco correcciones que redujeron la brecha de reconciliación de -35.7% a +0.89%

Criterio de aceptación del Word: *"La suma de cargos y abonos del reporte debe ser igual al
reporte nativo de gastos"*. Se validó comparando `SUM(Cargo) - SUM(Abono)` (vista póliza) contra
`SUM(Subtotal Neto)` (`Grd_Precio_Descontado_Importe`, cabecera) por operación, sobre todo enero
2025 (3,584 folios de gasto no cancelados).

| # | Corrección | Efecto | Por qué |
|---|---|---|---|
| 1 | Excluir `Cuentas de Orden` (grupo contable raíz `H` en `Grupo_Cuenta_Contable`) del lado de póliza | evita doble conteo | algunos folios postean tanto en una cuenta real (resultado) como en una cuenta de orden/memo (control interno) en dos pólizas distintas del mismo día; incluir ambas duplicaba el cargo |
| 2 | Excluir pólizas con `Es_Cve_Estado = 'CA'` (canceladas/sustituidas) | evita doble conteo | se encontraron folios con una póliza `CA` y una de reemplazo `AC`, ambas con el mismo detalle |
| 3 | Excluir folios de gasto con `Gasto_Registro.Es_Cve_Estado = 'CA'` — **no** `<> 'AC'** | evita sobreestimar el subtotal, sin descartar folios validos | `Es_Cve_Estado` tiene 3 valores: `AC` (activo), `AP` (aplicado) y `CA` (cancelado). El primer intento filtró `= 'AC'`, lo cual **excluía por error los 636 folios en estado `AP` de enero 2025** (incluido el folio de ejemplo validado, `01-0029621`) — el filtro correcto es `<> 'CA'` |
| 4 | Merge cabecera×póliza posicional (`merge_header_poliza`), no relacional por `Operacion (ID)` | evita explosión combinatoria | ~80 folios de 2,948 tienen más de un `Grd_ID` (documento múltiple); un join relacional simple por operación multiplica cabecera×póliza (un caso pasó de ~450 filas reales a 51,076 filas fantasma) |
| 5 | Incluir también `Pd_Tipo = 2` en `Poliza_Detalle`, pero **solo** cuando la cuenta es de grupo `F` (Gastos) | corrige `Abono` | `Pd_Tipo` no es "cargo/abono" per cuenta de proveedor — es cargo/abono del asiento. En una **reclasificación de gastos** (folio con `Grd_Comentario` "Reclasificación de gastos (Cargos/Abonos)"), el abono SÍ referencia el `Gr_Folio` directamente y cae en una cuenta de Gastos, no de Pasivo/Proveedor. Sin este fix, el layout mostraba folios de reclasificación con Cargo > 0 y Abono siempre en 0, cuando en realidad se cancelan entre sí |

Resultado en enero 2025 completo: `Subtotal Neto` = $35,596,916.16 vs `Cargo - Abono` =
$35,914,462.67 (diferencia **+0.89%**, mejor que los intentos previos de -35.7%, +2.23% y -54.3%
recorridos durante esta iteración — ver historial de commits/versions para el detalle de cada
paso).

## Brecha residual conocida (0.89%) — para v2

- Folios de **reversión/provisión negativa** (p. ej. `01-0030155` "PROVISION PRIMA ANTIGUEDAD
  ENERO 2025", `Grd_Precio_Descontado_Importe = -178,959.60`) cuyo Cargo y Abono de póliza se
  cancelan correctamente entre sí (neto poliza = 0) pero el header trae un subtotal negativo — no
  es un error del extractor, es una discrepancia conceptual entre "lo que se devengó" (header,
  puede ser una reversión) y "lo que se contabilizó neto" (póliza, cero porque es un traspaso
  interno). Pendiente decidir con Contabilidad cómo debe verse esto en el layout.
- Operaciones cuyo único registro contable es una cuenta de orden (p. ej. `01-0029622`, visto en
  el Excel de referencia con concepto "CONSUMO INTERNO" pese a anclar en `Gasto_Registro`) quedan
  con `Cargo = 0` — es el comportamiento correcto (no son gasto real), pero conviene señalizarlas
  explícitamente en el reporte en vez de dejarlas en blanco sin explicación.
- Pendiente: desglose real de "Subtotal 0% / Subtotal 16% / Subtotal exento" — hoy se reporta
  `Subtotal Neto` total (pre-IVA) desde `Gasto_Registro_Documento`, sin partir por tasa. Requiere
  parsear `Comprobante_Digital.Cd_XML` por concepto (v2).
- Pendiente: catálogo SAT de "Forma de pago" (hoy se expone el código crudo, p. ej. `03`, sin la
  descripción "Transferencia electrónica de fondos").

## Archivos generados

- `data/header_2025_01.parquet`, `data/poliza_2025_01.parquet`: extracción de enero 2025 cacheada
  para no golpear la base en cada iteración de la app.
