# recibidos/nivel_documento — conciliación CFDI recibido ↔ Management Pro

> Consolidado aquí el 2026-09-10, portado desde el proyecto hermano
> `~/proyectos/conciliacion-master/adjuntar-xml`. Se retiraron `01`
> (exploración previa, ya cumplió su propósito) y `02` (el `03` lo contiene
> completo — ver abajo); la conexión (`connection_205_trivasadb3.py`) se
> adaptó para leer `MSSQL_205_USER`/`MSSQL_205_PASSWORD` del `.env` de la
> raíz de este repo en vez de depender de `trivasa-bi-core` (externo).
> Nada más cambió — metodología intacta, ver `docs/` para el detalle
> completo (no repetido aquí).

Responde: **¿lo que MPro tiene contabilizado en importes e impuestos es lo
mismo que se le reporta al SAT?** — la contraparte "nivel_documento" de
`recibidos/nivel_poliza/` (que responde una pregunta más profunda: ¿lo que
se *contabilizó en la póliza* cuadra?).

Base de datos: `mssql://192.168.117.205/TRIVASADB3` (`.205`, **no productiva** —
ver [Limitaciones](#limitaciones)). Empresa `TRI970922TL2` (Trivasa).

---

## Los reportes

| # | Script | Base | Grano | Pregunta |
|---|---|---|---|---|
| **03** | `03_conciliacion_xml_vs_mpro_impuestos.py` | CFDI recibido | grupo de conciliación | ¿Coincide el importe **e impuestos** del XML con el del registro? |
| **04** | `04_conciliacion_mpro_vs_xml.py` | registro de MPro | documento | ¿Qué se contabilizó sin respaldo de un CFDI? |
| **05** | `05_resumen_conciliacion.py` | los CSV de 03/04 | indicador | Consolidado ejecutivo |

El `04` invierte la base pero reutiliza el mismo agrupador que el `03`, para
que los dos reportes sean comparables entre sí.

## Cómo se corre

```bash
cd recibidos/nivel_documento   # desde la raíz del repo

python3 03_conciliacion_xml_vs_mpro_impuestos.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
python3 04_conciliacion_mpro_vs_xml.py           --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
python3 05_resumen_conciliacion.py               --fecha-ini 2026-01-01 --fecha-fin 2026-02-01   # lee los 2 CSV
```

El rango es **semiabierto**: `[fecha-ini, fecha-fin)`. Para un mes completo, la
fecha final es el día 1 del mes siguiente.

Cada script escribe `<nombre>_<fi>_<ff>.csv` en el directorio y saca a la
terminal tablas `rich` con el semáforo. El `05` debe correrse **al final**:
lee los CSV que dejaron los otros tres.

Tiempo de referencia (enero 2026, `.205`): `02` ~40 s, `03` ~60 s, `04` ~5 min,
`05` ~20 s. Lo lento es traer y parsear los `Cd_XML` (ntext, ~5 KB cada uno).

## Qué produce

| Archivo | Filas (ene-2026) | Contenido |
|---|---:|---|
| `02_conciliacion_xml_vs_mpro_*.csv` | 1,938 | Un grupo de conciliación por fila, 33 columnas |
| `03_conciliacion_xml_vs_mpro_impuestos_*.csv` | 1,938 | Lo anterior + 23 columnas fiscales |
| `04_conciliacion_mpro_vs_xml_*.csv` | 12,037 | Un documento de MPro por fila |
| `05_resumen_conciliacion_*.csv` | 49 | Indicadores con su base de cálculo |
| `hallazgos_conciliacion_2026-01-02.html` | — | Reporte navegable de los dos meses (copia local del Artifact) |

## Estructura del proyecto

```
adjuntar-xml/
├── README.md                            ← este archivo
├── conciliacion_xml_lib.py              ← núcleo compartido
├── connection_205_trivasadb3.py         ← conexión (copiada, patrón del repo)
├── helpers_output.py                    ← tablas rich
├── 0{1..5}_*.py                         ← los reportes
├── *.csv                                ← salidas
├── hallazgos_conciliacion_2026-01-02.html
├── SESION_2026-09-03.md                 ← transcripción de la sesión que originó el 01
├── LAST_SESSION.md                      ← transcripción de la sesión que originó 02–05
└── docs/
    ├── metodologia.md      ← el método: grano, cierre, complementos, tolerancias
    ├── esquema-datos.md    ← tablas, columnas y llaves, todas verificadas
    ├── decisiones.md       ← log de decisiones y por qué
    ├── hallazgos-2026-01.md
    └── hallazgos-2026-02.md
```

### `conciliacion_xml_lib.py`

| Función | Qué hace |
|---|---|
| `xml_recibidos(fi, ff)` | Universo de CFDI recibidos del periodo, con el XML parseado |
| `parsear_cfdi(xml)` | Extrae 30 campos fiscales del CFDI, **complementos incluidos** |
| `xml_por_folios(dict)` | Todos los CFDI colgados de unos folios, sin filtro de fecha |
| `cerrar_universo(x)` | Expande el universo hasta cerrar las componentes |
| `asignar_grupos(x)` | Etiqueta cada CFDI y cada documento con su componente conexa |
| `registros_mpro_por_mes(fi, ff)` | Cabeceras de MPro fechadas en el periodo |
| `registros_mpro_por_folios(dict)` | Cabeceras de folios específicos, sin filtro de fecha |
| `impuestos_mpro(...)` | Impuestos por documento, normalizados al código del SAT |
| `montos_por_uuid(uuids)` | `Cd_Monto` de unos UUID — para el cruce REP → factura |
| `conciliar_importes(fi, ff)` | El reporte 02 completo; devuelve `(grupos, xml, registros)` |

## Documentación

- **[Metodología](docs/metodologia.md)** — por qué el grano es la componente
  conexa, cómo se cierran los grupos, qué complementos esconden el importe,
  cómo se comparan los impuestos y qué tolerancias se usan. **Léelo antes de
  tocar el código.**
- **[Esquema de datos](docs/esquema-datos.md)** — `Comprobante_Digital`, los
  ocho módulos de MPro, sus columnas de importe e impuesto, y las llaves de
  unión con su tasa de match medida.
- **[Decisiones](docs/decisiones.md)** — log con fecha y evidencia de cada
  decisión de alcance que cambia los números.
- **[Hallazgos enero 2026](docs/hallazgos-2026-01.md)** — resultados y su
  interpretación.
- **[Hallazgos febrero 2026](docs/hallazgos-2026-02.md)** — segundo mes, con la
  comparación contra enero: qué es estructural y qué era particular de un mes.

## Limitaciones

1. **`.205` no es la base productiva.** La productiva es `.207`. Los porcentajes
   de estructura (formas de la relación, cadena documental, complementos)
   deberían sostenerse; los importes exactos hay que reconfirmarlos antes de
   convertirlos en un ajuste contable. Para cambiar de base basta apuntar
   `connection_205_trivasadb3.py` a `.207` — no hay nada más específico de `.205`
   en el código.
2. ~~`connection_205_trivasadb3.py` trae la contraseña embebida.~~ **Corregido
   el 2026-09-10**: ahora sigue el patrón canónico de
   `trivasa-bi-core/connections/` — usuario y password salen de
   `shared/db_credentials.py` (o de `TRIVASA_MSSQL_USER` / `_PASSWORD` si ese
   repo no está disponible); host, puerto y base se quedan en el archivo porque
   son topología, no secreto (ver
   `trivasa-context/docs/arquitectura/credenciales-y-conexiones.md`, incidente
   2026-08-29). Verificable con `git grep -n "mssql+pymssql://.*:.*@"`.
3. **Sólo CFDI recibidos.** Los emitidos (venta, complementos de pago propios,
   notas de crédito propias) se concilian en el proyecto hermano
   [`conciliacion-emitidos`](../conciliacion-emitidos/README.md), construido el
   2026-09-10.
4. **SQL Server anterior a 2017** en `.205`: no hay `STRING_AGG`. Las
   agregaciones de texto se hacen en pandas.

## Historia

Los reportes `02`–`05` y esta documentación salieron de la sesión del
2026-09-04, transcrita en **[LAST_SESSION.md](LAST_SESSION.md)** — que vale la
pena leer antes de tocar el código: dos hallazgos importantes salieron de
corregir supuestos equivocados a medio camino.

El `01_semaforo_folio_xml.py` es de una sesión anterior (2026-09-03,
transcrita en `SESION_2026-09-03.md`) y trabaja a grano folio de gasto. Los
reportes `02`–`05` son del 2026-09-04 y **corrigen su premisa**: el XML no se
amarra al folio sino al documento (`Grd_ID`), y la relación no es 1:1. El `01`
se conserva porque su semáforo por origen de gasto sigue siendo útil, pero
para conciliar importes usa el `02`.
