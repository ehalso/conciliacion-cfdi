# Cierre bloque 1-56 — Layout de Gastos (enero 2026)

**Fecha:** 2026-08-07
**Universo:** 1,425 folios, enero 2026, `.200/TRIVASADB3`, empresa `0001`
**Repo:** `layout-gastos-pasos` (reorganización en pasos lógicos, reemplaza
las exploraciones 1 y 2 previas)

## Resultado

El bloque 1-56 del layout de 60 columnas queda **completo y validado**.
Solo quedan pendientes las columnas 57-60 (Cuenta/Cargo/Abono), que viven
en un archivo aparte por tener grano distinto (ver sección de diseño).

Archivo final: `v7_reporte_maestro_1_40_enero2026.csv` (nombre heredado
del primer merge, contiene columnas 1-56, no solo 1-40).

## Cobertura por bloque

| Columnas | Bloque | Cobertura | Fuente |
|---|---|---|---|
| 1-6 | Operación/Fecha/Moneda/Proveedor | 100% | `etapa6_columnas_1_18.sql` |
| 7-10, 12-16 | Cobro/pago | 95.7% (1364/1425) | `etapa6_columnas_1_18.sql` |
| 11 | FACTURA_REF | 99.0% (1411/1425) | `factura_ref.sql` (nuevo, ver hallazgo) |
| 17-18 | Tipo/Número de comprobante | 91.8%-94.0% | `etapa6_columnas_1_18.sql` |
| 19-21, 24-40 | Subtotales/impuestos/retenciones | 100% | `v5_impuestos_layout.sql` |
| 22-23 | Descuento/Descuento Global | 0 explícito, gap real sin origen | `v5_impuestos_layout.sql` |
| 41-42 | UUID / UUID_4 | 92.8%/1.2%/6.0% | `uuid_factura.sql` (nuevo) |
| 43, 47-52 | Fecha Factura / XML detalle | 92.8%-94.0% | `xml_detalle.sql` (nuevo) |
| 44-46 | Concepto gasto / Uso CFDI | 100%/91.7%/91.7% | `uso_cfdi_por_folio.sql` (nuevo) |
| 53-56 | Póliza descriptiva | 99.3%-99.4% | `poliza_descriptiva.sql` (nuevo) |
| 57-60 | Cuenta/Cargo/Abono | 100% reconciliado, grano distinto | `v03_detalle_cuenta_centro_costo.sql`, aparte |

## Gaps reales que quedan (todo el layout de 60 columnas)

Solo **2**, ambos ya cerrados como decisión de diseño, no como pendientes:

- **Descuento / Descuento Global** (22-23): `CAST(0 AS money)` explícito.
  Sin origen identificado — coincide con el reporte del programador
  externo (`aaron_query/`), que también los deja hardcodeados en 0.
- No hay más gaps reales. `FACTURA_REF` (11), que estaba documentado como
  gap desde el wiki original, se resolvió esta sesión (ver hallazgo).

## Hallazgos de esta sesión

### 1. FACTURA_REF = `Grd_Referencia`

`Gasto_Registro_Documento.Grd_Referencia` — el mismo campo ya usado para
el match de CXP por referencia consolidada (combustible) — es también la
fuente de `FACTURA_REF`. No se había identificado antes porque se conocía
solo por su uso en CXP, no se había probado como candidato para esta
columna. 99.0% de cobertura, 20 folios "VARIOS" (múltiples documentos con
referencia distinta dentro del mismo folio — mismo patrón de dedup que
UUID/XML).

### 2. Catálogo `Uso_CFDI` existe en MPRO (no hace falta hardcodear el SAT)

Para la columna 46 (Descripción Uso bien o servicio) se sospechó que
había que mantener un diccionario Python del catálogo SAT `c_UsoCFDI`.
Existe en MPRO como tabla real: `dbo.Uso_CFDI` (`Uc_Cve_Uso_CFDI`,
`Uc_Descripcion`, + columnas de régimen fiscal aplicable). 24 filas,
confirmado que cubre el 100% de las claves que aparecen en los datos
reales de enero 2026 (`claves_sin_descripcion=0`). Se usa vía `JOIN` en
pandas, no en SQL — ver bug de driver abajo.

### 3. `Cd_Metodo_Pago` vs `Cd_Metdo_Pago_CFDI` — mismo dato, cobertura distinta

`Comprobante_Digital` tiene dos columnas de método de pago (`Cd_Metodo_Pago`
y `Cd_Metdo_Pago_CFDI`, con typo en la segunda). Confirmado con datos
reales: cuando ambas están pobladas, **coinciden 100%** (80,640/80,640).
`Cd_Metdo_Pago_CFDI` cubre 12,471 filas adicionales que `Cd_Metodo_Pago`
no tiene (contra solo 986 al revés) — se usa
`COALESCE(Cd_Metdo_Pago_CFDI, Cd_Metodo_Pago)` para máxima cobertura sin
riesgo de inconsistencia.

### 4. `Cd_Serie_Folio` (no `Cd_Factura`) es el folio real del XML

