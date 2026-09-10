# Investigación folio por folio de los pendientes (sesión 2026-09-09/10)

> Sesión nocturna pedida por Esteban: revisar **todos** los pendientes de
> conciliación, origen por origen, documentar cada hallazgo y — cada vez que
> aparece un patrón — correrlo contra el resto del universo para ver cuántos
> otros CFDI arregla. Sin push a GitHub.
>
> Punto de partida: **1,351 / 1,500 (90.1%)** conciliados en febrero 2026.

## Resultado

| Periodo | Universo | Conciliados | % | Pendientes |
|---|---:|---:|---:|---:|
| 2026-01 | 1,585 | 1,572 | 99.2% | 13 |
| **2026-02** | **1,500** | **1,492** | **99.5%** | **8** |
| 2026-03 | 1,736 | 1,722 | 99.2% | 14 |
| 2026-04 | 1,775 | 1,771 | **99.8%** | 4 |
| 2026-05 | 1,545 | 1,532 | 99.2% | 13 |
| 2026-06 | 1,431 | 1,422 | 99.4% | 9 |
| **H1 2026** | **9,572** | **9,511** | **99.36%** | **61** |

Febrero, que es el mes con el que se venía trabajando, pasó de **90.1% a
99.5%**. En dinero, lo que queda sin cuadrar en febrero son **$27,651.98 de
$48,941,616.38 — el 0.056%**.

### Cómo se llegó ahí (febrero, paso a paso)

| # | Fix | Conciliados | % |
|---|---|---:|---:|
| 0 | Punto de partida | 1,351 | 90.1% |
| 1 | Tipo de cambio + filtro estructural de cuentas de orden | 1,393 | 92.9% |
| 2 | `Descuento` del CFDI | 1,426 | 95.1% |
| 3 | IEPS a la base del gasto | 1,438 | 95.9% |
| 4 | Nota de crédito contra total, IVA no acreditable, importe del documento, tolerancia por materialidad | 1,463 | 97.5% |
| 5 | Arrendamiento financiero + gasto repartido entre folios | 1,478 | 98.5% |
| 6 | Doble conteo por los dos formatos de `Cd_Documento` | 1,485 | 99.0% |
| 7 | Folio completo, renglón del folio, cheque agrupado, importe del documento de origen | 1,492 | **99.5%** |

### Por qué cuadra cada CFDI (semestre completo)

| Vía de cuadre | CFDI |
|---|---:|
| cargo = base CFDI (el chequeo de siempre) | 9,160 |
| arrendamiento financiero (interés + capital) | 106 |
| capturado en un renglón del folio | 76 |
| nota de crédito = total | 62 |
| pago directo (Cheque = total) | 37 |
| IVA no acreditable (cargo = total) | 31 |
| capturado en el documento (gasto distribuido menor) | 19 |
| capturado en el documento de origen | 8 |
| gasto repartido entre folios hermanos | 6 |
| el CFDI cubre el folio completo | 4 |
| cheque que liquida varias facturas | 2 |

---

# Parte 1 — Hallazgos que corrigen el método

## A. El CFDI está en su moneda original; la póliza, en MXN

**Resolvió ~28 pendientes de febrero.**

`raw_sat.cfdi_recibidos.subtotal`/`.total` vienen en la **moneda original del
CFDI** (mismo criterio que `Comprobante_Digital.Cd_Monto`, gotcha ya
documentado en `trivasa-context`), pero `Poliza_Detalle` y
`Gasto_Registro_Control` postean **siempre en MXN**. La diferencia entre
cargo y subtotal era exactamente el tipo de cambio: 43 de los 149 pendientes
eran CFDI en USD, todos con ratio cargo/subtotal entre 15 y 20.

Cada tabla de origen trae su propio par `Mn_Cve_Moneda` / `Xx_Tipo_Cambio`, y
**ése** es el factor a usar — no un tipo de cambio de mercado ni el
`Cd_Tipo_Cambio` de `Comprobante_Digital`, que en varios casos difiere del que
se usó para postear (CADECO: 17.2698 real vs 17.6900 en `Comprobante_Digital`).

