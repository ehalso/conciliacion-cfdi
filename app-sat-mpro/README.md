# Conciliación SAT vs MPRO

Cruza por UUID los CFDI descargados del SAT (`raw_sat_api.cfdi`, Postgres) con los comprobantes adjuntos en MPRO (`Comprobante_Digital`, SQL Server .205/TRIVASADB3).

## Estatus
| Código | Estatus | Regla |
|---|---|---|
| OK | Conciliado | UUID en ambos, importe dentro de $1.00 y RFC iguales |
| DIF | Con diferencias | UUID en ambos con importe o RFC distinto |
| CAN | Cancelado en MPRO | UUID en ambos pero todos los documentos MPRO están en estado CA |
| FSM | Falta en MPRO | Está en el SAT y no en MPRO (fecha ≤ corte) |
| PEN | Pendiente de carga | Está en el SAT con fecha posterior al último timbre cargado en MPRO |
| FSAT | Falta en SAT | Está en MPRO y no en el SAT |
| NOM | Nómina | CFDI tipo N: no se registra en MPRO |

Un CFDI propio (emisor Trivasa) se trata como emitido; el resto como recibido.

## Uso
1. `python3 exportar_conciliacion.py [desde] [hasta]` (requiere credenciales MPRO en el entorno y `PG_DSN` en `~/ehalso/sat-descarga-cfdi/.env`) → `data.json`.
2. `python3 build.py` → `index.html` (pendientes + resumen) y `extra.json` (conciliados y nómina).
3. `APP_USER=.. APP_PASS=.. PORT=32836 python3 serve.py` para el servidor LAN (autenticación básica). Sin servidor, `index.html` abre solo con pendientes.

La app incluye KPIs, avance por mes, contrapartes con más pendientes, filtros (dirección, tipo, mes, búsqueda), detalle por UUID y exportación a Excel. Los archivos generados no se versionan (`.gitignore`).
