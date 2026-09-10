# Hallazgos — enero 2026

Corrida del 2026-09-04 contra `.205/TRIVASADB3`, periodo `[2026-01-01,
2026-02-01)`. Versión de los reportes: la posterior a la corrección de
complementos ([D7](decisiones.md#d7--los-cfdi-cuyo-importe-vive-en-un-complemento-no-cuentan-como-descuadre) y
[D8](decisiones.md#d8--los-impuestos-locales-se-suman-al-iva-del-lado-xml)).

Reporte navegable de los dos meses: `../hallazgos_conciliacion_2026-01-02.html`.

---

## Resumen

| Indicador | Valor |
|---|---:|
| CFDI recibidos en el mes | 2,700 vínculos · 2,037 UUID |
| Grupos de conciliación | 1,938 |
| Grupos que concilian (±$1) | **1,872 · 96.6%** |
| Importe de los CFDI | $96,762,857.42 |
| Importe registrado en MPro | $93,134,160.95 |
| Descuadre real | **$4,105,233.21 · 4.24%** |
| Importe en complemento (no es descuadre) | $1,310,702.25 |
| **IVA acreditable con CFDI ligado** | **99.77%** |
| Pendiente de captura limpio | $105,102.74 · 17 documentos |

> **Cifras recalculadas el 2026-09-04 por la noche** con las correcciones
> [D13](decisiones.md#d13--los-cfdi-intercompañía-se-marcan-no-se-cuentan-como-hueco)
> y [D14](decisiones.md#d14--un-cfdi-repartido-entre-módulos-complementarios-no-es-descuadre),
> que salieron de la corrida de febrero. El descuadre bajó de $4,270,134.38 a
> $4,105,233.21 al reclasificar 12 grupos con el CFDI repartido entre módulos.

**Veredicto:** los importes e impuestos de MPro sí están soportados por los CFDI
que se le reportan al SAT. Lo que no cuadra tiene causa identificada y, salvo
$105 k, no es un hueco de captura.

---

## Reporte 02 — importes

| Estatus | Grupos | % |
|---|---:|---:|
| `CONCILIA` | 1,826 | 94.2% |
| `DIF_CENTAVOS` | 46 | 2.4% |
| `DIF_MATERIAL` | 42 | 2.2% |
| `IMPORTE_EN_COMPLEMENTO` | 12 | 0.6% |
| `REPARTIDO_ENTRE_MODULOS` | 12 | 0.6% |
| `SIN_REGISTRO` | 0 | — |

**Cero grupos sin registro**: todo CFDI recibido del mes tiene su documento en
MPro. La cobertura del lado XML es total; el problema, donde lo hay, es de
importe o de vinculación.

### Por módulo

| Origen | Grupos | Concilia | Centavos | Complem./repartido | Descuadre | Importe CFDI | Descuadre $ |
|---|---:|---:|---:|---:|---:|---:|---:|
| GASTO_REGISTRO | 849 | 807 | 6 | 6 | 30 | 11,896,333.02 | 2,796,899.61 |
| COMPRA | 665 | 623 | 36 | 6 | 0 | 35,505,129.77 | 0.00 |
| CHEQUE | 336 | 309 | 4 | 12 | 11 | 35,234,387.57 | 1,307,391.25 |
| CUENTA_X_PAGAR | 72 | 72 | 0 | 0 | 0 | 12,484,087.83 | 0.00 |
| FACTURA | 8 | 8 | 0 | 0 | 0 | 1,555,954.21 | 0.00 |
| NOTA_CREDITO_PROVEEDOR | 6 | 6 | 0 | 0 | 0 | 72,377.97 | 0.00 |
| ANTICIPO_CXP · COMPRA_INDIRECTO | 2 | 1 | 0 | 0 | 1 | 14,587.05 | 1,986.06 |
| **Total** | **1,938** | **1,826** | **46** | **24** | **42** | **96,762,857.42** | **4,105,233.21** |

`CUENTA_X_PAGAR` concilia al 100% en sus 72 grupos: la CxP hereda el importe del
documento que la origina y ese camino no tiene fugas.

### H1 · Arrendamiento financiero — el CFDI cubre más que el gasto
*Contable, no error · 18 grupos · ~$990 k*

El CFDI del banco incluye la **amortización de capital** junto con los
intereses; MPro registra en el gasto únicamente los intereses, porque el capital
abate pasivo. Verificado al centavo:

```
Folio 01-0034761 · CFDI total $68,380.24
  concepto AMORTIZACION 022/048    $45,035.69
  concepto INTERES                  $6,962.44
  concepto INTERES                  $8,062.41   → suma $15,024.85
MPro · gasto "INTERESES ARRENDAMIENTO FINANCIERO"
  subtotal $15,024.85 + IVA $1,113.99 = $16,138.84
```

Emisores: START BANREGIO 14 grupos ($518,619.35), BBVA 3 ($252,969.88),
CATERPILLAR CRÉDITO 1 ($218,274.31).

**No requiere corrección contable.** Sí conviene saber que estos CFDI nunca van
a cuadrar contra el gasto y filtrarlos de las alertas.

### H2 · CFDI multi-concepto amarrado a un solo documento del folio
*Vinculación · 6 grupos · $1,469,137.23*

El CFDI del IMSS trae dos conceptos y el folio de gasto sí tiene los cuatro
documentos que corresponden, pero `Comprobante_Digital` sólo amarra el
comprobante al primero.

```
Folio 01-0034851 · CFDI IMSS total $2,145,416.46
  concepto "Cuotas IMSS"   $846,229.41
  concepto "Cuotas RCV"  $1,299,187.05
MPro · documento 0001 $846,229.41  ← el CFDI se ligó aquí, cuadra exacto
       documento 0002 $146,198.98  (Retiro)
       documento 0003 $515,949.88  (Cesantía y vejez)
       documento 0004 $365,497.41  (Aportación INFONAVIT)
```

**El importe registrado es correcto.** Lo que falta es el vínculo del XML con
los documentos 0002–0004. Es lo más accionable de esta sección.

### H3 · El `Total` no siempre es el importe — vales de despensa
*Estructural · 12 grupos · $1,310,702.25*

Ver [metodología §3](metodologia.md#vales-de-despensa) y
[D7](decisiones.md#d7--los-cfdi-cuyo-importe-vive-en-un-complemento-no-cuentan-como-descuadre).
En corto: 19 CFDI de TOKA con `Total = $0.01` mueven $792,344.95 a 1,445
trabajadores por el complemento `ValesDeDespensa`; los REP que los liquidan
pagan el saldo real ($518,357.30). MPro registra el `Total` del comprobante en
toda la cadena y **hace bien** — el gasto real está en nómina
(`Tg_Cve_Tipo_Gasto = '0020'`, $804,741.62 en enero).

> Este hallazgo se publicó primero como "12 cheques capturados en $0.01 — error
> de captura". Era un límite del parser, no un error del ERP. Corregido.

### H4 · Formas de la relación

| Forma | Grupos |
|---|---:|
| 1:1 | 1,818 |
| 1:N | 82 |
| N:1 | 21 |
| N:M | 17 |

El 93.8% es 1:1, pero el 6.2% restante concentra casi todo el descuadre
aparente. Sin el grano de grupo, el reporte 04 marcaba 651 gastos descuadrados
en vez de 72.

### H15 · Doce grupos con el CFDI repartido entre módulos
*Estructural — detectado en la corrida de febrero, aplicado a enero*

Pares `COMPRA` ↔ `GASTO_REGISTRO` donde el CFDI se reparte: la mercancía a la
compra y un cargo accesorio al gasto. Ninguno cuadra solo, la suma sí.

```
CFDI $93,472.10 = COMPRA:05-0029777 $85,352.11 + GASTO_REGISTRO:05-0175851 $8,120.00
CFDI $33,466.00 = COMPRA:07-0010696 $31,726.00 + GASTO_REGISTRO:07-0082493 $1,740.00
```

Ver [D14](decisiones.md#d14--un-cfdi-repartido-entre-módulos-complementarios-no-es-descuadre).
Estos 12 grupos estaban contados como descuadre material en la primera corrida.

---

## Reporte 03 — impuestos

| Concepto | CFDI | MPro | Diferencia | % |
|---|---:|---:|---:|---:|
| IVA trasladado *(federal + local)* | 8,006,513.88 | 7,861,176.72 | 145,337.16 | 1.82% |
| IVA retenido | 79,899.57 | 79,899.54 | **0.03** | 0.00% |
| ISR retenido | 14,747.71 | 14,747.68 | **0.03** | 0.00% |
| IEPS trasladado | 879.59 | 0.00 | 879.59 | 100% |
| **Neto** | **7,912,746.19** | **7,766,529.49** | **146,216.70** | 1.85% |

| Estatus | Grupos |
|---|---:|
| `CONCILIA` | 1,488 |
| `SIN_IMPUESTOS` | 36 |
| `DIF_CENTAVOS` | 17 |
| `DIF_MATERIAL` | 60 |
| `NO_COMPARABLE_MODULO` | 337 |

Sobre los 1,601 comparables: 95.2% concilia exacto, 96.25% con tolerancia.

### H5 · Las retenciones cuadran al centavo
*Limpio*

Tres centavos de diferencia en IVA retenido y tres en ISR retenido, sobre todo
el mes. Es el resultado más limpio de los tres reportes y vale registrarlo: el
lado de las retenciones no tiene ningún problema.

### H6 · El descuadre de IVA es la sombra del de importes
*Arrastre · 29 grupos · $141,241.29*

De los 60 grupos con diferencia material en impuestos, 29 arrastran los casos de
H1 y H2: si MPro registra sólo los intereses del arrendamiento, también registra
sólo el IVA de esos intereses. Esos 29 concentran $141,241.29 de los
$145,337.16 de diferencia. **No es un problema propio de los impuestos.**

```
Folio 01-0034761 · IVA del CFDI $8,319.70 · IVA del gasto $1,113.99
El IVA registrado es el 16% de $15,024.85 (los intereses), no del comprobante.
```

### H7 · Treinta y un grupos con el importe correcto y el impuesto mal
*Captura · $2,044.48 · **el hallazgo propio de esta sección***

Es lo que el reporte 02 no puede ver: el total cuadra exacto y la composición
fiscal no. Tres causas distintas:

| Causa | Grupos | Importe | Qué hacer |
|---|---:|---:|---|
| IEPS que MPro no sabe registrar | 23 | 879.59 | Dar de alta una clave con código SAT `003` |
| Impuesto local del CFDI no capturado | 7 | 322.10 | Capturarlo (MPro lo lleva dentro del IVA) |
| IVA no desglosado | 1 | 842.79 | Corregir el gasto |

El caso de IVA: `GASTO_REGISTRO:01-0035607`, importe $6,110.16 idéntico en ambos
lados, IVA del CFDI **$842.78** contra **$0.00** en MPro — se capturó el total
como subtotal, sin separar el impuesto.

### H8 · El IEPS no existe en la configuración de MPro
*Estructural · 23 CFDI · $879.59*

Ninguna clave del catálogo `Impuesto` tiene código SAT `003`. Los 23 CFDI son
compras menores en tiendas de conveniencia y autoservicio (OXXO 7, San Francisco
de Asís 5, Chedraui 4, Go Mart 3, otros 4). No es error documento por documento:
el concepto no está configurado.

### H9 · MPro suma el impuesto local dentro del IVA
*Corrección · 9 grupos*

De los $434.59 de impuesto local del mes, MPro capturó $112.49 en 2 gastos
—cuadrando al centavo— y no registró $322.10 en 7. La primera versión del
reporte marcaba los 2 buenos como "IVA mal capturado" porque sólo leía el IVA
federal. Ver [D8](decisiones.md#d8--los-impuestos-locales-se-suman-al-iva-del-lado-xml).

---

## Reporte 04 — cobertura desde MPro

12,037 documentos, $344,721,698.78.

| | Docs | % |
|---|---:|---:|
| Con CFDI | 2,616 | 21.7% |
| Sin CFDI, explicado | 8,429 | 70.0% |
| Sin CFDI, pendiente | 992 | 8.2% |

> El 21.7% **no** es un indicador de riesgo: cuenta consumo interno y nómina,
> que nunca llevan CFDI de proveedor. El indicador que importa es el IVA
> acreditable con CFDI: **99.77%**.

### Por qué 8,429 documentos no llevan comprobante y está bien

| Clase | Docs | Importe | Cómo se determina |
|---|---:|---:|---|
| Origen interno | 5,542 | 51,866,877.68 | Consumo interno, nómina, reclasificación: 0% de cobertura medida |
| CFDI en el documento origen | 1,718 | 44,043,621.56 | La cadena CxP → gasto/compra se resuelve y ese documento sí tiene UUID |
| Cancelado | 865 | 41,783,358.56 | `Es_Cve_Estado = 'CA'` |
| Importe negativo | 174 | −12,637,474.18 | Aplicaciones y reversas de anticipo |
| Traspaso interno | 95 | 56,912,919.04 | Cheque cuyo beneficiario es la propia Trivasa |
| Importe cero | 35 | 0.34 | Nada que respaldar |

### H10 · Los 992 pendientes no son un bloque homogéneo

| Bloque | Docs | Importe | Lectura |
|---|---:|---:|---|
| Cheques sin REP | 660 | 37,182,203.39 | Ver H11 |
| Gastos de provisión y depreciación | 144 | 17,681,072.58 | Ver H12 |
| Anticipos a proveedor | 63 | 8,047,062.61 | Pagados con cheque; sin CFDI de anticipo capturado |
| Cuentas por pagar | 108 | 3,689,062.81 | 93 vienen de gasto sin CFDI en el origen |
| Compra y compra indirecta | 14 | 104,628.57 | **Pendiente real** |
| Notas de crédito de proveedor | 3 | 474.17 | Depuración de facturas |

### H11 · De los $37.2 M en cheques sin REP, $24.4 M no podían tenerlo
*Estructural*

| Beneficiario | Cheques | Importe |
|---|---:|---:|
| Proveedores y otros | 482 | 12,781,703.29 |
| Crédito bancario | 63 | 7,974,069.11 |
| Nómina (remuneraciones por pagar) | 73 | 7,482,803.99 |
| Fisco | 16 | 6,093,535.00 |
| Seguridad social (IMSS, INFONAVIT) | 26 | 2,850,092.00 |

Nómina, fisco, seguridad social y amortización de crédito no generan complemento
de pago de proveedor. Quedan $12.78 M en 482 cheques donde el REP sí
correspondería.

**Precisión importante:** la falta del REP **no afecta la deducción del gasto**
—esa se soporta con la factura, que sí está en compra o gasto— pero sí es
requisito del complemento de pago en operaciones PPD.

### H12 · Los $17.7 M de gasto sin CFDI son provisiones
*Contable*

Los 144 documentos son costo estándar, depreciación y provisiones; el concepto
de cada uno lo dice. No hay operación con proveedor detrás.

| Concepto | Docs | Importe |
|---|---:|---:|
| Mantenimiento preventivo (costo estándar) | 3 | 3,862,996.54 |
| Mantenimientos mayores (costo estándar) | 3 | 2,409,059.92 |
| Depreciación de maquinaria y equipo | 1 | 1,406,447.11 |
| Moldes (costo estándar) | 2 | 1,286,706.01 |
| Bandejas de madera y tarimas | 2 | 1,230,750.37 |
| Renta maq-eq transporte | 3 | 1,082,914.86 |
| Retiro anticipado de dividendos | 16 | 731,013.30 |
| Cesantía y vejez | 6 | 718,928.57 |

**Lo que confirma que no son riesgo fiscal:** de todo ese bloque cuelgan
$13,951.51 de IVA acreditable — el 0.23% del IVA del mes.

### H13 · Diecisiete documentos sin CFDI — el único hueco limpio
*Captura · $105,102.74*

```
COMPRA            76-0000678 $17,112.83 · 76-0000677 $11,956.79
                  76-0000670 $11,534.44 · 76-0000673  $9,866.59
                  05-0029690  $3,748.32 · 05-0029650    $527.88
                  76-0000672 · 76-0000674 · 76-0000676 · 76-0000680  ($220.83 c/u)
COMPRA_INDIRECTO  76-0000499 $16,332.80 · 76-0000500 $16,332.80
                  76-0000497  $8,849.12 · 76-0000498  $7,483.68
NOTA_CREDITO_PROV 01-0001234    $445.71 · 01-0001244     $18.53 · 01-0001243 $9.93
```

Diez de las catorce compras son del mismo proveedor (`0000003356`) y sucursal.
Todas traen la factura declarada en la referencia pero sin XML ligado en el ERP.

---

## Acciones sugeridas

| Acción | Importe | Dónde | Prioridad |
|---|---:|---|---|
| Ligar el XML de 17 compras y NC de proveedor | 105,102.74 | R4 `SIN_XML_PENDIENTE` | Alta |
| Amarrar el CFDI del IMSS a los 4 documentos del folio | 1,469,137.23 | R2 `MPRO_REGISTRA_MENOS` | Alta |
| Registrar el IVA del gasto `01-0035607` | 842.79 | R3 `IVA_TRASLADADO_MPRO_MENOS` | Media |
| Capturar el impuesto local de 7 gastos | 322.10 | R3 `CFDI_CON_IMPUESTO_LOCAL` | Media |
| Dar de alta el IEPS en el catálogo de impuestos | 879.59 | R3 `IEPS_MPRO_MENOS` | Media |
| Decidir política de REP en cheques a proveedor | 12,781,703.29 | R4 `CHEQUE` pendiente | A definir |
| Filtrar los CFDI de arrendamiento de las alertas | — | R2 H1 | Baja |

---

## Advertencia

Todo se midió sobre **`.205`, que no es la base productiva**. Antes de convertir
cualquiera de estos números en un ajuste contable hay que repetir la corrida
contra `.207`. Los porcentajes de estructura deberían sostenerse; los importes
exactos hay que reconfirmarlos.
