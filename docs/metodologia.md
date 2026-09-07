# Metodología

Hay tres niveles de conciliación en este repo, de más simple a más
detallado. Cada uno responde una pregunta distinta.

## Nivel 1 — Existencia e importe por CFDI (`main.py` / `src/reconcile.py`)

Pregunta: **¿el CFDI que el SAT dice que existe, existe también en mpro
(algún módulo lo timbró/registró), y el importe coincide?**

- Universo: todos los CFDI de `raw_sat.cfdi_recibidos` para el/los
  periodo(s) pedidos.
- Para cada UUID, se busca en `Comprobante_Digital` (puede aparecer en más
  de un `Cd_Tabla`); se toma el primer XML parseable y se comparan
  `subtotal`, `iva`, `total` contra los mismos campos del lado SAT, con
  tolerancia de $1.00 por campo (ajustable con `--tolerancia`).
- Estatus posibles: `OK`, `DIFERENCIA_IMPORTE`, `MPRO_SIN_XML` (existe el
  registro en mpro pero no se pudo parsear o no trae XML),
  `SOLO_SAT`/`SOLO_MPRO`/`SOLO_MPRO_SIN_XML`.
- Este nivel **no toca pólizas ni cuentas contables** — solo compara el
  CFDI (SAT) contra el XML que mpro tiene almacenado del mismo CFDI. Sirve
  para detectar CFDIs que nunca entraron a mpro, o que entraron con un
  importe distinto al timbrado.

## Nivel 2 — Trazabilidad a póliza, agnóstica de origen (`poliza_reconciliation.py`, piloto)

Pregunta: **¿este CFDI tiene huella contable (alguna póliza activa lo
referencia), y esa huella cuadra con el total?**

Usa `Poliza_Detalle_Comprobante` — un anexo que liga directamente
`(Pl_Folio, Pd_ID)` con el UUID del CFDI, sin pasar por
`Comprobante_Digital`. Cobertura parcial (~34% de las pólizas lo llenan),
y no garantiza que ambos lados de la partida doble (cargo y abono) queden
etiquetados con el mismo UUID — así que no se fuerza que cuadren, se
reporta lo que hay. Este nivel fue el piloto que validó que la ruta
CFDI→póliza es viable antes de construir el nivel 3, más preciso.

## Nivel 3 — Por origen de documento, con dos formas de cuadre (`reconciliacion_por_origen.py`)

Pregunta real de negocio (formulada por Esteban): **de la base de CFDI que
sí tienen un documento de mpro con XML adjunto, ¿la suma de lo
contabilizado en cuentas y pólizas es igual a la suma de esos CFDI? Y,
sobre todo, ¿qué tipos de documento de mpro (Compra, Gasto, Cheque, Nota
de Crédito, ...) son los que hay que reconciliar?**

### La base: solo documentos con XML adjunto

El universo son los CFDI de SAT que aparecen en `Comprobante_Digital`
(es decir, mpro ya les asoció un XML). Los documentos de mpro que **no**
tienen ningún CFDI/XML adjunto quedan fuera del alcance por ahora — no se
intenta reconciliar "todo mpro", solo la porción que ya cruza con SAT.
Esto es una decisión de alcance explícita de Esteban (2026-09-07), no un
descuido.

### Trazar cada CFDI a su origen real

`Comprobante_Digital.Cd_Tabla` dice el módulo (Compra, Gasto_Registro,
Cheque, Cuenta_x_Pagar, Nota_Credito_Proveedor, Compra_Indirecto, ...) y
`Cd_Documento` el folio — con truco: `Cd_Documento` trae el folio real (10
caracteres, formato `XX-NNNNNNN`) **más un sufijo de 4 a 8 caracteres**
(identificador de sub-documento/línea) que **no** existe en
`Poliza_Control.Pc_Documento`. Se trunca a los primeros 10 caracteres
antes de cualquier join — ver `hallazgos.md` para la evidencia.

### Aislar el cargo/abono correcto dentro de la póliza

Una póliza en mpro puede consolidar varios documentos del mismo origen
(ej. varias compras del mismo día en una sola póliza). Sumar todo
`Poliza_Detalle` de esa póliza sobreestima brutalmente. La corrección —
ya usada en el proyecto `layout-gastos` para Gasto_Registro y generalizada
aquí a los demás orígenes — es filtrar además por
`Poliza_Detalle.Pd_Referencia = <folio real>`, que aísla justo las líneas
de ese documento.

Excepción: **Cheque**. Ahí `Pd_Referencia` es poco confiable (documentado
en el proyecto `poliza-explor`: ~72% de las veces trae una referencia
externa del banco, no el folio del cheque). El método alterno es
match por monto: `ABS(Poliza_Detalle.Pd_Importe - Cheque.Ch_Importe) <= 1`.

### Dos formas de comparar — documento y agregado

**a) Documento por documento** (columna `estatus` en las hojas
`Resumen_por_documento` / `Detalle`): para cada documento real, se compara
su cargo (o abono) contra el total del/los CFDI que cubre, y si no
cuadra, contra el subtotal. `CUADRA` si alguno de los dos cuadra dentro de
$1; si no, `CON_POLIZA_SIN_CUADRAR`; si no se encontró ninguna póliza,
`SIN_POLIZA`. Cheque tiene su propia regla: si el método de match por
monto encontró algo, ya cuadra por construcción (ver `hallazgos.md` sobre
por qué no tiene sentido comparar Cheque contra el total del CFDI).

**b) Agregado por origen** (hoja `Cuadre_Agregado`) — pedido explícito de
Esteban: no exigir que cada documento cuadre individualmente, sino sumar
TODO el cargo/abono contabilizado de la base de un origen y compararlo
contra la suma de subtotal/total de esos mismos CFDI. Esto es más
indulgente con casos donde el desglose documento a documento falla por
partición (un gasto repartido en muchos centros de costo, una nota de
crédito partida en dos folios) pero el total, sumado, sí coincide. En la
práctica el agregado y el detalle cuentan historias distintas por origen —
ver `resultados_2026-02.md`.

### ¿Por qué a veces se compara contra subtotal y no contra total?

Para Compra, Cuenta_x_Pagar y buena parte de Gasto_Registro, el cargo
aislado por `Pd_Referencia` cae en una cuenta de inventario/gasto **sin
IVA** — el IVA se postea en una línea/cuenta aparte que no lleva la misma
referencia. Por eso se compara primero contra el total y, si no cuadra,
contra el subtotal — ver el hallazgo detallado en `hallazgos.md`.

### Tolerancia

$1.00 MXN por comparación, en todos los niveles (`TOLERANCIA` en cada
script) — margen para redondeos, no para diferencias reales.
