# Decisiones

Log de las decisiones de alcance y método que **cambian los números**. Cada una
con su fecha, su porqué y la evidencia que la respalda. Si alguien revierte una
de estas, los resultados dejan de ser comparables con los publicados.

---

## D1 · El grano es la componente conexa, no el CFDI ni el registro
**2026-09-04**

**Decisión:** conciliar sobre la componente conexa del grafo bipartito
CFDI ↔ documento, calculada por módulo.

**Por qué:** la relación no es 1:1. Un CFDI de gasto se reparte hasta en 108
documentos; un cheque acumula hasta 33 REP. Comparar fila por fila produce
descuadres que no existen.

**Evidencia:** en enero, a grano documento el reporte 04 marcaba **651** gastos
con diferencia material; con el grano de grupo son **72**. Los otros 579 eran
artefactos del grano.

**Alternativa descartada:** grano (UUID, origen), que resuelve el caso 1:N pero
no el N:1 — los 33 REP de un mismo cheque seguirían descuadrando cada uno.

---

## D2 · Las componentes se cierran hacia atrás
**2026-09-04**

**Decisión:** expandir el universo iterativamente (folio → sus CFDI → sus
documentos) hasta que no entre nada nuevo, aunque eso traiga comprobantes de
otros periodos.

**Por qué:** un folio de cheque de anticipo acumula CFDI durante años. Armar el
grupo sólo con los del mes lo deja truncado y descuadra por construcción.

**Evidencia:** cheque `01-0060062` — un anticipo con 8 CFDI colgando, de enero
2024 a febrero 2026. En enero 2026 el cierre agregó 26 comprobantes, todos en
`CHEQUE`, y convergió en una pasada.

**Costo:** los grupos afectados salen del mes calendario. Se marcan con
`N_XML_PERIODO < N_XML` y el motivo `ARRASTRA_CFDI_DE_OTRO_PERIODO` para que sea
visible.

---

## D3 · Nunca unir componentes entre módulos
**2026-09-04**

**Decisión:** la componente se calcula **por `Cd_Tabla`**. Un UUID que aparece en
dos módulos genera dos grupos independientes.

**Por qué:** la `Cuenta_X_Pagar` se genera desde el gasto. Unirlos sumaría dos
veces el mismo importe del lado de MPro.

**Evidencia:** 41 UUID de enero aparecen en dos módulos — 30 en
`CUENTA_X_PAGAR`+`GASTO_REGISTRO`, 6 en `COMPRA`+`GASTO_REGISTRO`, 4 en
`COMPRA`+`FACTURA`, 1 en `ANTICIPO_CXP`+`CHEQUE`.

---

## D4 · `TRASLADO` fuera del universo
**2026-09-04**

**Decisión:** excluir `Cd_Tabla = 'TRASLADO'` de la conciliación y contarlo
aparte.

**Por qué:** es 100% autoemitido (emisor = receptor = Trivasa), `Cd_Monto = 0`,
moneda `XXX`. Carta porte por mover material propio. No hay importe que
conciliar; incluirlo agregaría 3,686 filas de ruido con 100% de "N/A".

**Cómo queda visible:** el reporte 02 imprime el conteo y el importe de los
autoemitidos en la cabecera de la corrida, para que la exclusión no se lea como
omisión.

---

## D5 · `FACTURA` fuera del universo del reporte 04
**2026-09-04**

**Decisión:** `Factura_Encabezado` no entra a la base del reporte 04, pero los
CFDI recibidos que cuelgan de una factura sí aparecen en el 02 y el 03.

**Por qué:** es el módulo de venta y su CFDI es **emitido** — fuera del encargo,
que pidió lo recibido. Incluirlo mandaría 2,259 facturas de enero a "sin XML
recibido", lo cual es cierto y también inútil.

**Lo que sí se reporta:** los 8 casos de factura de venta con un CFDI recibido
colgando, como anomalía a revisar.

---

## D6 · El importe comparable de un REP es `MontoTotalPagos`
**2026-09-04**

**Decisión:** para CFDI tipo `P`, el importe comparable sale del complemento de
pagos, no del `Total` del comprobante.

**Por qué:** por diseño del SAT, el `Total` de un REP vale 0. Usarlo daría 100%
de descuadre falso en los 416 REP del mes.

---

## D7 · Los CFDI cuyo importe vive en un complemento no cuentan como descuadre
**2026-09-04, tarde — corrige un hallazgo publicado**

**Decisión:** nuevo estatus `IMPORTE_EN_COMPLEMENTO`, excluido del descuadre.
El monto va en su columna propia `XML_COMPLEMENTO_IMPORTE`.

**Por qué:** el `Total` del comprobante no siempre es el importe de la
operación. Los CFDI de vales de despensa se timbran por la **comisión**
(`Total = $0.01`) y la dispersión real viaja en
`valesdedespensa:ValesDeDespensa/@total`.

