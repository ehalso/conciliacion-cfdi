# Esquema de datos

Las tablas de `TRIVASADB3` que estos reportes tocan, con sus columnas
relevantes y las llaves de unión. **Cada llave trae su tasa de match medida**
sobre enero 2026 — ninguna se asume.

---

## 1. `Comprobante_Digital` — el puente

Tabla genérica del ERP entre un documento de cualquier módulo y su CFDI.
690,970 filas, desde 2012-01-10. PK `(Cd_Tabla, Cd_Documento)`.

### Columnas que se usan

| Columna | Tipo | Para qué |
|---|---|---|
| `Cd_Tabla` | nvarchar(50) | Módulo de origen — 14 valores distintos |
| `Cd_Documento` | nvarchar(30) | Folio del módulo + sufijos (ver abajo) |
| `Cd_Timbre_UUID` | nvarchar(50) | UUID del CFDI. **Normalizar a mayúsculas** |
| `Cd_Timbre_Fecha` | datetime | = `FechaTimbrado` del TFD. Filtro del periodo |
| `Cd_RFC_Emisor` / `Cd_RFC_Receptor` | nvarchar(20) | Clasificación recibido/emitido |
| `Cd_Monto` | decimal(18,9) | **≡ `Total` del XML**, 2,700/2,700 en enero |
| `Cd_Moneda`, `Cd_Tipo_Cambio` | | Moneda del comprobante |
| `Cd_Tipo_CFDI` | nvarchar(15) | `I` / `E` / `P` / `T` / `RETENCIONES` |
| `Cd_Serie_Folio` | nvarchar(50) | Serie+folio del emisor |
| `Es_Cve_Estado` | nvarchar(4) | `AC` vigente / `CA` cancelado |
| `Cd_XML` | ntext | **El CFDI completo.** La fuente real de todo |

`Cd_Tipo_Comprobante_CFDI` (`INGRESO`/`PAGO`/`NOMINA`/`EGRESO`) viene **vacío**
para varios módulos — no es confiable; se usa `Cd_Tipo_CFDI` o se lee el XML.

### Estructura de `Cd_Documento`

```
GASTO_REGISTRO   01-003485100010001   folio(10) + Grd_ID(4) + secuencia(4)
GASTO_REGISTRO   01-00345910001       folio(10) + Grd_ID(4)
COMPRA           05-00296120002       folio(10) + secuencia(4)
CHEQUE           01-00851890001       folio(10) + secuencia(4)
FACTURA          76-0000585           folio(10)
```

**Llaves verificadas (enero 2026):**

| Llave | Regla | Match |
|---|---|---:|
| CFDI → folio del módulo | `LEFT(Cd_Documento, 10)` | **100%** en los 8 módulos |
| CFDI de gasto → documento | `SUBSTRING(Cd_Documento, 11, 4) = Grd_ID` | **100%** (1,479/1,479) |

En los módulos que no son gasto, el tramo 11–14 es un **consecutivo de
comprobante por folio**, no un sub-documento: la compra `05-0029612` tiene
sufijo `0002` y un solo registro en `Compra_Encabezado`.

Folios que matchearon contra su tabla de origen: gasto 1,301/1,301, compra
692/692, cheque 342/342, CxP 84/84, NCP 6/6, anticipo 1/1, compra indirecta 1/1,
factura 8/8.

---

## 2. Los ocho módulos de MPro

Todos se normalizan al mismo shape en `conciliacion_xml_lib.REG_SQL`:

```
ORIGEN, FOLIO, DOC_ID, FECHA, ESTADO, SUBORIGEN, PROVEEDOR,
MONEDA, TIPO_CAMBIO, SUBTOTAL, IMPUESTOS, TOTAL, CONCEPTO
```

`DOC_ID` sólo se usa en `GASTO_REGISTRO` (= `Grd_ID`); en el resto va vacío.

