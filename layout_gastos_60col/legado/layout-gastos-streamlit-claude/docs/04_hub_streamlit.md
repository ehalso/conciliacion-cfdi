# Hito — publicación en Streamlit, menú compartido con el reporte existente

## Arquitectura

`explore.frento.com.mx` esta mapeado por `cloudflared` (`/etc/cloudflared/config.yml`) a
`http://localhost:8501`, servido por un unico proceso systemd. Antes de este hito ese proceso
corria `consumo_interno_trazabilidad/streamlit_app.py` directamente. Para publicar el nuevo
"Layout de Gastos" **sin abrir un puerto/hostname nuevo** (instrucción explícita del usuario:
"usa el mismo tunnel... has menú para cada reporte nuevo, más el que ya está corriendo"), se
reemplazó el entrypoint por un hub (`layout-gastos/hub_app.py`) que usa `st.navigation` /
`st.Page` para exponer ambos reportes como paginas de una misma app, en el mismo puerto.

```
cloudflared (explore.frento.com.mx) -> localhost:8501 -> streamlit-hub.service -> hub_app.py
                                                                                    ├── Inicio
                                                                                    ├── Layout de Gastos      (layout-gastos/streamlit_app.py)
                                                                                    └── Consumo Interno       (consumo_interno_trazabilidad/streamlit_app.py, sin cambios de fondo)
```

## Cambios hechos

1. `layout-gastos/hub_app.py` (nuevo): entrypoint con `st.navigation`, referencia ambos scripts
   por ruta absoluta.
2. `consumo_interno_trazabilidad/streamlit_app.py`: el `st.set_page_config(...)` de la linea 29
   se envolvió en `try/except st.errors.StreamlitAPIException` — necesario porque solo puede
   llamarse una vez por sesion, y el hub ya lo llama antes de despachar a cualquier pagina. Es
   el **unico** cambio al reporte existente; su logica de consulta no se toco.
3. Servicio systemd: se retiro `streamlit-consumo-interno.service` (deshabilitado, no borrado —
   backup del unit file original en `/etc/systemd/system/streamlit-consumo-interno.service.bak-pre-hub`)
   y se creo `streamlit-hub.service` apuntando a `hub_app.py`, mismo puerto (8501),
   mismo `127.0.0.1`, usando el venv de `layout-gastos` (tiene todas las dependencias de ambos
   reportes: streamlit, pandas, sqlalchemy, pymssql, openpyxl).

## Validación antes del corte

- `streamlit.testing.v1.AppTest` sobre `layout-gastos/streamlit_app.py` standalone: sin
  excepciones, 4 metricas, 2 tablas, 3 tabs — resultado esperado.
- `AppTest` sobre `consumo_interno_trazabilidad/streamlit_app.py` standalone, con **ambos** venvs
  (el propio y el de `layout-gastos`): sin excepciones en ninguno — confirma que el venv
  compartido es compatible antes de tocar el servicio real.
- Servidor real de `hub_app.py` en un puerto alterno (8511) antes del corte: `curl` a `/`,
  `/inicio`, `/layout-gastos`, `/consumo-interno` — los 4 devolvieron 200, sin trazas de error en
  el log del servidor.
- Después del corte (servicio real en 8501): mismas 4 rutas verificadas en 200, servicio estable
  (mismo PID, sin reinicios) pasados ~50 segundos.

## Incidente durante la migración (transparencia)

A las 07:04:46 UTC, mientras se hacían las pruebas de validación (antes de tocar el servicio),
`streamlit-consumo-interno.service` se detuvo solo (log: "Stopping..." seguido de
"Deactivated successfully", exit code 0 — no fue un crash). No se encontro ningun
`systemctl stop` en el journal en ese rango, y los comandos `pkill` usados en esta sesión
apuntaban a patrones con puertos distintos (8510/8511) que no calzan por substring con el
comando real del servicio (puerto 8501) — no se identificó una causa concluyente. Se
restauró el servicio de inmediato (`systemctl start`) y se confirmó sano (HTTP 200) antes de
continuar con cualquier otro cambio. Mencionado aquí por transparencia; si vuelve a ocurrir
conviene revisar si hay algun límite de recursos o watchdog externo no documentado en este
repo.

## Cómo hacer rollback

```bash
sudo systemctl stop streamlit-hub.service
sudo systemctl disable streamlit-hub.service
sudo cp /etc/systemd/system/streamlit-consumo-interno.service.bak-pre-hub \
        /etc/systemd/system/streamlit-consumo-interno.service
sudo systemctl daemon-reload
sudo systemctl enable --now streamlit-consumo-interno.service
```

Esto revierte a exactamente el estado previo (mismo unit file, mismo venv, mismo comando).
