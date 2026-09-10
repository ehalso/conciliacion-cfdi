# Hallazgos — febrero 2026

Corrida del 2026-09-04 contra `.205/TRIVASADB3`, periodo `[2026-02-01,
2026-03-01)`. **Segundo mes**: sirve para ver qué es estructural y qué era
particular de enero. Enero se volvió a correr con la misma versión del código,
así que las dos columnas son comparables. Reporte navegable:
`../hallazgos_conciliacion_2026-01-02.html`.

---

## Enero vs febrero

| Indicador | Enero | Febrero | Δ |
|---|---:|---:|---:|
| CFDI recibidos (vínculos) | 2,104 | 2,250 | +146 |
| Grupos de conciliación | 1,938 | 1,858 | −80 |
| Concilia exacto | 94.2% | 93.5% | −0.7 |
| Concilia ±$1 | 96.6% | 95.7% | −0.9 |
| Importe de los CFDI | 96,762,857.42 | 103,159,628.18 | +6.4 M |
| Importe registrado en MPro | 93,134,160.95 | 98,998,089.12 | +5.9 M |
| **Descuadre real** | **4,105,233.21** | **4,490,083.77** | +384 k |
| Descuadre % | 4.24% | 4.35% | +0.11 |
| Importe en complemento (vales) | 1,310,702.25 | 1,318,636.26 | +8 k |
| Grupos con CFDI repartido | 12 | 16 | +4 |
| CFDI intercompañía | 20 | 22 | +2 |
| IVA del CFDI | 8,006,513.88 | 7,541,656.60 | −465 k |
| IVA en MPro | 7,861,176.72 | 7,333,797.82 | −527 k |
| Impuestos concilian | 97.0% | 96.9% | −0.1 |
| **IVA acreditable con CFDI** | **99.77%** | **99.68%** | −0.09 |
| Hueco de captura limpio | 105,102.74 (17 docs) | 126,506.48 (15 docs) | +21 k |

**Febrero confirma enero.** Ningún indicador se mueve de forma que cambie la
conclusión: los importes e impuestos de MPro siguen soportados por los CFDI, el
descuadre se mantiene en el mismo rango y con las mismas causas, y el IVA
acreditable con respaldo documental sigue arriba del 99.6%.

---

## Lo que se repite igual

| Patrón | Enero | Febrero |
|---|---|---|
| **Arrendamiento financiero** (BANREGIO, BBVA, Caterpillar) | 18 grupos, ~$990 k | 15 grupos, $744,569.63 |
| **Vales de despensa** en complemento | 19 CFDI, $792,344.95, 1,445 trabajadores | 13 grupos, $1,318,636.26 |
| **Hueco limpio**: mismo proveedor `0000003356`, folios `76-xxxx`, facturas de explosivos | 17 docs, $105,102.74 | 15 docs, $126,506.48 |
| **Retenciones** | $0.06 de diferencia | $19.00 de diferencia |
| **Cero CFDI sin registro** en módulos de compra/gasto | 0 | 0 |

El hueco de captura es **el mismo caso recurrente**: proveedor `0000003356`,
sucursal 76, compras e indirectos de explosivos que se registran con la factura
declarada en la referencia pero sin XML ligado. Se repite semana a semana en los
dos meses. **Es un proceso, no un descuido puntual** — vale la pena atacar la
causa, no los documentos uno por uno.

---

## Lo que febrero trajo nuevo

Los tres hallazgos siguientes no aparecían en enero y llevaron a corregir el
código. Enero se recalculó con esas correcciones.

### H14 · Operaciones intercompañía — 8 CFDI que salían como "sin registro"
*Estructural · corrige una etiqueta engañosa*

`TRIVASADB3` alberga **varias razones sociales del grupo**:

| Empresa | RFC |
|---|---|
| `0001` TRIVASA S.A. DE C.V. | `TRI970922TL2` |
| `0002` FACILITADORES DE LA CONSTRUCCIÓN S.A. DE C.V. | `FCO190610893` |
| `0003` FLEXBEEL S.A. DE C.V. | `FLE1903199Y7` |
| `0004` TRITURADOS DE VALLADOLID S.A. DE C.V. | `TVA910627E25` |

Un CFDI emitido por una de ellas a Trivasa **es** un comprobante recibido — es
una operación intercompañía real — pero su registro vive en el módulo de
**venta** de la otra empresa, que estos reportes no leen. En febrero, 6
`COMPROBANTE_PAGO` y 2 `NOTA_CREDITO` de Triturados de Valladolid salían como
`SIN_REGISTRO`, que se lee como hueco y no lo es.