| Módulo | Tabla | Folio | Fecha | Subtotal | Impuestos | Total |
|---|---|---|---|---|---|---|
| GASTO_REGISTRO | `Gasto_Registro_Documento` ⋈ `Gasto_Registro` | `Gr_Folio` + `Grd_ID` | `Gr_Fecha` | `Grd_Precio_Descontado_Importe` | `Grd_Impuesto_Importe` | `Grd_Precio_Neto_Importe` |
| COMPRA | `Compra_Encabezado` | `Co_Folio` | `Co_Fecha` | `Co_Precio_Descontado_Importe` | `Co_Impuesto_Importe` | `Co_Precio_Neto_Importe` |
| CUENTA_X_PAGAR | `Cuenta_X_Pagar` | `Cxp_Folio` | `Cxp_Fecha` | `Cxp_Precio_Descontado_Importe` | `Cxp_Impuesto_Importe` | `Cxp_Precio_Neto_Importe` |
| CHEQUE | `Cheque` | `Ch_Folio` | `Ch_Fecha` | — | — | `Ch_Importe` |
| ANTICIPO_CXP | `Anticipo_CXP` | `An_Folio` | `An_Fecha` | — | — | `An_Importe` |
| COMPRA_INDIRECTO | `Compra_Indirecto` (agregado) | `Ci_Folio` | `Ci_Fecha` | `SUM(Ci_Precio_Descontado_Importe)` | `SUM(Ci_Impuesto_Importe)` | `SUM(Ci_Precio_Neto_Importe)` |
| NOTA_CREDITO_PROVEEDOR | `Nota_Credito_Proveedor` (agregado) | `Nc_Folio` | `Nc_Fecha` | `SUM(Nc_Precio_Descontado_Importe)` | `SUM(Nc_Impuesto_Importe)` | `SUM(Nc_Precio_Neto_Importe)` |
| FACTURA | `Factura_Encabezado` | `Fc_Folio` | `Fc_Fecha` | `Fc_Precio_Descontado_Importe` | `Fc_Impuesto_Importe` | `Fc_Precio_Neto_Importe` |

`Compra_Indirecto` y `Nota_Credito_Proveedor` son tablas **de detalle** (una
fila por partida): se agregan por folio.

### `SUBORIGEN` — de dónde viene el documento

Convención recurrente del ERP: dos columnas genéricas guardan de qué tabla viene
el documento y cuál es su folio.

| Módulo | Columna | Valores en enero 2026 |
|---|---|---|
| GASTO_REGISTRO | `Gr_Tabla` | `CONSUMO_INTERNO` 3,021 · `''`→GASTO_DIRECTO 764 · `CONTROL_COMBUSTIBLE` 384 · `VIAJE` 354 · `GASTO_REGISTRO_NOMINA` 111 · `ORDEN_COMPRA` 76 · `GASTO_RECLASIFICACION` 15 |
| COMPRA | `Co_Tabla` | `ORDEN_COMPRA` 620 · `''`→COMPRA_DIRECTA 137 · `CONTRATO_CONSIGNA_REPOSICION` 11 · `FIN_CONTRATO_CONSIGNA` 2 |
| CUENTA_X_PAGAR | `Cxp_Tabla` | `Gasto_Registro:<folio>` 1,333 · `Compra` 761 · `GASTO_REGISTRO_NOMINA` 111 · `Cuenta_X_Pagar` 104 · `Anticipo_Cxp` 64 · `Recibo_Pago` 58 · … |
| CHEQUE | `Ch_Tabla` | vacío en todos los de enero |

### La cadena documental de `Cuenta_X_Pagar`

Es la que evita reportar 1,718 huecos falsos. Se resuelve así:

```
Cxp_Tabla = 'Gasto_Registro:01-0034686'  +  Cxp_Documento = '0001'
   → GASTO_REGISTRO, folio 01-0034686, Grd_ID 0001

Cxp_Tabla = 'Compra'                     +  Cxp_Documento = '05-0029632'
   → COMPRA, folio 05-0029632

Cxp_Tabla = 'Compra_Indirecto'           +  Cxp_Documento = <Ci_Folio>
```

Implementado en `04_conciliacion_mpro_vs_xml.resolver_cadena()`.

