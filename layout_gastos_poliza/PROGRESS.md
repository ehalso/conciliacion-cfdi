# layout-gastos — estado vivo

## 2026-09-02

- **Reconciliación CECO (`Gasto_Registro_Control` vs. `Poliza_Detalle`) resuelta al 99.95%–100%**
  para los 5 orígenes normales (`CONTROL_COMBUSTIBLE`, `GASTO_DIRECTO`,
  `VIAJE`, `ORDEN_COMPRA`, `GASTO_RECLASIFICACION`). Script vigente:
  `07_reconciliacion_completa_ceco.py`.
  - Enero 2026: **100.00%** (7,691/7,691).
  - Enero-Marzo 2026: **99.95%** (17,935/17,944) — 3 folios residuales,
    ver "Residual conocido" abajo.
  - `CONSUMO_INTERNO` sigue excluido del universo — pendiente aparte, ya
    documentado en `trivasa-context` que tiene su propia estructura de
    doble póliza.

### Camino recorrido (por si hay que retomar el razonamiento)

1. **`01`/`02`** — baseline a nivel CECO/`Grc_ID`, confirma que
   `Grc_Importe` reproduce el importe total esperado.
2. **`03`** — comparación directa `Grc_ID` vs. póliza a nivel folio×centro
   (sin bajar a documento/cuenta): 98.09% ene / 97.56% ene-mar. Bien pero
   no baja lo suficiente para saber *dónde* falla.
3. **`04`** — intento de colapsar por `(Grd_ID, Centro)`: 93.35%. Peor —
   confirma que el documento no es la llave correcta.
4. **`05`** — `04` + regla de reversión (folios con `IMPORTE ≤ -$1`:
   comparar contra Abono, no Cargo — rescatada de
   `layout-gastos-pasos/docs/queries/gastos/v02_reversion.sql`): 94.05%.
5. **`06`** — cambio de llave a `(Tg_Cve_Tipo_Gasto, Centro)` + reversión:
   **99.09%**. Resuelve `GASTO_DIRECTO`, `VIAJE`, `CONTROL_COMBUSTIBLE`,
   `ORDEN_COMPRA` al 100%. Solo queda `GASTO_RECLASIFICACION` (51.05%).
6. **`07`** — `06` + regla de signo por línea para `GASTO_RECLASIFICACION`
   (el signo de `Grc_Importe`, no si el folio completo es negativo, decide
   Cargo vs. Abono — hallazgo nuevo, no documentado en ningún proyecto
   anterior; el histórico `v02_reclasificacion.sql` solo llegaba a nivel
   folio, nunca a CECO). **100.00% ene / 99.95% ene-mar.**

### Residual conocido (enero-marzo, 9 filas / 3 folios) — documentado, no resuelto

Límite de la técnica de rank-pairing (emparejar por posición dentro de
`FOLIO+CENTRO`, ordenando por importe — no existe llave real entre
`Grc_ID` y `Poliza_Detalle`). Cuando el conteo de líneas no coincide
exacto entre los dos lados en un folio puntual, el orden se desalinea en
cascada. Aislado, <0.06% del universo del trimestre — no es un patrón
sistémico.

- `0005-0182622` (`GASTO_RECLASIFICACION`, centro `103`): desajuste $3,894.
- `0001-0035339` (`COMPROBACION_GASTO`): $4.95 sin contraparte. **Causa
  identificada** (2026-09-02): el centro `000079` aparece 2 veces dentro
  del mismo documento (`Grd_ID` 0001, `Grc_ID` 24 y 25, $7.92 y $0.49) —
  al colapsar por `(Tipo_Gasto, Centro)` se suman en un renglón, pero del
  lado póliza esas dos porciones caen en sub-cuentas distintas dentro del
  mismo centro (`2120.010.005.XXX.002`, una por departamento) — el conteo
  de grupos no coincide y el rank-pairing se desalinea en el centro
  `000501`. Ver "`COMPROBACION_GASTO` — investigado" abajo para el
  contexto completo de este origen.
- `0023-0007297` (`GASTO_DIRECTO`): 4 filas con patrón de "corrimiento".
  **Causa identificada** (2026-09-02): folio de cuotas IMSS/Infonavit
  (sucursal UMAN, 4 documentos con `Tg_Cve_Tipo_Gasto` distinto cada uno:
  IMSS, Retiro, CyV, Infonavit), cada uno repartido en los mismos 2
  centros (`000158`/`000215`) pero con líneas en **$0.00** cuando ese
  documento no le toca nada a ese centro. Como cada documento tiene tipo
  de gasto distinto, no se colapsan entre sí — quedan filas en cero
  compitiendo por una posición en el rank-pairing, que las corre todo un
  lugar. Misma familia de fragilidad que `COMPROBACION_GASTO` (rank-pairing
  sin llave real), causa raíz distinta (ceros de más vs. centro
  duplicado).

### Nota de arquitectura

Este enfoque (comparar `Gasto_Registro_Control` contra `Poliza_Detalle` a
nivel CECO) es un ejercicio de **diagnóstico de calidad de datos**, no la
fuente del reporte final — `Poliza_Detalle` sola ya reconcilia al 100%
contra el folio (`ref/reconciliacion_cargo_abono_ceco.py`). Se sigue este
camino porque el proyecto necesita específicamente la granularidad que
aporta `Gasto_Registro_Control`/`Grc_ID` (no solo validar el total).

## 2026-09-02 (continuación) — `CONSUMO_INTERNO` incorporado

- **`09_reconciliacion_completa_con_consumo_interno.py`** — extiende `07`
  agregando `CONSUMO_INTERNO` como sexto origen. **99.75%** total
  (10,735/10,762, enero 2026); `CONSUMO_INTERNO` solo: **99.12%**
  (3,044/3,071) — coincide con el 99.1% que ya estaba documentado en
  `trivasa-context/docs/proyectos/layout-gastos/index.md` (calculado en
  otra sesión, nunca con script guardado hasta ahora).
- Requirió una query de póliza **distinta** a la de los otros 5 orígenes —
  `CONSUMO_INTERNO` genera dos pólizas paralelas por folio (memo de
  inventario `10500`/`10600` vs. gasto real), así que hay que aislar la de
  gasto real filtrando `Poliza.Pl_Comentario` (excluir "CUENTAS DE
  ORDEN"/"CTS ORDEN"/"CUENTA ORDEN"). Confirmado que el filtro es correcto:
  totales cuadran exacto con lo ya documentado (Importe $6,594,522.55,
  Cargo gasto real $6,388,627.47).
- **Simplificación pendiente**: a `CONSUMO_INTERNO` no se le aplicó la
  regla de reversión ni ninguna otra de las de `07` — solo comparación
  plana contra Cargo. No se investigó si `CONSUMO_INTERNO` tiene sus
  propios folios de reversión.

### Drill-down de las 27 filas que no cuadran (23 folios) — CORRIGE una suposición heredada

**No son un hueco de datos.** La documentación previa (`layout-gastos/index.md`
en `trivasa-context`) asumía "26 folios sin póliza de gasto real — hueco
real en los datos". Drill-down folio a folio (`07-0082417` primero,
después confirmado en los 23) muestra que **21 de 23 (91%) sí tienen su
gasto contabilizado** — solo que en un caso de negocio distinto:
**capitalización de activo fijo**, no gasto del periodo.

Patrón encontrado, sistemático:
- `Grd_Comentario` empieza con `U-NNN` / `UNNN` (ej. `U-241`, `U445`, `U550`)
  — un código de proyecto/unidad de activo en construcción.
- La póliza real usa `Pd_Referencia = 'NNN'` (ese mismo número corto), **no**
  el `Gr_Folio` completo — por eso `pd.Pd_Referencia = gr.Gr_Folio` nunca
  la encuentra.
- La cuenta contable es `1210.xxx` ("Maquinaria Y Equipo" y similares) —
  cuenta de **Activo Fijo**, no de Gasto (`6xxx`/raíz `F`). El material
  consumido se suma al costo del activo, no se gasta.

