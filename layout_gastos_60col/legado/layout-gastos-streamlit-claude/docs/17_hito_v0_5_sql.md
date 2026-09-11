# Hito v0.5 — versión SQL pura (sin post-proceso en Python)

Pedido explícito del usuario: *"con todo lo aprendido, como haríamos este reporte pero
con una consulta SQL... sin nada muy sofisticado, solo hardcodeando algunos casos
especiales que hayas encontrado"*, tomando como base `ContabilidadRepository.cs` /
`QueryAuditoria2.0.sql` (código de otro programador que intentó este reporte antes,
compartido por el usuario).

Archivo listo para entregar: `sql/layout_gastos_v0_5.sql`. Wrapper Python (para
validarlo con el mismo patrón que v0.1-v0.4.2): `scripts/layout_gastos_v0_5.py`.

## Diferencia clave con v0.4.2 (deliberada)

v0.4.2 atribuye Cargo/Abono a nivel de **documento individual** (`Grd_ID`), usando
`Gasto_Registro_Control` + emparejamiento por valor + reparto proporcional + una
salvaguarda de re-enrutado — preciso, pero no es "SQL simple".

v0.5 atribuye a nivel de **folio completo** (como v0.2): el Cargo/Abono de la póliza se
pega al **último** `Grd_ID` del folio, sin repartir entre documentos. Es exactamente lo
que hacía el query de referencia del usuario (ahí ni siquiera se evitaba la duplicación
al cruzar cada documento contra todas las líneas de póliza del folio).

## Qué se tomó del query de referencia

- Estructura general (CTEs, un `OUTER APPLY` para el comprobante digital, agrupación por
  folio).
- El join a `Poliza_Control` → `Poliza` → `Poliza_Detalle` por `Pd_Referencia = Gr_Folio`.

## Qué se corrigió del query de referencia

1. **`Es_Cve_Estado = 'AP'`** → excluía 3,494 de 4,502 folios de enero 2026 (el estado
   más común es `AC`, no `AP`). Cambiado a `<> 'CA'` (nuestra regla validada).
2. **`LEFT JOIN Comprobante_Digital ... LIKE ...`** → duplica la fila cuando un documento
   matchea 2+ UUID (bug real encontrado en `docs/12`). Cambiado a `OUTER APPLY TOP 1`.
3. **`Poliza_Detalle_Comprobante`** → se investigó y NO sirve para esta atribución: liga
   UUID de **complemento de pago**, no el UUID del CFDI de registro (verificado con
   folio `01-0034739`: la misma línea de póliza aparecía ligada a los 9 UUID de sus 9
   documentos por igual). Se eliminó esa dependencia.
4. **Solo `Pd_Tipo = 1` (Cargo)**, sin ningún manejo de Abono ni de los orígenes
   especiales (`GASTO_RECLASIFICACION`, `CONSUMO_INTERNO`, reversiones). Se agregaron
   todos los casos especiales aprendidos (ver abajo).

## Casos especiales hardcodeados (aprendidos en v0.1-v0.4.2)

1. `CONSUMO_INTERNO` / `GASTO_REGISTRO_NOMINA`: sin poliza (Cargo/Abono/Cuenta `NULL`).
2. `GASTO_RECLASIFICACION`: no tiene póliza real — Cargo/Abono por signo de
   `Grd_Precio_Descontado_Importe`, cuenta de `Tipo_Gasto.Tg_Cuenta_Contable`.
3. Abono solo cuenta si la cuenta es raíz `'F'` (Gastos), o sin grupo y empieza con
   `'6'`, o su descripción es "Gastos a cuenta de costo estandar" (docs/16).
4. Reversiones (Importe de folio ≤ -$1): se usa solo el Abono, Cargo en 0 (docs/15).

## Validación

| Periodo | Filas | Tiempo | Comprobación | Discrepancias |
|---|---|---|---|---|
| Enero 2026 | 8,083 | ~3s | 99.7%+ (100% en CONTROL_COMBUSTIBLE/GASTO_RECLASIFICACION/ORDEN_COMPRA/VIAJE) | 2 de 1,425 (ambas redondeo) |
| 2025 completo | ~53,000 | **22s** | 99.90% | 15 de 15,047 (todas redondeo, 0 sin explicar) |

Resultado sorprendentemente bueno para una versión "simple": al validar a nivel folio
completo (igual que v0.4.2 hace para folios multi-documento), los **totales** cuadran
igual de bien — solo se pierde el desglose fino de CUÁL documento específico dentro de
un folio multi-documento recibió cuánto Cargo/Abono (eso solo importa si alguien filtra
o agrupa por documento individual dentro de un folio así, no para el total del reporte).

## Cuándo usar v0.5 vs v0.4.2

- **v0.5**: para entregar a un programador / FlexMonster — una sola consulta SQL,
  mantenible sin conocer todo el proceso de descubrimiento. Suficiente si el consumo es
  agregado (por proveedor, por cuenta, por periodo) y no se necesita saber exactamente
  qué documento de un folio multi-documento aportó cada peso.
- **v0.4.2**: cuando se necesita precisión por documento individual (ej. conciliar contra
  un CFDI específico dentro de un folio de varios documentos).