---

## 3. Impuestos

### El catálogo `Impuesto`

28 claves activas. Columnas que importan:

| Columna | Para qué |
|---|---|
| `Im_Cve_Impuesto` | Clave del ERP (`0001`…`0028`) |
| `Im_Descripcion` | Nombre legible |
| `Im_Codigo_SAT` | `001` ISR / `002` IVA / `003` IEPS — **la traducción** |
| `Im_Tasa` | **Su signo separa traslado (>0) de retención (<0)** |
| `Im_Tipo_Impuesto` | `IVA` / `ISR` / `IMSS` |

Claves más usadas en enero (gasto):

| Clave | Descripción | SAT | Tasa | n |
|---|---|---|---:|---:|
| `0001` | IVA ACREDITABLE 16% | 002 | 16.0 | 1,065 |
| `0002` | IVA ACREDITABLE 16% VARIABLE | 002 | 16.0 | 441 |
| `0015` | IVA RETENIDO SOBRE FLETES 4% | 002 | −4.0 | 323 |
| `0004` | IVA ACREDITABLE EXENTO | 002 | 0.0 | 68 |
| `0003` | IVA ACREDITABLE 0% | 002 | 0.0 | 59 |
| `0022` | **IMSS PATRON** | 001 | +1.0 | 22 |
| `0026` | ISR RETENIDO RESICO 1.25% | 001 | −1.25 | 20 |
| `0013` | ISR RETENIDO SOBRE DIVIDENDOS 10% | 001 | −10.0 | 16 |

> ⚠️ **`0019`, `0020`, `0021` y `0022` traen código SAT sin ser impuestos de
> CFDI.** Son provisiones de nómina (IMSS trabajador, subsidio al empleo, ISR a
> favor, IMSS patrón). Están en la constante `IMPUESTOS_NO_CFDI` y se excluyen
> de la comparación; se cuentan en `MPRO_IMP_NO_CFDI`.

> ⚠️ **Ninguna clave tiene código SAT `003`.** MPro no sabe registrar IEPS a
> nivel comprobante — de ahí los $879.59 sin contraparte en enero.

### Tablas de impuestos por módulo

| Módulo | Tabla | Grano | Clave | Importe |
|---|---|---|---|---|
| GASTO_REGISTRO | `Gasto_Registro_Impuesto` | folio + `Grd_ID` | `Im_Cve_Impuesto` | `Gri_Importe` |
| COMPRA | `Compra_Total_Impuesto` | folio | `Ct_Impuesto` | `Ct_Impuesto_Importe` |
| CUENTA_X_PAGAR | `Cuenta_X_Pagar_Impuesto` | folio | `Im_Cve_Impuesto` | `Cxpi_Importe` |
| COMPRA_INDIRECTO | `Compra_Indirecto_Impuesto` | folio + `Ci_ID` | `Im_Cve_Impuesto` | `Im_Importe` |
| NOTA_CREDITO_PROVEEDOR | `Nota_Credito_Proveedor_Impuesto` | folio + `Nc_ID` | `Im_Cve_Impuesto` | `Im_Importe` |
| FACTURA | `Factura_Total_Impuesto` | folio | `Ft_Impuesto` | `Ft_Impuesto_Importe` |

