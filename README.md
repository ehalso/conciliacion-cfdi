# conciliacion

Reporte web de gastos, compras, compras indirectas, notas de crédito de proveedor y cuentas por pagar de Mpro,
con layout de póliza (una fila por cuenta contable; las cifras del folio solo en su primera fila) y exportación a Excel.

> El código anterior (scripts por carpeta, pipeline CFDI vs Mpro, Streamlit) quedó únicamente en el tag **`v2.2`**:
> `git checkout v2.2`.

## Estructura

```
conciliacion/
  config.py       variables de entorno -> Mpro, Servidor
  db.py           engine SQL Server, consultas, tablas temporales
  sql.py          todas las consultas SQL
  gasto.py        armado del Gasto (póliza + reparto por CECO)
  documentos.py   Compra, Indirecto, NC proveedor, CxP libre, CxP orden compra
  posproceso.py   cargo/abono, prorrateo, totales, catálogos SAT
  reporte.py      construir(engine, fi, ff) -> DataFrame unificado
  resumen.py      DataFrame -> resumen SAT vs Mpro por tipo de CFDI y lista de diferencias
  vista.py        DataFrame -> JSON de la interfaz (layout / ceco, agrupado por cuenta)
  servidor.py     http.server con auth básica, caché por periodo (con precalentado del periodo por defecto y el mes en curso), /api/reporte, /api/estado y /api/actualizar
  static/         index.html (SheetJS) y columnas.json
tests/            pruebas unitarias de las funciones puras
docs/             reglas de negocio y mejoras futuras
```

## Uso

```bash
pip install -e .            # pandas, sqlalchemy, pymssql
export MPRO_HOST=... MPRO_DB=... MPRO_USER=... MPRO_PASSWORD=...
export APP_USER=... APP_PASS=... APP_PORT=8080 TTL_SEG=600
python -m conciliacion      # sin APP_PORT usa un puerto libre y lo imprime
```

API: `/api/reporte?ini=YYYY-MM-DD&fin=YYYY-MM-DD[&vista=layout|ceco][&agrupar=0|1][&refresh=1]`
(`fin` exclusivo, máximo 366 días). Los datos son financieros: nada se escribe a disco.

## Cruce con el SAT (BM:CB)

Con credenciales de Postgres (`SAT_PG_USER`/`SAT_PG_PASSWORD` o `POSTGRES_DW_RO_USERNAME`/`PASSWORD`; host/puerto/base por `SAT_PG_HOST`/`SAT_PG_PORT`/`SAT_PG_DB`, por omisión `localhost:5433/trivasa_dw`; sin respaldo: las credenciales viven en el `.env` del servicio, tomadas de Infisical) el reporte agrega dos grupos de columnas cruzando por UUID contra `raw_sat_api.cfdi` (RECIBIDO y los autoemitidos, que en `tipo` llegan como EMITIDO con emisor = receptor; cancelados desde `raw_sat_api.cancelados`):

- **Base de datos SAT**: UUID, serie, folio, estatus, tipo de CFDI, fecha, concepto (primera descripción del XML), RFC y nombre del proveedor, importe y "No localizados" (vacío, pendiente de definir).
- **Conciliación SAT**: existe en Mpro, existe en SAT, coincide existencia y coincide importes (`XML_MONTO` vs importe SAT, tolerancia 0.05).

**Solo SAT:** además se agregan, con Tipo "Solo SAT", los CFDI recibidos vigentes (no cancelados) del periodo, por fecha del CFDI, cuyo UUID no existe en `Comprobante_Digital` de Mpro (cualquier módulo y fecha de registro). Solo llevan el bloque SAT y la conciliación (Existe en Mpro = No, en SAT = Sí, existencia = No, importes = No); el folio es `SAT-<inicio del UUID>`.

La sesión a Postgres es de solo lectura. Si no hay credenciales o el SAT falla, el reporte sale sin esas columnas (`meta.sat = false`).

## Ventas y cobranza (emitidos)

Selector "Recibidos / Emitidos" junto a las pestañas Detalle/Resumen (`/api/reporte?...&sentido=recibidos|emitidos`; por omisión recibidos). El layout de emitidos usa las mismas columnas que recibidos, adaptadas a cliente (las columnas de proveedor se rotulan "Clave cliente", "RFC cliente", "Cliente"):

