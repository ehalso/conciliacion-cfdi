"""
reporte_ui_config.py -- UI compartida de CONT-4/CONT-5, los reportes
exploratorios que reemplazan rank-pairing por reconstruccion real via
Poliza_Configuracion (ver layout_gastos_config_lib.py y PROGRESS.md).

Misma pestana de Reconciliacion que CONT-1/CONT-2 (reusa resumen_qa/
resumen_por_folio de layout_gastos_lib.py TAL CUAL -- opera a nivel folio,
no depende del grano de la tabla de Datos). Lo que cambia entre CONT-4 y
CONT-5 es la tabla de Datos: documento (GRD_ID, XML 1:1) vs cuenta
contable (colapsado, XML agregado) -- parametrizado por `grano`.
"""
import io
import os
import sys
from datetime import date, timedelta

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "layout_gastos_poliza"))
from layout_gastos_config_lib import reporte_cont4, reporte_cont5  # noqa: E402
from layout_gastos_lib import resumen_qa, resumen_por_folio  # noqa: E402

VERSION = "v1 (exploratorio)"


@st.cache_data(ttl=1800, show_spinner="Consultando TRIVASADB3 (.205) -- reconstruyendo Poliza_Configuracion...")
def _cargar(grano: str, fecha_ini: str, fecha_fin: str):
    return reporte_cont4(fecha_ini, fecha_fin) if grano == "documento" else reporte_cont5(fecha_ini, fecha_fin)


