# Metodología

Cómo se concilia un CFDI recibido contra su registro en Management Pro, y por
qué cada decisión está donde está. Todo lo que se afirma aquí se midió contra
`.205/TRIVASADB3` el 2026-09-04 sobre enero 2026; donde hay una cifra, es una
cifra de esa corrida, no una estimación.

---

## 1. El universo: qué es "un XML recibido"

Base: la tabla `Comprobante_Digital`, que es el puente genérico del ERP entre
un documento de cualquier módulo y su CFDI (`Cd_Tabla` / `Cd_Documento` →
`Cd_Timbre_UUID`).

**Recibido** = `Cd_RFC_Receptor = 'TRI970922TL2'` **y** `Cd_RFC_Emisor <> ese`.

La clasificación por RFC es limpia, no ambigua. Medido en enero 2026:

| `Cd_Tabla` | Filas | Recibido | Emitido | Autoemitido |
|---|---:|---:|---:|---:|
| TRASLADO | 3,686 | 0 | 0 | **3,686** |
| FACTURA | 2,236 | 8 | 2,228 | 0 |
| GASTO_REGISTRO | 1,510 | **1,479** | 31 | 0 |
| COMPRA | 692 | **692** | 0 | 0 |
| COMPROBANTE_PAGO | 570 | 0 | 570 | 0 |
| CHEQUE | 429 | **429** | 0 | 0 |
| NOTA_CREDITO | 204 | 0 | 204 | 0 |
| CUENTA_X_PAGAR | 84 | **84** | 0 | 0 |
| CONSTANCIA_RETENCION | 16 | 0 | 16 | 0 |
| NOTA_CREDITO_PROVEEDOR | 6 | **6** | 0 | 0 |
| ANTICIPO_CXP | 1 | **1** | 0 | 0 |
| COMPRA_INDIRECTO | 1 | **1** | 0 | 0 |
| **Total** | **9,435** | **2,700** | 3,049 | 3,686 |

**`TRASLADO` queda fuera del universo.** Es 100% autoemitido (emisor = receptor
= Trivasa), `Cd_Monto = 0`, moneda `XXX`: carta porte por mover material propio
entre plantas. No hay importe que conciliar. Se cuenta y se reporta aparte para
que su ausencia no se lea como omisión.

**Los ocho módulos de origen** del universo recibido son entonces:
`GASTO_REGISTRO`, `COMPRA`, `CHEQUE`, `CUENTA_X_PAGAR`, `ANTICIPO_CXP`,
`COMPRA_INDIRECTO`, `NOTA_CREDITO_PROVEEDOR` y `FACTURA` (este último, anómalo:
ocho facturas de venta con un CFDI recibido colgando — ver hallazgos).

### Fecha del periodo

El filtro es `Cd_Timbre_Fecha` — la fecha de timbrado ante el SAT, que es
idéntica al `FechaTimbrado` del `TimbreFiscalDigital` (verificado por muestreo).
No se usa la fecha de emisión del comprobante ni la del registro de MPro.

Consecuencia medida: 90 de los 2,700 CFDI timbrados en enero tienen `Fecha` de
emisión en diciembre 2025. Aparecen en el reporte con `XML_FECHA` fuera del mes,
lo cual es correcto: se timbraron en enero.

---

## 2. El grano: por qué no es "un XML" ni "un registro"

**La relación CFDI ↔ documento de MPro no es 1:1.** Comparar fila por fila
inventa descuadres que no existen. Medido en enero:

| Forma | Grupos | Qué es |
|---|---:|---|
| 1:1 | 1,818 | Un CFDI, un documento |
| 1:N | 82 | Un CFDI repartido en varios documentos (hasta **108**) |
| N:1 | 21 | Varios CFDI sobre un documento (hasta **33** REP en un cheque) |
| N:M | 17 | Las dos cosas a la vez |

Los dos casos extremos son reales y explicables: un CFDI de gasto se prorratea
entre muchos documentos (una póliza de seguro entre sucursales), y un cheque
paga muchas facturas de un proveedor, cada una con su propio REP.

### La solución: componente conexa

