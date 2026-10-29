# Reglas de negocio del reporte

## Tipos de documento

- **Tipo** (primera columna): `Gasto`, `Compra`, `Indirecto` (compra indirecta), `NC proveedor` (nota de crédito de proveedor), `CxP libre` y `CxP orden compra`. Los cinco últimos vienen de las consultas de auditoría RPTRV79 (`conciliacion/documentos.py`; los dos de CxP son el reporte `05 cxp_libre`). No se traen columnas exclusivas de v3 (descuento, comprador, almacén, causa, estado, cantidad control…).
- La llave de documento es (Tipo, Folio): hay folios que se repiten entre tipos.
- Las NC de proveedor van en negativo (subtotales e impuestos); su póliza son abonos, así que cargo − abono cuadra con el subtotal neto.
- Póliza de compras: se filtra por `Pd_Referencia = folio` y se excluyen las líneas memo (10500/10600), impuesto (1170), proveedor (2110) y 2150, para que solo queden los subtotales.
- Subtotal neto ya viene neto de descuento.
- **Gasto totaliza igual que el reporte nativo RPAG008** (ene–sep 2026, empresa 0001: 42,452 / 42,452 documentos, diferencia de +$15.62 por redondeo del prorrateo por CECO). El Gasto se arma desde las líneas de póliza con CECO; `completar` (`conciliacion/gasto.py`) agrega las filas que la póliza no cubre: los (FOLIO, CECO) del reparto de `Gasto_Registro_Control` sin línea de póliza, y los documentos sin reparto ni póliza con CECO (CECO vacío, importes de `Gasto_Registro_Documento`). Esas filas llevan `CARGO = ABONO = 0`, salvo que la póliza tenga una línea sin CECO cuyo neto iguale el subtotal de ese (FOLIO, CECO): `atribuir_sin_ceco` se la asigna, así que el folio cuadra contra su póliza (651 folios de 42,452 siguen descuadrados, casi todos por centavos de redondeo). El emparejamiento de `CONSUMO_INTERNO` de activo fijo (`emparejar_activo_fijo`) ya no se limita a una línea por folio cuando un folio se reparte en varios CECO.
- **Cuentas por pagar (CxP libre y CxP orden compra)**: ver la sección siguiente.
- **Layout por documento** (única vista en la interfaz): subtotales, impuestos, TOTAL, XML_MONTO y MONTO_COBRADO solo en la primera fila del documento (en gasto con varios documentos, el pago es el de la cuenta por pagar de cada documento; ver REVISION_OBSERVACIONES.md); las demás filas llevan folio/Tipo y los campos de póliza. En `registro_gasto`, `control_combustible`, `orden_compra` y `viaje` los datos de texto (proveedor, UUID, XML, pago) se repiten en todas las filas del folio, como pidió Ismael; las cifras no se repiten. Con "Agrupar por cuenta contable" (activo por omisión) las líneas de póliza se suman por cuenta (CECO = el único o `VARIOS`).
- El prorrateo por CECO de v1 ya no se ofrece en la interfaz; el parámetro `vista=ceco` del API sigue disponible para consultas directas.
- Las columnas sin ningún dato en el resultado no se envían (salvo Tipo, Folio, Fecha, Subtotal neto, Total, Cargo, Abono). Las claves `IMP_xxxx` nuevas se agregan solas.
- **Exportar a Excel**: encabezado (empresa, fecha inicial, fecha final, vista), fila de numeración 1..N, títulos con autofiltro y fila final `TOTAL` con `SUBTOTAL(109,…)` (respeta el filtro de Excel) en las columnas de importe.
- Ver `MEJORAS_FUTURAS.md` para lo pendiente de decidir.

## Criterios de conciliación (documentos de Gasto que por su naturaleza no tienen CFDI)

Columna `CRITERIO_CONCILIACION`: marca (no excluye) los folios de Gasto que, por su naturaleza, nunca van a
tener un CFDI asociado, para no compararlos contra el SAT como si fueran una compra pendiente de factura.
Se calcula con dos fuentes, ambas códigos de catálogo (no texto libre, salvo donde se indica):