**`CHEQUE` y `ANTICIPO_CXP` no tienen tabla de impuestos** — por diseño, no por
omisión (ver [metodología §5](metodologia.md#5-los-impuestos)).

---

## 4. Nómina — donde aterrizan los vales de despensa

| Tabla | Para qué |
|---|---|
| `Gasto_Registro_Nomina_Gasto` | Gasto de nómina por concepto y centro de costo |
| `Tipo_Gasto` | Catálogo, 249 claves, 1 fila por clave |

Columnas: `Grn_Folio`, `Gng_ID`, `Cc_Cve_Centro_Costo`, `Tg_Cve_Tipo_Gasto`,
`Gng_Importe`, `Gr_Folio`, `Pv_Cve_Proveedor`.

`Tg_Cve_Tipo_Gasto = '0020'` = **VALES DE DESPENSA**. Es la contrapartida
contable de los CFDI con complemento `ValesDeDespensa` — ver
[metodología §3](metodologia.md#vales-de-despensa).

---

## 5. Estructura del CFDI que se lee

`parsear_cfdi()` es namespace-agnóstico (`{*}`) porque conviven CFDI 3.3 y 4.0
—aunque en enero 2026 los 2,700 son 4.0.

```
cfdi:Comprobante              @Version @Fecha @Serie @Folio @SubTotal @Descuento
                              @Total @Moneda @TipoCambio @TipoDeComprobante
                              @MetodoPago @FormaPago
├── cfdi:Emisor               @Rfc @Nombre
├── cfdi:Receptor             @Rfc @UsoCFDI
├── cfdi:Conceptos
│   └── cfdi:Concepto         ← sus cfdi:Impuestos NO se leen (duplicarían el IVA)
├── cfdi:Impuestos            ← ESTE, hijo directo de la raíz
│   ├── @TotalImpuestosTrasladados @TotalImpuestosRetenidos
│   ├── cfdi:Traslados/Traslado    @Impuesto @TipoFactor @Base @Importe
│   └── cfdi:Retenciones/Retencion @Impuesto @Importe
└── cfdi:Complemento
    ├── tfd:TimbreFiscalDigital        @UUID @FechaTimbrado
    ├── pago20:Pagos                   ← tipo P
    │   ├── Totales                    @MontoTotalPagos @TotalTrasladosImpuestoIVA16
    │   └── Pago                       @Monto @FechaPago
    │       └── DoctoRelacionado       @IdDocumento @ImpPagado @ImpSaldoAnt
    ├── valesdedespensa:ValesDeDespensa  @total @tipoOperacion
    │   └── Conceptos/Concepto         @curp @rfc @nombre @importe @numSeguridadSocial
    └── implocal:ImpuestosLocales      @TotaldeTraslados @TotaldeRetenciones
```

### Campos que devuelve `parsear_cfdi()`

`XML_OK`, `XML_ERROR`, `XML_VERSION`, `XML_FECHA`, `XML_SERIE`, `XML_FOLIO`,
`XML_TIPO`, `XML_MONEDA`, `XML_TIPO_CAMBIO`, `XML_METODO_PAGO`,
`XML_FORMA_PAGO`, `XML_EMISOR_NOMBRE`, `XML_USO_CFDI`, `XML_SUBTOTAL`,
`XML_DESCUENTO`, `XML_TOTAL`, `XML_IVA_TRASLADADO`, `XML_IEPS_TRASLADADO`,
`XML_RET_IVA`, `XML_RET_ISR`, `XML_TRASLADOS_TOTAL`, `XML_RETENIDOS_TOTAL`,
`XML_BASE_EXENTA`, `XML_PAGOS_MONTO`, `XML_PAGOS_IVA`, `XML_N_CONCEPTOS`,
`XML_COMPLEMENTOS`, `XML_VALES_DESPENSA`, `XML_VALES_N_TRAB`,
`XML_IMP_LOCAL_TRAS`, `XML_IMP_LOCAL_RET`, `XML_DR_UUIDS`, `XML_DR_PAGADO`.

Un XML corrupto no rompe la corrida: `XML_OK = False` y el mensaje en
`XML_ERROR`. En enero, 2,700/2,700 parsearon limpio.

---

## 6. Gotchas del motor

- **`.205` corre SQL Server anterior a 2017**: no existe `STRING_AGG`. Las
  agregaciones de texto se hacen en pandas.
- **`Cd_XML` es `ntext`**: hay que castear a `nvarchar(MAX)` para leerlo con
  pymssql.
- **No unir `sys.partitions` con `sys.allocation_units`** para contar filas: el
  join multiplica el conteo en toda tabla con columnas LOB. `Comprobante_Digital`
  llegaba a reportar 1.37 M filas cuando son ~690 k.
- **UUID con casing inconsistente** en la fuente: normalizar siempre a
  mayúsculas antes de comparar.
