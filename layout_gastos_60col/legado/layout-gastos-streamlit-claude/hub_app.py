"""
Hub de reportes Streamlit - punto de entrada compartido para explore.frento.com.mx

Por que existe: el tunel cloudflared (`/etc/cloudflared/config.yml`) mapea el hostname
explore.frento.com.mx a un solo puerto local (8501), y ese puerto lo sirve un unico
servicio systemd (`streamlit-consumo-interno.service`). Para publicar el nuevo reporte
"Layout de Gastos" sin abrir un puerto/hostname nuevo, este hub reemplaza el entrypoint
del servicio: usa `st.navigation` para exponer un menu con todos los reportes (el nuevo y
el que ya corria) dentro del mismo proceso/puerto/tunel.

Ver docs/04_hub_streamlit.md para el detalle de la migracion del servicio systemd.
"""
import os

import streamlit as st

LAYOUT_GASTOS_DIR = os.path.dirname(os.path.abspath(__file__))
CONSUMO_INTERNO_DIR = os.path.join(LAYOUT_GASTOS_DIR, "..", "consumo_interno_trazabilidad")
EXISTENCIA_FECHA_DIR = os.path.join(LAYOUT_GASTOS_DIR, "..", "existencia_a_una_fecha")

st.set_page_config(page_title="Reportes Trivasa", layout="wide", page_icon="📊")
st._layout_gastos_embedded = True  # evita doble set_page_config en las paginas hijas


def home():
    st.title("Reportes Trivasa")
    st.markdown(
        "Selecciona un reporte en el menu de la izquierda.\n\n"
        "- **Layout de Gastos**: reporte extendido de gastos para auditoria externa "
        "(Bates y Asociados). Ver `layout-gastos/docs/`.\n"
        "- **Consumo Interno · FIFO on the fly**: trazabilidad de consumo interno "
        "contra compras (metodo FIFO), agregado por producto.\n"
        "- **Consumo Interno · por línea**: mismo método, una fila por cada línea "
        "real de Consumo_Interno (Ci_Folio + Ci_ID).\n"
        "- **Consumo Interno · Caso simple**: por línea, pero el folio de compra/UUID "
        "solo se calcula para productos cuyo histórico completo es exclusivamente "
        "compra + consumo interno.\n"
        "- **Consumo Interno · normalizado**: agregado por producto como el primero, "
        "pero 1 fila por cada folio/UUID en vez de concatenarlos en una celda.\n"
        "- **Movimientos en un periodo**: movimientos efectivos de inventario (compras, "
        "ventas, producción, ajustes...), reconciliados contra existencia a una fecha.\n"
        "- **Movimientos en un periodo · V2 (UUID compra)**: lo mismo, más cada salida "
        "enlazada a su UUID de factura de compra vía FIFO."
    )


pages = [
    st.Page(home, title="Inicio", icon="🏠", url_path="inicio", default=True),
    st.Page(
        os.path.join(LAYOUT_GASTOS_DIR, "streamlit_app.py"),
        title="Layout de Gastos",
        icon="🧾",
        url_path="layout-gastos",
    ),
    st.Page(
        os.path.join(CONSUMO_INTERNO_DIR, "streamlit_app.py"),
        title="Consumo Interno",
        icon="📦",
        url_path="consumo-interno",
    ),
    st.Page(
        os.path.join(CONSUMO_INTERNO_DIR, "streamlit_app_lineas.py"),
        title="Consumo Interno · por línea",
        icon="🧵",
        url_path="consumo-interno-lineas",
    ),
    st.Page(
        os.path.join(CONSUMO_INTERNO_DIR, "streamlit_app_caso_simple.py"),
        title="Consumo Interno · Caso simple",
        icon="✅",
        url_path="consumo-interno-caso-simple",
    ),
    st.Page(
        os.path.join(CONSUMO_INTERNO_DIR, "streamlit_app_normalizado.py"),
        title="Consumo Interno · normalizado",
        icon="🗂️",
        url_path="consumo-interno-normalizado",
    ),
    st.Page(
        os.path.join(EXISTENCIA_FECHA_DIR, "streamlit_app.py"),
        title="Movimientos en un periodo",
        icon="🔄",
        url_path="movimientos-periodo",
    ),
    st.Page(
        os.path.join(EXISTENCIA_FECHA_DIR, "streamlit_app_uuid_fifo.py"),
        title="Movimientos en un periodo · V2 (UUID compra)",
        icon="🔗",
        url_path="movimientos-periodo-uuid",
    ),
]

nav = st.navigation(pages)
nav.run()
