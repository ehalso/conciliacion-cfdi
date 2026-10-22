# app-conciliacion

Reporte web del layout de gastos con formato de póliza (una fila por cuenta
contable; los datos del folio solo en su primera fila). Atiende las 18
observaciones de Ismael sobre el reporteador. Estilo copiado del reporteador
web de Trivasa (Roboto 12px, naranja `#FF8000`).

| Archivo | Para qué |
|---|---|
| `build_reporte.py` | Consulta `.205/TRIVASADB3` y arma el DataFrame (`construir` + `post`). Genera `rep_<ini>_<fin>.pkl`. |
| `columnas.json` | Las 65 columnas (clave, etiqueta, grupo, tipo) y si son de nivel línea (`linea`) o solo de la primera fila del folio. |
| `exportar_datos.py` | Convierte el `.pkl` en `index.html` inyectando los datos en `plantilla.html`. |
| `plantilla.html` | Página única: tabla paginada (300 filas), chips por origen, buscador, KPIs, botón Exportar a Excel (SheetJS desde cdnjs; CSV si no carga). |
| `serve.py` | Sirve la carpeta con `http.server` en `0.0.0.0` y basic auth. |

## Uso

```bash
export MSSQL_205_USER=... MSSQL_205_PASSWORD=...      # ver layout_gastos_poliza/connection_205_trivasadb3.py
python3 build_reporte.py 2026-01-01 2026-02-01         # fin exclusivo -> rep_2026-01-01_2026-02-01.pkl
python3 exportar_datos.py rep_2026-01-01_2026-02-01.pkl  # -> index.html
APP_USER=... APP_PASS=... APP_PORT=8080 python3 serve.py # sin APP_PORT usa un puerto libre y lo imprime
```

`index.html` (≈6 MB) y los `.pkl` contienen datos financieros: están en
`.gitignore`, no se versionan.

## Notas

- Depende de los módulos `22_`, `23_`, `24_` y `21_` de `../layout_gastos_poliza/`.
- Subtotales e impuestos vienen a grano (FOLIO, CECO): se prorratean entre las
  líneas de póliza por peso para no duplicarlos.
- SQL Server `.205` no tiene `STRING_AGG`: se usa `STUFF(... FOR XML PATH(''))`.
- Pendientes: residuo de centavos por redondeo del prorrateo, descuento y
  factura de referencia sin fuente en BD, 14 de 28 claves de impuesto (solo las
  con movimiento en enero), GASOMATIC sin conciliar, y decidir si consumo
  interno (proveedor genérico "PROVEEDORES VARIOS") y nómina salen del reporte.
- El botón de Excel no funciona dentro de un artifact de claude.ai (el visor
  bloquea descargas); sí en el servidor.

## Reporte en vivo (BD .207)
`APP_USER=.. APP_PASS=.. APP_PORT=32838 python3 serve_vivo.py` — sirve `plantilla.html` y `/api/reporte?ini=&fin=[&vista=layout|ceco][&agrupar=0|1][&refresh=1]` consultando `.207/TRIVASADB` (credenciales por `trivasa-bi-core`, caché 10 min por periodo; el DataFrame se reutiliza al cambiar de vista). `exportar_datos.py <pkl>` sigue generando el HTML estático con datos incrustados.

## v2: tipos de documento y vistas

- **Tipo** (primera columna): `Gasto`, `Compra`, `Indirecto` (compra indirecta), `NC proveedor` (nota de crédito de proveedor), `CxP libre` y `CxP orden compra`. Los cinco últimos vienen de las consultas de auditoría RPTRV79 (`tipos_documento.py`; los dos de CxP son el reporte `05 cxp_libre`). No se traen columnas exclusivas de v3 (descuento, comprador, almacén, causa, estado, cantidad control…).
- La llave de documento es (Tipo, Folio): hay folios que se repiten entre tipos.
- Las NC de proveedor van en negativo (subtotales e impuestos); su póliza son abonos, así que cargo − abono cuadra con el subtotal neto.
- Póliza de compras: se filtra por `Pd_Referencia = folio` y se excluyen las líneas memo (10500/10600), impuesto (1170), proveedor (2110) y 2150, para que solo queden los subtotales.
- Subtotal neto ya viene neto de descuento.
- **Gasto totaliza igual que el reporte nativo RPAG008** (ene–sep 2026, empresa 0001: 42,452 / 42,452 documentos, diferencia de +$15.62 por redondeo del prorrateo por CECO). El Gasto se arma desde las líneas de póliza con CECO; `completar_gasto` (`build_reporte.py`) agrega las filas que la póliza no cubre: los (FOLIO, CECO) del reparto de `Gasto_Registro_Control` sin línea de póliza, y los documentos sin reparto ni póliza con CECO (CECO vacío, importes de `Gasto_Registro_Documento`). Esas filas llevan `CARGO = ABONO = 0`, así que el KPI "Documentos cuadrados" las marca como descuadradas. El emparejamiento de `CONSUMO_INTERNO` de activo fijo (`_emparejar_activo_fijo`, módulo `24_`) ya no se limita a una línea por folio cuando un folio se reparte en varios CECO.
- **Cuentas por pagar (CxP libre y CxP orden compra)**: ver la sección siguiente.
- **Vista Layout** (por defecto): subtotales, impuestos, TOTAL, XML_MONTO y MONTO_COBRADO solo en la primera fila del documento; las demás filas llevan folio/Tipo y los campos de póliza. Con "Agrupar por cuenta contable" (activo por omisión) las líneas de póliza se suman por cuenta (CECO = el único o `VARIOS`).
- **Vista Análisis por CECO**: el prorrateo de v1 (subtotales e impuestos repartidos entre las líneas de un CECO, TOTAL por línea).
- Las columnas sin ningún dato en el resultado no se envían (salvo Tipo, Folio, Fecha, Subtotal neto, Total, Cargo, Abono). Las claves `IMP_xxxx` nuevas se agregan solas.
- **Exportar a Excel**: encabezado (empresa, fecha inicial, fecha final, vista), fila de numeración 1..N, títulos con autofiltro y fila final `TOTAL` con `SUBTOTAL(109,…)` (respeta el filtro de Excel) en las columnas de importe.
- Ver `MEJORAS_FUTURAS.md` para lo pendiente de decidir.