**Corregido:** nuevo estatus `MODULO_NO_CUBIERTO` y columna `INTERCOMPANIA`
poblada cruzando `Cd_RFC_Emisor` contra la tabla `Empresa`. Volumen:

| Mes | CFDI intercompañía | Módulos |
|---|---:|---|
| Enero | 83 | 68 CHEQUE de Facilitadores, 8 FACTURA + 4 COMPRA de Triturados, 3 CxP |
| Febrero | 22 | 6 COMPROBANTE_PAGO, 5 FACTURA, 4 COMPRA, 2 CHEQUE, 2 NOTA_CREDITO, 1 ANTICIPO |

### H15 · El CFDI repartido entre dos módulos complementarios
*Estructural · 16 grupos en febrero, 12 en enero*

[D3](decisiones.md#d3--nunca-unir-componentes-entre-módulos) concilia cada
módulo por separado para no duplicar el lado de MPro. Es correcto cuando un
módulo **se deriva** del otro (la CxP hereda el importe del gasto: cada uno vale
lo mismo que el CFDI). Pero hay pares **complementarios**, donde el CFDI se
reparte y cada módulo registra una parte: ninguno cuadra solo y la suma sí.

```
CFDI 90227AAD-5578-496D-8137-DEEF7367644C · INDUSTRIAL DE ALAMBRES · $161,190.75
  COMPRA:23-0007859            $160,070.26   (la mercancía)
  COMPRA_INDIRECTO:23-0000126    $1,120.49   (el cargo accesorio)
                              ─────────────
                               $161,190.75   ← suma exacta
```

El IVA se reparte igual: $22,078.66 + $154.55 = $22,233.21, el IVA del CFDI.

**Corregido:** nuevo estatus `REPARTIDO_ENTRE_MODULOS`, que sale del descuadre.
La regla es genérica —si la suma de los importes de MPro de todos los grupos de
un mismo UUID cuadra con el CFDI— y **se auto-protege del caso derivado**: si
dos módulos registran cada uno el importe completo, la suma da el doble y no se
marca.

Al aplicarlo a enero aparecieron 12 grupos más que estaban mal clasificados
(pares `COMPRA` ↔ `GASTO_REGISTRO`). El descuadre de enero bajó de $4,270,134.38
a **$4,105,233.21**.

### H16 · REP duplicado del proveedor
*Captura del emisor · $904,311.91*

El cheque `01-0085713` (TRITURADORA Y PROCESADORA DE MATERIALES SANTA ANITA,
$904,311.91) tiene **dos REP con el mismo monto, la misma fecha de pago y los
mismos siete documentos relacionados**, timbrados con 27 minutos de diferencia:

```
B788B699-011F-11F1-9C04-19F9072C35BC   2026-02-03 10:45:16   $904,311.91
EBFA7321-011B-11F1-A761-1F92C186DE56   2026-02-03 10:18:06   $904,311.91
  ambos con DR: TPF06-3530, 3606, 3641, 3642, 3671, 3801, 3833
```

El proveedor timbró el mismo pago dos veces. Uno de los dos debería cancelarse.
Es el mayor descuadre individual del mes.

---

## Reporte 02 — importes

| Estatus | Grupos |
|---|---:|
| `CONCILIA` | 1,738 |
| `DIF_MATERIAL` | 42 |
| `DIF_CENTAVOS` | 41 |
| `REPARTIDO_ENTRE_MODULOS` | 16 |
| `IMPORTE_EN_COMPLEMENTO` | 13 |
| `MODULO_NO_CUBIERTO` | 8 |

Formas: 1:1 1,684 · 1:N 116 · N:M 30 · N:1 20.

### Mayores descuadres

| Grupo | N XML | N doc | CFDI | MPro | Diferencia | Motivo |
|---|---:|---:|---:|---:|---:|---|
| `CHEQUE:01-0085713` | 2 | 1 | 1,808,623.82 | 904,311.91 | 904,311.91 | REP duplicado (H16) |
| `CHEQUE:01-0086348` | 3 | 2 | 4,499,756.00 | 3,824,792.61 | 674,963.39 | — |
| `CHEQUE:01-0046128` | 10 | 1 | 650,864.40 | 65,086.45 | 585,777.95 | Parcialidades (H17) |
| `CHEQUE:01-0060062` | 8 | 1 | 60,395.38 | 626,916.82 | −566,521.44 | Anticipo con notas de crédito |
| `GASTO_REGISTRO:05-0176980` | 1 | 1 | 397,161.00 | 131,430.58 | 265,730.42 | Secretaría de Administración |
| `GASTO_REGISTRO:01-0035173` | 1 | 2 | 370,808.62 | 150,260.62 | 220,548.00 | Caterpillar Crédito |

### H17 · El cierre de componentes sobrecuenta en pagos por parcialidades
*Límite conocido del método*

El cheque `01-0046128` (ECOPULSE, $65,086.45, fechado 2022-12-27) tiene **10 REP,
uno por mes**, de julio 2025 a junio 2026 — cada uno una parcialidad del mismo
importe. El cierre hacia atrás ([D2](decisiones.md#d2--las-componentes-se-cierran-hacia-atrás))
los junta todos: 10 × $65,086.44 = $650,864.40 contra un cheque de $65,086.45.

**No es un error de captura ni del ERP**: es el método sobrecontando cuando un
folio de cheque representa un pago recurrente en parcialidades. Queda
identificable por el motivo `ARRASTRA_CFDI_DE_OTRO_PERIODO` y por
`N_XML > N_XML_PERIODO`. Si el volumen crece, la mejora sería usar
`NumParcialidad` del `DoctoRelacionado` para quedarse sólo con la parcialidad
del periodo.

### Descuadre de gasto por emisor

| Emisor | Grupos | Diferencia |
|---|---:|---:|
| START BANREGIO | 14 | 524,021.63 |
| SECRETARÍA DE ADMINISTRACIÓN Y FINANZAS | 1 | 265,730.42 |
| CATERPILLAR CRÉDITO | 1 | 220,548.00 |
| COMISIÓN NACIONAL DEL AGUA | 4 | 11,895.00 |
| INSTITUTO MEXICANO DEL SEGURO SOCIAL | 1 | 7,244.74 |

Mismo perfil que enero: arrendamiento financiero y organismos públicos, donde el
CFDI cubre más de lo que el asiento debe registrar.

---

## Reporte 03 — impuestos

| Concepto | CFDI | MPro | Diferencia |
|---|---:|---:|---:|
| IVA trasladado *(federal + local)* | 7,541,656.60 | 7,333,797.82 | 207,858.78 |
| IVA retenido | — | — | **0.10** |
| ISR retenido | — | — | **18.90** |
| IEPS trasladado | 120.34 | 0.00 | 120.34 |

1,494 grupos comparables, **96.9% concilia** (enero: 97.0%).

### H18 · Las retenciones siguen cuadrando, con una excepción de $18.95

`CUENTA_X_PAGAR:23-0010049` (RIGER ROMAN CHALE VICINAIZ): el CFDI trae $18.95 de
ISR retenido y MPro registró $0.00. Es el único caso del mes y explica toda la
diferencia de ISR retenido. Comparado con enero ($0.03 en todo el mes), sigue
siendo un lado limpio.

### H19 · Impuestos mal capturados: 32 grupos, $11,119.68

Con el importe correcto y la composición fiscal no:

| Causa | Grupos | Importe | Enero |
|---|---:|---:|---:|
| IVA no desglosado | 7 | 10,123.54 | 1 · $842.79 |
| Impuesto local no capturado | 12 | 856.85 | 7 · $322.10 |
| IEPS que MPro no sabe registrar | 14 | 120.34 | 23 · $879.59 |

**El IVA no desglosado creció**: de 1 caso en enero a 7 en febrero, y de $843 a
$10,124. El mayor es `NOTA_CREDITO_PROVEEDOR:01-0000786` (Caterpillar Crédito),
donde MPro registró $55,496.00 de IVA contra $48,265.68 del CFDI —$7,230.32 de
más—. Los otros seis son gastos donde MPro registró IVA $0.00 sobre un total que
sí lo incluye (Abarrotera del Duero $2,769.83, Fomento Gasolinero $76.89,
Corporativo Gasolinero del Caribe $34.78, Servicios Ecológicos Mayapán $7.04).

Sigue siendo importe chico, pero **la tendencia merece vigilancia**: si en marzo
vuelve a crecer, es un problema de proceso de captura, no casos aislados.

---

## Reporte 04 — cobertura desde MPro

11,630 documentos, $488,202,171.22.

| Clase | Docs | Importe |
|---|---:|---:|
| `SIN_XML_ORIGEN_INTERNO` | 5,370 | 85,844,990 |
| `CON_XML_CONCILIA` | 2,350 | 83,889,330 |
| `SIN_XML_CFDI_EN_ORIGEN` | 1,680 | 40,531,230 |
| `SIN_XML_PENDIENTE` | 908 | 113,756,332 |
| `SIN_XML_CANCELADO` | 855 | 78,759,030 |
| `CON_XML_DIF_MATERIAL` | 160 | 5,638,143 |
| `SIN_XML_IMPORTE_NEGATIVO` | 127 | −23,945,700 |
| `SIN_XML_TRASPASO_INTERNO` | 97 | 101,089,300 |
| `CON_XML_DIF_CENTAVOS` | 55 | 2,639,533 |
| `SIN_XML_IMPORTE_CERO` | 28 | 0.27 |

### H20 · El pendiente casi se duplica en pesos con menos documentos

$66.70 M (992 docs) en enero → **$113.76 M (908 docs)** en febrero. No es un
deterioro: febrero fue un mes de movimiento financiero fuerte.

| Origen | Docs | Importe |
|---|---:|---:|
| CHEQUE | 624 | 76,600,830.40 |
| ANTICIPO_CXP | 51 | 23,098,204.00 |
| GASTO_REGISTRO | 121 | 10,667,906.18 |
| CUENTA_X_PAGAR | 97 | 3,262,884.92 |
| COMPRA + COMPRA_INDIRECTO | 15 | 126,506.48 |

Cheques pendientes por tipo de beneficiario:

| Tipo | Cheques | Importe |
|---|---:|---:|
| Banca / crédito | 79 | 35,946,599.70 |
| Proveedores y otros | 456 | 29,533,015.77 |
| Nómina | 66 | 7,037,968.44 |
| Fisco | 15 | 3,046,090.00 |
| Seguridad social | 8 | 1,037,156.49 |

Los cinco cheques más grandes explican $43.4 M de los $76.6 M:

```
01-0087068  19,650,000.00  SABADELL           "REBOTE"          ← devolución de cheque
01-0087110   9,523,553.66  BBVA               "PAGO CREDITO"
01-0087468   5,262,370.84  VE POR MAS         "PAGO CREDITO VX+"
01-0087434   4,976,438.49  VE POR MAS         "CANCELACION CREDITO BX+"
01-0087300   4,004,073.92  VE POR MAS         "PAGO CREDITO VX+"
```

Ninguno lleva CFDI de proveedor: un rebote es un reverso bancario y las
amortizaciones de crédito no generan comprobante deducible. El traspaso interno
también creció ($56.9 M → $101.1 M), consistente con el mismo movimiento
financiero.

### H21 · Los gastos sin CFDI bajaron y siguen siendo provisiones

$17.68 M (144 docs) en enero → $10.67 M (121 docs) en febrero. Mismo perfil:
costo estándar, depreciación y provisiones. El IVA acreditable colgado de todo
ese bloque es $17,489.97 — el 0.32% del IVA del mes.

---

## Veredicto de febrero

**Igual que enero: los registros de MPro sí están bien contemplados.**

- 99.68% del IVA acreditable con CFDI ligado ($5,409,962 de $5,427,452).
- Descuadre real de 4.35% del importe, con las mismas causas de siempre:
  arrendamiento financiero, organismos públicos y un REP duplicado del proveedor.
- Las retenciones cuadran salvo $18.95 en un documento.
- El único hueco de captura limpio son $126,506.48 en 15 documentos, y es **el
  mismo caso recurrente de enero** — mismo proveedor, misma sucursal.

### Lo que cambia respecto a enero

1. **Atacar el proceso del proveedor `0000003356` / sucursal 76.** Dos meses
   seguidos con el mismo hueco semanal ($105 k + $127 k) no es un descuido.
2. **Vigilar el IVA no desglosado**: de 1 caso a 7, de $843 a $10,124.
3. **Cancelar uno de los dos REP** del cheque `01-0085713`.
4. **Corregir el ISR retenido** de `CUENTA_X_PAGAR:23-0010049` ($18.95).

### Advertencia

Todo se midió sobre **`.205`, que no es la base productiva**. Antes de convertir
cualquiera de estos números en un ajuste contable hay que repetir la corrida
contra `.207`.
