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
  servidor.py     http.server con auth básica, caché por periodo y /api/reporte
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

## Resumen SAT vs Mpro

Pestaña "Resumen SAT vs Mpro" (`/api/resumen?ini=&fin=[&refresh=1]`, mismo caché del reporte): cantidad y monto de CFDI por tipo, SAT, Mpro y diferencia. El lado **SAT** se consulta directo a `raw_sat_api.cfdi` por periodo (fecha del CFDI, uno por UUID, sin cancelados de `raw_sat_api.cancelados`); en complementos de pago el monto es `pagos_monto_total`. **Recibidos** (Ingreso, Egreso, Traslado, Pago, Retención): Mpro = un documento por UUID con su `XML_MONTO` (NC proveedor = Egreso, el resto = Ingreso); Pago = complementos únicos adjuntos a cheques, sin monto (n/d). **Emitidos** (incluye Nómina, autoemitidos): solo lado SAT, Mpro "n/d" porque no vive en Mpro. Retención no tiene fuente aún (0). "Exportar diferencias a Excel" baja el resumen y la lista de documentos con diferencia de existencia o de importe.

## Pruebas

```bash
python -m unittest discover -s tests -t .
```