**Evidencia:** CFDI `C02E0287-545A-4409-8688-208431A63D79`, `Total` $0.01,
complemento `@total = 166,758.94`, 303 trabajadores con CURP y NSS. MPro
registra $0.01 en toda la cadena (gasto → CxP → cheque) y **hace bien**: el
gasto real se lleva por nómina, `Gasto_Registro_Nomina_Gasto` con
`Tg_Cve_Tipo_Gasto = '0020'`, $804,741.62 en enero, y 17 de los 19 CFDI empatan
al centavo con uno de esos folios.

**Qué corrigió:** la primera versión del reporte marcaba esos 12 grupos como
"cheques capturados con importe de un centavo — error de captura". No lo eran.
El descuadre bajó de $4,788,491.56 a **$4,270,134.38** (95.05% → **95.59%** de
importe conciliado).

**Cómo se detecta, sin codificar al proveedor:** (a) el comprobante trae el
complemento; o (b) es un REP cuyos `DoctoRelacionado` liquidan más de lo que
suman los `Cd_Monto` de esos comprobantes.

**Origen de la corrección:** una pregunta del usuario — *"¿no hay relación entre
TOKA y nómina? ¿lo que falta de registro en TOKA es lo que sobra en XMLs?"*.
Las dos mitades resultaron ciertas.

---

## D8 · Los impuestos locales se suman al IVA del lado XML
**2026-09-04, tarde — corrige dos falsos positivos**

**Decisión:** el lado XML del par de IVA es
`XML_IVA_TRASLADADO + XML_IMP_LOCAL_TRAS`.

**Por qué:** MPro no lleva el concepto por separado — lo suma dentro de su clave
de IVA.

**Evidencia:** gasto `05-0175447`, IVA federal del CFDI $208.86 + ISH $58.75 =
$267.61, **exactamente** lo que MPro registró bajo "IVA ACREDITABLE 16%". Mismo
patrón en `05-0176981`: $191.08 + $53.74 = $244.82.

**Qué corrigió:** dos de los tres casos reportados como "IVA mal capturado" no
lo eran. Queda uno real (`01-0035607`, $842.78) más $322.10 de impuesto local
que MPro efectivamente no registró en 7 gastos.

---

## D9 · El join del reporte 04 no se acota por fecha de timbrado
**2026-09-04**

**Decisión:** al buscar el CFDI de un registro de MPro, no filtrar
`Comprobante_Digital` por periodo.

**Por qué:** un registro de enero puede traer su CFDI timbrado en diciembre o en
febrero. Filtrar inventaría huecos.

**Evidencia:** 171 documentos de enero traen su CFDI timbrado en otro mes. Caso
real: compra `05-0029612`, `Co_Fecha` 2025-12-31, CFDI timbrado el 2 de enero.

---

## D10 · "Sin XML" se clasifica con evidencia, nunca por criterio
**2026-09-04**

**Decisión:** las clases `SIN_XML_*` del reporte 04 se asignan resolviendo el
dato, no aplicando una regla de negocio asumida.

**Casos:**
- `SIN_XML_ORIGEN_INTERNO` — el reporte **imprime la cobertura medida** por
  suborigen. `CONSUMO_INTERNO`, `GASTO_REGISTRO_NOMINA` y
  `GASTO_RECLASIFICACION` salen en 0.0%: la etiqueta es auditable.
- `SIN_XML_CFDI_EN_ORIGEN` — se resuelve la cadena documental real
  (`Cxp_Tabla` = `'Gasto_Registro:<folio>'` + `Cxp_Documento` = `Grd_ID`) y sólo
  se marca cuando **ese documento efectivamente tiene un UUID ligado**. En
  enero: 1,718 CxP, $44.04 M que habrían salido como huecos falsos.
- `SIN_XML_TRASPASO_INTERNO` — beneficiario del cheque = la propia Trivasa.
- `SIN_XML_IMPORTE_NEGATIVO` — aplicaciones y reversas, no operaciones nuevas.

**Lo que queda en `SIN_XML_PENDIENTE`** es el residual honesto, y el reporte lo
desglosa por bloque en vez de presentarlo como un número único.

---

## D11 · Tolerancia de un peso para "no material"
**2026-09-04**

**Decisión:** `TOL_CENTAVOS = 0.05` para "concilia" y `TOL_MENOR = 1.00` para
"diferencia de centavos".

**Por qué:** el prorrateo de IVA entre partidas genera diferencias de centavos
sistemáticas. En enero, 46 grupos caen en esa banda — 36 de ellos en `COMPRA`,
lo que confirma el origen (redondeo por partida en compras multi-línea).

**Riesgo asumido:** una diferencia real de menos de un peso pasa como
conciliada. Dado el volumen ($96.76 M en 1,938 grupos), es despreciable.

