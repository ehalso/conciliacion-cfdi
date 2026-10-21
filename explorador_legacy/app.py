import os
import streamlit as st
from catalogo import CATALOGO

st.set_page_config(page_title="Explorador legacy", layout="wide")
host = (st.context.headers.get("Host") or "localhost").split(":")[0]

st.title("Explorador de apps legacy")
st.caption("Clasificación propuesta: aún no se movió ni borró nada. Cada app legacy corre en su propio puerto.")

ICON = {"VIVO": "🟢", "LEGACY": "🟠", "HISTORICO": "⚪"}
filtro = st.multiselect("Estado", ["LEGACY", "HISTORICO", "VIVO"], default=["LEGACY", "HISTORICO", "VIVO"])
grupos = []
for e in CATALOGO:
    if e["estado"] in filtro and e["grupo"] not in grupos:
        grupos.append(e["grupo"])

for g in grupos:
    st.header(g)
    for e in [x for x in CATALOGO if x["grupo"] == g and x["estado"] in filtro]:
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(f"**{ICON[e['estado']]} {e['nombre']}**  ·  `{e['estado']}`")
                st.caption(e["nota"])
                st.code(e["ruta"], language=None)
            with c2:
                if e["puerto"]:
                    st.link_button(f"Abrir :{e['puerto']}", f"http://{host}:{e['puerto']}{e.get('ruta_url', '/')}")
            if e["readme"] and os.path.exists(e["readme"]):
                with st.expander("Ver README"):
                    st.markdown(open(e["readme"], encoding="utf-8").read())
