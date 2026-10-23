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

## Pruebas

```bash
python -m unittest discover -s tests -t .
```