def render(numero: str, titulo: str, grano: str, key_prefix: str):
    st.title(f"{numero} · {titulo}")
    st.caption(f"Version {VERSION} · Reconstruccion real via Poliza_Configuracion (config 0450) -- no rank-pairing")
    st.warning(
        "**Cobertura parcial**: solo folios cuya poliza vino de la config `0450` "
        "(la dominante de `GASTO_DIRECTO`/`CONTROL_COMBUSTIBLE`/`VIAJE`/`ORDEN_COMPRA`). "
        "No incluye `CONSUMO_INTERNO`, `GASTO_RECLASIFICACION` ni `GASTO_REGISTRO_NOMINA` "
        "-- para el universo completo, ver **CONT-1**/**CONT-2**.",
        icon="⚠️",
    )
    if grano == "documento":
        st.markdown(
            "Grano **`(FOLIO, GRD_ID, CUENTA)`** -- el documento, mismo grano que usa "
            "`Comprobante_Digital` para el XML. Cada renglon de `Poliza_Configuracion` "
            "trae el JOIN real a `Gasto_Registro_Control`, no hay que adivinar por orden."
        )
    else:
        st.markdown(
            "Grano **`(FOLIO, CUENTA_CONTABLE)`** -- colapsa el documento. Construido a "
            "propósito junto a **CONT-4** para comparar: coincide con el documento en "
            "86.28% de los folios, pero falla más donde más importa (ver pestaña "
            "Documentación)."
        )

    with st.sidebar:
        st.subheader("Periodo")
        fecha_ini = st.date_input("Desde", value=date(2026, 1, 1), key=f"{key_prefix}_ini")
        fecha_fin = st.date_input("Hasta", value=date(2026, 1, 31), key=f"{key_prefix}_fin")

    if fecha_ini > fecha_fin:
        st.error("La fecha 'Desde' debe ser anterior o igual a 'Hasta'.")
        return

    datos = _cargar(grano, str(fecha_ini), str(fecha_fin + timedelta(days=1)))

    if datos.empty:
        st.warning("No hay folios de la config 0450 en ese periodo.")
        return

    with st.sidebar:
        st.subheader("Filtros")
        origenes = sorted(datos["ORIGEN"].dropna().unique())
        f_origen = st.multiselect("Origen", origenes, default=origenes, key=f"{key_prefix}_origen")
        buscar = st.text_input("Buscar (folio, cuenta)", key=f"{key_prefix}_buscar")

    df = datos[datos.ORIGEN.isin(f_origen)].copy()
    if buscar:
        campos = ["FOLIO", "CUENTA", "CUENTA_DESCRIPCION"]
        mask = pd.Series(False, index=df.index)
        for c in campos:
            mask |= df[c].astype(str).str.contains(buscar, case=False, na=False)
        df = df[mask]

    k1, k2, k3 = st.columns(3)
    k1.metric("Filas", f"{len(df):,}")
    k2.metric("Folios", f"{df.FOLIO.nunique():,}")
    if grano == "documento":
        pct_xml = 100 * df.TIENE_XML.sum() / len(df) if len(df) else 0
        k3.metric("% con XML ligado", f"{pct_xml:.2f}%",
                   help="Documentos (FOLIO, GRD_ID) con un CFDI ligado en Comprobante_Digital.")
    else:
        pct_amb = 100 * df.AMBIGUO.sum() / len(df) if len(df) else 0
        k3.metric("% filas ambiguas", f"{pct_amb:.2f}%",
                   help="Filas donde el numero de documentos y el numero de XML no coincide -- "
                        "el grano cuenta contable no corresponde limpio a un solo documento.")

    k4, k5, k6 = st.columns(3)
    k4.metric("Σ Cargo", f"${df.CARGO.sum():,.2f}")
    k5.metric("Σ Abono", f"${df.ABONO.sum():,.2f}",
              help="0 para esta config: el Abono queda consolidado a nivel proveedor dentro "
                   "de una poliza que a su vez consolida varios folios -- no atribuible por "
                   "folio aqui. Ver pestaña Documentación.")
    importe_mpro = df.drop_duplicates("FOLIO")["IMPORTE_FOLIO"].sum()
    k6.metric("Importe reporte MPRO", f"${importe_mpro:,.2f}",
              help="Importe nativo por folio (Gasto_Registro_Documento) -- misma cifra que "
                   "reporta MPRO. 1 valor por folio, no por línea.")

    tab_datos, tab_recon, tab_docs = st.tabs(["Datos", "Reconciliación", "Documentación"])

    if grano == "documento":
        columnas = ["FOLIO", "ORIGEN", "GRD_ID", "CUENTA", "CUENTA_DESCRIPCION", "CARGO", "ABONO",
                    "TIENE_XML", "XML_UUID", "XML_MONTO", "XML_RFC_EMISOR", "XML_FACTURA"]
    else:
        columnas = ["FOLIO", "ORIGEN", "CUENTA", "CUENTA_DESCRIPCION", "CARGO", "ABONO",
                    "N_DOCUMENTOS", "N_XML", "AMBIGUO", "XML_UUIDS", "XML_MONTO_TOTAL"]

    with tab_datos:
        st.dataframe(df[columnas], width="stretch", height=560, hide_index=True)
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df[columnas].to_excel(writer, index=False, sheet_name=numero)
        st.download_button(
            "Descargar Excel (filtrado)", data=buf.getvalue(),
            file_name=f"layout_gastos_{numero}_{fecha_ini}_{fecha_fin}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{key_prefix}_download",
        )

    with tab_recon:
        st.markdown(
            "Compara, **por folio**, `Cargo - Abono` contra el importe nativo del folio "
            "(`Importe reporte MPRO`) -- idéntica lógica y misma función que **CONT-1**/"
            "**CONT-2**, sin importar el grano más fino de la tabla de Datos."
        )
        qa = resumen_qa(df)
        for _, row in qa.iterrows():
            if row.pct >= 99.9:
                st.success(f"**{row.ORIGEN}** -- {int(row.cuadran):,}/{int(row.folios):,} folios ({row.pct}%)")
            elif row.pct >= 95:
                st.warning(f"**{row.ORIGEN}** -- {int(row.cuadran):,}/{int(row.folios):,} folios ({row.pct}%)")
            else:
                st.error(f"**{row.ORIGEN}** -- {int(row.cuadran):,}/{int(row.folios):,} folios ({row.pct}%)")
        st.dataframe(qa, width="stretch", hide_index=True)

        pf = resumen_por_folio(df)
        mal_folio = pf[~pf.CUADRA].sort_values("DIFERENCIA", key=lambda s: s.abs(), ascending=False)
        st.markdown(f"**Folios que no cuadran:** {len(mal_folio):,}")
        if len(mal_folio):
            tabla_mal = mal_folio.rename(columns={"IMPORTE_FOLIO": "IMPORTE REPORTE MPRO"})[
                ["FOLIO", "ORIGEN", "CARGO", "ABONO", "IMPORTE REPORTE MPRO", "DIFERENCIA"]
            ]
            st.dataframe(tabla_mal, width="stretch", hide_index=True)

    with tab_docs:
        st.markdown(
            "**Metodología completa:** `PROGRESS.md`, entrada \"Rank-pairing vs. "
            "reconstrucción real vía `Poliza_Configuracion`\", en este mismo directorio "
            "(y su versión promovida en `trivasa-context/docs/proyectos/layout-gastos/`).\n\n"
            "**Por qué existe esto:** el rank-pairing de CONT-1/CONT-2 (ordenar por valor "
            "dentro de `(FOLIO, CECO)` y emparejar por posición) no tiene llave real "
            "visible entre `Gasto_Registro_Control` y `Poliza_Detalle` -- pero sí existe "
            "una llave real un nivel más abajo: `Poliza_Configuracion_Detalle.Pcd_Relacion` "
            "ya hace el JOIN real por `(Gr_Folio, Grd_ID)` que usa el motor de MPRO para "
            "generar cada renglón de póliza. Reconstruirlo da una llave real en 99.61% de "
            "los casos probados (config `0450`), 0.39% queda irreducible -- ni el propio "
            "motor lo distingue, lo descartó al generar el dato.\n\n"
            "**Por qué documento y no cuenta contable para el XML:** el CFDI liga a "
            "`Comprobante_Digital.Cd_Documento`, que decodificado es `Gr_Folio + Grd_ID` -- "
            "el documento, no la cuenta. Comparado con datos reales: 86.28% de los folios "
            "tienen el mismo número de documentos que de cuentas (y de esos, 99.86% son "
            "biyección real), pero el 13.72% restante diverge -- y ese grupo divergente "
            "tiene MÁS XML ligado (81.77%) que el que sí coincide (61.92%). Agrupar por "
            "cuenta falla justo donde más importa.\n\n"
            "**Contra qué se compara el monto del XML:** `Grd_Precio_Neto_Importe` "
            "(importe nativo del documento, con impuesto -- mismo campo que usa "
            "`IMPORTE_FOLIO` a nivel folio), no `CARGO` (neto de póliza, sin impuesto -- "
            "el IVA vive en otro renglón). Agrupado por `XML_UUID`, no por documento: "
            "1.83% de los XML se repiten en varios `Grd_ID` (una factura partida en N "
            "líneas idénticas queda registrada como N documentos que apuntan al mismo "
            "CFDI) -- sumar antes de comparar. Con esas dos correcciones: **97.76% "
            "(1,922/1,966 XML_UUID)** cuadra exacto contra `Cd_Monto`; el residual no se "
            "investigó a fondo, parece concentrado en documentos en USD (posible doble "
            "aplicación de tipo de cambio).\n\n"
            "**Abono en 0**: para la config `0450`, una sola `Poliza` consolida varios "
            "`Gasto_Registro` folios a la vez (confirmado con datos reales) -- el Abono "
            "(pago a proveedor) queda a nivel de esa póliza consolidada, con "
            "`Pd_Referencia` = referencia de la factura del proveedor, no `Gr_Folio`. No "
            "es atribuible por folio con la información disponible; se deja la columna "
            "(no se oculta) por honestidad y por si se generaliza a otra config donde sí "
            "aplique.\n\n"
            "**Cobertura**: solo config `0450`, 1 de ~67 configs distintas del universo de "
            "`layout-gastos`. Generalizar a las demás queda pendiente."
        )