## CxP libre y CxP de orden de compra

Ambas son registros de `Cuenta_X_Pagar` que **no** nacen de un documento Compra, Compra indirecta ni Gasto; se distinguen por `Cxp_Tabla`:

| Tipo en el reporte | `Cxp_Tabla` | Qué es |
|---|---|---|
| `CxP libre` | `Cuenta_X_Pagar` | CxP capturada directamente (facturas de arrendamiento, activos, servicios sin orden de compra, etc.). |
| `CxP orden compra` | `ORDEN_COMPRA` | Inversiones que se hacen desde una orden de compra, pero que en vez de generar un documento Compra generan una CxP. |

**No confundir** con la columna *Origen* `orden_compra` de los **Gastos**: ahí es un `Gasto_Registro` que se generó desde una OC y es del Tipo `Gasto`. Aquí es una CxP (Tipo `CxP orden compra`) y no tiene registro de gasto. En 2026 (ene–ago, empresa 0001) ninguna CxP de OC está referenciada por un gasto, y solo 2 CxP libres (05-0136733 y 05-0136734) lo están, vía su pago, por lo que no hay doble conteo.

Reglas (las del reporte 05 original, `rptrv79_05_cxp_libre*`):
- Fecha: `Cxp_Fecha`; se excluyen canceladas (`Es_Cve_Estado='CA'`) y se filtra por empresa de la sucursal.
- **No se excluye ningún concepto ni proveedor**, para que el layout totalice igual que el reporte nativo RPCXP08 (filtrado por `Cxp_Tabla`). El reporte 05 original sí excluía los conceptos `0023` (carga de glosa FONACOT), `0019` (depósitos en garantía), `0016` (primas de seguro y fianzas), `0017` (placas, tenencias y otros) y el proveedor `0000000021` (Control Integral de Combustibles) por no ser compras; ese criterio queda para la etapa de criterios de conciliación (ver `MEJORAS_FUTURAS.md`).
- Una fila por `Cxp_Folio` (único; los folios empiezan en `01-` o `05-`). Subtotal neto = `Cxp_Precio_Descontado_Importe × tipo de cambio`; total = `Cxp_Precio_Neto_Importe × tipo de cambio`; impuestos desde `Cuenta_X_Pagar_Impuesto` (`Cxpi_Importe`, por clave `Im_Cve_Impuesto`). Subtotal + impuestos = total en el 100 % de los documentos (ene–ago 2026).
- XML desde `Comprobante_Digital` (`Cd_Tabla='Cuenta_X_Pagar'`); pago desde `Pago_CXP` de la propia CxP.
- **Póliza**: una misma póliza puede cubrir varias CxP (en ene–ago, 40 de 93 pólizas), con líneas de otros documentos. Por eso solo se toman las líneas cuya `Pd_Referencia` es el folio de la CxP o su `Cxp_Referencia` (la factura), y se omiten las cuentas 1170 (IVA), 2110 (proveedores), 2150 (retenciones) y **2130 (documentos por pagar a corto plazo)**, que en estas CxP lleva abonos grandes que no son subtotal. Con ese filtro cargo − abono cuadra con el subtotal neto en las 205 CxP de ene–ago 2026 (108 libres + 97 de OC); sin excluir 2130 descuadran 9. Cuentas típicas del cargo: 1210 (propiedades, planta y equipo), 1250 (sistemas y licencias), 1150 (rentas en garantía).
- No se replica la corrección `aplicar_correccion_cuenta_registro` (búsqueda alterna por importe aproximado) del reporte 05 original.