El grano de conciliación es la **componente conexa del grafo bipartito**
(CFDI) ↔ (documento de MPro), calculada **por módulo**. Se implementa con
union-find en `asignar_grupos()`. El identificador del grupo es
`<ORIGEN>:<folio más chico de la componente>` — estable entre corridas.

**Por módulo, nunca entre módulos.** La `Cuenta_X_Pagar` se genera desde el
gasto: si un mismo UUID cae en `GASTO_REGISTRO` y en `CUENTA_X_PAGAR` (41 casos
en enero), unir los dos lados duplicaría el importe de MPro. Cada módulo se
concilia por separado y el UUID aparece en dos grupos, cada uno con su propia
comparación. Eso es correcto: tanto el gasto como la CxP deben valer lo mismo
que el CFDI.

### El cierre hacia atrás

Un folio de cheque de anticipo acumula su factura y sus notas de crédito
durante meses o años. Si el grupo se arma sólo con los CFDI del periodo, queda
truncado y descuadra por construcción.

`cerrar_universo()` expande iterativamente: folio → todos sus CFDI → todos sus
documentos, hasta que no entra nada nuevo. En enero convergió en una pasada y
agregó **26 comprobantes** de otros periodos, todos en `CHEQUE`. Se marcan con
`N_XML_PERIODO < N_XML` y el motivo `ARRASTRA_CFDI_DE_OTRO_PERIODO`.

Caso real: cheque `01-0060062`, un anticipo con 8 CFDI colgando — una factura
de enero 2024 y siete notas de crédito repartidas entre septiembre 2024 y
febrero 2026.

> ⚠️ **Límite conocido:** el cierre **sobrecuenta en pagos por parcialidades**.
> El cheque `01-0046128` (ECOPULSE, $65,086.45) tiene 10 REP mensuales de julio
> 2025 a junio 2026, uno por parcialidad; el grupo suma $650,864.40 contra un
> cheque de $65,086.45. No es error de captura: es el método. Queda
> identificable por `ARRASTRA_CFDI_DE_OTRO_PERIODO` y `N_XML > N_XML_PERIODO`.
> La mejora sería usar `NumParcialidad` del `DoctoRelacionado`.

---

## 3. El importe comparable del lado XML

**`Total` del comprobante no siempre es el importe de la operación.** Esta es
la trampa central de la conciliación, y la razón de que la primera versión de
estos reportes tuviera un hallazgo equivocado.

Censo de complementos sobre los 2,700 CFDI recibidos de enero:

| Complemento | CFDI | ¿Mueve el importe fuera del `Total`? |
|---|---:|---|
| `TimbreFiscalDigital` | 2,700 | No (es el timbre) |
| `EstadoDeCuentaCombustible` | 436 | **No** — el `Total` es correcto, verificado en los 436 |
| `Pagos` (REP) | 416 | **Sí** — el `Total` es 0 por diseño del SAT |
| `CartaPorte` | 290 | No |
| `ValesDeDespensa` | 19 | **Sí** — el `Total` es sólo la comisión |
| `ImpuestosLocales` | 12 | El importe no; **los impuestos sí** |
| `Divisas` | 4 | No |
| `Aerolineas` | 3 | No |
| `Donatarias` | 2 | No |
| `CFDIRegistroFiscal` | 1 | No |

### Regla de lectura

```
tipo P (REP)                 → pago20:Totales/@MontoTotalPagos
complemento ValesDeDespensa  → el Total NO es la operación; ver abajo
resto (I, E)                 → cfdi:Comprobante/@Total
```

### Vales de despensa

El CFDI se timbra por la **comisión** —`Total = $0.01`, concepto "COMISION"— y
la dispersión real viaja en `valesdedespensa:ValesDeDespensa/@total`,
desglosada trabajador por trabajador con CURP y número de seguridad social.

Enero 2026: **19 comprobantes de $0.01 que mueven $792,344.95 a 1,445
trabajadores**, emisor TOKA INTERNACIONAL (`TIN090211JC9`).

