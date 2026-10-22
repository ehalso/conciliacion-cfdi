# Rama v3 — notas de trabajo

Rama creada desde `main` (53d09e0). Objetivo: traer a la app los campos nuevos del
modelo `Modelo_conciliaci_n_BD_Mpro_vs_BD_SAT_Ago_2026.xlsx` (hoja `Recibidos`,
columnas BM:CB), cuya fuente es Postgres, esquema `raw_sat_api`.

## Campos objetivo

- Bloque SAT (BM:BW): UUID, Serie UUID, Folio UUID, Estatus, Tipo de CFDI, Fecha UUID,
  Concepto UUID, RFC del proveedor, Nombre del proveedor, Importe, No localizados.
- Bloque conciliación (BY:CB): Existe UUID en Mpro, Existe UUID en SAT,
  Coincide existencia, Coincide importes.

## Lo que se hizo

1. **Acceso a `raw_sat_api`.** El rol RO veía el esquema pero no tenía SELECT. Se otorgó
   SELECT sobre `raw_sat_api.cfdi` y `raw_sat_api.cancelados` usando la credencial admin
   de Infisical (permiso explícito del usuario). Las credenciales se inyectan con
   `infisical run --env dev --projectId <id> --recursive -- <cmd>`; nunca se guardan en el repo.
   Variables: `POSTGRES_DW_RO_*` (SAT), `MSSQL_205_*` (Mpro).
   **Pendiente recomendado:** rotar la credencial admin (quedó con superusuario).
2. **`src/extract_sat_api.py`** (nuevo). `extract_sat_api(tipo, periodos=None, con_concepto=True, uuids=None)`
   devuelve las columnas BM:BW desde `raw_sat_api.cfdi`:
   - filtra por `direccion` (RECIBIDO / EMITIDO; AUTOEMITIDO queda aparte);
   - Estatus = `Cancelado` si el UUID está en `raw_sat_api.cancelados` con `estatus='0'`;
   - Concepto UUID = Descripcion del primer Concepto del XML;
   - Importe = `total`; para recibidos la contraparte es el emisor;
   - acepta lista de `uuids` (en bloques de 400) para no depender del mes de timbrado.
   Nota: la columna `tipo` fue reemplazada por `direccion` y ya no hay UUID duplicados.
3. **`layout_gastos_poliza/26_consolidado_vs_sat.py`** (nuevo). Toma el consolidado de v2
   (`25_consolidado_final`, que ya trae `UUID` y `XML_MONTO` de Mpro con sus reglas de
   deduplicación), cruza por UUID contra `extract_sat_api` y agrega BM:BW y BY:CB.
   Exporta `layout_gastos_60col/CONSOLIDADO_SAT_*.xlsx`. Tolerancia de importes: 0.05.
   Admite `--csv` para usar un consolidado ya generado.

## Estado de pruebas

- Lado SAT probado contra datos reales (p. ej. 2,048 recibidos en 2026-01).
- Cruce probado con un consolidado simulado (coincide / importe distinto / solo Mpro / sin UUID).
- **No probado de punta a punta:** el SQL Server `.205` (Mpro) no fue alcanzable desde el runner
  ("No route to host"). Estatus Cancelado tampoco se vio con datos reales.

## Pendientes

- **Integrar en `app-conciliacion`.** El trabajo se hizo sobre scripts de `layout_gastos_poliza/`
  por error; el reporte activo es `app-conciliacion`. Hay que llevar el cruce con SAT ahí
  (reutilizando `extract_sat_api.py`) y exponer BM:CB como columnas de la app.
- **No localizados (BW):** marca calculada en el cruce para filtrar UUID de Mpro que no están en la
  BD del SAT. Definición pendiente; hoy queda vacío. (No es la lista 69-B del SAT.)
- Definir si "Coincide importes" usa tolerancia 0.05 u otra.
- Cruce solo desde filas de Mpro; los UUID que están solo en el SAT no se listan.
- Rotar la credencial admin de Postgres.

## Pendiente: limpieza del repo

El repo mezcla código activo con scripts antiguos/legacy, y eso llevó a trabajar sobre el
código equivocado. Antes de seguir con v3:

- Identificar qué es activo (`app-conciliacion/` y lo que realmente consume) y qué es legacy
  (`layout_gastos_poliza/` numerados, `layout_gastos_60col/legado/`, `recibidos/nivel_documento/`
  CLI, `extract_sat.py` sobre `raw_sat`, etc.).
- Mover lo legacy a una carpeta `legacy/` o eliminarlo, y documentar en el README qué es activo.
- Dejar un README corto de "dónde se trabaja" y de dónde sale cada columna del reporte.
- Confirmar si todo el cruce debe migrar de `raw_sat` a `raw_sat_api`.
