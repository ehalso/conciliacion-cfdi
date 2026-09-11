# Requerimiento: Layout de registro de gastos

Fuente: `Requerimiento_de_Reportes_de_Contabilidad_auditoria_V2.docx` (Ismael Valdez, Contabilidad y Finanzas).
Contexto: auditoría externa trimestral con Bates y Asociados. De los 3 reportes solicitados en ese
documento (layout de gastos, layout de consumo interno, layout de notas de crédito), **este proyecto
cubre únicamente el layout de gastos**. Consumo interno y notas de crédito quedan fuera de alcance
por instrucción explícita del usuario.

## Objetivo

Reporte extendido de gastos: cada folio de gasto debe traer, en la misma fila (o filas relacionadas),
sus datos de pago, proveedor, factura (CFDI), datos del XML y datos contables (póliza).

Las fuentes son las mismas del reporte nativo de gastos **a excepción de `CONSUMO_INTERNO` y
`GASTO_REGISTRO_NOMINA`** (nómina se resuelve en otro layout, no en este).

## Dos vistas requeridas

1. **Vista base (detalle):** por la naturaleza de las pólizas y el registro de gastos en centros de
   costo, puede haber múltiples filas por un mismo folio de gasto. Es la vista de comprobación.
2. **Vista agrupada:** la misma información agregada **por cuenta contable**, de forma que exista
   una sola fila por folio de gasto (con la excepción de gastos que tengan dos cuentas contables en
   el detalle de la póliza).

## Campos requeridos (detalle completo en el Word)

- **Datos del pago:** Operación (ID), Fecha, Moneda, Cobrado en Efectivo, Cobrado con
  Cheque/Transferencia, Banco, Cuenta bancaria, Fecha de cheque, No. Cheque o Transferencia, Monto
  Cobrado.
- **Datos del proveedor:** Clave, RFC, Nombre.
- **Datos de la factura (CFDI):** Número de factura, UUID, Fecha factura, Tipo de comprobante,
  FACTURA_REF.
- **Importes e impuestos:** Subtotal 0%, Subtotal 16%, Subtotal exento, Descuento, Subtotal Neto,
  IVA acreditable, Retenciones de IVA, Retenciones de ISR, Total.
- **Datos del XML:** RFC emisor, Monto, Serie, Folio, Método de pago, Forma de pago.
- **Datos contables (póliza):** Fecha de póliza, Tipo de póliza, Número de póliza, Concepto de
  póliza, Cuenta Registro, Nombre Cuenta Registro, Cargo, Abono.

## Comprobación obligatoria

> La suma de cargos y abonos del reporte debe ser igual al reporte nativo de gastos (exceptuando
> CONSUMO_INTERNO y REGISTRO_NOMINA).

Esto es el criterio de aceptación cuantitativo del proyecto: cualquier versión del reporte debe
poder validarse contra este total.
