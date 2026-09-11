# Layout de gastos — 60 columnas (requerimiento original del Word)

Construido 2026-09-11, a partir del código legado rescatado en
`legado/` (ver `legado/README.md` para la procedencia completa: tres
proyectos previos de `~/backups/`, nunca antes revisados a fondo). El
requerimiento original completo está transcrito en
`legado/layout-gastos-streamlit-claude/docs/00_requerimiento.md` —
auditoría externa trimestral (Bates y Asociados), pedido de
Contabilidad. Alcance inicial: solo `GASTO_REGISTRO` (5 orígenes
normales), excluyendo `CONSUMO_INTERNO`/`GASTO_REGISTRO_NOMINA` — después
ampliado a los 7 orígenes completos (ver `layout_gastos_poliza/
PROGRESS.md`, entrada 2026-09-11, para el detalle completo de cómo y por
qué).

Los scripts que construyen este layout viven en `../layout_gastos_poliza/`
(numerados `18`-`25`, continuando la convención del directorio), no aquí —
esta carpeta solo guarda el código legado rescatado (`legado/`) y los CSV
de salida (gitignored, se regeneran corriendo los scripts).

## Scripts (en `../layout_gastos_poliza/`)

| Script | Bloque | Columnas del Word |
|---|---|---|
| `24_bloque_poliza_directo.py` | Póliza — join directo `Pd_Referencia=Gr_Folio`, sin rank-pairing | Fecha/Tipo/Número/Concepto de póliza, Cuenta Registro, Nombre Cuenta, Cargo, Abono |
| `19_bloque_impuestos.py` + `21_impuestos_por_ceco.py` | Impuestos, atribuidos por CECO vía `Grc_Factor` | Subtotal 0/16/exento, Subtotal Neto, IVA acreditable, Retenciones IVA/ISR |
| `22_bloque_proveedor_pago.py` | Proveedor/cobro/pago | Fecha, Moneda, Proveedor, Cobrado efectivo/cheque, Banco, Monto cobrado |
| `23_bloque_xml_concepto.py` | UUID/XML + Concepto/Uso CFDI | Núm. factura, UUID, Fecha factura, Tipo comprobante, datos XML, Concepto/Uso CFDI |
| `25_consolidado_final.py` | Une los 4 bloques por `FOLIO` (impuestos también por `CECO`) | Los 52 (de 60) campos con fuente identificada |
| `18_generalizar_reconstruccion_configs.py` | **Cross-check**, no fuente — valida el bloque póliza por una técnica independiente (`reconstruir_config()`, join real vía `Poliza_Configuracion`) | — |

Grano de salida: **detalle** (`FOLIO x POLIZA x CUENTA x CECO`), un solo
reporte — confirmado con el usuario que no hace falta partir en dos por
grano distinto, siempre que cada bloque se atribuya al grano correcto
(logrado con `Grc_Factor` para impuestos).

## Validación

Cada bloque se valida contra el **reporte nativo de MPro**
(`legado/layout-gastos-pasos/README.md`, Paso 1/2 — el Excel real
exportado del sistema, no algo derivado por nosotros), no solo
internamente:

- 5 orígenes del Word, enero 2026: 1,425 folios, SUBTOTAL_NETO
  $22,283,791.24, TOTAL $23,368,068.46 — coincide exacto.
- 7 orígenes (con NOMINA/CONSUMO_INTERNO), enero 2026: 4,494 folios,
  SUBTOTAL_NETO/IMPUESTO/TOTAL coinciden exacto a $0.00; Cargo−Abono
  ($39,469,326.09) vs. baseline ($39,469,269.50) — diferencia de $56.59
  (0.00014%, redondeo a centavos entre `Poliza_Detalle` y los campos
  nativos de `Gasto_Registro_Documento`, no un problema de datos).

## Pendiente conocido

- `MONTO_COBRADO` (bloque 22) infla ~41.6% cuando un `Cxp_Folio` se
  comparte entre varios folios (factura consolidada) — decidido dejarlo
  así por ahora, sin prorratear.
- `FACTURA_REF`, `DESCUENTO`/`DESCUENTO_GLOBAL` — sin fuente en el
  sistema, placeholder `NULL`.
- Vista **agrupada por cuenta contable** (segunda vista que pide el
  Word, 1 fila/folio) — solo se construyó la vista detalle.
- "2 órdenes de compra con doble cargo" (`legado/layout-gastos-pasos/
  paso4d_drill_down_4_pendientes_207.py`) — nunca revisado en esta
  sesión.
- Bug conocido y no corregido en `CONSUMO_INTERNO`: folio `05-0174748`
  duplica $64.51 (1 de 9,090 combinaciones FOLIO×CECO en ene-mar 2026) —
  ver `layout_gastos_poliza/PROGRESS.md` para el detalle completo.
