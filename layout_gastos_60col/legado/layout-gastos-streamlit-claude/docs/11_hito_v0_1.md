# Hito v0.1 — replica del reporte nativo "Facturas de gastos (por documento)"

Punto de partida más simple: reproduce el reporte nativo de MPRO (`RPAG008_99.asp`,
`Agrupar=99`, "FACTURAS DE GASTOS (POR DOCUMENTO)") a nivel `Gasto_Registro_Documento`
(`Gr_Folio` + `Grd_ID`), **sin** el detalle de póliza/cuenta contable que usan v1/v1.1.

## Validación contra export real de MPRO (enero 2026)

Insumos que dio el usuario: captura de pantalla del reporte en vivo, export a Excel
(`gastos_por_documento_enero_26.xlsx`, 7,043 filas, 4,494 folios únicos) y la URL exacta del
`.asp` que lo genera.

| Campo | Nuestro | MPRO (Excel) | Diferencia |
|---|---|---|---|
| Filas | 7,043 | 7,043 | 0 |
| Folios únicos | 4,494 | 4,494 | 0 |
| IMPORTE | $39,469,269.50 | $39,469,269.59 | $0.09 |
| IMPUESTOS | $1,084,277.23 | $1,084,277.29 | $0.06 |
| TOTAL | $40,553,546.72 | $40,553,546.79 | $0.07 |

Match estructural exacto (mismas filas, mismos folios); la diferencia de centavos es ruido
de redondeo repartido en 7,043 filas, no un error de lógica.

## Bug encontrado y corregido en el camino: falta multiplicar por tipo de cambio

Primer intento: **17 de 4,494 folios** no cuadraban, con diferencias grandes (hasta
$54,294 en un solo folio). Causa: `Gasto_Registro_Documento` guarda los importes en la
**moneda original** del documento (`Mn_Cve_Moneda`), no en pesos. El reporte nativo
multiplica por `Grd_Tipo_Cambio` para mostrar el equivalente en MXN.

Ejemplo verificado (folio `05-0175047`, "RENTA DE MONTACARGAS U-1269"): USD 3,201.60 ×
tipo de cambio 17.9587 = MXN 57,496.57 — exacto contra el Excel. Fix: multiplicar
`Grd_Precio_Descontado_Importe` / `Grd_Impuesto_Importe` / `Grd_Precio_Neto_Importe` por
`Grd_Tipo_Cambio` (=1.0 para MXN, no afecta esos registros). Tras el fix: 0 folios sin
cuadrar.

## Hallazgo importante para v1/v1.1 (columna `origen`)

El usuario pidió agregar una columna `origen` = `Gasto_Registro.Gr_Tabla`. Al revisar sus
valores para enero 2026 se encontró algo que **contradice un supuesto de
`layout_gastos_v1.py`**: `Gr_Tabla` puede venir como `'CONSUMO_INTERNO'` o
`'GASTO_REGISTRO_NOMINA'` — es decir, esos dos orígenes **sí generan filas dentro de
`Gasto_Registro`** (2,970 documentos / $6.59M y 2,250 documentos / $10.59M
respectivamente en enero 2026), contra el supuesto documentado en `layout_gastos_v1.py`
de que "anclar en Gasto_Registro los excluye automáticamente por estar en tablas
separadas". Ese supuesto era incorrecto -- `layout_gastos_v1.py` (usado por v1.1) **no
filtra por `Gr_Tabla` en ningún lado**, así que ha estado incluyendo estos dos orígenes
pese a que el requerimiento original (`docs/00_requerimiento.md`) pide excluirlos
explícitamente. Ver nota de seguimiento en `decisions/` (pendiente decidir si se corrige
v1.1 ahora).

`v0.1` **incluye todos los orígenes** (así es el reporte nativo) y expone `origen` como
columna filtrable — el usuario puede excluir `CONSUMO_INTERNO`/`GASTO_REGISTRO_NOMINA`
manualmente en la UI si quiere replicar el alcance de v1.1, o dejarlos si quiere el
reporte nativo completo.

## Columnas

`folio`, `fecha_registro` (`Gr_Fecha`), `fecha_documento` (`Grd_Fecha`), `referencia`,
`proveedor_clave`, `proveedor_nombre`, `comentario`, `moneda`, `tipo_cambio`, `importe`,
`impuestos`, `total` (los 3 últimos ya en MXN), `origen` (`Gr_Tabla`), `tiene_comprobante`,
`uuid`.