MPro registra el `Total` del comprobante en toda la cadena —gasto $0.01 → CxP
$0.01 → cheque $0.01— y **hace bien**: el gasto real de los vales es una
prestación al trabajador y se lleva por nómina. Comprobado:
`Gasto_Registro_Nomina_Gasto` con `Tg_Cve_Tipo_Gasto = '0020'` (VALES DE
DESPENSA) suma **$804,741.62** en enero en 19 folios, y **17 de los 19 CFDI
empatan al centavo** con uno de esos folios ($636,193.23). Los 2 restantes
($168,141.40) caen contra un folio de $168,548.39 — $406.99 de diferencia,
no confirmado al centavo.

Los REP que liquidan esas facturas pagan el saldo real (`ImpSaldoAnt` de
$166,758.95 contra una factura de $0.01), de ahí el aparente descuadre contra
cheques de $0.01.

### Detección genérica

No se codifica "TOKA" en ningún lado. El marcado es por estructura:

1. El comprobante trae `ValesDeDespensa` → `COMPLEMENTO_IMPORTE = @total`.
2. Es un REP cuyos `DoctoRelacionado` liquidan más de lo que suman los
   `Cd_Monto` de esos comprobantes → `COMPLEMENTO_IMPORTE = ImpPagado`.
   Se resuelve con `montos_por_uuid()`, una consulta barata a
   `Comprobante_Digital` por los UUID que el REP referencia.

Los grupos así marcados salen del descuadre con el estatus
`IMPORTE_EN_COMPLEMENTO` y su monto queda en la columna
`XML_COMPLEMENTO_IMPORTE`. En enero: 12 grupos, $1,310,702.25 ($792,344.95 de
vales + $518,357.30 de REP).

---

## 4. El importe del lado MPro

Cada módulo tiene su columna de total, normalizada a un shape único
(`ORIGEN, FOLIO, DOC_ID, FECHA, ESTADO, SUBORIGEN, PROVEEDOR, MONEDA,
TIPO_CAMBIO, SUBTOTAL, IMPUESTOS, TOTAL, CONCEPTO`) — ver
[esquema-datos.md](esquema-datos.md).

**Moneda:** MPro guarda los importes en la moneda original del documento, igual
que el CFDI. Verificado contra los 35 CFDI en USD y 1 en EUR de enero: la
comparación es directa, sin conversión. `TIPO_CAMBIO` se conserva como columna
informativa.

---

## 5. Los impuestos

### Lado XML

Se leen del nodo `cfdi:Impuestos` **hijo directo** de `cfdi:Comprobante`.

> ⚠️ El mismo nodo existe dentro de cada `cfdi:Concepto`. Sumar los dos niveles
> **duplica el IVA**. Es un error real que ya ocurrió en el ELT de
> `raw_sat.cfdi_recibidos` y se corrigió allá el 2026-09-02. Aquí se evita por
> construcción usando `root.find("{*}Impuestos")`, que sólo mira hijos directos.

Se extraen cuatro categorías, por código del SAT:

| Categoría | Origen en el XML |
|---|---|
| IVA trasladado | `Traslados/Traslado[@Impuesto='002']/@Importe` |
| IEPS trasladado | `Traslados/Traslado[@Impuesto='003']/@Importe` |
| IVA retenido | `Retenciones/Retencion[@Impuesto='002']/@Importe` |
| ISR retenido | `Retenciones/Retencion[@Impuesto='001']/@Importe` |

Los `Traslado` con `TipoFactor="Exento"` no traen `Importe`; su `Base` se
acumula aparte en `XML_BASE_EXENTA`.

### Lado MPro

Cada módulo tiene su tabla de impuestos. La clave propia del ERP
(`Im_Cve_Impuesto`) se traduce al código del SAT con el catálogo `Impuesto`:

- `Im_Codigo_SAT` → `001` ISR / `002` IVA / `003` IEPS.
- **El signo de `Im_Tasa` separa traslado de retención**: tasa positiva =
  traslado, negativa = retención.
- MPro guarda las retenciones **en negativo** y el CFDI en positivo: se comparan
  en valor absoluto.

**Cuatro claves traen código SAT sin ser impuestos de CFDI** y se excluyen:
`0019` IMSS TRABAJADOR, `0020` SUBSIDIO AL EMPLEO, `0021` ISR A FAVOR, `0022`
IMSS PATRON. Son provisiones de nómina. Se cuentan aparte en
`MPRO_IMP_NO_CFDI` — $202,472.45 en enero, todo de la clave `0022`.