---

## D12 · El indicador que se reporta es el IVA acreditable con CFDI
**2026-09-04**

**Decisión:** la conclusión ejecutiva se apoya en el % de IVA acreditable con
CFDI ligado, no en el % de documentos con XML.

**Por qué:** el % de documentos (21.7% en enero) es engañoso — cuenta consumo
interno y nómina, que nunca llevan CFDI de proveedor. El IVA acreditable es lo
que se le reporta al SAT y lo que se puede acreditar.

**Cómo se calcula:** `05_resumen_conciliacion.py` cruza los impuestos por
documento contra la cobertura del reporte 04, sobre documentos **no cancelados**
de los módulos que generan IVA acreditable (gasto, compra, compra indirecta, NC
de proveedor). Enero: **99.77%**.


---

## D13 · Los CFDI intercompañía se marcan, no se cuentan como hueco
**2026-09-04, tarde — hallazgo de la corrida de febrero**

**Decisión:** nuevo estatus `MODULO_NO_CUBIERTO` para los grupos cuyo módulo de
origen no está entre los ocho que el reporte sabe leer, y columna
`INTERCOMPANIA` poblada cruzando `Cd_RFC_Emisor` contra la tabla `Empresa`.

**Por qué:** `TRIVASADB3` alberga cuatro razones sociales del grupo (Trivasa
`0001`, Facilitadores de la Construcción `0002`, Flexbeel `0003`, Triturados de
Valladolid `0004`). Un CFDI emitido por una de ellas a Trivasa **es** un
comprobante recibido, pero su registro vive en el módulo de **venta** de la otra
empresa, que estos reportes no leen. Salía como `SIN_REGISTRO`, que se lee como
hueco.

**Evidencia:** febrero 2026, 6 `COMPROBANTE_PAGO` y 2 `NOTA_CREDITO` de
`TVA910627E25`. Volumen intercompañía: 83 CFDI en enero, 22 en febrero.

**Pendiente:** si se quiere conciliar también ese lado, hay que agregar los
módulos de venta (`Factura_Encabezado` ya está; faltarían el de complementos de
pago y el de notas de crédito propias) y decidir cómo tratar la operación
intercompañía, que aparece dos veces en la misma base.

---

## D14 · Un CFDI repartido entre módulos complementarios no es descuadre
**2026-09-04, tarde — hallazgo de la corrida de febrero, aplicado también a enero**

**Decisión:** nuevo estatus `REPARTIDO_ENTRE_MODULOS`, dentro de
`ESTATUS_EXPLICADO`. Se marca cuando la **suma** de los importes de MPro de
todos los grupos que comparten un UUID cuadra con el importe del CFDI.

**Por qué:** [D3](#d3--nunca-unir-componentes-entre-módulos) concilia cada módulo
por separado para no duplicar el lado de MPro, y eso es correcto cuando un módulo
se **deriva** del otro. Pero hay pares **complementarios** donde el CFDI se
reparte: ninguno cuadra solo y la suma sí.

**Evidencia:** CFDI `90227AAD` de $161,190.75 repartido entre
`COMPRA:23-0007859` ($160,070.26, la mercancía) y `COMPRA_INDIRECTO:23-0000126`
($1,120.49, el cargo accesorio). El IVA se reparte igual: $22,078.66 + $154.55 =
$22,233.21.

**La regla se auto-protege:** si dos módulos registran cada uno el importe
completo (el caso derivado, gasto → CxP), la suma da el doble y no se marca.

**Qué corrigió:** febrero 16 grupos, enero 12 que estaban mal clasificados como
descuadre material. El descuadre de enero bajó de $4,270,134.38 a
**$4,105,233.21**.

**Corolario en impuestos:** el estatus fiscal hereda `REPARTIDO_ENTRE_MODULOS`,
porque el impuesto se reparte en la misma proporción que el importe.

---

## Límite conocido, sin decisión todavía

**El cierre de componentes sobrecuenta en pagos por parcialidades.** Un folio de
cheque que representa un pago recurrente acumula un REP por parcialidad, y
[D2](#d2--las-componentes-se-cierran-hacia-atrás) los junta todos. Caso real:
cheque `01-0046128` (ECOPULSE, $65,086.45) con 10 REP mensuales de julio 2025 a
junio 2026 — el grupo suma $650,864.40 contra un cheque de $65,086.45.

Queda identificable por `ARRASTRA_CFDI_DE_OTRO_PERIODO` y `N_XML >
N_XML_PERIODO`. La mejora, si el volumen crece, sería usar `NumParcialidad` del
`DoctoRelacionado` para quedarse sólo con la parcialidad del periodo. No se hizo
porque afecta a pocos grupos y agregar la regla sin más casos que la validen
tiene su propio riesgo.
