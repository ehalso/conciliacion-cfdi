# Hallazgos del Excel de referencia (no literal)

Archivo: `Layout de gastos enero 2025 con detalles.xlsx`. El usuario advirtió que **tiene errores y
no debe tomarse como verdad literal**, solo como referencia de forma. Confirmado al abrir las hojas
auxiliares del propio archivo (`Observaciones`, `poliza contable`): el autor original dejó ahí una
bitácora de errores conocidos pendientes con TI. Se resume porque cambia decisiones de diseño:

## 1. Nómina no debe entrar a este layout

> "Actualmente el layout no trae el de origen: Gasto_registro_nómina" — y la respuesta acordada es
> que no debe traerlo. Coincide con el Word: se excluye `GASTO_REGISTRO_NOMINA`.

## 2. Bug conocido #1 — la vista agrupada debía sumar por cuenta contable, no por centro de costo

> "Mejoras acordadas con Esteban: En la consulta traiga la información sumada por Cuenta contable y
> no por cada centro de costo."

Ejemplo documentado en la propia hoja (operación `01-0029623`, cuenta `6100.001.015.002` -
"Comision Por Manejo De Cuenta"): la consulta original traía **5 filas** (una por centro de costo:
33, 47, 378, 517, 519) con cargos 2.54 / 12.03 / 15.87 / 6.86 / 1.54. La vista agrupada correcta
debe traer **1 fila** con Cargo = 38.84 (la suma). Esto es exactamente la "vista 2" que pide el
Word ("se agrupe por cuenta contable, de esta manera se logra una sola fila por cada registro de
gasto"). **Decisión de diseño:** en `v1` implementamos la agrupación agregando `SUM(Pd_Importe)`
por `(Gr_Folio, Cc_Cve_Cuenta_Contable)`, colapsando `Centro_Costo`.

## 3. Bug conocido #2 — el layout no traía el desglose completo de la póliza

Ejemplo documentado (operación `01-0030276`, "AMORTIZACION DE PLACAS Y TENENCIAS"): la póliza real
tiene ~20 líneas de detalle (una por centro de costo, cuentas `6100.001.014.001`,
`6200.001.014.001`, `6300.001.014.001`, etc.), pero el Excel de referencia solo capturó 2. El resto
están marcadas "Este no lo trae" en la hoja de observaciones.

**Implicación para el diseño:** la extracción debe recorrer *todas* las líneas de
`Poliza_Detalle` que referencian al folio de gasto (`Pd_Referencia = Gr_Folio`), sin truncar. No hay
límite de filas esperado por operación.

## 4. Consumo interno aparece mezclado en el Excel, pero no debe estar

Fila de ejemplo: operación `01-0029622`, concepto de póliza "CONSUMO INTERNO DEL 02/ene/2025".
Se confirmó contra la base viva (`TRIVASADB3`) que `01-0029622` **no existe en `Gasto_Registro`**
(sí en `Consumo_Interno`, verificado en `Consumo_Interno` — de hecho ni siquiera aparece ahí con ese
folio exacto en la consulta rápida, lo que sugiere que el Excel original mezcló datos de distintas
tablas al construir el reporte sin filtrar por origen).

**Implicación de diseño (importante):** si la extracción usa como tabla ancla `Gasto_Registro`
(no un barrido genérico de `Poliza_Detalle` por `Pd_Referencia`), la exclusión de
`CONSUMO_INTERNO` y `GASTO_REGISTRO_NOMINA` es automática — esas operaciones simplemente no existen
en `Gasto_Registro`. No hace falta un filtro explícito de "origen"; hace falta *no* mezclar tablas.

## 5. Bug conocido #3 (no aplica a este reporte)

> "Los folios que vienen de consumos internos que corresponden a la configuración de póliza 396 los
> trae en cero en la columna de subtotal neto."

Bug de consumo interno — fuera de alcance de este layout, documentado aquí solo para no
reintroducirlo si algún día se retoma el layout de consumo interno.

## Estructura real de la hoja `Layout`

Encabezado en la fila 6 (no fila 1); filas 1-4 son metadatos (empresa, rango de fechas). 60
columnas, 6,401 filas de datos para enero 2025. Confirma el patrón de "múltiples filas por folio"
que describe el Word: la primera fila de un folio trae todos los campos (pago/proveedor/factura),
las filas siguientes del mismo folio solo traen las columnas de póliza (una por línea de
`Poliza_Detalle` / centro de costo).
