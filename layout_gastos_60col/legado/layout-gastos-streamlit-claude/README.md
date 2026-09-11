# Layout de gastos

Reporte extendido de gastos para la auditoria externa trimestral (Bates y Asociados). Ver
`docs/00_requerimiento.md` para el requerimiento completo y `docs/` en general para el resto de
la documentacion (modelo de datos, bugs conocidos del Excel de referencia, hitos de cada
iteracion).

## Estructura

```
layout-gastos/
├── docs/                 documentacion por hito (00_requerimiento, 01_hallazgos_excel..., etc)
├── scripts/
│   ├── db.py              conexion compartida a TRIVASADB3
│   ├── layout_gastos_v1.py  extraccion (cabecera + poliza) y vista agrupada
│   └── validate.py         comprobacion cuantitativa (Cargo-Abono vs Subtotal Neto)
├── data/                  parquet cacheado de enero 2025 (evita golpear la BD en cada iteracion)
├── output/                CSVs de reconciliacion generados por validate.py
├── streamlit_app.py       la app del reporte (standalone o embebida en el hub)
├── hub_app.py             entrypoint que sirve este reporte + Consumo Interno en un solo menu
├── versions/              snapshots congelados por version (ver CHANGELOG.md)
├── CHANGELOG.md
└── streamlit_venv/        venv local (streamlit, pandas, sqlalchemy, pymssql, openpyxl)
```

## Correr localmente

```bash
cd layout-gastos
./streamlit_venv/bin/streamlit run streamlit_app.py --server.port 8502
```

## En produccion

Servido por `streamlit-hub.service` (systemd) en el puerto 8501, expuesto via cloudflared en
`explore.frento.com.mx`. Ver `docs/04_hub_streamlit.md` para la arquitectura completa y el
procedimiento de rollback.

## Regenerar la extraccion de un periodo

```bash
cd scripts
../streamlit_venv/bin/python3 validate.py 2025-01-01 2025-02-01 --out ../output/reconciliacion_2025_01.csv
```
