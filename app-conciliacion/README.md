# app-conciliacion

Reporte web del layout de gastos con formato de póliza (una fila por cuenta
contable; los datos del folio solo en su primera fila). Atiende las 18
observaciones de Ismael sobre el reporteador. Estilo copiado del reporteador
web de Trivasa (Roboto 12px, naranja `#FF8000`).

| Archivo | Para qué |
|---|---|
| `build_reporte.py` | Consulta `.205/TRIVASADB3` y arma el DataFrame (`construir` + `post`). Genera `rep_<ini>_<fin>.pkl`. |
| `columnas.json` | Las 58 columnas (clave, etiqueta, grupo, tipo) y si son de nivel línea (`linea`) o solo de la primera fila del folio. |
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
