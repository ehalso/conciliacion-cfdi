# Layout de Gastos — Pasos de comprobación

Esta carpeta reúne, en orden cronológico/lógico, los scripts de
comprobación que fueron validando cada pieza del layout de gastos (60
columnas). Es un mapa de navegación sobre `~/trivasa-bi-dev/layout_gastos/`
— los scripts originales siguen viviendo ahí; aquí solo hay copias
renombradas por paso para poder recorrer la historia sin tener que
adivinar el orden por fecha de archivo.

Baseline de referencia en todos los pasos: **enero 2026**
(`2026-01-01` a `2026-02-01`), empresa `0001`, contra `.200`/TRIVASADB3.

---

## Paso 1 — `paso1_v01_reporte_nativo.py`

**Qué hace:** reconstruye el gasto por folio (`IMPORTE`, `IMPUESTOS`,
`TOTAL`) desde cero, a nivel `Gasto_Registro` + `Gasto_Registro_Documento`,
**incluyendo TODOS los orígenes** (`GASTO_REGISTRO_NOMINA`,
`CONSUMO_INTERNO`, `VIAJE`, `ORDEN_COMPRA`, `CONTROL_COMBUSTIBLE`,
`GASTO_RECLASIFICACION`, y `GASTO_DIRECTO` sin tabla), y compara el
total contra el reporte nativo de MPRO como ground truth.

**Resultado:** ✅ CUADRA — 4,494 folios, IMPORTE $39,469,269.50, exacto
contra el esperado del reporte nativo.

**Por qué importa:** es la **prueba de que la reconstrucción desde tablas
crudas es correcta** antes de empezar a construir el layout de 60
columnas. Sin este paso, cualquier discrepancia posterior sería
indistinguible entre "error en mi query" vs. "caso de negocio legítimo".

**Nota:** incluye Nómina (99 folios, $10.59M) y Consumo Interno (2,970
folios, $6.59M) — universos que el layout de gastos de Contabilidad NO
necesita (nómina y consumo interno tienen su propio flujo, no llevan
póliza de gasto). Por eso el Paso 2 los excluye.

## Paso 2 — `paso2_v01_gastos_base_sin_nomina_consumo.py`

**Qué hace:** mismo query base que el Paso 1, pero **filtrando fuera**
`GASTO_REGISTRO_NOMINA` y `CONSUMO_INTERNO` — este es el universo real
que va a alimentar el layout de 60 columnas.

**Resultado:** 1,425 folios, IMPORTE $22,283,791.24, IMPUESTOS
$1,084,277.23, TOTAL $23,368,068.46. Desglose por origen:

| Origen | Folios | Total |
|---|---|---|
| (vacío = GASTO_DIRECTO) | 610 | $20,010,666.49 |
| VIAJE | 346 | $1,874,932.35 |
| ORDEN_COMPRA | 72 | $1,006,294.44 |
| CONTROL_COMBUSTIBLE | 384 | $476,175.18 |
| GASTO_RECLASIFICACION | 13 | $0.00 |

**Output:** `v01_baseline_enero2026_sin_nomina_consumo.csv` — este es el
**archivo baseline que usan todas las etapas posteriores** (4, 6, y las
piezas de CXP) como universo de verdad contra el cual validar folio por
folio. Cualquier `.merge(base, how="left")` en scripts posteriores parte
de este CSV.

**Por qué importa:** define el universo exacto (1,425 folios) y el
desglose por `ORIGEN` que se repite como referencia en TODO el resto del
proyecto — es la piedra angular, no solo un paso más.

## Paso 3 — `paso3_notebook_construccion_v03.py`
**Qué hace:** primer intento de construir el SQL de Cargo/Abono al detalle
de cuenta contable.

**Resultado:** ⚠️ Trae la estructura correcta, pero **aún con errores** en
dos casos de negocio: `GASTO_RECLASIFICACION` y folios con importe
negativo (reversiones).

**Por qué importa:** es el punto de partida de la línea de Cargo/Abono —
expone los dos casos difíciles que toma varias iteraciones resolver (ver
Paso 4).

---

## Paso 4 — Resolviendo Cargo/Abono (arco de 6 scripts)

Este paso documenta la secuencia completa de depuración de Cargo/Abono,
de intento roto a query vigente. Se deja como narrativa de varios
archivos en vez de un solo script, porque cada iteración resuelve un
problema puntual del anterior — verlas sueltas pierde el hilo.

1. **`paso4a_v02c_fix_join_simple.py`** — Empieza a resolverse:
   reclasificación con importe en 0; negativos con Cargo y Abono en el
   mismo row (mismo monto), lo cual **sigue sin cuadrar**.
2. **`paso4b_v02_validacion_enero.py`** — ¿Ya con la corrección aplicada?
   *(pendiente de confirmar qué corrigió exactamente vs. el paso anterior)*.
3. **`paso4c_v02_semestre_por_mes_207.py`** — Confirma que los combustibles
   que en algún mes aparecían sin póliza, en `.207` **ya están pagados**
   (no es un gap real, es rezago temporal).
4. **`paso4d_drill_down_4_pendientes_207.py`** — Aísla los pendientes
   reales: solo quedan diferencias en pesos (no en folios completos) y
   **2 órdenes de compra con doble cargo**.
5. **`paso4e_notebook_v02_final.py`** — Cierra el caso normal, el caso de
   reclasificación (**sin dividir su detalle todavía**) y los negativos.
6. **`paso4f_v03_detalle_cuenta.py`** — Lleva todo al detalle de cuenta
   contable (grano final: N filas/folio, una por cuenta × centro de costo).

**Pendiente abierto:** ¿dónde se separa el output cuando es N filas/folio
vs. el resto del layout que es 1 fila/folio? — Esto es exactamente el
"riesgo bloqueante" que quedó documentado en `docs/ESTADO_2026-08-04.md`
y que sigue sin resolverse. Queda para después.

---

## Paso 5 — CXP (arco de 5 scripts)

1. **`paso5a_validar_cxp_general_v2.py`** + **`paso5b_validar_cxp_general_semestre.py`**
   — Primer cuadre de CXP caso general. **Falta combustible**, que vive
   en un origen de match distinto (`CONTROL_COMBUSTIBLE`).
2. **`paso5c_validar_cxp_completo_enero2026.py`** + **`paso5d_validar_cxp_v3_completo.py`**
   — Ya incluyen el origen de combustible. Parecen equivalentes entre sí
   *(pendiente confirmar diferencia exacta, si la hay)*.
3. **`paso5e_validar_cxp_v3_semestre_207.py`** — Valida todo el semestre
   contra `.207`; los 2 folios que no encuentra están **pendientes de
   pago** (no es un gap de query, es estado real de negocio).

---

## Paso 6 — Impuestos / cierre de columnas (arco de 3 scripts)

1. **`paso6a_validar_impuestos_v4c.py`** — Dice que valida, pero **no se
   ve el detalle en el output** *(revisar si vale la pena reusar o si
   quedó superado por `validar_impuestos_v5.py`, versión vigente según
   `INDICE_ETAPAS_REPORTE.md` — no copiado a esta carpeta todavía)*.
2. **`paso6b_validar_etapa6_columnas_1_18.py`** — Validación con buenos
   números para las columnas 1-18 (proveedor/pago/comprobante).
3. **`paso6c_validar_etapa6_extension_combustible.py`** — Debe cerrar el
   gap de combustible en el bloque de pago (384 folios pendientes, según
   `PROGRESS.md`).