- `ORIGEN = consumo_interno` → **Consumo interno** (salida de almacén/activo fijo, `Gr_Tabla='CONSUMO_INTERNO'`).
- `ORIGEN = gasto_registro_nomina`, o el grupo de `Tipo_Gasto` del folio (`Gasto_Registro_Documento.Tg_Cve_Tipo_Gasto`
  → `Tipo_Gasto.Gtg_Cve_Grupo_Tipo_Gasto`) es `0001` (Remuneración al personal) → **Nómina**. El grupo cubre más
  folios que el `ORIGEN` solo (974 vs. 900 en ene-sep 2026): hay nómina capturada también como `registro_gasto`.
- Grupo de `Tipo_Gasto` en `{0011, 0013, 0014}` (depreciación de activo fijo, amortización de activos intangibles
  y otras amortizaciones), o `Tipo_Gasto` individual en `{0102, 0211, 0212}` (cuentas incobrables, provisión de
  gastos de distribución, provisión de derechos SDS; viven en el grupo mixto `0009` y no se pueden tomar por
  grupo) → **Provisión contable**.
- `Tipo_Gasto` individual en 14 códigos "(COSTO ESTANDAR)" más "Fletes a producción" (`conciliacion.posproceso.
  TIPOS_COSTO_ESTANDAR`) → **Costo estándar**: salida de almacén/producción valuada a costo estándar en vez de
  a la factura real. El grupo `0005` (Mantenimiento costo estándar) no sirve como filtro por sí solo: mezcla
  estos tipos con su par "(CUENTA DE BALANCE)" que sí tiene CFDI (24.4 % de pureza como grupo completo); hay
  que filtrar por `Tipo_Gasto` individual.

El Tipo_Gasto (y su grupo) representativo del folio es el de la línea de mayor importe (`GASTO_TIPO_GASTO_SQL`,
mismo patrón que el proveedor representativo). Se eligieron estos cuatro por ser 100 % (o casi) sin CFDI en
ene-sep 2026 (42,451 folios de Gasto): Consumo interno 27,080/27,081, Nómina 974/974, Provisión contable
97/97, Costo estándar 247/247. Con los cuatro marcados, el resto de Gasto (14,052 folios, los que sí deberían
conciliar contra el SAT) baja de 67.9 % a solo **3.1 % sin CFDI** (436 folios). Quedan pendientes, por no ser
igual de limpios, "No deducibles" (`Tipo_Gasto` `0092`, 85.6 % sin CFDI: el resto son compras reales, p. ej.
gasolineras, que simplemente no son deducibles fiscalmente) e "Impuesto Sobre Nómina" (`Tipo_Gasto` `0025`,
86 % sin CFDI: los que sí tienen CFDI son de la Secretaría de Hacienda) — ver `MEJORAS_FUTURAS.md`.

## CxP libre y CxP de orden de compra

Ambas son registros de `Cuenta_X_Pagar` que **no** nacen de un documento Compra, Compra indirecta ni Gasto; se distinguen por `Cxp_Tabla`:

| Tipo en el reporte | `Cxp_Tabla` | Qué es |
|---|---|---|
| `CxP libre` | `Cuenta_X_Pagar` | CxP capturada directamente (facturas de arrendamiento, activos, servicios sin orden de compra, etc.). |
| `CxP orden compra` | `ORDEN_COMPRA` | Inversiones que se hacen desde una orden de compra, pero que en vez de generar un documento Compra generan una CxP. |

**No confundir** con la columna *Origen* `orden_compra` de los **Gastos**: ahí es un `Gasto_Registro` que se generó desde una OC y es del Tipo `Gasto`. Aquí es una CxP (Tipo `CxP orden compra`) y no tiene registro de gasto. En 2026 (ene–ago, empresa 0001) ninguna CxP de OC está referenciada por un gasto, y solo 2 CxP libres (05-0136733 y 05-0136734) lo están, vía su pago, por lo que no hay doble conteo.

