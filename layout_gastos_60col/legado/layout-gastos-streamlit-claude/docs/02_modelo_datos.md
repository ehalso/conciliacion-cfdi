# Modelo de datos real (TRIVASADB3, `192.168.117.200`)

`connection_200_trivasadb3.py` (raíz del repo) es la conexión viva — ver
`decisions/2026-07-conexion-trivasadb3-vs-trivasadb.md`. `TRIVASADB` (sin el 3) es una copia
desactualizada, no usar.

Todo lo de abajo se verificó contra datos reales de enero 2025 (folio de ejemplo `01-0029621`,
"RENTA DE OFICINA SOLARE", tomado del propio Excel de referencia) antes de escribir el SQL de
extracción.

## Cadena de tablas (grano → grano)

```
Gasto_Registro (Gr_Folio)                                  1 fila por folio de gasto
  └─ Gasto_Registro_Documento (Gr_Folio, Grd_ID)            1 fila por "línea" del folio (moneda, proveedor, importes, tipo de gasto)
       ├─ Proveedor (Pv_Cve_Proveedor)                      catálogo proveedor
       ├─ Tipo_Gasto (Tg_Cve_Tipo_Gasto)                     catálogo tipo de gasto
       │
       ├─ Cuenta_X_Pagar                                    Cxp_Tabla = 'Gasto_Registro:' + Gr_Folio
       │    (Cxp_Folio)                                     Cxp_Documento = Grd_ID
       │     └─ Pago_CXP (Cxp_Folio, Pc_ID)                  1+ pagos por CXP (pago parcial/múltiple)
       │          ├─ Pc_Tabla / Pc_Documento                'Cheque' + folio de cheque, o 'APLICACION_CXP', etc.
       │          ├─ Pc_Banco / Pc_Cuenta_Bancaria / Pc_Referencia   datos bancarios directos en Pago_CXP
       │          ├─ Fp_Cve_Forma_Pago → Forma_Pago          texto "TRANSFERENCIA ELECTRONICA", etc.
       │          └─ Pago_Cxp_Comprobante (Cxp_Folio, Pc_ID, Pcc_Id)  número de factura, UUID, RFC emisor/receptor
       │
       ├─ Comprobante_Digital                                Cd_Tabla = 'GASTO_REGISTRO'
       │    (Cd_Tabla, Cd_Documento)                          Cd_Documento = REPLACE(Gr_Folio,'-','') + Grd_ID + sufijo (match con LIKE)
       │                                                      trae los campos "XML ..." (RFC emisor, monto, serie, folio, método/forma de pago)
       │
       └─ Poliza_Control                                     Pc_Tabla = 'GASTO_REGISTRO', Pc_Documento = Gr_Folio
            (Pl_Folio, Pc_Tabla, Pc_Documento)                un folio de gasto puede caer en 1+ pólizas (normalmente 1)
             └─ Poliza (Pl_Folio)                             fecha, tipo, número de póliza (¡ojo! Pl_Numero es el consecutivo
                                                               *por tipo y periodo*, no el que aparece en Excel; ahí se
                                                               usa Pl_Folio, el folio global)
                  └─ Poliza_Detalle (Pl_Folio, Pd_ID)         FILTRAR Pd_Referencia = Gr_Folio AND Pd_Tipo = 1
                       └─ Cuenta_Contable                     nombre de "Cuenta Registro"
```

## Hallazgo clave: una póliza es un lote diario, no 1:1 con el folio de gasto

`Poliza` para gastos nacionales se genera **una vez por día** (tipo 3, comentario
"REGISTRO DE GASTOS NACIONAL DEL dd/mmm/yyyy") y agrupa las líneas de *todos* los folios de gasto
de ese día. Verificado con la póliza `0000425403` (02-ene-2025): 81 líneas de detalle, folios de
gasto de sucursales `01,05,07,09,11,18,23` mezclados.

Por eso el join correcto **no** es "una póliza por folio", sino:
`Poliza_Control` para encontrar en qué póliza(s) cayó el folio → `Poliza_Detalle` filtrado por
`Pd_Referencia = Gr_Folio` para quedarnos solo con las líneas de ese folio dentro de esa póliza.

