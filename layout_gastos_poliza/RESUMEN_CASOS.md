# Resumen — casos distintos por origen (reconciliación CECO)

Estado al 2026-09-02, enero 2026, empresa 0001. Ver `PROGRESS.md` para el
detalle completo de cómo se llegó a cada resultado (scripts `01`-`09`) y
`08_notebook_hito_ceco.py` para la narrativa con SQL de los 5 orígenes
normales.

## Tabla por origen

| Origen | Filas | Casos identificados dentro del origen | Regla | Estado |
|---|---:|---|---|---|
| **CONTROL_COMBUSTIBLE** | 591 | 1 caso (normal) | `(Tg_Cve_Tipo_Gasto, Centro)` vs Cargo | ✅ 100% |
| **ORDEN_COMPRA** | 80 | 1 caso (normal) | `(Tg_Cve_Tipo_Gasto, Centro)` vs Cargo | ✅ 100% |
| **VIAJE** | 346 | 1 caso (normal — no hizo falta regla especial de anticipos, como se temía al inicio) | `(Tg_Cve_Tipo_Gasto, Centro)` vs Cargo | ✅ 100% |
| **GASTO_DIRECTO** (vacío) | 6,531 | 2 casos: (1) normal, (2) reversión (4 folios, `IMPORTE ≤ -$1`) | (1) vs Cargo · (2) vs Abono | ✅ 100% |
| **GASTO_RECLASIFICACION** | 143 | 1 caso: par espejo Cargo=Abono | signo de `Grc_Importe` por línea decide Cargo/Abono | ✅ 100% |
| **CONSUMO_INTERNO** | 3,071 | 4 casos: (1) normal filtrando póliza memo, (2) capitalización de activo fijo (21 folios), (3) provisión/pasivo (1 folio), (4) sin explicación (2 folios) | (1) `Pl_Comentario` excluye memo · (2)-(4) sin regla aún | 🟡 99.12% resuelto directo · 21 folios con causa identificada mas sin regla · 3 folios sin resolver |
| **GASTO_REGISTRO_NOMINA** | 270 folios (rango ene-mar) | 1 caso: normal, igual mecanismo que los 5 orígenes normales; validado a `(FOLIO, CENTRO)` **y** a `(FOLIO, CENTRO, CONCEPTO)` (join por texto `Tg_Descripcion`=`Cc_Descripcion`, no hay FK real) | `Pd_Centro_Costo <> ''` excluye reclasificaciones de pasivo (ISR/IMSS/sueldos por pagar) vs Cargo real | ✅ 100% ambos grados (2026-09-03) |
| **COMPROBACION_GASTO** | 2 folios (rango ene-mar) | 1 caso: comprobación de fondo fijo/caja chica — mismo enfoque normal, sin regla propia | `(Tg_Cve_Tipo_Gasto, Centro)` vs Cargo | 🟡 1 folio 100%, 1 folio con 1/82 filas fuera (límite de rank-pairing, no de negocio) |

## Total de "casos de negocio" distintos encontrados: 9

1. **Normal** — mayoría de folios, 4 orígenes (`CONTROL_COMBUSTIBLE`,
   `ORDEN_COMPRA`, `VIAJE`, `GASTO_DIRECTO`). `Grc_Importe` agrupado por
   `(Tg_Cve_Tipo_Gasto, Centro)` cuadra directo contra Cargo real de
   `Poliza_Detalle` agrupado por `(Cuenta, Centro)`.
2. **Reversión de folio completo** (`GASTO_DIRECTO`, 4 folios) — cuando
   `IMPORTE ≤ -$1`, el Cargo cae en cuenta de Provisión/Pasivo; comparar
   contra Abono, no Cargo. Regla rescatada de
   `layout-gastos-pasos/docs/queries/gastos/v02_reversion.sql`.
3. **Par espejo por signo** (`GASTO_RECLASIFICACION`, 143 filas) — el
   signo de `Grc_Importe` por línea (no si el folio completo es negativo)
   decide si esa línea es Cargo (positivo) o Abono (negativo). Hallazgo
   nuevo de esta exploración — el histórico `v02_reclasificacion.sql`
   solo llegaba a nivel folio.
4. **Doble póliza memo/gasto-real** (`CONSUMO_INTERNO`, universo base) —
   cada folio genera dos pólizas paralelas; se filtra `Poliza.Pl_Comentario`
   para quedarse solo con la de gasto real. Da 99.12% directo.
5. **Capitalización de activo fijo vía código de proyecto `U-NNN`**
   (`CONSUMO_INTERNO`, 21 folios) — `Grd_Comentario` empieza con
   `U-NNN`/`UNNN`; la póliza real usa `Pd_Referencia = 'NNN'` (no el
   folio) y cuenta `1210.xxx` (Activo Fijo, no Gasto). Causa identificada,
   regla de query pendiente de construir.
6. **Provisión/pasivo con referencia de folio completo pero cuenta
   `2120...`** (`CONSUMO_INTERNO`, 1 folio: `05-0174748`, "LLANTA
   PONCHADA") — no es capitalización, patrón distinto, sin investigar a
   fondo.
7. **Folios sin ninguna póliza encontrada** (`CONSUMO_INTERNO`, 2 folios
   genuinos: `05-0175286`, `05-0176482`) — sin match ni por folio ni por
   importe en ninguna póliza ligada.
8. **`GASTO_REGISTRO_NOMINA`** (2026-09-03) — investigado: **no es un caso
   de negocio nuevo**, es el mismo caso 1 (Normal) que los 4 orígenes de
   arriba, solo que el grano de comparación baja a `(FOLIO, Centro)` en vez
   de `(Tg_Cve_Tipo_Gasto, Centro)` porque nómina desagrega el Cargo en
   muchas más cuentas `6xxx` por concepto (Sueldos, Bonos, Fondo de ahorro,
   Comisiones...) de las que `Grc_ID` distingue. Cada póliza también trae
   líneas de reclasificación de pasivo sin centro de costo (ISR, IMSS,
   sueldos/fondo de ahorro por pagar) que cierran el balance Cargo=Abono de
   la póliza pero se excluyen de la comparación (`Pd_Centro_Costo <> ''`).
   **100.00%**, 270/270 folios. Validado también al grano más fino
   `(FOLIO, Centro, Concepto)` (une por texto, sin FK real
   `Tipo_Gasto→Cuenta_Contable`) — **también 100.00%** (6,591/6,591), o
   sea que el reparto entre tipos de gasto dentro del mismo centro
   también es exacto, no solo la suma agregada. Ver `PROGRESS.md`
   2026-09-03 y `13_reconciliacion_nomina_ceco.py`.
9. **`COMPROBACION_GASTO`** (2 folios, rango ene-mar) — comprobación de
   gastos de fondo fijo/caja chica (Abono a `1110.002.001.019 "FONDO
   FIJO..."`). No necesita regla propia — el enfoque normal ya funciona;
   el único fallo (`01-0035339`, 1 de 82 filas) es un caso más del límite
   de rank-pairing (centro duplicado dentro del mismo documento), no un
   tratamiento contable distinto.
