# Arquitectura

## Por qué está partido en dos agentes

El proyecto conecta dos ambientes que normalmente no se hablan: las bases
de datos de Esteban (en su máquina `ctunlinux`, dentro de su red) y este
entorno de Cowork (en la nube de Anthropic, sin acceso directo a esa red).
La solución, decidida explícitamente al arrancar el proyecto:

- **Claude Code**, corriendo en `ctunlinux`, construyó y mantiene una API
  HTTP mínima — la "bridge" — que expone `postgres_dw` (la bodega SAT) y
  dos instancias de SQL Server de mpro. Esa es su única responsabilidad:
  nada de lógica de negocio, nada de parseo de CFDI, nada de conciliación.
- **Este repo (Cowork)** hace todo el trabajo de datos: extracción vía la
  bridge, parseo de XML, reglas de conciliación, reportes.

Esto mantiene las credenciales de base de datos fuera de este entorno (la
bridge solo entrega un token bearer, nunca una cadena de conexión) y evita
que la lógica de negocio dependa de que Claude Code esté corriendo.

## La bridge API

- **URL**: `https://reportesweb.frento.com.mx/query` (hardcodeada en
  `src/bridge_client.py` — es un endpoint, no un secreto; el secreto es el
  token bearer, que nunca se versiona).
- **Contrato**: `POST /query` con body `{"target": "...", "sql": "..."}` →
  responde `{"columns": [...], "rows": [[...], ...], "row_count": N,
  "truncated": bool}`.
- **Solo lectura**: cualquier sentencia de escritura (INSERT/UPDATE/DELETE/DDL)
  es rechazada del lado del servidor. No hay forma de escribir a través de
  esta bridge, por diseño.
- **Sin bind params confiables**: el soporte de `params` de la bridge no
  está verificado contra mssql, así que todo el SQL dinámico se arma con
  literales, escapando strings con `bridge_client.sql_quote()` (duplica
  comillas simples). Los únicos valores dinámicos que se insertan son
  UUIDs, folios, periodos y fechas ISO — bajo riesgo, pero se escapan
  igual.
- **502/503/504 transitorios**: se ven ocasionalmente en consultas de
  tabla completa sin `WHERE` selectivo. `run_query()` reintenta hasta 3
  veces con backoff (2s, 4s, 6s).
- **Auth**: `Authorization: Bearer <token>`. El token se lee de la
  variable de entorno `QUERY_API_TOKEN` o, si no está, del archivo en
  `QUERY_API_TOKEN_FILE` (default `/home/claude/.query_api_token`, fuera
  de este repo, permisos 600). Nunca se debe pegar el token en código,
  logs, o mensajes — si alguna vez se comparte en texto plano por error,
  tratarlo como comprometido y rotarlo.

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