## `Pd_Tipo` en `Poliza_Detalle`

No hay columna explícita de cargo/abono. Por inspección:

- `Pd_Tipo = 1`: cuentas de gasto (6xxx), IVA acreditable (1170...), ajustes por redondeo — bucket
  de **cargo**. Las líneas con `Pd_Referencia = Gr_Folio` (atribuibles a un folio específico) son
  siempre de este tipo cuando se trata de la cuenta de gasto en sí.
- `Pd_Tipo = 2`: proveedor (2110...) y retenciones (2150...) — bucket de **abono**. Sus
  `Pd_Referencia` casi siempre son el número de factura del proveedor, no el `Gr_Folio` — por eso no
  aparecen al filtrar por folio de gasto, y está bien que no aparezcan: ese es el lado "cuenta por
  pagar", no el lado "cuenta de gasto" que pide el layout.
- Las líneas de IVA acreditable / retenciones a nivel de póliza (agregadas del día completo) tienen
  `Pd_Referencia` **vacío** — por eso el filtro `Pd_Referencia = Gr_Folio` las excluye
  automáticamente sin necesitar lógica adicional.

**Consecuencia para el reporte:** la sección "Cargo/Abono" del layout, con el filtro
`Pd_Tipo = 1 AND Pd_Referencia = Gr_Folio`, siempre cae en la columna Cargo (Abono queda en 0 salvo
que aparezca una reclasificación/ajuste negativo — pendiente de validar en más periodos).

## Ejemplo verificado end-to-end (folio `01-0029621`)

| Campo | Valor | Tabla origen |
|---|---|---|
| Operación (ID) | 01-0029621 | `Gasto_Registro.Gr_Folio` |
| Proveedor | MILENIUM PROPERTYS / MPR080808HV3 | `Proveedor` |
| Cxp_Folio | 01-0085759 | `Cuenta_X_Pagar` (`Cxp_Tabla='Gasto_Registro:01-0029621'`) |
| Forma de pago / banco | TRANSFERENCIA ELECTRONICA / BANCOMER / 449706976 | `Pago_CXP` |
| No. de transferencia | 2483395214 | `Pago_CXP.Pc_Referencia` |
| Número de factura / UUID | 3189 / 0515C3FB-112A-4088-B359-95582F84C8C6 | `Pago_Cxp_Comprobante` |
| RFC emisor (XML) | MPR080808HV3 | `Comprobante_Digital.Cd_RFC_Emisor` |
| Cuenta Registro | 6500.001.007.003 / "Renta De Oficinas A Persona Moral..." | `Poliza_Detalle` + `Cuenta_Contable` |
| Cargo (detalle, 2 centros de costo) | 12,000 + 12,000 = 24,000 | `Poliza_Detalle` (Pd_ID 0054, 0055) |

Los 24,000 coinciden con `Grd_Precio_Descontado_Importe` de `Gasto_Registro_Documento` (subtotal
antes de IVA), y el IVA (3,840) es la línea agregada a nivel de póliza — confirma que
`Subtotal`/`IVA`/`Total` deben tomarse de `Gasto_Registro_Documento` / `Cuenta_X_Pagar` (que ya
traen esos importes desglosados por documento), no de `Poliza_Detalle`.

## Pendientes a validar en próximas iteraciones

- Confirmar el patrón exacto del sufijo de `Comprobante_Digital.Cd_Documento` (por ahora se usa
  `LIKE` con prefijo, funciona pero no es una igualdad exacta).
- Validar el caso de "dos cuentas contables" que menciona el Word para la vista agrupada.
- Revisar folios con `Gr_Genera_Cxp = 'NO'` (pago directo sin CXP) — el ejemplo validado tenía
  `Gr_Genera_Cxp = 'NO'` pero sí generó CXP igual, hay que revisar si ese campo realmente predice
  ausencia de datos de pago.
- Validar comprobación cuantitativa (suma cargos/abonos vs. reporte nativo) sobre el periodo
  completo de enero 2025.
