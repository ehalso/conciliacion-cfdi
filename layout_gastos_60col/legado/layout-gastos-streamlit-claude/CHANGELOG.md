# Changelog — Layout de Gastos

Formato: cada hito documentado en `docs/NN_*.md`, snapshot de código congelado en
`versions/vN/`. El código "vivo" (el que corre en produccion) siempre está en la raíz
(`streamlit_app.py`, `hub_app.py`, `scripts/`) — `versions/` es solo un respaldo para poder
revertir si una iteración degrada el reporte.

## v1.1 — 2026-07-26

- **Fix de correctitud** en la vista agrupada (`group_by_cuenta_contable`): podia devolver mas de
  una fila por operacion cuando una operacion tenia mas lineas de poliza que filas de cabecera
  (columnas de cabecera en NULL rompian el agrupamiento). Ahora agrupa `poliza` de forma
  independiente y pega la cabecera deduplicada — garantiza 1 fila por `(Operacion, Cuenta
  Registro)` y que ninguna operacion desaparezca. Ver `docs/05_hito_v1_1.md`.
- Catalogo SAT de forma de pago (`scripts/catalogs.py`): traduce el codigo crudo (`03`) a su
  descripcion (`Transferencia electronica de fondos`) en una columna adicional.

Revertir a v1.1 (superset de v1, no deberia hacer falta salvo degradacion de este mismo hito):

```bash
cp versions/v1_1/streamlit_app.py streamlit_app.py
cp versions/v1_1/hub_app.py hub_app.py
cp versions/v1_1/scripts/*.py scripts/
sudo systemctl restart streamlit-hub.service
```

## v1 — 2026-07-26

- Primera extraccion funcional del Layout de Gastos (vista base + vista agrupada por cuenta
  contable) contra `TRIVASADB3`, ancla en `Gasto_Registro` (excluye `CONSUMO_INTERNO` y
  `GASTO_REGISTRO_NOMINA` por construccion).
- Reconciliación cuantitativa (Cargo - Abono vs Subtotal Neto) validada sobre enero 2025
  completo: **brecha +0.89%** (3,584 folios). Ver `docs/03_hito_v1.md` para las 5 correcciones
  que se hicieron para llegar ahí (empezó en -35.7%).
- Publicado en Streamlit, integrado al hub compartido (`hub_app.py`) que sirve tambien el
  reporte de Consumo Interno ya existente, mismo puerto/tunel (`explore.frento.com.mx`). Ver
  `docs/04_hub_streamlit.md`.
- Pendiente conocido (no bloqueante): desglose Subtotal 0%/16%/exento (requiere parseo de XML),
  catalogo SAT de forma de pago, ~1.5% de folios con diferencia residual sin explicar del todo.

Para revertir a esta version si una iteracion futura degrada el reporte:

```bash
cp versions/v1/streamlit_app.py streamlit_app.py
cp versions/v1/hub_app.py hub_app.py
cp versions/v1/scripts/layout_gastos_v1.py scripts/layout_gastos_v1.py
cp versions/v1/scripts/validate.py scripts/validate.py
sudo systemctl restart streamlit-hub.service
```