| Origen | Tabla | Folio | Tipo de cambio | ¿Moneda? |
|---|---|---|---|---|
| COMPRA | `Compra_Encabezado` | `Co_Folio` | `Co_Tipo_Cambio` | sí |
| COMPRA_INDIRECTO | `Compra_Indirecto` | `Ci_Folio` | `Ci_Tipo_Cambio` | sí |
| CUENTA_X_PAGAR | `Cuenta_X_Pagar` | `Cxp_Folio` | `Cxp_Tipo_Cambio` | sí |
| NOTA_CREDITO_PROVEEDOR | `Nota_Credito_Proveedor` | `Nc_Folio` | `Nc_Tipo_Cambio` | sí |
| CHEQUE | `Cheque` | `Ch_Folio` | `Ch_Tipo_Cambio` | **no** |
| FACTURA | `Factura_Encabezado` | `Fc_Folio` | `Fc_Tipo_Cambio` | sí |
| GASTO_REGISTRO | `Gasto_Registro_Documento` | `(Gr_Folio, Grd_ID)` | `Grd_Tipo_Cambio` | sí |

⚠️ `Cheque` **no tiene** `Mn_Cve_Moneda`. Pedirla no da error de SQL: devuelve
`HTTP 502` genérico, el mismo gotcha de "columna inexistente parece caída del
bridge".

Implementado en `src/extract_moneda.py` y en el paso `[3d/5]` del baseline.

### ⚠️ Corrección: BRIGGS EQUIPMENT **no** era captura duplicada

`hallazgos.md` punto 16 (escrito ayer) afirma que los 5 CFDI de BRIGGS
EQUIPMENT con `Grc_Importe = $45,060.3725` idéntico eran un error de captura
por lote. **Es falso.** Los 5 CFDI son de **USD 2,615.00 cada uno** (la misma
renta mensual de montacargas) con el mismo tipo de cambio 17.2315:
2,615.00 × 17.2315 = 45,060.3725 en los cinco. El importe se repite porque el
importe en dólares y el tipo de cambio se repiten. Los 8 CFDI de BRIGGS (5 de
$2,615 y 3 de $1,500) ya cuadran exacto. **Hay que corregir el punto 16 de
`hallazgos.md` y su entrada gemela en `trivasa-context`.**

## B. Cuentas de orden: el filtro por texto deja pasar variantes

**Resolvió 14 pendientes** (13 de CUENTA_X_PAGAR con ratio exactamente 2.0).

El filtro era `Pc_Descripcion NOT LIKE '%CUENTAS DE ORDEN%'`. El catálogo usa
cinco redacciones y tres se le escapan:

| Config | Tabla | Descripción |
|---|---|---|
| `0130` | Cuenta_x_Pagar | `X CUENTA X PAGAR LIBRE (CTS ORDEN) ENE2018-MAY2020` |
| `0360` | Cuenta_x_Pagar | `CUENTA X PAGAR LIBRE ( CUENTA DE ORDEN) 2020` |
| `0293` | Gasto_Registro | `CONSUMO INTERNO MTTO CORRECTIVO 2018 (CUENT ORDEN)` |
| `0296` | Gasto_Registro | `CONSUMO INTERNO ADIC Y MEJO 2018 EN AD(CTS ORDEN)` |
| `0235`/`0352` | Nota_Credito_Proveedor | `NOTAS DE CREDITO PROVEED (CUENTA ORDEN) 2020 EN AD` |

**Solución estructural, independiente de la redacción**: en `Cuenta_Contable`,
las cuentas de orden son exactamente las de **raíz de 5 dígitos** — `10100` a
`10600`, grupo `E.*` (`Cc_Acumula`: `E.A` Valores Ajenos, `E.B` Valores
Contingentes, `E.C` De Control). Las cuentas reales tienen raíz de 4 dígitos.

```sql
AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '10[1-6]00%'
```

Caso testigo: CFDI `C596D0FA…` (BANCO SABADELL, subtotal $300,000) — folios
`01-0094874`/`01-0094875`, cada uno con dos pólizas activas en paralelo:
config `0380` (real, cuenta `1150.003.001`) y config `0360` (cuentas de orden,
cuenta `10500.011.001`), con el mismo importe → sumaba $600,000.