Ejemplo confirmado (`07-0082417`, "U550 BASE PIVOTANTE", $114,771.88):
la línea real vive en `Pl_Folio 0000472954` ("CONSUMO INTERNO DEL
29/ene/2026"), `Pd_ID 0003`, cuenta `1210.002.002.001 "Maquinaria Y
Equipo"`, `Pd_Referencia = '550'`.

Quedan genuinamente sin explicar solo **2 folios**: `05-0175286`
("DESPLIEGUE DE CONVERTIDORES DE MEDIOS DE FIBRA ÓPT") y `05-0176482`
("SOLICITUD FORMATOS RECIBO DE CAJAS") — sin match ni por folio ni por
importe en ninguna póliza ligada. Estos sí podrían ser el hueco real.

Un caso aparte, no capitalización: `05-0174748` ("LLANTA PONCHADA") sí
matchea por folio completo, pero en cuenta `2120.010.004.005.002`
(familia de Provisión/Pasivo — mismo patrón visto antes en las
reversiones de los 5 orígenes normales, ver sección de arriba). No
investigado a fondo todavía.

**Conclusión:** el 99.12% de `09` **subestima** la reconciliación real —
no son huecos, son folios con tratamiento contable distinto que la query
actual no está diseñada para capturar.

## 2026-09-02 (continuación) — `COMPROBACION_GASTO` investigado

`COMPROBACION_GASTO` = **comprobación de gastos de fondo fijo** (reembolso
de caja chica / vales de empleados) — origen de bajo volumen, solo 439
folios en toda la historia (desde 2018, empresa 0001), 2 de ellos en
enero-marzo 2026.

- Estructura de póliza: Cargo al gasto real + IVA acreditable, **Abono a
  `1110.002.001.019 "FONDO FIJO..."`** (se acredita la cuenta de caja
  chica por el total gastado) — no es Cargo/Abono normal de proveedor, es
  liquidación de un fondo revolvente.
- `05-0179663` (simple): 1 documento, 1 centro — cuadra perfecto con el
  enfoque normal `(Tipo_Gasto, Centro)`.
- `01-0035339` (falla 1 de 82 filas): 1 documento ($242.50, "PALETAS
  PAYASO EVENTO 14FEB26") repartido en **82 centros de costo**, la póliza
  en **82 sub-cuentas** (`2120.010.005.XXX.002`, una por departamento).
  Causa del único fallo: el centro `000079` aparece 2 veces en
  `Gasto_Registro_Control` dentro del mismo documento — al colapsar por
  `(Tipo_Gasto, Centro)` se suman, pero la póliza las tiene en sub-cuentas
  separadas del mismo centro, desalineando el rank-pairing.

**No es un caso de negocio que necesite regla propia** — es el mismo
límite de fondo del rank-pairing (cuenta↔centro no es 1:1 cuando un
documento se reparte muy fino), no un tratamiento contable distinto como
la capitalización de `CONSUMO_INTERNO`. Se deja documentado como variante
del residual conocido, no como pendiente de regla.

## 2026-09-02 (continuación) — Cruce con XML (`Comprobante_Digital`), enero 2026

Cruce simple por folio (`Cd_Documento LIKE Gr_Folio + '%'`, `Cd_Tabla =
'GASTO_REGISTRO'`, `Cd_Timbre_UUID` distinto ≥1 ⇒ "con XML") sobre el
universo de los 6 orígenes (sin `GASTO_REGISTRO_NOMINA`). Mismo patrón ya
validado en `layout-contabilidad` (`v_uuid_por_folio.sql` — ver ese
archivo para los dos gotchas de rendimiento/dedup si se reconstruye esto
como query guardada).

| ORIGEN | Folios | Con XML | Sin XML | % Con |
|---|---:|---:|---:|---:|
| CONTROL_COMBUSTIBLE | 384 | 384 | 0 | 100.00% |
| VIAJE | 346 | 346 | 0 | 100.00% |
| ORDEN_COMPRA | 72 | 72 | 0 | 100.00% |
| GASTO_DIRECTO | 610 | 537 | 73 | 88.03% |
| CONSUMO_INTERNO | 2,970 | 0 | 2,970 | 0.00% (esperado, sale de inventario propio) |
| GASTO_RECLASIFICACION | 13 | 0 | 13 | 0.00% (esperado, movimiento contable puro) |
| **TOTAL** | 4,395 | 1,339 | 3,056 | 30.47% |

17 folios "Varios" (2+ UUID distintos) dentro del total.

### Drill-down de los 73 `GASTO_DIRECTO` sin XML

Categorización por `Grd_Comentario`:

| Categoría | Folios | Importe |
|---|---:|---:|
| Provisión/Saldo/Reclasificación (estimado contable) | 35 | $8,329,191 |
| ISN (impuesto autoliquidado, no lleva CFDI) | 13 | $286,714 |
| SaaS/publicidad extranjera (Canva, Zerotier, Asana, ChatGPT, Meta) | 8 | $9,883 |
| Ajuste fiscal / no deducible | 5 | $13,031 |
| Amortización/Depreciación (asiento no monetario) | 3 | $2,655,337 |
| Servicio de envío | 2 | $24,812 |
| Intereses bancarios | 1 | $3,524 |
| Seguro equipo de cómputo | 1 | $430,399 |
| Otro (revisados uno a uno, ver abajo) | 5 | -$78,749 |

**Regla de negocio confirmada, reusable:** cuenta contable
`Cc_Descripcion = 'No Deducibles'` (código `XXXX.009.008`/`XXXX.007.008`,
una por sucursal) → **se espera que no tenga XML por diseño**. De los 73,
**13 caen exactamente en esa cuenta** (los de SaaS extranjero, ajuste
fiscal, y comisión cajero) — el contador ya los marca ahí precisamente
*porque* no tienen CFDI (sin factura válida no se puede deducir
fiscalmente en México). Más confiable que categorizar por palabra clave
del comentario — es una señal que ya vive en los datos.

Drill-down uno a uno de los 5 "Otro" + los 3 dudosos de la tabla de
categorías, usando el segundo camino de UUID que la documentación
histórica menciona pero nunca se había probado (`Pago_Cxp_Comprobante`,
vía `Cuenta_X_Pagar` → `Pago_CXP`, en vez de `Comprobante_Digital`
directo):

| Folio | Comentario | Conclusión |
|---|---|---|
| `05-0177386` | SOLICITUD BDZIB | No es hueco — reversión con sub-póliza de "entrega pendiente" (ver residual conocido arriba) |
| `01-0034993` | COMISIÓN CAJERO ($50) | No es hueco — proveedor genérico `0000000000`, comisión bancaria, cuenta `No Deducibles` |
| `05-0177135` | CELEBRACIONES PROD ($4,034) | Probable hueco menor — proveedor genérico, sin `Cuenta_X_Pagar`, gasto de caja chica sin factura capturada |
| `05-0176458` | U445 PROGRAMA SIMULADOR ($250) | **Hueco real** — proveedor real (`0000005150`), pagado vía `Pago_CXP`, `Pago_Cxp_Comprobante` vacío |
| `05-0177138` | CURSOS Y CAPACITACIONES ($4,760) | Probable hueco menor — mismo patrón que Celebraciones |
| `05-0174692` | U-393 SERV DE ENVÍO ($5,498) | **Hueco real** — proveedor real (`0000001858`), pagado, `Pago_Cxp_Comprobante` vacío |
| `05-0174929` | U-323 SERV DE ENVÍO ($19,314) | **Hueco real** — mismo proveedor y patrón que el anterior |
| `01-0034939` | SEGURO EQUIPO DE CÓMPUTO ($430,399) | No es hueco — sin `Cuenta_X_Pagar` en absoluto, es amortización mensual de póliza ya pagada (mismo patrón que `AMORT SEGURO MEDICO`) |

**Conclusión: de los 73 folios `GASTO_DIRECTO` sin XML, solo 3 son un
hueco real de datos** (`05-0176458`, `05-0174692`, `05-0174929` — los tres
con proveedor real y pago confirmado pero sin CFDI ligado; candidatos a
reportar a contabilidad). El resto (70, 96%) tiene explicación de negocio
válida — provisión, ISN, SaaS extranjero, amortización, o proveedor
genérico sin factura por diseño.

## 2026-09-02 (continuación) — "Varios" de XML: artefacto de grano, no ambigüedad real

17 folios de enero 2026 (universo completo, sin excluir `CONSUMO_INTERNO`/
`GASTO_RECLASIFICACION`) traían 2+ UUID distintos ("Varios" en el sentido
de `layout-gastos-pasos/docs/v2_1_cierre.md`). Bajando de folio a
**documento** (`Grd_ID`): **16 de 17 desaparecen** — cada documento dentro
de esos folios tiene exactamente 1 UUID propio; "Varios" solo aparecía
porque el folio agrega 2-9 documentos, cada uno con su propia factura.

**Solo 1 caso real de ambigüedad incluso a nivel documento:**
`01-0034855` ("COMISIÓN BANCARIA ENERO 2026") — 8 documentos, importe
simbólico $0.01 cada uno. 3 de los 8 documentos (`Grd_ID` 0001, 0004,
0005, 0006 — el 0004/0005/0006 con RFC emisor **distinto** cada vez, BBVA
`BBA830831LJ2` + BanBajío `BVM951002LX0`) tienen 2 UUID cada uno.
**No es error**: el folio consolida comisiones bancarias mensuales de
varios bancos en documentos con importe simbólico — el gasto real vive en
los CFDI individuales del banco, no en el importe de `Gasto_Registro`.

**Conclusión:** a nivel documento/CECO (el grano que usamos en toda esta
exploración), el problema de "Varios" queda prácticamente resuelto — no
hay ningún caso genuino de ambigüedad real de a qué factura corresponde
un gasto en enero 2026, todo era artefacto de agregar por folio en vez de
por documento.

## Pendiente

- **Mejorar la query de `CONSUMO_INTERNO` para resolver el problema de
  doble póliza de forma más elegante.** El filtro actual
  (`Pl_Comentario NOT LIKE '%CUENTAS DE ORDEN%'` etc.) es un `LIKE` sobre
  texto libre capturado por quien contabiliza — funciona hoy (validado al
  99.12%), pero es frágil: no hay garantía de que el comentario se siga
  escribiendo igual en el futuro, ni cubre variantes de redacción no
  vistas todavía. Alternativa más robusta a explorar: aislar por cuenta
  contable (raíz `F` de Gastos / cuentas `10500`/`10600` excluidas
  explícitamente) en vez de por texto del comentario — ya se documentó en
  `trivasa-context` que ambos caminos dan el mismo resultado exacto a
  nivel folio, falta confirmar que también coinciden a nivel CECO.
- Revisar si `CONSUMO_INTERNO` tiene folios de reversión y aplicarles la
  misma regla que a los otros 5 orígenes.
- ~~**Construir la rama de capitalización** para `CONSUMO_INTERNO`: cuando
  `Grd_Comentario` empieza con `U-NNN`/`UNNN`, buscar `Pd_Referencia = NNN`
  (no `Gr_Folio`) en cuentas `1210.xxx`~~ — resuelto 2026-09-08, ver esa
  entrada: la hipótesis de parsear `Grd_Comentario` era incorrecta, el
  código corto ya vive tal cual en `Gasto_Registro.Gr_Referencia`.
- Investigar a fondo los 2 folios genuinamente sin match (`05-0175286`,
  `05-0176482`) y el caso aparte `05-0174748` (cuenta `2120...`, patrón de
  Provisión, no capitalización).
- Opcional: los 3 folios residuales de la sección anterior, si hace falta
  cerrar al 100% exacto.
- Reportar a contabilidad los 3 huecos reales de XML encontrados
  (`05-0176458`, `05-0174692`, `05-0174929` — proveedor real, pagado, sin
  CFDI ligado) para que liguen el comprobante faltante.
- Guardar la regla de "cuenta `No Deducibles` ⇒ sin XML esperado" como
  query reusable (hoy solo se probó ad-hoc, no vive en ningún script) y
  extenderla al resto de los orígenes/al rango completo (esto solo se hizo
  para `GASTO_DIRECTO`, enero 2026).
- ~~Correr el cruce de XML también para `CONSUMO_INTERNO`/
  `GASTO_RECLASIFICACION`~~ — descartado a propósito (2026-09-02): ambos
  ya confirmados en 0% con XML **esperado por diseño** (inventario propio
  / movimiento contable puro, sin transacción con proveedor), no vale la
  pena el drill-down que sí se justificó para `GASTO_DIRECTO`.

## 2026-09-03 — `GASTO_REGISTRO_NOMINA` investigado: SÍ liga con póliza real

Origen que quedaba como "sin investigar" en `RESUMEN_CASOS.md`. Se liga
**exactamente por el mismo mecanismo** que los 5 orígenes normales —
`Poliza_Control` (`Pc_Tabla='GASTO_REGISTRO'`, `Pc_Documento=Gr_Folio`) →
`Poliza` → `Poliza_Detalle` (`Pd_Referencia=Gr_Folio`). El comentario en
`queries/v03_detalle_cuenta_centro_costo.sql` ("Nómina se contabiliza por
otro mecanismo, ajeno a este reporte") está **desactualizado/incorrecto** —
misma situación ya encontrada con `CONSUMO_INTERNO` (también excluido por
ese mismo comentario, y también resultó tener póliza real, ver sección
`09` arriba).

Diferencia de grano: cada folio de nómina genera muchas más líneas de
Cargo en la póliza que `Grc_ID` (una por concepto — Sueldos, Bono Por
Productividad/Puntualidad/Asistencia, Fondo de ahorro, Comisiones,
Vacaciones, Prima Vacacional, Pagos Por Retiro — cada una en su propia
cuenta `6xxx`), así que la comparación se hace a nivel `(FOLIO, CENTRO)`
en vez de por cuenta. Cada póliza también trae líneas de Cargo/Abono
**sin centro de costo** (`Pd_Centro_Costo=''`) — reclasificaciones de
pasivo (ISR retenido, Cuotas IMSS, Sueldos y salarios por pagar, Fondo de
ahorro por pagar, Vales de despensa por pagar...) que cierran el balance
Cargo=Abono de la póliza pero no son gasto por centro; se excluyen
filtrando `Pd_Centro_Costo <> ''`.

**Resultado: 100.00%** (2,549/2,549 filas FOLIO×CENTRO, 270 folios activos
de 294 totales — 24 cancelados —, enero-marzo 2026, empresa 0001). Cero
folios sin póliza ligada. Mejor resultado de cualquier origen investigado
en este proyecto. Script: `13_reconciliacion_nomina_ceco.py`.

**Validación de seguimiento, a grano más fino (`FOLIO, CENTRO, CONCEPTO`):**
el 100% de arriba es a nivel centro — no probaba que el reparto *entre*
tipos de gasto dentro del mismo centro también fuera correcto (1,155 de
2,549 combinaciones folio×centro traen 2+ `Tg_Cve_Tipo_Gasto` distintos,
ej. Sueldos + Bono Productividad + Fondo de ahorro en el mismo centro —
un mal reparto entre ellos se cancela en la suma). No hay FK real
`Tipo_Gasto → Cuenta_Contable` para nómina (`Tg_Cuenta_Contable` vacío en
los 249 tipos, mismo hueco de `ref/README.md`) — se unió por texto
normalizado (`Tg_Descripcion` = `Cc_Descripcion` exacto). **También
100.00%** (6,591/6,591 filas, cero conceptos huérfanos en ningún lado) —
el reparto por concepto individual es exacto, no solo la suma por centro.
Función `validar_grano_concepto()` en el mismo script.

**Pendiente:** decidir si se incorpora `GASTO_REGISTRO_NOMINA` como
séptimo origen en `07_reconciliacion_completa_ceco.py`/al universo del
reporte final — dado el 100%, no hay obstáculo técnico; falta decidir a
nivel negocio si nómina debe aparecer en el mismo layout de gastos que
los demás orígenes o reportarse aparte (dato sensible, ver
`trivasa-context/docs/schema/dominios.md`: dominio NÓMINA marcado "Baja
prioridad — definir acceso antes").

## 2026-09-05 — Bug real en `xml_gasto_registro()`: filtro `LEN(Cd_Documento)=18` excluía un segundo formato válido completo

Encontrado haciendo drill-down manual de los folios de `ORDEN_COMPRA`
que salían "sin XML" (17 de 72, enero 2026) en el análisis de cobertura
por origen. Los 17 SÍ tenían XML ligado — el filtro de
`xml_gasto_registro()` (`poliza_configuracion_lib.py`, usado por `15` y
por `reporte_ui_config.py`/CONT-4/CONT-5) solo aceptaba
`Cd_Documento` de longitud 18 (`Gr_Folio(10) + Grd_ID(4) + sufijo fijo
'0001'(4)`), pero existe un **segundo formato de longitud 14**
(`Gr_Folio(10) + Grd_ID(4)`, sin el sufijo) que también es
`Cd_Tabla='GASTO_REGISTRO'` y decodifica igual de limpio (verificado
contra datos reales) — se estaba excluyendo por completo.

**Magnitud confirmada**: 22,520 de 96,872 registros históricos de
`Cd_Tabla='GASTO_REGISTRO'` (~23%) usan el formato de 14. Solo en enero
2026: 441 de 1,510 documentos con XML (29%) se perdían por este filtro.

**Efecto en cobertura por origen** (recalculado, enero 2026, universo
completo 7 orígenes vía `Gasto_Registro`/`Gasto_Registro_Documento`
directo, no solo config `0450`):

| Origen | % docs (antes → corregido) | % importe (antes → corregido) |
|---|---|---|
| ORDEN_COMPRA | 76.39% → **100.00%** | 96.31% → **100.00%** |
| CONTROL_COMBUSTIBLE | 0.00% → **100.00%** | 0.00% → **100.00%** |
| GASTO_DIRECTO | 81.65% → 85.85% | 34.94% → 35.04% |
| VIAJE | 100.00% (sin cambio) | 100.00% (sin cambio) |
| CONSUMO_INTERNO / NOMINA / RECLASIFICACION | 0.00% (sin cambio, esperado por diseño) | 0.00% (sin cambio) |

`CONTROL_COMBUSTIBLE` era el cambio más grande — se había documentado
(en esta misma conversación, antes del drill-down) como "0% esperado,
se captura por vales/tickets, no CFDI", explicación que **era
incorrecta**: sí genera CFDI, solo estaba invisible por el bug. El hueco
real de `GASTO_DIRECTO` (35% de importe con XML) **no cambia
significativamente** — no era artefacto de este bug.

**Segundo hallazgo, al reparar el filtro**: un mismo `(FOLIO, GRD_ID)`
puede tener 2 filas en `Comprobante_Digital` (una por formato) —
confirmado enero-marzo 2026, 27 pares. **20 son el mismo XML capturado
dos veces** (mismo `Cd_Timbre_UUID` en ambos formatos) — sin deduplicar,
el merge cuenta el importe del documento 2x contra ese UUID (caso real:
folio `23-0006650`, `IMPORTE_DOC` salía exactamente el doble de
`Cd_Monto`). Corregido con `drop_duplicates(subset=["FOLIO","GRD_ID",
"XML_UUID"])` al final de `xml_gasto_registro()`. **Los otros 7 pares
tienen un `Cd_Timbre_UUID` genuinamente distinto entre formatos** (2 CFDI
reales ligados al mismo documento, patrón visto: fechas de timbrado
distintas, casi siempre el de formato 14 es posterior — compatible con
una recaptura/corrección) — **no resuelto**, queda como ambigüedad real
documentada (ver docstring de `xml_gasto_registro()`), no afecta el
rango de interés actual (solo 3 de 232 folios ambiguos históricos caen
en enero-marzo 2026).

**Efecto en el resultado de `15` (config `0450`, enero-abril 2026)**:
cobertura de documentos con XML sube de facto (mas documentos visibles),
pero el % de folios cuya suma de documento cuadra contra `Cd_Monto`
**baja** de 97.76% (1,922/1,966 `XML_UUID`, documentado antes en
`trivasa-context`) a **93.53%** (1,950/2,085, tras deduplicar) — no es
una regresión real, es que ahora hay 119 `XML_UUID` adicionales visibles
que antes ni se contaban, y una porción de ellos no cuadra en monto
(residual real, no causado por este fix). Discrepancias grandes
residuales (ej. `$57,496.57` vs `$3,201.60` en un solo documento) quedan
sin investigar — no explicadas por el bug de formato ni por la
duplicación, requieren su propio drill-down si se retoma esto.

**Corregido**: `poliza_configuracion_lib.py`, función
`xml_gasto_registro()` — `LEN(Cd_Documento) = 18` → `IN (14, 18)`, más
la deduplicación de arriba. Afecta también `reporte_ui_config.py`
(CONT-4/CONT-5, que importan esta función) — no re-validado en Streamlit
todavía, solo vía script `15`.

### Segunda corrección el mismo día: `Cd_Monto` viene en moneda ORIGINAL del CFDI, no convertida a MXN

Investigando el residual de cuadre de monto vía drill-down real de
`ORDEN_COMPRA` (12 `XML_UUID` que no cuadraban, ratio de diferencia hasta
18x): **los 12 son documentos en `Mn_Cve_Moneda='USD'`** (tipo de cambio
17.2–17.98). `importe_documento()` (`15_reconciliacion_xml_via_poliza_
configuracion.py`) calculaba `Grd_Precio_Neto_Importe * Grd_Tipo_Cambio`
(la misma fórmula de `IMPORTE_FOLIO_SQL` de `layout_gastos_lib.py`,
correcta ahí porque es un total en MXN para sumar folios de distinta
moneda) — pero `Comprobante_Digital.Cd_Monto` viene en la **moneda
original del CFDI**, sin convertir. Comparar el importe ya convertido a
MXN contra el monto nativo del XML explica exactamente la magnitud del
error (factor = tipo de cambio).

**Confirmado con datos reales**: los 12 casos cuadran **exacto ($0.00 de
diferencia)** comparando `Grd_Precio_Neto_Importe` SIN convertir contra
`Cd_Monto`. Seguro también para MXN — verificado que `Grd_Tipo_Cambio`
es siempre `1.0` para `Mn_Cve_Moneda='MXN'` (7,026/7,026 documentos,
enero 2026), así que quitar la conversión no cambia nada en el caso
normal, solo corrige USD/EUR.

**Corregido**: `importe_documento()` en `15_reconciliacion_xml_via_
poliza_configuracion.py` — ya no multiplica por `Grd_Tipo_Cambio`.

**Efecto en `ORDEN_COMPRA`** (dentro de config `0450`): cuadre de monto
sube de 83.33% (135/162) a **98.15%** (159/162) — quedan 3 `XML_UUID`
sin explicar, residual nuevo, no investigado.

**Esto resuelve el residual que quedaba anotado en `trivasa-context`
desde ayer** ("Residual no investigado a fondo — parece concentrado en
documentos en USD... compatible con doble aplicación de tipo de cambio")
— confirmado exacto, era doble aplicación de tipo de cambio, no doble
conteo de documentos.

**Pendiente**:
- Actualizar `trivasa-context/docs/proyectos/layout-gastos/{index,PROGRESS}.md`
  y `streamlit-reportes/reportes/*` si aplica — documentan el 97.76%/
  97.21% viejo como resultado validado, ahora desactualizado (y la nota
  de "residual USD sin investigar" ya está resuelta).
- Investigar los 3 `XML_UUID` de `ORDEN_COMPRA` que siguen sin cuadrar
  tras la corrección de moneda — residual nuevo, sin drill-down todavía.
- `CONTROL_COMBUSTIBLE` da 0% de cuadre **dentro del universo de una
  sola config** (`0450`) porque sus facturas consolidadas cruzan a otras
  configs (confirmado con un caso real: una factura de 14 folios, 2 de
  ellos en config `0427`) — al sumar TODOS los folios reales ligados al
  UUID, sin restringir a una config, cuadra 100%. No es un bug de este
  fix, es un límite de alcance de `reconstruir_config()`/`15` (solo
  trabajan dentro de una config). Si se generaliza la reconstrucción a
  más configs (pendiente de antes), este problema debería desaparecer
  solo.
- Decidir un criterio para los 7 pares con ambigüedad real de UUID (ej.
  preferir el `Cd_Timbre_Fecha` más reciente) si algún caso concreto lo
  requiere — hoy no se resuelve, solo se documenta.
- Re-correr `07_reconciliacion_completa_ceco.py`/el resto del proyecto
  contra este mismo patrón de `Comprobante_Digital` no aplica (esos
  scripts no cruzan XML, son solo `Grc_ID` vs. `Poliza_Detalle`) — el fix
  es específico a la conciliación XML (`14`/`15`/CONT-4/CONT-5).

## 2026-09-05 (continuación) — HITO: `16`/`17`, conciliación XML por origen (sin config), y dos mejoras probadas con evidencia

Extiende lo de arriba a un panorama completo por origen, sin pasar por
`Poliza_Configuracion` (que solo cubre 1 de ~67 configs) — trabaja directo
contra `Gasto_Registro`/`Gasto_Registro_Documento`/`Comprobante_Digital`,
para los 4 orígenes que sí deberían llevar XML por lógica de negocio:
`GASTO_DIRECTO`, `VIAJE`, `ORDEN_COMPRA`, `CONTROL_COMBUSTIBLE`.
(`CONSUMO_INTERNO`/`GASTO_REGISTRO_NOMINA`/`GASTO_RECLASIFICACION` quedan
fuera a propósito, confirmado 0% de cobertura por diseño, no por hueco.)

**`16_reconciliacion_xml_por_origen.py`**: consolida las 3 correcciones
de la entrada anterior (formato de longitud, deduplicado, moneda nativa)
en un solo script reusable. Resultado limpio: **VIAJE, ORDEN_COMPRA y
CONTROL_COMBUSTIBLE en 100%/100%** (cobertura y cuadre de monto, enero
2026). `GASTO_DIRECTO` queda con el hueco real del proyecto: 85.94% de
documentos con XML (35.04% del importe), y de esos, 89.30% cuadra en
monto — 58 de 542 `XML_UUID` sin explicar.

**Investigación del residual de GASTO_DIRECTO** (con ayuda de investigar
`~/proyectos/conciliacion-master/adjuntar-xml/` y `~/proyectos/layout-
contabilidad/layout_gastos/`, proyectos paralelos de otras sesiones que
resuelven el mismo problema — ver hallazgos completos más abajo): de 58
`XML_UUID`, **31 (53%) son CFDI tipo RETENCIONES** (MPro los liga con
`Cd_Monto=0` bajo `Cd_Tabla='GASTO_REGISTRO'`, el monto real vive en una
fila hermana del mismo UUID bajo `Cd_Tabla='CONSTANCIA_RETENCION'` —
Trivasa es el emisor de esa constancia, obligación fiscal al retener ISR
de honorarios a personas físicas). De esos 31, **16 cuadran exacto** con
`IMPORTE_DOC = Cd_Monto_constancia × 0.90` (ISR 10%); los otros 15 no
tienen constancia ligada, sin explicar. Los **27 restantes (47%)** son
CFDI tipo Ingreso normal sin patrón único — al menos uno confirmado como
"CFDI repartido en varios documentos" (mismo `Cd_Monto` en 2 `Grd_ID`
distintos del folio `01-0034832`), el resto sin explicación clara.

**`17_reconciliacion_xml_grano_grupo.py`**: incorpora dos mejoras sobre
`16`, probadas empíricamente (no supuestas) en 3 rangos de fecha (enero,
enero-marzo, enero-mayo 2026) para elegir con evidencia:

1. **Grano de componente conexa (union-find)** en vez de `(FOLIO,GRD_ID)`
   ↔ `XML_UUID` por par — idea de `adjuntar-xml/conciliacion_xml_lib.
   asignar_grupos()`, reimplementada en versión **ligera** (sin traer
   `Cd_XML`, el texto completo del CFDI) porque el entorno de exploración
   solo tiene ~5GB de RAM con <400MB libres — confirmado con `free -h`
   que la versión con `Cd_XML` completo agota memoria y el proceso muere
   sin traceback (no era el usuario deteniéndolo, se verificó
   explícitamente). Efecto medido en `GASTO_DIRECTO` (enero 2026):
   27.56% → 27.73% de importe que cuadra — **marginal**, contrario a lo
   esperado de `adjuntar-xml` (ahí el mismo cambio resolvía ~9x más
   descuadres). El residual de este proyecto NO era mayormente por
   reparto de documentos.
2. **Fix de retenciones** (ver arriba, `Cd_Monto_constancia × 0.90`) —
   este sí importa: 27.73% → **31.40%** (+3.67pp).

**Efecto total, `GASTO_DIRECTO`, % de importe que cuadra sobre el total
del origen, por rango de fecha** (el % no varía mucho entre rangos —
ningún periodo es claramente "mejor", se documentan los 3 como evidencia):

| Rango | GASTO_DIRECTO | CONTROL_COMBUSTIBLE | TOTAL (4 orígenes) |
|---|---:|---:|---:|
| Enero 2026 | 31.40% | 100.00% | 40.28% |
| Enero-Marzo 2026 | 33.13% | 100.00% | 41.15% |
| Enero-Mayo 2026 | 32.03% | **73.49%** | 39.94% |

`VIAJE`/`ORDEN_COMPRA` se mantienen ~100% en los 3 rangos.
**`CONTROL_COMBUSTIBLE` cae a 73.49% en enero-mayo** (era 100% en los dos
rangos más cortos) — hallazgo nuevo, no investigado, ver Pendiente.

**Ideas evaluadas y NO incorporadas todavía** (documentado el porqué, no
solo "pendiente" a secas):
- **Parsear `Cd_XML` para complementos** (CFDI de Pago/REP, Vales de
  Despensa) — propuesta real de `adjuntar-xml`, pero el residual de
  `GASTO_DIRECTO` resultó ser mayoritariamente RETENCIONES (mecanismo ya
  cubierto), no REP/Vales. Se pospone a un futuro script si el residual
  de 27 `XML_UUID` tipo Ingreso lo amerita — ahí sí haría falta leer el
  XML completo, con cuidado de memoria (solo esos ~27 casos puntuales).
- **`Cuenta_X_Pagar` como cadena alterna para `CONTROL_COMBUSTIBLE`**
  (validado por `layout-contabilidad/layout_gastos/docs/control_
  combustible_hallazgo.md`, otra sesión, 30/30 y 32/32 en dos meses) — no
  hizo falta en enero/enero-marzo (el union-find ya resolvía 100%), pero
  podría ser la explicación del nuevo residual de enero-mayo.
- **Marcar CFDI intercompañía** — no se encontraron casos en el universo
  de estos 4 orígenes durante las pruebas.

**Pendiente**:
- Investigar por qué `CONTROL_COMBUSTIBLE` cae a 73.49% en enero-mayo
  (nuevo, sin investigar) — candidato: mismo mecanismo de `Cuenta_X_Pagar`
  de `layout-contabilidad`.
- Los 15 CFDI de RETENCIONES sin constancia ligada (de los 31 encontrados).
- Los 27 `XML_UUID` tipo Ingreso normal sin patrón único identificado.
- Considerar traer las mejoras de `adjuntar-xml` (parseo de `Cd_XML`,
  `Cuenta_X_Pagar`) en una máquina con más memoria si se retoma esto —
  aquí se evitó a propósito por el límite de RAM del entorno.

## 2026-09-08 — `CONSUMO_INTERNO`: resuelta la rama de capitalización de activo fijo, vía `Poliza_Configuracion`

Origen: pregunta de usuario sobre un folio concreto que no conciliaba con
Cargo=Abono=0 (`07-0082044`, póliza `472949`), a pesar de tener póliza real
contabilizada. Investigado con drill-down manual, luego confirmado leyendo
directamente `Poliza_Configuracion`/`Poliza_Configuracion_Detalle` (ver
`trivasa-context/docs/proyectos/poliza-explor/configuracion-polizas.md`) en
vez de inferir el patrón por prueba y error.

**Hipótesis anterior (incorrecta, quedaba en "Pendiente" arriba):** que el
código corto de referencia salía de parsear `Grd_Comentario` (`U-NNN` →
quitar la `U`). **Real:** `Poliza_Configuracion_Detalle.Pcd_Referencia` de
las configs `0295`/`0414` (ambas "CONSUMO INTERNO ADICION Y MEJORAS", las
que cubren el grupo de `Tipo_Gasto` de activo fijo — `0181`-`0188`, `0192`,
`0246`) es literalmente `Gasto_Registro.Gr_Referencia` — una columna real
de la tabla, no algo derivado. Para el folio de ejemplo, `Gr_Referencia =
'445'`, exactamente el valor que trae `Poliza_Detalle.Pd_Referencia` de la
línea de cargo en cuenta `1210.xxx`.

**Segundo hallazgo, más grande:** la fuente operativa real que usa el motor
de pólizas para estas 2 configs no es `Gasto_Registro_Documento`/
`Gasto_Registro_Control` (lo que usan `07`/`09`/`11`/`12` de este proyecto)
— es `Consumo_Interno` + `Consumo_Interno_Ceco`, ligadas por
`Gasto_Registro.Gr_Documento = Consumo_Interno.Ci_Folio`, con importe
`Ci_Costo_Importe * Cic_Factor`. Coincide en este caso con `Grc_Importe`
(por eso nunca se notó como discrepancia de cifra, solo como "sin match"),
pero es la tabla que de verdad alimenta la póliza — no se migró la
reconciliación a esa fuente, se mantuvo `Gasto_Registro_Control` porque ya
está validada para los otros 6 orígenes y el importe coincide.

**Complicación real, no trivial:** `Gr_Referencia` NO es único dentro de
una póliza — 8 de 29 pólizas de esta rama en enero-marzo 2026 consolidan
2+ folios bajo el mismo código de referencia (ej. dos folios "U-241" con
importes distintos, mismo centro y cuenta). Se resuelve con la misma
técnica de rank-pairing que ya usa el resto del proyecto (`emparejar()`,
ordenar ambos lados por importe dentro de `(Pl_Folio, Referencia)` y
emparejar por posición) — no hay llave 1:1 real, igual que
`Grc_ID`↔`Poliza_Detalle` en los orígenes normales.

**Aplicado en `12_reporte_base_ceco_consumo_interno.py`** (`POLIZA_SQL_CI_ACTIVO_FIJO`
+ `GR_REFERENCIA_SQL`, rank-pairing por `(PL_FOLIO, REFERENCIA)` antes de
unir con el resto de `detalle_ci`). Resultado, enero-marzo 2026:

| | Filas | Cuadran | % |
|---|---:|---:|---:|
| Antes | 9,139 | 9,081 | 99.37% |
| Después | 9,140 | 9,125 | **99.84%** |

45 de 47 folios de activo fijo recuperados. **Residual conocido (2
folios):** `22-0015271`/`22-0015571` reparten el gasto en 2 centros de
costo cada uno — el rank-pairing por `(Pl_Folio, Referencia)` (sin CECO en
la llave, porque `Gr_Referencia` no trae centro) no los desagrega
correctamente. No investigado a más detalle — volumen bajo (2/47).

**Pendiente que queda abierto:**
- Los ~13 folios que aún no cuadran en el run completo de `12` (mezcla de
  huecos reales de datos ya documentados + estos 2 residuales) — no se
  investigó folio por folio.
- Evaluar si migrar la reconciliación de `CONSUMO_INTERNO` completo (no
  solo la rama de activo fijo) a `Consumo_Interno`/`Consumo_Interno_Ceco`
  como fuente operativa, ya que es la fuente real del motor — hoy se usa
  `Gasto_Registro_Control` por inercia del resto del proyecto, funciona
  porque las cifras coinciden, pero no se confirmó que coincidan siempre.
- Aplicar el mismo tipo de verificación (leer `Poliza_Configuracion`
  directamente en vez de inferir el join por prueba y error) a los otros
  orígenes de este proyecto antes de asumir que sus joins actuales son
  definitivos.

## 2026-09-09 — CONT-6: promoción de `adjuntar-xml/04` a Streamlit (grano documento/`Grd_ID`, XML adjunto)

Origen: pregunta de usuario sobre si ya existía un reporte tipo CONT-2 a
grano folio/`Grd_ID` para adjuntar XML. Respuesta: no como Streamlit — solo
como scripts de exploración (`adjuntar-xml/04_conciliacion_mpro_vs_xml.py`,
el más maduro; `16`/`17` de este directorio, acotados al universo CECO).

**Elegido `04` de `adjuntar-xml`** por ser el más completo: cubre los 7
módulos de MPro que reciben CFDI de proveedor (no solo `Gasto_Registro`),
cuadra a nivel de **grupo** (componente conexa documento↔XML, no documento
suelto — un CFDI puede repartirse en N documentos), deduplica el bug de
formato doble de `Cd_Documento`, y clasifica el "sin XML" con motivo real
(`CLASE`) en vez de un simple sí/no.

**Choque de nombre**: `CONT-4` ya existe en este mismo venv
(`3_CONT-4_Layout_Gastos_por_Documento_XML.py`), pero es un reporte
distinto y más limitado (grano documento, solo config `0450`, vía
`reconstruir_config()`). Se decidió con el usuario **no tocar CONT-4/CONT-5**
y usar **CONT-6** para este nuevo reporte.

**Implementación**:
- `xml_documento_lib.py` (nuevo) — `reporte_completo(fi, ff)`, extraída de
  `construir()` de `adjuntar-xml/04_conciliacion_mpro_vs_xml.py` sin
  cambios de lógica. Importa `adjuntar-xml/conciliacion_xml_lib.py` por
  `sys.path` (proyecto hermano, ~850 líneas de parseo de CFDI/agrupamiento
  — import cruzado, no duplicado, mismo patrón que
  `poliza_configuracion_lib.py` ya usa para conexiones).
- `reporte_ui_xml_documento.py` (nuevo) — UI: sidebar (Periodo, Origen,
  Clase, Buscar), KPIs (Documentos, % con XML, % concilia de los que
  tienen XML, pendiente real), tabs Datos/Cobertura (semáforo por
  `CLASE`, tablas de `SIN_XML_PENDIENTE` y `CON_XML_DIF_MATERIAL`)/
  Documentación.
- `pages/8_CONT-6_Layout_Gastos_por_Documento_con_XML.py` (nuevo) —
  wrapper delgado, patrón idéntico a CONT-1/2/4/5.
- `streamlit_app.py` — tarjeta CONT-6 agregada al home.

**Validado con `AppTest`** (obligatorio por el skill
`trivasa-streamlit-reportes` antes de dar por bueno un reporte): carga sin
excepción, métricas de enero 2026 coinciden exacto con el CSV original de
`04` (12,037 docs, 2,616 con XML 21.7%, 93.5% concilia, $344,721,698.78
total, 992 pendiente $66,704,504.13); interacción de los 3 filtros
(Origen, Clase, Buscar) sin excepción, incluido el caso borde de 0 filas
tras un filtro que no matchea nada.

**Pendiente**: investigar a fondo `CON_XML_DIF_MATERIAL` (el residual real
sin explicar, ver siguiente entrada de esta misma fecha).

## 2026-09-09 (continuación) — `CON_XML_DIF_MATERIAL` investigado: ~49% del importe tiene causa estructural identificada, no es ruido

Universo: 270 filas / $9,557,036.77 (enero+febrero 2026 combinados, CSV de
`adjuntar-xml/04`). Se investigó explotando la columna `UUIDS` de cada fila
y buscando el mismo UUID repetido bajo **`GRUPO` distinto** — la firma de
que la componente conexa (`asignar_grupos()`/`cerrar_universo()`) no fusionó
documentos que en realidad son la misma operación real.

### Causa 1 — componente conexa que no cruza fronteras (mes / módulo): 31 UUID, 68 grupos, **$4,703,325.86 (49.2%)**

Tres variantes del mismo patrón raíz, todas con la firma inconfundible de
que **el mismo `DIF_GRUPO` (a veces al centavo) se repite en dos grupos
distintos**:

1. **Cheques que liquidan con un REP (complemento de pagos) compartido
   entre exhibiciones de meses distintos.** Cada corrida de `04` es
   mensual — solo ve el universo de ese mes, así que si el REP también
   liga a un cheque del mes siguiente/anterior, cada corrida cuenta el
   REP completo por su cuenta. Caso real confirmado con XML parseado:
   UUID `2F027671-...` (REP, `XML_TIPO='P'`, `XML_PAGOS_MONTO=$674,963.39`)
   ligado a `Cheque 01-0086348` (enero, `$1,349,926.80`) **y**
   `Cheque 01-0086789` (febrero, `$2,474,865.81`), mismo proveedor "JJ
   REMOLQUES EN RENTA" — `DIF_GRUPO = $674,963.39` idéntico en ambos.
   **Diagnóstico completo 2026-09-09**: cada cheque tiene además su PROPIO
   REP que cuadra exacto centavo a centavo (`48354EA4-...`=$1,349,926.80
   para el de enero, `9EA4410C-...`=$2,474,865.81 para el de febrero) — el
   problema es únicamente el tercer REP (`2F027671-...`) que MPro capturó
   ligado a los DOS cheques a la vez, cuando por sus propios documentos
   relacionados (`XML_DR_UUIDS`) parece pertenecer a un tercer pago no
   identificado. **Es un dato duplicado en la captura de MPro, no un error
   de este reporte** — candidato a reportar a soporte TIC/Contabilidad si
   se quiere corregir en origen. Otros casos del mismo patrón: `MATERIALES
   DEZA` (3 cheques, 2 meses), `TRITURADORA... SANTA ANITA` ($904,311.91).
2. **`Cuenta_X_Pagar` que consolida muchos folios chicos de
   `Gasto_Registro`/otros módulos bajo un solo CFDI** — mayormente
   proveedor genérico `0000000021` (7 UUID distintas, 6-13 folios cada
   una). El grupo de la CXP y el grupo de los `Gasto_Registro` que
   consolida **no se fusionan** pese a compartir UUID — aparecen como
   `CUENTA_X_PAGAR:01-0095256` y `GASTO_REGISTRO:01-0035307` (esta
   segunda etiqueta es engañosa: el folio `01-0035307` tiene formato de
   CXP, no de `Gr_Folio` — el nombre del grupo lo pone `asignar_grupos()`
   tomando un miembro cualquiera de la componente). Montos chicos por
   caso (~$50-$580), pero se repite en 7 instancias distintas.
3. **`COMPRA` ↔ `GASTO_REGISTRO` y `COMPRA` ↔ `COMPRA_INDIRECTO`, mismo
   CFDI, dos módulos.** 6 pares con `TOTAL`/`DIF_GRUPO` literalmente
   intercambiados entre las dos filas (ej. UUID `0004B4C1-...`: `COMPRA
   07-0010617` trae `TOTAL=$1,705.20, DIF=$870.00` y `GASTO_REGISTRO
   07-0082019` trae `TOTAL=$870.00, DIF=$1,705.20` — la misma operación
   capturada en dos módulos, cada uno viendo solo la mitad).

### Causa 2 — CFDI de organismos de gobierno (IMSS/INFONAVIT/Secretaría de Administración y Finanzas) con Total mayor al registrado — **hipótesis de "factura consolidada" investigada, NO se cierra limpio (corregido 2026-09-09)**

Proveedores `0000006355`/`0000006354` (recurrente enero **y** febrero,
mismo par, mismos montos aprox.), `0000001253`/`0000001256` (IMSS/INFONAVIT)
y `0000000345` (Secretaría de Administración y Finanzas) muestran
`XML_GRUPO` 2-4x más grande que `MPRO_GRUPO` en forma `1:N`/`N:M`.

**Confirmado con drill-down real** (folio `01-0035538`, cuotas IMSS/INFONAVIT
de sucursal `0001`, corte 2026-02-28): el CFDI del IMSS (UUID `E9D53EB5-...`,
RFC emisor `IMS421231I45` — coincide con el RFC real del IMSS) trae
`Total=$2,329,828.61`, contra solo `$806,484.72` registrados en este folio
— y el de INFONAVIT (`5E1E75B6-...`, RFC `INF7205011ZA`) trae
`$1,087,142.92` contra `$350,326.93` registrados. **Cada UUID está ligado a
UN SOLO documento de `Gasto_Registro`** (confirmado consultando
`Comprobante_Digital` sin filtro de tabla/fecha) — no es el mismo bug de
UUID compartido entre documentos que la Causa 1.

**Se probó la hipótesis obvia — sumar todas las sucursales del mismo corte
— y NO cierra**: cuota IMSS de las 6 sucursales activas el 28-feb-2026 suma
$814,789.94 (vs. CFDI $2,329,828.61). Sumando también SAR ($155,184.52) y
Cesantía y Vejez ($551,885.39) — los otros 2 conceptos de la misma familia
de proveedor IMSS — el total sube a solo $1,521,859.85: **sigue faltando
~$807,968.76**. Ampliar la ventana a enero-marzo completo tampoco cierra
(la cuota IMSS sola ya suma $2.72M en 3 meses, más que el CFDI completo,
así que "sumar más meses" tampoco es la respuesta).

**Catálogo de proveedores identificado en el camino** (útil para futuras
exploraciones de nómina/gasto de personal, mismo RFC salvo INFONAVIT):
`0000001253`=Cuota IMSS, `0000001254`=SAR, `0000001255`=Cesantía y Vejez,
`0000001262`=Ret. Créd. INFONAVIT (vía nómina, sin movimiento este periodo),
`0000001256`=INFONAVIT Aportación Patronal (RFC `INF7205011ZA`).

**Conclusión: NO se confirma el patrón de `CONTROL_COMBUSTIBLE`** (ahí sí
cerraba exacto sumando los folios reales ligados al mismo UUID, porque el
UUID SÍ se repetía entre folios). Aquí el UUID no se repite — el CFDI
simplemente es más grande que la suma de lo que Trivasa tiene capturado en
`Gasto_Registro` bajo esos proveedores/fechas, por una razón que no se pudo
determinar con datos (¿recargos/actualizaciones del IMSS? ¿otra razón
social del grupo? ¿un periodo de pago que no coincide con el corte
contable?). **Requiere preguntarle a Contabilidad qué representa
exactamente ese pago** — no es un caso que se resuelva con más SQL.

### Resto sin explicar: 138 filas, $4,853,710.91 (50.8%)

No investigado a más detalle. Incluye casos genuinamente raros que valdría
la pena revisar con Contabilidad: `Cheque 01-0086879` a "TOKA INTERNACIONAL"
capturado con `Ch_Importe=$0.01` pero XML real de $181,609.16 (probable
cheque simbólico + REP real, patrón similar al de RETENCIONES ya
documentado); `Cheque 01-0087231` con signo invertido (`MPRO_GRUPO >
XML_GRUPO` por $191,458.97, el único caso grande en esa dirección).

**Conclusión práctica:** el residual `CON_XML_DIF_MATERIAL` no es ruido
aleatorio de datos — casi la mitad de su importe tiene causa estructural
identificada (límite del algoritmo de agrupación de `conciliacion_xml_lib.
asignar_grupos()`/`cerrar_universo()`, que no fusiona componentes que
cruzan meses o módulos para la misma transacción real). **No se corrigió
el código** — es un cambio de alcance no trivial (requeriría correr la
detección de componentes sobre un universo multi-mes, o resolver
explícitamente la cadena CXP→origen dentro de `asignar_grupos()`, no solo
en la clasificación de `04`) y no se pidió en esta sesión.

**Pendiente**:
- Decidir si vale la pena generalizar `cerrar_universo()` a un universo
  multi-mes (o correr `04`/CONT-6 sobre rangos más amplios en vez de mes a
  mes) para que estos grupos se fusionen solos.
- Usar la cadena `resolver_cadena()` (ya existe en `xml_documento_lib.py`,
  usada solo para clasificar `SIN_XML_CFDI_EN_ORIGEN`) también dentro de
  `asignar_grupos()`, para que CXP y su(s) `Gasto_Registro` de origen caigan
  en el mismo grupo por diseño, no por coincidencia de UUID.
- ~~Drill-down real de la Causa 2 (proveedores `0000006355`/`0000001253`)
  para confirmar que es el mismo patrón de `CONTROL_COMBUSTIBLE`~~ — hecho
  2026-09-09, **no se confirmó** (ver esa sección: sumar sucursales/
  conceptos/meses no cierra la diferencia). Preguntar a Contabilidad qué
  representa el pago real detrás del CFDI de IMSS/INFONAVIT del folio
  `01-0035538` (y por extensión, del patrón `0000006355`/`0000000345`,
  no investigados con el mismo nivel de detalle).
- Investigar los 2 casos de signo/monto raro (`TOKA INTERNACIONAL`,
  `TRITURADOS DE VALLADOLID`) con Contabilidad directamente.

## 2026-09-09 (continuación) — CONT-6 v2: acotado a `Gasto_Registro`, formato tipo CONT-2, UUID + visor de CFDI legible

Corrección de alcance pedida por el usuario tras ver la v1 (que cubría los
7 módulos de MPro, igual que `adjuntar-xml/04`): CONT-6 debía ser **una
versión de CONT-1/CONT-2** (mismo universo -- solo `Gasto_Registro`, 6-7
orígenes vía `Gr_Tabla`, incluyendo NOMINA), a grano `(FOLIO, DOC_ID)` en
vez de `(FOLIO, CECO, TIPO_GASTO)`, con **UUID/XML** en vez de
**Póliza/Cuenta/CECO** (ese detalle vive en `Poliza_Detalle`, un grano más
fino que este reporte no baja).

**Cambios**:
- `xml_documento_lib.reporte_completo()` acepta `origenes` (default los 7
  módulos, CONT-6 pasa `["GASTO_REGISTRO"]`) -- un solo parámetro nuevo,
  sin duplicar lógica.
- `reporte_ui_xml_documento.py` reescrito estilo CONT-2: KPIs
  (Documentos/Folios/%con XML/%1:1/ΣTotal/Pendiente), filtro "Origen" ahora
  sobre `Gr_Tabla` (no sobre los 7 módulos), columnas de `Datos` alineadas
  a CONT-2 (`FOLIO, ORIGEN, DOC_ID, FECHA, ESTADO, PROVEEDOR, CONCEPTO,
  MONEDA, SUBTOTAL, IMPUESTOS, TOTAL, UUID, CLASE, FORMA, DIF_GRUPO`).
- Pestaña **Reconciliación** (nueva, reemplaza "Cobertura"): tabla
  `resumen_reconciliacion()` (nueva función en el lib) con N documentos,
  % con XML, % sin XML, % 1:1 del total y % 1:1 de los que tienen XML, por
  origen (`Gr_Tabla`) -- exactamente la tabla que el usuario pidió ver
  aquí. Debajo, el semáforo por `CLASE` que ya existía.
- Pestaña **Ver CFDI** (nueva): busca un UUID (selector sobre los datos
  filtrados, o texto libre) y muestra el CFDI **parseado y legible**
  (`conciliacion_xml_lib.parsear_cfdi`) -- emisor, tipo, fechas, montos,
  y si es REP el monto real pagado -- en vez de aventar el XML crudo (que
  queda disponible en un expander aparte, "avanzado"). No hay URL pública
  para "linkear" al XML (no es un dato expuesto fuera de TRIVASADB3), así
  que este visor in-app es el equivalente práctico.

**Validado con `AppTest`** de nuevo tras el cambio: 7,519 documentos en
enero 2026 (coincide con el subtotal ya medido antes para
`ORIGEN=GASTO_REGISTRO`), filtro por origen (`CONTROL_COMBUSTIBLE` aislado:
384 docs, 100% con XML, 0.3% 1:1 -- coincide con el patrón de factura
consolidada ya documentado), y el visor de CFDI sigue encontrando el UUID
de prueba (REP de JJ Remolques) tras el cambio de universo.

**Desplegado** -- el proceso de Streamlit de este venv ya corría en
`0.0.0.0:8506` (PID persistente desde 2026-09-04); como los archivos son
leídos directo del disco (no hay build/Docker de por medio), los cambios
quedan disponibles de inmediato para sesiones nuevas del navegador.

## 2026-09-11 -- HITO: construido el layout de 60 columnas del Word (requerimiento original de Contabilidad), scripts `18`-`25`

Hasta ahora este directorio resolvía la reconciliación Cargo/Abono por
CECO (base de CONT-1/CONT-2). Esta sesión retomó el objetivo original que
le da nombre al proyecto padre (`layout-gastos`): el requerimiento real de
Contabilidad para la auditoría externa trimestral (Bates y Asociados),
transcrito en `layout_gastos_60col/legado/layout-gastos-streamlit-claude/
docs/00_requerimiento.md` (rescatado de `~/backups/`, nunca antes leído
completo por ninguna sesión de este repo). Alcance del Word: solo
`GASTO_REGISTRO`, excluye `CONSUMO_INTERNO`/`GASTO_REGISTRO_NOMINA`
explícitamente (después ampliado, ver más abajo) -- dos vistas (detalle N
filas/folio, agrupada 1 fila/folio salvo 2+ cuentas), criterio de
aceptación cuantitativo: **suma de Cargo/Abono == reporte nativo de
gastos**.

### Hallazgo central: `reconstruir_config()` resuelve un problema que este entregable no necesita

El script `18_generalizar_reconstruccion_configs.py` (nuevo) generalizó
`reconstruir_config()` (14/15/`poliza_configuracion_lib.py`) de la config
`0450` a las 44 configs reales de los 5 orígenes del Word -- **99.74%/
99.39% de cobertura (folios/Cargo $)**, **100.00% exacto** aplicando la
regla de reversión ya conocida. En el camino se corrigió un bug real en
`poliza_configuracion_lib.reconstruir_config()`: `Pcd_Condicion` vacío
(renglón sin condición extra, caso válido) se envolvía como `()`, SQL
inválido -- fix de una línea (`cond_sql = r.cond if r.cond.strip() else
"1=1"`), aditivo, sin riesgo para `0450`. Con eso, cruzado contra
rank-pairing (`layout_gastos_lib.py`, producción de CONT-1/2): **100%
coincide** donde ambas técnicas tienen dato.

Pero al revisar el requerimiento completo, **`reconstruir_config()`
resuelve un problema que el Word no pide**: atribuir cada línea de póliza
a su `Tipo_Gasto` de origen (algo que sí necesita CONT-1/2 para poder
reportar esa columna, pero el Word nunca la pide). Sin esa necesidad, el
**JOIN DIRECTO** a `Poliza_Detalle` por `Pd_Referencia = Gr_Folio`
(idéntico a `layout_gastos_60col/legado/layout-gastos-pasos/docs/queries/
gastos/v03_detalle_cuenta_centro_costo.sql`, ya "100% reconciliado" según
`RESUMEN_CASOS.md`) da Cargo/Abono exactos, sin ambigüedad, leyendo
`Pd_Tipo` directo -- **sin rank-pairing y sin la regla de reversión**
(esa regla existía solo para compensar que `reconstruir_config()` no lee
`Pd_Tipo`). Confirmado con un folio de reversión real (`01-0035793`,
$100,000): 2 líneas reales en `Poliza_Detalle`, una Cargo (Provisión, sin
CECO) y una Abono (Honorarios, con CECO) -- el propio `CONCEPTO_POLIZA`
dice "PROVISION HONORARIO C.E. **NEGATIVO**", dato que no teníamos antes.

**Además, `reconstruir_config()` no podía cubrir `GASTO_RECLASIFICACION`
completo** -- solo reconstruye renglones tipo Cargo de la config `0371`,
nunca el lado Abono del par espejo. El join directo captura ambos lados
sin ningún caso especial (confirmado: Cargo-Abono da $0.00 exacto para
los 44 folios de este origen).

`reconstruir_config()`/script `18` **no se descarta** -- queda como
cross-check independiente ya hecho, no como fuente. Nuevo script:
`24_bloque_poliza_directo.py`.

### Los 4 bloques del layout, cada uno un script nuevo

- **`19_bloque_impuestos.py`** (columnas 19-40) -- adaptado de
  `layout-gastos-pasos/docs/queries/gastos/v5_impuestos_layout.sql`.
  Hallazgo: comparar contra `TOTAL` (`Grd_Precio_Neto_Importe`, YA
  incluye IVA) da **0% de cuadre** en `CONTROL_COMBUSTIBLE`/`VIAJE`/
  `ORDEN_COMPRA` -- el Cargo real se postea NETO de IVA (el IVA
  acreditable va a su propia cuenta). Corregido comparando contra
  `SUBTOTAL_NETO` (`Grd_Precio_Descontado_Importe`, mismo campo que
  `IMPORTE_FOLIO_SQL`): **99.98%** (4,258/4,259, ene-mar), el único
  residual es el ya conocido límite de rank-pairing en `COMPROBACION_
  GASTO` (fondo fijo/82 CECOs). **Validado contra el reporte NATIVO de
  MPro** (no algo que derivamos nosotros): enero 2026, 5 orígenes del
  Word, coincide exacto ($0.00 de diferencia) contra
  `gastos_por_documento_enero_26.xlsx` documentado en
  `layout-gastos-pasos/README.md` (Paso 1/2) -- 1,425 folios,
  SUBTOTAL_NETO $22,283,791.24, IMPUESTO $1,084,277.23, TOTAL
  $23,368,068.46. Flag `--verificar-baseline-enero2026` para re-correr
  este chequeo como prueba de regresión.
- **`21_impuestos_por_ceco.py`** -- baja el bloque impuestos de grano
  FOLIO a grano FOLIO×CECO usando `Gasto_Registro_Control.Grc_Factor`
  (campo NATIVO de peso, confirmado que suma 1.0 exacto por documento,
  desde 1 centro hasta 79) en vez de repetir el total de folio en cada
  línea de CECO -- necesario para poder sumar impuestos a cualquier
  nivel de agregación sin inflar (19.3% de los documentos, 1,033 de
  5,340, se reparten en 2+ centros).
- **`22_bloque_proveedor_pago.py`** (columnas 1-18) -- adaptado de
  `etapa6_columnas_1_18.sql`. 91.8%-100% de cobertura, consistente con
  agosto. **Hallazgo real, sin corregir todavía**: `MONTO_COBRADO`
  infla **41.6%** ($8.73M de $21M, enero-marzo) cuando un `Cxp_Folio`
  se comparte entre varios folios (factura consolidada, hasta 31
  folios bajo el mismo pago -- mismo patrón de `CONTROL_COMBUSTIBLE`/
  `GASTO_DIRECTO` ya documentado en otro contexto) -- sumar por folio
  cuenta el mismo pago real una vez por cada folio que lo comparte.
  Decisión explícita: dejarlo así por ahora (no prorratear ni marcar),
  documentado como pendiente.
- **`23_bloque_xml_concepto.py`** (columnas 41-52, 44-46) -- adaptado
  de `uuid_factura.sql`/`xml_detalle.sql`/`concepto_y_uso_cfdi.sql`.
  Match `Cd_Documento LIKE folio+'%'` (comodín amplio, sin filtrar por
  `LEN`) -- **no hereda el bug de formato 14/18** que sí afectaba a
  `poliza_configuracion_lib.xml_gasto_registro()`.
- **`25_consolidado_final.py`** -- une los 4 bloques por `FOLIO`
  (impuestos también por `CECO`) sobre el grano de detalle real
  (`FOLIO x POLIZA x CUENTA x CECO`). 52 columnas. Confirmado con el
  usuario: **un solo reporte basta**, no hace falta partir en dos por
  grano distinto, siempre que cada bloque se pueda atribuir
  correctamente al grano más fino (que es justo lo que se logró con
  `Grc_Factor`).

### Ampliación de alcance: `GASTO_REGISTRO_NOMINA` + `CONSUMO_INTERNO`

Después de cerrar el alcance original del Word, se amplió a los 7
orígenes completos.

**`GASTO_REGISTRO_NOMINA`**: funciona **sin ningún cambio** en el join
directo -- 99 folios/$10,590,952.94 en enero 2026, exacto contra el
`$10.59M` ya documentado en `layout-gastos-pasos/README.md`. Investigado
a fondo por qué `MONTO_COBRADO`/UUID salen vacíos (esperado, pero no
confirmado hasta ahora):
- `Gr_Genera_Cxp = 'NO'` en el 100% de los folios de nómina -- bandera
  nativa del sistema, nómina no pasa por CXP por diseño (se paga por
  dispersión bancaria directa, un proceso separado).
- `CLAVE_PROVEEDOR`/`RFC_PROVEEDOR` en nómina **no son un proveedor
  real** -- son 4 cuentas de pasivo placeholder (`SYP - SUELDOS Y
  SALARIOS POR PAGAR`, `VACACIONES POR PAGAR`, `VALES DE DESPENSA POR
  PAGAR`, `AGUINALDOS POR PAGAR`), las 4 con el RFC genérico
  `XAXX010101000` ("público en general"). Documentar esto explícito en
  cualquier entregable -- fácil de confundir con un proveedor real.
- **`Comprobante_Digital.Cd_Tabla='NOMINA'`** (69,766 filas totales)
  **dejó de alimentarse en 2022** (`MAX(Cd_Timbre_Fecha) = 2022-12-31`,
  cero registros después) -- confirmado buscando SIN restringir
  `Cd_Tabla` en absoluto contra 15 folios de nómina de enero 2026: los
  únicos "hits" son coincidencias falsas de número de folio con
  documentos de `CHEQUE`/`FACTURA`/`TRASLADO` de otros módulos/años
  (ej. `01-0034715` "matchea" un `CHEQUE` de 2021-11-22, folio de
  numeración independiente). **Conclusión: hoy (2026) la nómina se
  timbra en un sistema externo no integrado con esta base** -- el
  vacío de XML/UUID es correcto, no un hueco de la query.

**`CONSUMO_INTERNO`**: filtro de doble póliza (memo de inventario vs.
gasto real) igual al ya validado, por `Pl_Comentario` NOT LIKE
`'%CUENTAS DE ORDEN%'`/`'%CTS ORDEN%'`/`'%CUENTA ORDEN%'`. Se probó la
alternativa "más robusta" que quedaba pendiente en `trivasa-context`
(filtrar por raíz de cuenta `6xxx` en vez de comentario) -- **descartada**:
excluye 1,319 de 2,970 folios legítimos (muchas cuentas de gasto real de
este origen NO son raíz `6xxx`). El filtro de comentario, pese a su bug
conocido, es muchísimo más completo.

**Bug real encontrado, documentado, no corregido**: folio `05-0174748`
("LLANTA PONCHADA") tiene **4 pólizas reales** (configs `0274`/`0277`/
`0234`/`0396`), no 2 como asume el diseño memo/gasto-real. El filtro de
comentario excluye correctamente las 2 de memo (`10500.012.003`,
comentario con "orden"), pero **una tercera póliza tipo "Provisión"**
(`2120.010.004.005.002`, config `0274`, comentario "CONSUMO INTERNO
LLANTAS DEL..." -- sin la palabra "orden") se escapa y duplica el Cargo
real ($64.51 x2 = $129.02 en vez de $64.51). Probado también filtrar por
`Poliza_Configuracion.Pc_Descripcion` en vez de `Pl_Comentario` -- **no
resuelve nada**, la config `0274` tampoco menciona "orden" en su
descripción. Cuantificado a escala: **1 combinación (FOLIO,CECO) de
9,090 en todo ene-mar 2026** -- extremadamente raro, no vale la pena una
regla nueva para cerrarlo. **Corrige la documentación previa**: este
folio NO es uno de los "2-3 folios genuinamente sin póliza" que se
creía -- sí tiene póliza(s), el problema es de sobra, no de falta.

**Rama de capitalización de activo fijo, reincorporada** (configs
`0295`/`0414`, resuelta 2026-09-08 en `12_reporte_base_ceco_consumo_
interno.py` pero **nunca portada a producción** -- ni a `layout_gastos_
lib.py`/CONT-1/2, ni usada hasta ahora en este trabajo). `Pd_Referencia`
de estas pólizas es `Gasto_Registro.Gr_Referencia` (código corto de
proyecto, ej. "445"), no `Gr_Folio` -- el join directo nunca las
encuentra por sí solo (tampoco hay riesgo de doble conteo entre las dos
consultas). `Gr_Referencia` no es único dentro de una póliza -- se
resuelve con rank-pairing por `(POLIZA, REFERENCIA)`, la única excepción
al principio "sin rank-pairing" de este script, justificada porque aquí
sí falta una llave real (no hay forma de evitarlo, a diferencia de los
demás casos). Con la rama incorporada: `CONSUMO_INTERNO` enero 2026 pasa
de 2,950 a **2,970 folios exactos** (el número esperado), Cargo
$6,594,596.21 (esperado $6,594,522.55 -- diff $73.66, los 2 residuales ya
conocidos que reparten en más de 1 centro).

### Validación final, universo completo (7 orígenes)

Consolidado final (`25`) con los 7 orígenes, enero 2026: **CARGO-ABONO =
$39,469,326.09** vs. baseline nativo completo (`paso1`, incluye
NOMINA+CONSUMO_INTERNO) **$39,469,269.50** -- diferencia de solo **$56.59
(0.00014%)**, mismo redondeo de siempre (`Poliza_Detalle` postea
redondeado a centavos, los campos nativos de `Gasto_Registro_Documento`
no). Bloque impuestos, mismo universo: coincide **exacto a $0.00** contra
el mismo baseline en las 4 cifras (folios, SUBTOTAL_NETO, IMPUESTO,
TOTAL) -- confirma que NOMINA/CONSUMO_INTERNO aportan $0 de impuesto
(esperado, ninguno de los dos tiene IVA/retención).

CSV consolidado final: `layout_gastos_60col/CONSOLIDADO_<fi>_<ff>.csv`
(52 columnas, gitignored -- se regenera corriendo `25_consolidado_
final.py`). Gaps permanentes documentados, sin fuente identificada:
`FACTURA_REF`, `DESCUENTO`/`DESCUENTO_GLOBAL` (placeholder `NULL`, igual
que el legado).

**Pendiente real, sin cerrar**:
- `MONTO_COBRADO`: fan-out del `Cxp_Folio` compartido (41.6% de
  inflación) -- decidido dejarlo así por ahora, no prorratear.
- "2 órdenes de compra con doble cargo" (mencionado en
  `layout-gastos-pasos/paso4d_drill_down_4_pendientes_207.py`, agosto) --
  nunca se revisó en esta sesión.
- Vista **agrupada por cuenta contable** (1 fila/folio, la segunda vista
  que pide el Word) -- solo se construyó la vista detalle; la agrupada
  es un `groupby(FOLIO, CUENTA_REGISTRO)` sobre el mismo CSV, no
  debería requerir tocar la base de datos otra vez.
- Nota aclaratoria en el CSV/documentación de que `CLAVE_PROVEEDOR`/
  `RFC_PROVEEDOR`/`NOMBRE_PROVEEDOR` en filas de `GASTO_REGISTRO_NOMINA`
  son cuentas de pasivo placeholder, no un proveedor real -- pendiente
  de decidir si se agrega una columna/flag explícito o basta con la
  documentación.