### Impuestos locales

MPro **no lleva el concepto por separado: lo suma dentro de su clave de IVA.**
Por eso el lado XML del par de IVA es `XML_IVA_TRASLADADO + XML_IMP_LOCAL_TRAS`.

Verificado al centavo: gasto `05-0175447`, IVA federal del CFDI $208.86 + ISH
$58.75 = **$267.61**, exactamente lo que MPro registró bajo "IVA ACREDITABLE
16%". Sin esta suma el reporte marcaba dos falsos positivos de "IVA mal
capturado".

De los $434.59 de impuesto local de enero, MPro capturó $112.49 (2 gastos) y
dejó fuera $322.10 (7 gastos). Eso último sí es un faltante real.

### Módulos sin tabla de impuestos

`CHEQUE` y `ANTICIPO_CXP` no tienen tabla de impuestos en el ERP, y **no debería
tenerla**: un REP no genera IVA acreditable propio — el acreditamiento vive en
la factura que el REP paga. Esos grupos salen como `NO_COMPARABLE_MODULO` y su
IVA ($36,641.97 en enero) se reporta aparte para que no se lea como faltante.

---

## 6. Tolerancias y semáforo

```python
TOL_CENTAVOS = 0.05   # ruido de redondeo puro
TOL_MENOR    = 1.00   # diferencia < 1 peso: no material
```

### Reportes 02 y 03 — estatus de importes

| Estatus | Condición | ¿Cuenta como descuadre? |
|---|---|---|
| `CONCILIA` | \|dif\| ≤ 0.05 | No |
| `DIF_CENTAVOS` | \|dif\| ≤ 1.00 | No |
| `IMPORTE_EN_COMPLEMENTO` | El importe del CFDI vive en un complemento | **No** |
| `REPARTIDO_ENTRE_MODULOS` | El CFDI se reparte entre módulos complementarios y la suma cuadra | **No** |
| `REGISTRO_EN_CERO` | MPro ≈ 0 con CFDI > 1 | Sí |
| `DIF_MATERIAL` | El resto | Sí |
| `MODULO_NO_CUBIERTO` | El módulo de origen no es de compra/gasto (intercompañía) | No comparable |
| `SIN_REGISTRO` | No hay documento y el módulo sí se lee | Sí |

Los conjuntos `ESTATUS_CUADRA` y `ESTATUS_EXPLICADO` en el lib son la fuente
única de esa clasificación; los reportes no la reimplementan.

La columna `MOTIVO` acumula pistas cuando hay diferencia:
`ARRASTRA_CFDI_DE_OTRO_PERIODO`, `MEZCLA_INGRESO_Y_EGRESO`,
`CFDI_CANCELADO_EN_MPRO`, `REGISTRO_CANCELADO`, `MPRO_REGISTRA_MENOS` /
`MPRO_REGISTRA_MAS`, `CFDI_VALES_DE_DESPENSA`,
`REP_LIQUIDA_CFDI_CON_COMPLEMENTO`, `CFDI_REPARTIDO_ENTRE_MODULOS`,
`INTERCOMPANIA`.

### CFDI repartido entre módulos complementarios

`D3` concilia cada módulo por separado para no duplicar el lado de MPro. Eso es
correcto cuando un módulo se **deriva** del otro (la CxP hereda el importe del
gasto). Pero hay pares **complementarios** donde el CFDI se reparte:

```
CFDI 90227AAD · $161,190.75
  COMPRA:23-0007859            $160,070.26   la mercancía
  COMPRA_INDIRECTO:23-0000126    $1,120.49   el cargo accesorio
                              ─────────────
                               $161,190.75   suma exacta
```

La detección es genérica: si la **suma** de los importes de MPro de todos los
grupos que comparten un UUID cuadra con el CFDI, los grupos pasan a
`REPARTIDO_ENTRE_MODULOS` y salen del descuadre. **Se auto-protege del caso
derivado**: si dos módulos registran cada uno el importe completo, la suma da el
doble y no se marca. Enero 12 grupos, febrero 16.

### Operaciones intercompañía