## C. `Descuento` del CFDI: `raw_sat` solo guarda el subtotal bruto

**Resolvió 33 pendientes.**

`raw_sat.cfdi_recibidos` **no tiene columna de descuento**; su `subtotal` es el
bruto, antes del `Descuento` a nivel Comprobante. mpro captura y postea el
importe **neto**. Confirmado contra el XML crudo:

```
AT&T COMUNICACIONES   SubTotal 12,472.32 - Descuento 12,120.64 =    351.68 = cargo mpro
AGENCIA COMERCIALIZ.  SubTotal 118,205.26 - Descuento 70,215.11 = 47,990.15 = cargo mpro
G3M                   SubTotal  4,449.96 - Descuento  1,557.49 =  2,892.47 = cargo mpro
AUTO PARTES Y MAS     SubTotal 12,901.65 - Descuento  1,290.17 = 11,611.48 = cargo mpro
```

El parseo del XML pasó de hacerse solo para GASTO_REGISTRO a hacerse para todo
el universo (~5,500 XML por mes). Se cachea en
`output/xml_ajustes_<periodo>.csv` (no versionado).

## D. El IEPS trasladado se suma a la BASE del gasto, no al impuesto

**Resolvió 12 pendientes.** Mismo mecanismo que el complemento
`implocal:ImpuestosLocales` (punto 18 de `hallazgos.md`), pero con un impuesto
federal: **IEPS**, clave `003` (combustibles, refrescos, botanas,
telecomunicaciones). No es acreditable, así que se va al gasto:

```
CADENA COMERCIAL OXXO    100.11 + IEPS 3.63 = 103.74  = Grc_Importe capturado
SUPER SAN FRANCISCO      143.73 + IEPS 4.37 = 148.10  = Grc_Importe capturado
GO MART YUC              109.26 + IEPS 8.74 = 118.00  = Grc_Importe capturado
TELEFONOS DE MEXICO   (528.55 - 65.00 desc) + IEPS 9.73 = 473.28 = Grc_Importe capturado
```

⚠️ `raw_sat.cfdi_recibidos.iva` **no sirve** para detectarlo: trae
`TotalImpuestosTrasladados`, que mezcla IVA e IEPS, y en varios casos ni
siquiera coincide con la suma (OXXO: `iva`=8.76 pero
`TotalImpuestosTrasladados`=12.39). Hay que leer los `cfdi:Traslado` con
`Impuesto="003"` del nodo `Impuestos` de nivel Comprobante.

Regla final de la base comparable:

```
base = (SubTotal - Descuento + IEPS + impuestos_locales) × tipo_de_cambio_del_documento
```

## E. Doble conteo por los dos formatos de `Cd_Documento` — bug nuestro

**Resolvió 7 pendientes que parecían un error del cliente.**

Siete CFDI de febrero mostraban exactamente **2× su importe** y los había
clasificado como "capturados dos veces en mpro". No lo estaban: el mismo
`(Gr_Folio, Grd_ID)` aparece **dos veces en `Comprobante_Digital`**, una fila
en formato de 14 caracteres y otra en el de 18, con el mismo UUID y el mismo
monto — el gotcha que `layout-gastos` ya tenía documentado en
`trivasa-context`. El dedup de `baseline_universal.py` usaba el `documento`
completo, que no colapsa los dos formatos:

```
05-01784220001      (14)  05E5388C-…  9,373.96
05-017842200010001  (18)  05E5388C-…  9,373.96   <- la misma captura
```

Corregido deduplicando por `documento[:14]` (folio + Grd_ID), que es la llave
granular real. **Lección**: antes de reportar un "error de captura del
cliente", verificar que no sea doble conteo propio — es la segunda vez en dos
días que un patrón "2×" o "importe repetido" resulta ser nuestro.

---

# Parte 2 — Vías de cuadre nuevas (tratamientos contables legítimos)

Todas se aplican **solo si falla el cuadre normal**, y cada una deja su
etiqueta en la columna `Vía de cuadre` del reporte para que sea auditable.

