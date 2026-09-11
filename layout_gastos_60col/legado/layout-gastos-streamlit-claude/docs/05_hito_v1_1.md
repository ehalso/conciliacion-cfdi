# Hito v1.1 — fix de la vista agrupada + catálogo SAT de forma de pago

## Bug encontrado y corregido: la vista agrupada podia devolver mas de una fila por operacion

Al agregar la columna `XML FORMA PAGO (desc)` se noto que la vista "Agrupada por cuenta
contable" dejo de producir una sola fila para `01-0029621` (folio de ejemplo, ver
`docs/02_modelo_datos.md`): aparecian 2 filas de $12,000 en vez de 1 de $24,000.

Causa raiz: `group_by_cuenta_contable` agrupaba sobre `detail`, el resultado de
`merge_header_poliza` (merge **posicional**, ver `docs/03_hito_v1.md` correccion #4). Ese merge
solo repite los datos de cabecera (proveedor, pago, factura...) en la primera fila de cada
operacion; en las filas siguientes (cuando hay mas lineas de poliza que filas de cabecera) esas
columnas quedan en `NULL`. Como el `groupby` incluia esas columnas de cabecera como parte de la
llave de agrupacion, una fila con `NULL` y otra con valor real terminaban en grupos distintos —
rompiendo justo la garantia que pide el Word ("de esta manera se logra una sola fila por cada
registro de gasto").

**Fix:** `group_by_cuenta_contable(header, poliza)` ahora recibe `header` y `poliza` por
separado (no el `detail` ya fusionado), agrupa `poliza` solo por
`(Operacion (ID), Cuenta Registro, Nombre Cuenta Registro)`, y pega la cabecera (deduplicada a 1
fila por operacion) con un merge `outer` — así una operacion sin ninguna linea de poliza
(caso "solo cuenta de orden", ver hallazgo previo) sigue apareciendo en la vista agrupada con
Cargo/Abono en 0, en vez de desaparecer.

Validado: 3,584 operaciones en la cabecera == 3,584 operaciones en la vista agrupada (antes del
fix, el conteo de "filas" ya no correspondia 1:1 con operaciones). Máximo de filas por
`(Operacion, Cuenta Registro)`: 1 (confirmado con `groupby().size().max() == 1`).

## Catálogo SAT de forma de pago

`scripts/catalogs.py`: mapeo `c_FormaPago` (Anexo 20 CFDI) para traducir el codigo crudo de
`XML FORMA PAGO` (p. ej. `03`) a su descripcion (`Transferencia electronica de fondos`). Se
expone como columna adicional `XML FORMA PAGO (desc)`, sin reemplazar la columna original (el
auditor puede necesitar el codigo crudo para cruzar contra el XML).

## Versionado

Snapshot de esta iteracion en `versions/v1_1/`. `CHANGELOG.md` actualizado.