- **Venta**: `Factura`/`Factura_Impuesto` (CFDI emitido tipo I). Póliza `Pc_Tabla='VENTA'`, ligada por `Fc_Documento` (o `Fc_Folio` si está vacío), ventana de ±45 días por reciclaje de folios, solo pólizas activas; las líneas de ingreso se ligan por `<Fc_Serie><folio de serie a 10 caracteres>`.
- **NC cliente**: `Nota_Credito`/`Nota_Credito_Impuesto` (CFDI emitido tipo E), importes con signo negativo. Se excluyen las cuentas 1120, 2140, 1140 y 5100 (inventario, costo, anticipos).
- **Cobranza**: complemento de pago emitido (CFDI tipo P) desde `Pago_Parcial` (un renglón por factura pagada; `Pp_Folio` = `Cd_Documento` del `COMPROBANTE_PAGO`). Periodo por la fecha del pago en Mpro (`Pp_Fecha`), sin cancelados. Un documento por folio (si paga varias facturas: sumas y "VARIOS"); subtotal/IVA/total del pago de `Pp_SubTotal`/`Pp_Impuesto`/`Pp_Total` y grupo "Factura pagada" (factura, UUID, parcialidad, saldos). Los PXC (pago sin timbrar) salen sin UUID ni póliza. Póliza: `Pc_Tabla='PAGO_CXC'` (documento = `Cxc_Folio`+`Pc_ID`), una "COBRANZA DEL <día>" con todos los cobros; el cargo a bancos es único por recibo y se muestra en el primer cobro del recibo, y el abono a clientes (1120) se asigna al cobro de importe más cercano (±0.05). El IVA de esa póliza va agregado por día, no por documento. Forma de pago: descripción de `Forma_Pago` (claves propias de Mpro, no SAT). En el SAT el monto de un P es `pagos_monto_total`.
- Impuestos de venta: 0006 IVA 16 %, 0007 tasa 0, 0008 exento.
- Cruce SAT contra `tipo = 'EMITIDO'` (las columnas "RFC/Nombre del cliente" son el receptor). "Solo SAT" en emitidos: CFDI I/E/P vigentes del periodo con emisor distinto del receptor y UUID ausente de `Comprobante_Digital`.

Limitaciones: solo `CONC_BACKEND=mssql` (el warehouse Postgres no replica Factura/Nota_Credito/Cliente; con postgres `sentido=emitidos` responde 400); el IVA trasladado de la póliza (2160) no se liga por documento en ventas ni en cobranza (el IVA está en `IMP_0006`); el precalentado de caché solo cubre recibidos; monedas distintas de MXN sin probar.

## Resumen SAT vs Mpro

Pestaña "Resumen SAT vs Mpro" (`/api/resumen?ini=&fin=[&refresh=1]`; en la UI se elige año y mes o "Todo el año"): cantidad y monto de CFDI por tipo, SAT, Mpro y diferencia, con dos agregados directos (sin construir el reporte completo; un mes tarda ~1 s, un año ~4 s). **SAT**: `raw_sat_api.cfdi` por fecha del CFDI, uno por UUID, sin cancelados de `raw_sat_api.cancelados`; en complementos de pago el monto es `pagos_monto_total`; Retención desde `raw_sat_api.retenciones` (`monto_tot_ret`, provisional; requiere `GRANT SELECT`, si no se muestra n/d). **Mpro**: `Comprobante_Digital` por fecha de timbre, un documento por UUID sin cancelados (`Es_Cve_Estado='CA'`); emitidos = `Cd_RFC_Emisor` igual a `RFC_PROPIO` (por omisión TRI970922TL2), recibidos = el resto; Pago sin monto (n/d), Nómina n/d (se timbra en Nominpaq), Retención = constancias de retención. "Exportar diferencias a Excel" baja el resumen y la lista de documentos con diferencia de existencia o de importe (`/api/diferencias`, usa el reporte completo del periodo, ~1 min por mes).

## Pruebas

```bash
python -m unittest discover -s tests -t .
```
