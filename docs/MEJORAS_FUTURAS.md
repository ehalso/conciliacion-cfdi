# Mejoras futuras y pendientes de decidir

## Pendiente de decidir

- **Orden de columnas igual al Excel de referencia** (`Layout_de_gastos_enero_2025_con_detalles.xlsx`). Hoy el orden es el de `columnas.json` (Tipo, Origen, Folio, datos del registro, comprobante XML, subtotales, impuestos, total, póliza, pago). No se ha decidido si se reordena como el Excel; se retoma después.

## Criterios de conciliación (4)

Ya implementado: columna `CRITERIO_CONCILIACION` para Consumo interno, Nómina, Provisión contable y Costo
estándar (ver `REGLAS_NEGOCIO.md`). Con los cuatro marcados, de los 717 folios "sin explicar" que quedaban tras
la primera pasada (Consumo interno/Nómina/Provisión contable de grupo), Costo estándar + la extensión de
Provisión contable explican 281 (39.2 %) con 100 % de pureza cada uno. Pendiente:

- **No deducibles**: `Tipo_Gasto` `0092` (catálogo Mpro) solo tiene 85.6 % de folios sin CFDI; el 14.4 %
  restante sí tiene CFDI (son compras reales, p. ej. gasolineras) que simplemente no son deducibles
  fiscalmente — no se puede marcar como "sin CFDI por naturaleza" sin decisión de negocio (¿se concilia igual
  cuando sí hay CFDI, y solo se excluye cuando no lo hay?).
- **Impuesto Sobre Nómina**: `Tipo_Gasto` `0025`, 86 % sin CFDI; los folios con CFDI son de la Secretaría de
  Hacienda (17 folios) — mismo matiz que "No deducibles", no es un sí/no limpio.
- **Residual sin patrón**: quedan ~195 folios dispersos en muchos `Tipo_Gasto` de baja pureza individual
  (erogaciones preoperativas, cuotas y suscripciones, intereses bancarios, telefonía celular, recargos...),
  sin un eje estructural adicional — probablemente timing de captura de CFDI o proveedores extranjeros (SaaS,
  aerolíneas) ya vistos en la exploración inicial, no un criterio nuevo que valga la pena codificar.
- **Filtro dedicado en la interfaz**: hoy `CRITERIO_CONCILIACION` es una columna más (visible, buscable con el
  buscador de texto libre, con autofiltro en el Excel exportado), pero no tiene un control dedicado como el
  dropdown de "Origen del gasto" en `static/index.html`. Si se necesita filtrar/aislar por este criterio desde
  la interfaz web (no solo en Excel), falta ese control (y su color/leyenda, igual que `ORI` para Origen).
- **4.1 Reporte propuesto filtrado y resultado**: falta un bloque de totales (KPI) que muestre cuánto del
  universo de Gasto se excluye por cada criterio y cuánto queda como "esperado conciliar con el SAT", para
  comparar ese resto contra lo que realmente aparece en la conciliación SAT (columnas `CONC_*`).

## Validación por folio (no implementada)

Comparar, por documento, `SUBTOTAL_NETO` contra el cargo contable neto de la póliza (cargo − abono) y marcar las diferencias.

- Ya existe una versión básica en la interfaz (KPI "Documentos cuadrados", tolerancia 0.05).
- Siguiente paso: columna o filtro "Diferencia" por documento, con causa probable (póliza ausente, línea memo, redondeo, IVA no acreditable).
- En Sep 2026: Compra, Indirecto y NC proveedor cuadran al 100 % (CxP libre y OC también en ene–ago 2026); en Gasto quedan 57 de 4,994 con diferencias de centavos (comportamiento heredado de v1).
- Gasto en ene–sep 2026: 651 de 42,452 folios con descuadre contra su póliza (antes 663; suma de |diferencias| de $97,469 a $4,959), aunque el total por documento ya iguala a RPAG008. Ya se atribuyen las líneas de póliza sin CECO (`atribuir_sin_ceco`) y se reparten las líneas agregadas compartidas por varios folios de consumo interno (`_emparejar_activo_fijo`). Lo que queda:
  - 648 folios con diferencias de centavos por el redondeo del prorrateo por CECO.
  - `05-0187796`: doble contabilización real (configuraciones de póliza 0414 y 0396 registran el mismo gasto), $3,824.62.
  - `05-0188329` y `05-0188332`: duplicidad 0324 (provisión) + 0450 (registro) sobre una `orden_compra`, $320.70 y $283.22.