`Cd_Factura` está casi vacía (2/95,561 filas) — no es fuente de nada.
`Cd_Serie_Folio` es el folio numérico real (`398`, `3606`, etc.), ya usado
para `NUMERO_FACTURA` (columna 18) y reusado aquí para `XML_FOLIO` (50) —
son la misma columna con dos nombres de layout distintos, no dos datos.

### 5. Bug de driver: JOIN a tabla catálogo dentro de CTE anidado (pymssql/FreeTDS)

Un `LEFT JOIN Uso_CFDI` que funciona perfecto de forma aislada falla con
`Invalid column name 'Uc_Cve_Uso_CFDI'` cuando se anida como 4to CTE
dentro de una cadena de CTEs (`folios` → `uso_cfdi` → `uso_cfdi_agg` →
`uso_cfdi_con_desc`). Confirmado que la columna existe (schema real,
`SELECT *` funciona, join aislado funciona) — es un bug de resolución de
nombres del driver con CTEs profundos, no un problema de schema.
**Mitigación:** cuando se necesite un `JOIN` a tabla catálogo chica desde
dentro de una cadena de CTEs, resolver ese join en pandas después de traer
los datos, no dentro del SQL.

## Decisión de diseño: Cargo/Abono (57-60) queda aparte, no en el maestro

Cargo/Abono y Cuenta Registro tienen grano distinto al resto del layout
(N filas por folio — cuenta × centro de costo — contra 1 fila/folio en
todo lo demás). Se investigó reducir el grano:

- **"Cuenta sola" (sin centro de costo):** reduce folios de 1 línea de
  1,019 → 1,108 (de 1,425), pero **no colapsa del todo**. Folios de
  depreciación, seguros y prestaciones capitalizadas (IMSS/Infonavit/
  Retiro) siguen con 45-85 líneas — confirmado con datos reales
  (folio `0001-0035004`, 85 cuentas contables *distintas y legítimas*,
  no artefacto de centro de costo: cada combinación sucursal × tipo de
  activo es una cuenta contable real en el catálogo de MPRO).
- **Conclusión:** no existe un nivel de agregación que deje Cargo/Abono en
  1 fila/folio sin perder información contable real. Repetir los totales
  de CXP/Impuestos en cada línea contable (opción "columna de metadata",
  mismo patrón que `GRANULARIDAD_CXP` en v3.0) se descartó porque un folio
  de 85 líneas repetiría el mismo total 85 veces — riesgo real de que un
  consumidor sume por accidente y multiplique el monto.

**Diseño elegido:** dos archivos, mismo `FOLIO` como llave de unión:
- `v7_reporte_maestro_1_40_enero2026.csv` — 1 fila/folio, columnas 1-56.
- `v8_detalle_cuenta_enero2026.csv` — N filas/folio, columnas 57-60,
  reconciliado 100% contra `IMPORTE` del baseline (misma prueba que
  `paso4f`).

En el reporte final (destino: Streamlit, `explore.frento.com.mx`), el
detalle de cuenta contable se presenta como **fila expandible** por folio
(vía `streamlit-aggrid`, soporta master-detail nativo) — no como columnas
repetidas ni como archivo separado sin conexión visual.

## Scripts de esta sesión (`paso7` a `paso13`)

| Script | Qué agrega | Query nueva |
|---|---|---|
| `paso7_reporte_maestro.py` | Merge inicial 1-18 + 19-40 | — (reusa `etapa6_columnas_1_18.sql`, `v5_impuestos_layout.sql`) |
| `paso8_detalle_cuenta.py` | Detalle 57-60, archivo aparte | — (reusa `v03_detalle_cuenta_centro_costo.sql`) |
| `paso9_uuid_factura.py` | 41-42 | `uuid_factura.sql` |
| `paso10_concepto_uso_cfdi.py` | 44-46 | `uso_cfdi_por_folio.sql` |
| `paso11_xml_detalle.py` | 43, 47-52 | `xml_detalle.sql` |
| `paso12_poliza_descriptiva.py` | 53-56 | `poliza_descriptiva.sql` |
| `paso13_factura_ref.py` | 11 (ex-gap) | `factura_ref.sql` |

Investigación descartada pero documentada (no dejó script permanente):
`paso7a`/`paso7b_reconciliar_granularidades.py` (exploración de niveles de
agregación de Cargo/Abono, llevó a la decisión de diseño de arriba).

## Pendiente

1. Prototipar la vista Streamlit (maestro + detalle expandible).
2. Actualizar el wiki personal (`ehalsou`, `content/trivasa/layout-gastos/`)
   con este cierre — el wiki actual (`exploracion-2026-08-04.md`) quedó
   desactualizado desde antes de esta sesión (no reflejaba ni el cierre de
   Descuento ni la investigación de `Oc_ID`, y mucho menos este bloque
   1-56).
3. Escalar de enero 2026 a semestre completo, contra `.207`, una vez
   validado el prototipo con Ismael/Carlos.
