# Arquitectura

## De bridge HTTP a conexión directa (2026-09-09)

Hasta el 2026-09-09 este proyecto corría en un entorno de Cowork **sin
ruta de red** hacia la LAN de Trivasa (`192.168.117.0/24`, donde viven
tanto `postgres_dw` como los dos SQL Server de mpro). La solución de
entonces: **Claude Code**, corriendo en `ctunlinux` (dentro de esa red),
construyó y mantuvo una API HTTP mínima — la "bridge"
(`https://reportesweb.frento.com.mx/query`) — cuya única responsabilidad
era exponer los tres targets de solo lectura; nada de lógica de negocio,
nada de parseo de CFDI, nada de conciliación. Este repo hacía todo el
trabajo de datos consultando esa bridge en vez de la base directamente.

Esa sesión pasó a correr **con acceso de red directo** a la LAN (VPN sobre
`192.168.117.0/24`, confirmado con conexión TCP real a los tres targets),
así que `src/bridge_client.py` se reescribió para conectar **directo**
por SQLAlchemy (`psycopg2`/`pymssql`) en vez de HTTP — sin tocar los ~10
extractores que lo importan, porque el contrato de `run_query(target,
sql) -> {"columns", "rows", "row_count", "truncated"}` se conservó
idéntico. Ver el docstring de ese archivo para el detalle de credenciales,
targets y el guard de solo lectura del lado cliente.

Validado 2026-09-09: la corrida completa de `baseline_universal.py
--periodo 2026-02` contra la conexión directa dio el mismo resultado ya
documentado (1,492/1,500, 99.5%) que contra la bridge.

**Qué se conserva del diseño original** (ya no por falta de red, sino
porque sigue siendo la práctica correcta):

- **Solo lectura**: `bridge_client._guard_readonly()` rechaza cualquier
  cosa que no sea un único `SELECT`/`WITH` (mismo espíritu que el
  `sql_guard.py` del lado servidor de la bridge, ahora aplicado del lado
  cliente porque ya no hay servidor intermedio). Postgres además abre la
  conexión en modo `postgresql_readonly=True`; para los SQL Server
  (pymssql no tiene un modo read-only por sesión) la red de seguridad es
  no llamar `commit()` nunca.
- **Sin bind params**: todo el SQL dinámico se sigue armando con
  literales, escapando strings con `bridge_client.sql_quote()`. Los
  únicos valores dinámicos son UUIDs, folios, periodos y fechas ISO.
- **Credenciales fuera del código**: usuario/password de cada target
  viven en un `.env` local (gitignored, ver `.env.example`) o variable de
  entorno — nunca hardcodeados. Host/puerto/nombre de base sí van
  hardcodeados en `bridge_client.py` (topología de red, no secreto).

Si en el futuro esta sesión (o una nueva) vuelve a correr sin ruta de red
a la LAN, el patrón de bridge HTTP de arriba es el fallback conocido —
recuperable de la historia de git de este archivo.

## Los tres targets

| target | motor | contenido |
|---|---|---|
| `postgres_dw` | PostgreSQL | Bodega `raw_sat`: XMLs de CFDI ya parseados/cargados por un ELT — `cfdi_recibidos`, `cfdi_emitidos`, `cfdi_retencion`. |
| `mssql_207` | SQL Server (`TRIVASADB` en el host `BACK-MPRO`) | La instancia de mpro **autoritativa** — confirmado explícitamente por Esteban 2026-09-07: "207 es la buena". |
| `mssql_205` | SQL Server (`TRIVASADB3` en el host `SVRMPRO`) | Instancia de mpro alterna. Mismas 4 empresas configuradas (mismos RFC), pero **va ligeramente atrasada** frente a 207 (ver abajo) y le faltan/sobran algunos orígenes de `Comprobante_Digital.Cd_Tabla`. |

### 205 vs 207 — qué se sabe y qué no

Hallazgo en vivo (2026-09-07), comparando ambas para el mismo corte:

- Máximo `Pl_Fecha` en `Poliza`: 207 → 2026-08-31; 205 → 2026-08-10. 207
  tiene más filas (340,227 vs 337,868).
- `Comprobante_Digital.Cd_Tabla` en 205 incluye `CONSTANCIA_RETENCION` y
  `CONTABILIDAD_ELECTRONICA`, que no aparecen en el censo de 207 — pero al
  probar UUIDs de retención conocidos, tampoco aparecieron ahí, así que
  esto **no resuelve** el pendiente de retención, solo indica dónde seguir
  buscando (ver `pendientes.md`).
- El nombre de host `BACK-MPRO` (207) sugiere "backup", pero tiene *más*
  datos y más recientes que `SVRMPRO` (205) — lo contrario de lo que un
  simple espejo de respaldo debería mostrar. La relación real entre ambas
  instancias (¿205 es una réplica más lenta? ¿un ambiente de desarrollo
  aparte?) no está confirmada del lado de infraestructura; Esteban
  confirmó que **207 es la fuente de verdad**, pero que por estar 207 en
  desarrollo se debe usar 205 mientras tanto.
- Validación cruzada: se corrió la conciliación por origen de febrero
  2026 contra ambas instancias. Los resultados fueron prácticamente
  idénticos (mismos porcentajes de cuadre, diferencias de solo 2–8
  documentos por origen) — da confianza de que usar 205 temporalmente no
  distorsiona las conclusiones ya reportadas.

### Decisión operativa

Todo el código de extracción de mpro importa un solo símbolo,
`MPRO_TARGET`, definido en `src/config.py`. Hoy vale `"mssql_205"`. Para
volver a 207 cuando esté listo, se cambia una sola línea en ese archivo —
ningún extractor necesita tocarse.

Mientras se use 205, el alcance de fechas acordado con Esteban es
**enero–junio 2026** (primer semestre) — no se ha validado cobertura de
205 fuera de ese rango.

## Flujo de datos (conciliación por origen, el caso más completo)

```
raw_sat.cfdi_recibidos (Postgres)          Comprobante_Digital (mpro)
         │  periodo → N CFDI                        │
         │                                           │
         └──────────────► UUID ◄────────────────────┘
                            │
              Cd_Tabla = origen (Compra, Gasto_Registro, ...)
              Cd_Documento = folio real (10 chars) + sufijo de sub-documento
                            │
                 truncar a 10 chars → documento_real
                            │
                            ▼
              Poliza_Control (Pc_Tabla = origen, Pc_Documento = documento_real)
                            │
                 JOIN Poliza (excluir canceladas, Es_Cve_Estado <> 'CA')
                            │
                 JOIN Poliza_Detalle
                   ON Pd_Referencia = Pc_Documento   ← aísla las líneas de
                                                        ESTE documento dentro
                                                        de una póliza que
                                                        puede consolidar varios
                            │
                 LEFT JOIN Poliza_Configuracion (excluir "cuentas de orden")
                            │
                            ▼
              SUM(Pd_Importe) por Pd_Tipo (1=Cargo, 2=Abono)
                            │
                            ▼
         comparar cargo/abono vs. subtotal/total del CFDI (por documento
         y, aparte, en agregado por origen — ver metodologia.md)
```

Cheque es la excepción: no usa `Pd_Referencia` (no es confiable para ese
origen, ver `hallazgos.md`), sino match por monto entre `Cheque.Ch_Importe`
y `Poliza_Detalle.Pd_Importe`.