- CxP libre: 329 folios sin póliza de registro (solo 96 tienen póliza de pago por cheque, `Pc_Tabla='Cheque'`). Es correcto dejarlos sin póliza; si se quiere distinguirlos, marcar "póliza solo de pago".

## Escalabilidad

- Caché por periodo con tope de 6 entradas en memoria; para rangos anuales o varios usuarios conviene mover el DataFrame a disco (parquet) o a una vista materializada.
- La consulta de un mes tarda ~20 s en vivo (Gasto + 5 tipos); el cambio de vista usa el caché (~2 s). Se podría consultar cada tipo en paralelo.
- Tabla paginada de 300 filas con todo el JSON en el cliente (~0.4 MB gzip por mes); para periodos largos, paginar en servidor.
- Si se agregan más tipos de reporte de auditoría, basta añadir un `SPEC` en `tipos_documento.py` y su `ORDEN_TIPO` en `exportar_datos.py`.
- Pendientes heredados: descuento y factura de referencia sin fuente en BD.

## CxP libre y CxP orden compra

- Incluidas desde v2 (detalle en README). Pendiente: replicar `aplicar_correccion_cuenta_registro` del reporte 05 original (búsqueda alterna por importe aproximado) si se detectan líneas de póliza mal asignadas.
- Si alguna CxP comparte póliza con otro documento y su referencia coincide con la de otra CxP, las líneas podrían aparecer en ambas; hoy no ocurre (cargo − abono cuadra al 100 %).
- Evaluar si la cuenta 2130 (documentos por pagar) debe mostrarse en una columna aparte en vez de omitirse.
- **Pendiente para la etapa de "criterios de conciliación"**: decidir si se vuelve a filtrar en CxP lo que el reporte 05 original excluía por no ser compras: conceptos `0023`, `0019`, `0016`, `0017` y proveedor `0000000021`. Hoy el layout NO los filtra, para totalizar igual que el nativo RPCXP08 (ene–sep 2026: 364 docs / −$10.6 M de esos conceptos y 320 docs / −$5.5 M de ese proveedor en CxP libre; 2 docs de concepto 0017 / $18.7 K en CxP orden compra). Si se vuelve a filtrar, mejor como marca o columna (p. ej. "es compra") filtrable en la vista, que como exclusión en la consulta.
- Efecto en póliza de no filtrar CxP (ene–sep 2026): de las 792 CxP libres, 329 no tienen línea de póliza que cruce por folio/referencia (320 del proveedor `0000000021`, $4.79 M; 9 del concepto 0023, $1.58 M) y 2 del concepto 0019 ($42,000) descuadran contra su póliza. Las 108 que ya entraban antes y las 101 de orden de compra cuadran al 100 %.
- Sucursales en baja (`BA`): el layout tampoco las filtra (el nativo las incluye); si algún criterio de conciliación las requiere excluir, que sea también como marca.
- **Cruce SAT**: definir "No localizados" (hoy vacío; la intención es marcar los UUID de Mpro que no están en la BD del SAT, que ya cubre "Existe UUID en SAT" = No) y confirmar la tolerancia de importes (0.05). Los folios con UUID "VARIOS" no se cruzan.

## Observaciones sep-2026 y auditoría de fuentes

Ver `REVISION_OBSERVACIONES.md` (documentación provisional de la rama; se pasa a `trivasa-context` cuando termine la revisión de todas las correcciones). Incluye 8 hallazgos de auditoría de fuentes aún no solicitados y la decisión pendiente de mostrar Uso CFDI, Método y Forma de pago en el bloque SAT.