| Vía | Qué reconoce | Evidencia que exige |
|---|---|---|
| **Nota de crédito = total** | Una nota de crédito reduce el adeudo **con IVA incluido**; nunca cuadra contra el subtotal | Cargo a proveedores (config `0451`, DEVOLUCION) o abono a inventario+IVA (config `0350`, BONIFICACION) = total del CFDI |
| **IVA no acreditable** | Gastos menores (gasolina, abarrotes) donde mpro manda el IVA al gasto | Importe contabilizado = total del CFDI, y total ≠ base |
| **Capturado en el documento** | El documento capturó el CFDI exacto pero el gasto distribuido es menor porque mpro aplicó un descuento propio (cuotas IMSS: la parte obrera no es gasto de la empresa) | `Grd_Precio_Neto_Importe` = base del CFDI |
| **Arrendamiento financiero** | El CFDI se parte entre gasto por intereses y amortización de capital | Póliza activa con cargo a pasivo `2130/2230` referenciando `Grd_Referencia`, cuyo abono a bancos = total del CFDI (o la suma de varias pólizas, si el CFDI ampara varias unidades) |
| **Gasto repartido entre folios hermanos** | Una factura se captura como varios folios, uno por sucursal, y solo uno queda etiquetado | Folios con misma `Grd_Referencia` y fecha, más de uno, cuya suma = base; y el folio etiquetado captura **de menos** |
| **El CFDI cubre el folio completo** | El CFDI ampara todos los renglones del folio pero solo uno quedó etiquetado | Suma de todo el folio = base, y el folio no tiene otro CFDI etiquetado |
| **Capturado en un renglón del folio** | El folio mezcla conceptos y uno de sus renglones es exactamente este CFDI | Un renglón con `neto` o `descontado` = base o total |
| **Cheque que liquida varias facturas** | Un cheque paga varias facturas a la vez | Importe del cheque = suma de los CFDI que tiene etiquetados (excluyendo el REP que ampara el cheque completo) |
| **Capturado en el documento de origen** | No se pudo aislar el cargo en la póliza, pero el documento sí trae el importe | `Xx_Precio_Neto_Importe` del documento = base o total |

### El detalle del arrendamiento financiero (el caso más instructivo)

CFDI `070FE9DB…` (START BANREGIO, total $69,185.79). Gasto_Registro solo
captura el interés ($14,540.09). La póliza de pago junta las dos piezas:

```
póliza 0000478988, config 0246 "AF - START BANREGIO"
  Cargo 2130.001.004.003.019   52,785.58  ref M17916      <- capital
  Cargo 2130.001.004.003.019   16,400.21  ref FNN704472   <- interés (= Grd_Referencia)
  Cargo 1170.001.001 (IVA)      9,140.88
  Abono 1110.003.001.010.001   69,185.79                  <- total del CFDI
  Abono 1170.002.001            9,140.88
```

La cadena de liga es `Comprobante_Digital` → `Gasto_Registro_Documento.Grd_Referencia`
→ `Poliza_Detalle.Pd_Referencia`. Cuando el CFDI ampara varias unidades
arrendadas hay **una póliza de pago por unidad** y hay que sumarlas
(CATERPILLAR: $211,890.64 + $158,917.98 = $370,808.62 = total del CFDI).

### Un criterio que se probó y se **descartó** por permisivo

`Pago_Cxp_Comprobante.Pcc_Timbre_UUID` liga pagos directamente con el UUID del
CFDI, y `Pcc_Monto` trae el total del comprobante. Tentador: cubre **1,407 de
1,500 CFDI (93.8%)** del universo de febrero. Precisamente por eso no sirve
como criterio de cuadre: aceptarlo habría "conciliado" de un plumazo casi
todo, incluidos los CFDI mal capturados (un CFDI contabilizado dos veces
también tiene su pago correcto). Se dejó como herramienta de investigación, no
como vía de cuadre.

### Tolerancia por materialidad