`TRIVASADB3` alberga cuatro razones sociales (Trivasa `0001`, Facilitadores de
la Construcción `0002`, Flexbeel `0003`, Triturados de Valladolid `0004`). Un
CFDI emitido por una de ellas a Trivasa es un comprobante recibido, pero su
registro vive en el módulo de **venta** de la otra empresa, que estos reportes
no leen. Se marcan con `INTERCOMPANIA` y, cuando su módulo no es de
compra/gasto, con el estatus `MODULO_NO_CUBIERTO` — no `SIN_REGISTRO`, que se
leería como hueco. Enero 83 CFDI, febrero 22.

### Reporte 04 — clases de cobertura

"Sin XML" **no** significa "sin respaldo". Cada clase se asigna con evidencia
del dato, nunca por criterio:

| Clase | Cómo se determina |
|---|---|
| `CON_XML_CONCILIA` / `_DIF_CENTAVOS` / `_DIF_MATERIAL` | Por la diferencia **del grupo**, no de la fila |
| `CON_XML_IMPORTE_EN_COMPLEMENTO` | El grupo trae complemento de vales |
| `SIN_XML_CANCELADO` | `Es_Cve_Estado = 'CA'` |
| `SIN_XML_IMPORTE_CERO` | \|total\| ≤ 0.05 |
| `SIN_XML_IMPORTE_NEGATIVO` | total < 0 — aplicaciones y reversas de anticipo |
| `SIN_XML_TRASPASO_INTERNO` | Cheque cuyo beneficiario es la propia Trivasa |
| `SIN_XML_ORIGEN_INTERNO` | Suborigen sin CFDI de proveedor por naturaleza |
| `SIN_XML_CFDI_EN_ORIGEN` | La cadena documental se resuelve y **ese documento sí tiene UUID** |
| `SIN_XML_PENDIENTE` | El resto: el hueco a revisar |

> **El orden de evaluación importa**: cancelado → importe cero → negativo →
> traspaso interno → origen interno → CFDI en origen → pendiente. Cambiarlo
> mueve documentos entre clases.

**`SIN_XML_ORIGEN_INTERNO`** cubre `CONSUMO_INTERNO`, `GASTO_RECLASIFICACION`,
`GASTO_REGISTRO_NOMINA(_CXP)` y `Recibo_Pago`. La etiqueta es auditable: el
reporte imprime la cobertura medida por suborigen, y los cuatro salen en 0.0%.

**`SIN_XML_CFDI_EN_ORIGEN`** resuelve la cadena de verdad.
`Cuenta_X_Pagar.Cxp_Tabla` guarda el módulo **y el folio** que la originó
(`'Gasto_Registro:01-0034686'`) y `Cxp_Documento` guarda el `Grd_ID`; para
compra, `Cxp_Tabla = 'Compra'` y `Cxp_Documento` es el `Co_Folio`. Sólo se marca
así cuando ese documento **efectivamente** tiene un CFDI ligado. En enero: 1,718
CxP, $44.04 M.

### El join del reporte 04 no se acota por fecha

Un registro de enero puede traer su CFDI timbrado en diciembre o en febrero.
Filtrar el join por el periodo inventaría huecos. Medido: **171 documentos** de
enero traen su CFDI timbrado en otro mes. Caso real: la compra `05-0029612`,
fechada 2025-12-31, con su comprobante timbrado el 2 de enero.

---

## 7. Cómo leer los porcentajes

Hay tres, y miden cosas distintas. Usar el equivocado da una conclusión falsa.

| Indicador | Enero 2026 | Qué mide |
|---|---:|---|
| % de grupos que concilian | 96.6% | Cuántos vínculos cuadran |
| % del importe conciliado | 95.59% | Cuánto dinero cuadra |
| % de documentos con XML (rep. 04) | 21.7% | **Engañoso**: cuenta consumo interno y nómina, que nunca llevan CFDI |
| **% del IVA acreditable con CFDI** | **99.77%** | **El que importa para el SAT** |

El último se calcula en `05_resumen_conciliacion.py` cruzando los impuestos por
documento contra la cobertura del reporte 04, sobre documentos **no cancelados**
de los módulos que generan IVA acreditable (gasto, compra, compra indirecta,
nota de crédito de proveedor).