Reglas (las del reporte 05 original, `rptrv79_05_cxp_libre*`):
- Fecha: `Cxp_Fecha`; se excluyen canceladas (`Es_Cve_Estado='CA'`) y se filtra por empresa de la sucursal.
- **No se excluye ningún concepto ni proveedor**, para que el layout totalice igual que el reporte nativo RPCXP08 (filtrado por `Cxp_Tabla`). El reporte 05 original sí excluía los conceptos `0023` (carga de glosa FONACOT), `0019` (depósitos en garantía), `0016` (primas de seguro y fianzas), `0017` (placas, tenencias y otros) y el proveedor `0000000021` (Control Integral de Combustibles) por no ser compras; ese criterio queda para la etapa de criterios de conciliación (ver `MEJORAS_FUTURAS.md`).
- Una fila por `Cxp_Folio` (único; los folios empiezan en `01-` o `05-`). Subtotal neto = `Cxp_Precio_Descontado_Importe × tipo de cambio`; total = `Cxp_Precio_Neto_Importe × tipo de cambio`; impuestos desde `Cuenta_X_Pagar_Impuesto` (`Cxpi_Importe`, por clave `Im_Cve_Impuesto`). Subtotal + impuestos = total en el 100 % de los documentos (ene–ago 2026).
- XML desde `Comprobante_Digital` (`Cd_Tabla='Cuenta_X_Pagar'`); pago desde `Pago_CXP` de la propia CxP.
- **Póliza**: una misma póliza puede cubrir varias CxP (en ene–ago, 40 de 93 pólizas), con líneas de otros documentos. Por eso solo se toman las líneas cuya `Pd_Referencia` es el folio de la CxP o su `Cxp_Referencia` (la factura), y se omiten las cuentas 1170 (IVA), 2110 (proveedores), 2150 (retenciones) y **2130 (documentos por pagar a corto plazo)**, que en estas CxP lleva abonos grandes que no son subtotal. Con ese filtro cargo − abono cuadra con el subtotal neto en las 205 CxP de ene–ago 2026 (108 libres + 97 de OC); sin excluir 2130 descuadran 9. Cuentas típicas del cargo: 1210 (propiedades, planta y equipo), 1250 (sistemas y licencias), 1150 (rentas en garantía).
- No se replica la corrección `aplicar_correccion_cuenta_registro` (búsqueda alterna por importe aproximado) del reporte 05 original.

## Póliza, método de pago y fuentes (observaciones sep-2026)

- Un documento con póliza en `Poliza_Control` cuyas líneas quedan todas filtradas (importe 0, cuentas memo/impuesto/proveedor) se muestra con la póliza y cargo 0 (`DOC_POLIZA_SIN_LINEAS_SQL`).
- Método de pago del XML: `Cd_Metdo_Pago_CFDI` y, si está vacío, `Cd_Metodo_Pago`.
- No se rellenan campos de una fuente con otra (registro Mpro, XML de Mpro, BD SAT). Detalle y pendientes en `REVISION_OBSERVACIONES.md`.

## Conciliación de importes por UUID (`CONC_IMPORTES`)

Se evalúa por UUID, no por línea, y el resultado (Sí/No) y `DIF_IMPORTE_UUID` se repiten en todas las líneas del UUID.

- Se compara |Σ `TOTAL` de los folios con ese UUID| contra el importe del SAT = `SAT_IMPORTE` (total del cuerpo) + `SAT_IMPORTE_COMPLEMENTO`.
- Se excluyen las filas Tipo "CxP libre" / "CxP orden compra": llevan el mismo UUID y repiten el dinero de los folios de gasto/compra (se duplicaría).
- Valor absoluto de la suma: las NC proveedor llevan signo negativo y el SAT positivo.
- Tolerancia: 0.05 + 0.01 por cada folio adicional del UUID (redondeo acumulado).
- `SAT_IMPORTE_COMPLEMENTO`: atributo `Total` del complemento `ecc12:EstadoDeCuentaCombustible` (consumo real de la factura consolidada de Control Integral de Combustibles). En Mpro el UUID agrupa los folios de consumo más el folio de comisión (cuerpo del CFDI), por eso se compara contra cuerpo + complemento.
- El KPI "% Conciliación" suma por UUID cuerpo + complemento.
- Sept 2026: 1,586 de 1,698 UUID cuadran (93.4 %); combustible 25/28 (los 3 restantes no tienen el folio de comisión en el mes).