Se pasó de `$1` fijo a `max($1, 0.005% de la base)`. El componente relativo
cubre el redondeo de convertir moneda extranjera renglón por renglón (un CFDI
de $70,000 puede diferir $1.02 solo por eso) sin volverse permisivo: en el
CFDI más grande del periodo son ~$45.

---

# Parte 3 — Lo que queda sin cuadrar (61 CFDI del semestre)

Ninguno es un misterio: los 61 caen en familias con mecanismo identificado.
El barrido numérico final (13 combinaciones de subtotal/IVA/total contra el
cargo) no encontró ninguna relación adicional que explote — el residual es
estructural, no de fórmula.

| Familia | CFDI | Monto | Qué pasa |
|---|---:|---:|---|
| **Nómina: IMSS** | 16 | $7,879,140 | El CFDI mezcla cuota **patronal** (gasto de la empresa) y cuota **obrera** (retención al trabajador, que ya se registró en la nómina). mpro solo lleva al gasto la parte patronal. Además la póliza de provisión (`config 0428`, "PROVISION GASTOS NAC (PREV SOCIAL)") **consolida varios CFDI** — en enero, 382 renglones y 5 referencias distintas para $2.06M. El ratio cargo/subtotal varía entre 0.14 y 0.48 según la composición de la nómina (y entre 0.50 y 0.94 en una muestra de 6 CFDI de febrero revisada 2026-09-10), así que no hay proporción fija que aplicar. **Confirmado con Esteban 2026-09-10: NO son un patrón estructural a modelar — son errores de captura reales. No se filtran del universo ni se les construye una vía de cuadre dedicada: se les aplica la misma Regla 1 (cargo=subtotal) que a cualquier otro CFDI, y quedan como no conciliados si no cuadra por ahí — eso es correcto, no un hueco del método.** |
| **Nómina: INFONAVIT** | 4 | $2,456,263 | Mismo mecanismo y misma póliza consolidada — misma instrucción: no filtrar, no regla especial. |
| **Crédito bancario** | 11 | $1,603,643 | CFDI de intereses de créditos simples (BBVA, Sabadell, Mifel, Ve por Más). La póliza de pago carga capital + interés a `2130.001.001.*` y abona el banco por la suma — pero, a diferencia del arrendamiento, el **capital no viene en el CFDI**, así que el abono al banco (ej. $815,171.67) no es comparable con el CFDI ($395,858.61). Además el interés posteado ($190,171.67) no coincide con el del CFDI: hay que revisar el contrato/tabla de amortización. |
| **Cheque consolidado** | 15 | $58,331 | CFDI etiquetados a un cheque que liquida facturas de **otros periodos** (uno de ellos, `01-0060062`, con fecha 2024-01-15 y $626,916.82 contra CFDI de 2026 que suman $60,395). No se puede cerrar con datos del periodo; conviene revisar si la etiqueta apunta al cheque correcto. |
| **Agencia aduanal** | 6 | $50,410 | El cargo es **mayor** que el CFDI (ratio 1.05 a 2.14): el folio de gasto agrupa el pedimento completo (impuestos, maniobras, honorarios) y el CFDI del agente es solo una parte. |
| **Otros** | 3 | $44,941 | Casos sueltos: una COMPRA con -$79.20, un CFDI de MAQUINAS DIESEL cuyo folio de compra agrupa 17× su importe, y un arrendamiento de BANORTE con +$86.82. |
| **SAT** | 2 | $43,499 | `Grc_Importe` = $0.01 simbólico: el pago de impuestos no se registra como gasto en Gasto_Registro. |
| **CONAGUA (derechos)** | 4 | $12,187 | **Captura parcial real**: de un CFDI de $5,944.00, Gasto_Registro solo recoge la actualización ($22) y los recargos ($121). Los derechos de agua ($5,801) no están en el módulo — se pagan como contribución sin ligar el CFDI. Confirmado también del lado del pago: las dos aplicaciones en `Pago_CXP` son por $22.00 y $121.00. **Esto sí conviene reportarlo a Trivasa.** |

## Lo único que parece error real de captura

- **CONAGUA (4 CFDI)**: el grueso del comprobante no se registra en el módulo
  de gastos. Vale la pena preguntar si es intencional (los derechos se
  contabilizan como contribución en otro lado) o si falta capturarlos.
- **Cheque `01-0060062`** (FABRICA DE IMPLEMENTOS, 3 CFDI de feb-2026
  etiquetados a un cheque de enero **2024** por $626,916.82): la etiqueta
  parece apuntar a un folio de cheque equivocado.

Todo lo demás es tratamiento contable legítimo o un límite del alcance actual
del pipeline, no un error.

---

# Parte 4 — Pendientes de esta investigación

## Documentación publicada (2026-09-10)

Ya está subido, tanto aquí como en el repo de contexto compartido:

1. **`hallazgos.md` punto 16 corregido** (BRIGGS EQUIPMENT): no era captura
   duplicada, era conversión USD→MXN (hallazgo A).
2. **Hallazgo nuevo, punto 26** — al verificar esa retractación apareció algo
   que no sabíamos: el "patrón simétrico del lado del abono" tampoco era
   duplicación. mpro **parte el pasivo en moneda extranjera en dos cuentas** —
   la de la divisa (`2110.001.001.002`, "Proveedor Nacional Dollar", que guarda
   el importe tal cual en USD) y una **complementaria** (`…004`, que guarda la
   diferencia en pesos) — y las dos **suman** la valuación en MXN al tipo de
   cambio del documento. Hay 9 cuentas con ese rol en el catálogo (proveedores
   nacionales y extranjeros, bancos Monex USD/EUR, arrendamiento). Importa
   cuando se extienda el chequeo al lado del abono: sumar solo una de las dos
   cuentas da un número equivocado.
3. **`trivasa-context` actualizado** (`docs/schema/calidad-de-datos.md`): la
   entrada gemela de BRIGGS quedó reescrita como retractación —conservando el
   modo de falla, que es lo que enseña— y se agregaron los hallazgos A (tipo de
   cambio por origen, con la tabla de columnas y el gotcha de `Cheque` sin
   `Mn_Cve_Moneda`), B (cuentas de orden por raíz de 5 dígitos), C (el
   `Descuento` que `raw_sat` no tiene), D (IEPS a la base) y E (deduplicar por
   `LEFT(Cd_Documento, 14)` al sumar importes).

## Trabajo técnico que quedó identificado

- **Familia nómina (IMSS/INFONAVIT, 20 CFDI, $10.3M)**: **corrección
  2026-09-10 (confirmado con Esteban) — no conciliar en agregado, no
  modelar la separación patronal/obrera, y no filtrarlos del universo.** La
  idea original de esta sección (modelar la provisión de nómina, o
  conciliar en agregado como alternativa barata) queda descartada por
  completo: son errores de captura reales. Se les aplica la misma Regla 1
  (cargo=subtotal) que a cualquier otro CFDI, sin ninguna vía de cuadre
  dedicada — que queden como no conciliados es el comportamiento correcto
  del método, no algo que haya que suavizar.
- **Créditos bancarios (11 CFDI, $1.6M)**: requiere la tabla de amortización
  del contrato para separar interés devengado de interés facturado.
- El chequeo sigue siendo de **un solo lado** (cargo). Extender el doble
  chequeo cargo+abono a todos los orígenes sigue pendiente.

## Archivos nuevos o modificados en esta sesión

```
src/extract_moneda.py         NUEVO  moneda y tipo de cambio por origen
src/extract_vias_extra.py     NUEVO  arrendamiento, folios hermanos, folio completo,
                                     cheque agrupado, importe del documento de origen
src/cfdi_parser.py            base_mpro ahora resta Descuento y suma IEPS
src/extract_gasto_registro.py devuelve también neto, descontado, folio y referencia
src/extract_poliza_por_origen.py  filtro estructural de cuentas de orden
baseline_universal.py         cascada de 11 reglas de cuadre + conversión a MXN +
                                     parseo de XML de todo el universo (con caché)
investigacion/dump_contexto.py NUEVO  vuelca el contexto de los pendientes a CSV
investigacion/triage.py        NUEVO  batería de relaciones numéricas candidatas
```
