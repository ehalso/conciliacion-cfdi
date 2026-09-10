"""
reporte_ui_xml_documento.py -- UI de CONT-6: version de CONT-1/CONT-2, mismo
universo (6-7 origenes de `Gasto_Registro` via `Gr_Tabla`, incluye NOMINA),
pero a grano `(FOLIO, DOC_ID=Grd_ID)` en vez de `(FOLIO, CECO, TIPO_GASTO)`
-- por eso trae **UUID/CFDI** en vez de **Poliza/Cuenta** (ese detalle
contable vive del lado de `Poliza_Detalle`, a un grano mas fino que este
reporte no baja). Wrapper delgado de `xml_documento_lib.reporte_completo`,
que a su vez reusa `adjuntar-xml/conciliacion_xml_lib.py` -- ver docstring
de ese modulo y `PROGRESS.md` (entrada 2026-09-08/09) para la metodologia
completa.
"""
import io
import os
import sys
from datetime import date, timedelta

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "recibidos", "nivel_documento"))
from xml_documento_lib import reporte_completo, resumen_reconciliacion, buscar_cfdi  # noqa: E402

VERSION = "v2"

CLASE_ORDEN = [
    "CON_XML_CONCILIA", "CON_XML_DIF_CENTAVOS", "CON_XML_IMPORTE_EN_COMPLEMENTO",
    "CON_XML_DIF_MATERIAL", "SIN_XML_ORIGEN_INTERNO", "SIN_XML_CFDI_EN_ORIGEN",
    "SIN_XML_CANCELADO", "SIN_XML_IMPORTE_NEGATIVO", "SIN_XML_TRASPASO_INTERNO",
    "SIN_XML_PENDIENTE", "SIN_XML_IMPORTE_CERO",
]


@st.cache_data(ttl=1800, show_spinner="Consultando TRIVASADB3 (.205) y parseando CFDI...")
def _cargar_reporte(fecha_ini: str, fecha_fin: str):
    # Solo GASTO_REGISTRO -- mismo universo que CONT-1/CONT-2, no los otros
    # 6 modulos que cubre adjuntar-xml/04 (Compra, Cheque, CXP, etc.).
    return reporte_completo(fecha_ini, fecha_fin, origenes=["GASTO_REGISTRO"])


@st.cache_data(ttl=3600, show_spinner="Buscando y parseando el CFDI...")
def _buscar_cfdi(uuid: str):
    return buscar_cfdi(uuid)


def render(numero: str = "CONT-6", titulo: str = "Layout de Gastos por Documento con XML", key_prefix: str = "cont6"):
    st.title(f"{numero} · {titulo}")
    st.caption(f"Version {VERSION} · Mismo universo que CONT-1/CONT-2 (Gasto_Registro), grano documento con XML adjunto")
    st.markdown(
        "Incluye `CONTROL_COMBUSTIBLE`, `GASTO_DIRECTO`, `GASTO_RECLASIFICACION`, "
        "`ORDEN_COMPRA`, `VIAJE`, `CONSUMO_INTERNO` y `GASTO_REGISTRO_NOMINA` -- los "
        "mismos orígenes que CONT-1/CONT-2. Grano **`(FOLIO, DOC_ID)`** -- `DOC_ID` es "
        "`Grd_ID` -- en vez de `(FOLIO, CECO, TIPO_GASTO)`: a este nivel más grueso no "
        "aplican `Póliza`/`Cuenta`/`CECO` (viven del lado de `Poliza_Detalle`, un grano "
        "más fino) -- en su lugar trae el **CFDI (UUID)** adjunto a cada documento."
    )

    with st.sidebar:
        st.subheader("Periodo")
        fecha_ini = st.date_input("Desde", value=date(2026, 1, 1), key=f"{key_prefix}_ini")
        fecha_fin = st.date_input("Hasta", value=date(2026, 1, 31), key=f"{key_prefix}_fin")

    if fecha_ini > fecha_fin:
        st.error("La fecha 'Desde' debe ser anterior o igual a 'Hasta'.")
        return

    # Ambas fechas del sidebar son inclusivas -- la capa de datos usa
    # limite superior EXCLUSIVO (fecha < fecha_fin), se traduce aqui.
    datos = _cargar_reporte(str(fecha_ini), str(fecha_fin + timedelta(days=1)))

    with st.sidebar:
        st.subheader("Filtros")
        origenes = sorted(datos["SUBORIGEN"].dropna().unique())
        f_origen = st.multiselect("Origen", origenes, default=origenes, key=f"{key_prefix}_origen")
        clases_presentes = [c for c in CLASE_ORDEN if c in set(datos["CLASE"].dropna().unique())]
        f_clase = st.multiselect("Clase", clases_presentes, default=clases_presentes, key=f"{key_prefix}_clase")
        buscar = st.text_input("Buscar (folio, proveedor, concepto, UUID)", key=f"{key_prefix}_buscar")

    df = datos[datos.SUBORIGEN.isin(f_origen) & datos.CLASE.isin(f_clase)].copy()
    if buscar:
        campos = ["FOLIO", "DOC_ID", "PROVEEDOR", "CONCEPTO", "UUIDS"]
        mask = pd.Series(False, index=df.index)
        for c in campos:
            mask |= df[c].astype(str).str.contains(buscar, case=False, na=False)
        df = df[mask]

    con_xml = df.N_XML > 0
    uno_a_uno = df.FORMA == "1:1"
    k1, k2, k3 = st.columns(3)
    k1.metric("Documentos", f"{len(df):,}")
    k2.metric("Folios", f"{df.FOLIO.nunique():,}")
    k3.metric("% con XML", f"{100*con_xml.mean():.1f}%" if len(df) else "—",
              help="Al menos 1 CFDI ligado. No es indicador de riesgo por sí solo -- "
                   "CONSUMO_INTERNO/NOMINA/RECLASIFICACION nunca llevan CFDI de proveedor, ver pestaña Reconciliación.")

    k4, k5, k6 = st.columns(3)
    k4.metric("% 1:1 (de los que tienen XML)",
              f"{100*uno_a_uno.sum()/con_xml.sum():.1f}%" if con_xml.sum() else "—",
              help="FORMA='1:1' -- exactamente 1 documento con exactamente 1 CFDI, sin facturas partidas ni consolidadas.")
    k5.metric("Σ Total", f"${df.TOTAL.sum():,.2f}")
    pend = df[df.CLASE == "SIN_XML_PENDIENTE"]
    k6.metric("Pendiente real (SIN_XML_PENDIENTE)", f"{len(pend):,} docs",
              help="Importe registrado, no cancelado, sin CFDI propio ni en su documento origen -- el único hueco sin explicación estructural.")

    tab_datos, tab_recon, tab_cfdi, tab_docs = st.tabs(["Datos", "Reconciliación", "Ver CFDI", "Documentación"])

    columnas_reporte = [
        "FOLIO", "SUBORIGEN", "DOC_ID", "FECHA", "ESTADO", "PROVEEDOR", "CONCEPTO",
        "MONEDA", "SUBTOTAL", "IMPUESTOS", "TOTAL", "UUIDS", "CLASE", "FORMA", "DIF_GRUPO",
    ]
    RENOMBRE = {"SUBORIGEN": "ORIGEN", "UUIDS": "UUID"}

    with tab_datos:
        st.dataframe(
            df[columnas_reporte].rename(columns=RENOMBRE),
            width="stretch", height=560, hide_index=True,
        )
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df[columnas_reporte].rename(columns=RENOMBRE).to_excel(
                writer, index=False, sheet_name="Layout Gastos Documento XML"
            )
        st.download_button(
            "Descargar Excel (filtrado)", data=buf.getvalue(),
            file_name=f"layout_gastos_documento_xml_{fecha_ini}_{fecha_fin}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{key_prefix}_download",
        )

    with tab_recon:
        st.markdown(
            "Cobertura y correspondencia **1:1** (documento↔XML) por origen (`Gr_Tabla`), "
            "a grano `(FOLIO, DOC_ID)` -- sobre los datos ya filtrados en el sidebar. "
            "**Uno a uno** = exactamente 1 documento con exactamente 1 CFDI (sin facturas "
            "partidas ni consolidadas, `FORMA='1:1'`) -- la correspondencia más limpia "
            "posible. `% con XML` incluye también 1:N/N:1/N:M (CFDI compartido entre "
            "varios documentos)."
        )
        recon = resumen_reconciliacion(df).drop(columns=["ORIGEN"]).rename(columns={"SUBORIGEN": "ORIGEN"})
        st.dataframe(
            recon.rename(columns={
                "N": "Documentos", "CON_XML": "Con XML", "UNO_A_UNO": "Uno a uno (1:1)",
                "IMPORTE": "Importe", "PCT_CON_XML": "% con XML", "PCT_SIN_XML": "% sin XML",
                "PCT_1A1_TOTAL": "% 1:1 (del total)", "PCT_1A1_CON_XML": "% 1:1 (de con XML)",
            }),
            width="stretch", hide_index=True, height=min(35 * (len(recon) + 1) + 3, 400),
        )

        st.divider()
        st.markdown(
            "**Semáforo por `CLASE`** -- ver pestaña Documentación para qué significa cada una. "
            "Verde = ya conciliado o explicado por diseño; amarillo = diferencia menor o en "
            "complemento; rojo = pendiente real o diferencia material sin explicar."
        )
        VERDE = {"CON_XML_CONCILIA", "SIN_XML_ORIGEN_INTERNO", "SIN_XML_CFDI_EN_ORIGEN",
                 "SIN_XML_CANCELADO", "SIN_XML_IMPORTE_NEGATIVO", "SIN_XML_TRASPASO_INTERNO",
                 "SIN_XML_IMPORTE_CERO"}
        AMARILLO = {"CON_XML_DIF_CENTAVOS", "CON_XML_IMPORTE_EN_COMPLEMENTO"}
        cob = df.groupby("CLASE").agg(DOCS=("FOLIO", "size"), IMPORTE=("TOTAL", "sum"))
        orden_presente = [c for c in CLASE_ORDEN if c in cob.index]
        cob = cob.reindex(orden_presente)
        for clase, row in cob.iterrows():
            texto = f"**{clase}** -- {int(row.DOCS):,} docs, ${row.IMPORTE:,.2f}"
            if clase in VERDE:
                st.success(texto)
            elif clase in AMARILLO:
                st.warning(texto)
            else:
                st.error(texto)

        if len(pend):
            st.markdown("**`SIN_XML_PENDIENTE` por origen** -- el hueco real, sin explicación estructural:")
            st.dataframe(
                pend.groupby("SUBORIGEN").agg(DOCS=("FOLIO", "size"), IMPORTE=("TOTAL", "sum")).reset_index()
                    .rename(columns={"SUBORIGEN": "ORIGEN"}).sort_values("IMPORTE", ascending=False),
                width="stretch", hide_index=True,
            )
            st.markdown("**Mayores documentos sin CFDI:**")
            st.dataframe(
                pend.nlargest(15, "TOTAL")[["SUBORIGEN", "FOLIO", "DOC_ID", "FECHA", "PROVEEDOR", "CONCEPTO", "TOTAL"]]
                    .rename(columns={"SUBORIGEN": "ORIGEN"}),
                width="stretch", hide_index=True,
            )

        dif_material = df[df.CLASE == "CON_XML_DIF_MATERIAL"]
        if len(dif_material):
            st.markdown(f"**`CON_XML_DIF_MATERIAL`** -- {len(dif_material):,} documentos con XML pero diferencia real sin explicar:")
            mayores_dif = dif_material.reindex(
                dif_material.DIF_GRUPO.abs().sort_values(ascending=False).index
            ).head(15)
            st.dataframe(
                mayores_dif[["SUBORIGEN", "FOLIO", "DOC_ID", "PROVEEDOR", "TOTAL", "XML_GRUPO", "MPRO_GRUPO", "DIF_GRUPO", "FORMA", "UUIDS"]]
                    .rename(columns={"SUBORIGEN": "ORIGEN", "UUIDS": "UUID"}),
                width="stretch", hide_index=True,
            )

    with tab_cfdi:
        st.markdown(
            "Busca un CFDI por su **UUID** (Timbre Fiscal Digital) y muestra sus campos "
            "parseados -- legible, no el XML crudo (el XML crudo queda disponible abajo "
            "en un expander, por si hace falta)."
        )
        uuids_disponibles = sorted({u for s in df.UUIDS.dropna() for u in s.split(";") if u})
        col_a, col_b = st.columns([2, 1])
        with col_a:
            uuid_sel = st.selectbox(
                "UUID (de los documentos filtrados arriba)",
                [""] + uuids_disponibles, key=f"{key_prefix}_uuid_sel",
            )
        with col_b:
            uuid_manual = st.text_input("...o escribe cualquier UUID", key=f"{key_prefix}_uuid_manual")
        uuid_buscar = uuid_manual.strip() or uuid_sel

        if uuid_buscar:
            cfdi = _buscar_cfdi(uuid_buscar)
            if cfdi is None:
                st.warning(f"No se encontró ningún CFDI con UUID `{uuid_buscar}` en `Comprobante_Digital`.")
            else:
                p, cab = cfdi["parsed"], cfdi["cabecera"]
                if not p.get("XML_OK", True):
                    st.error(f"El XML no pudo parsearse: {p.get('XML_ERROR', '(sin detalle)')}")
                st.success(f"**{p.get('XML_EMISOR_NOMBRE', '(sin nombre)')}** · "
                           f"{p.get('XML_SERIE', '')} {p.get('XML_FOLIO', '')} · UUID `{uuid_buscar}`")

                c1, c2, c3 = st.columns(3)
                c1.metric("Tipo CFDI", p.get("XML_TIPO", "") or "—",
                          help="I=Ingreso, E=Egreso, P=Pago (REP), T=Traslado")
                c2.metric("Fecha timbrado", str(p.get("XML_FECHA", ""))[:19])
                c3.metric("Moneda", p.get("XML_MONEDA", "") or "—")

                c4, c5, c6 = st.columns(3)
                c4.metric("Subtotal", f"${p.get('XML_SUBTOTAL', 0):,.2f}")
                c5.metric("IVA trasladado", f"${p.get('XML_IVA_TRASLADADO', 0):,.2f}")
                c6.metric("Total", f"${p.get('XML_TOTAL', 0):,.2f}",
                          help="En un REP (tipo P) el Total es simbólico -- ver el aviso abajo.")

                if p.get("XML_TIPO") == "P":
                    st.info(
                        f"Es un **REP** (complemento de pagos) -- el Total del comprobante es "
                        f"simbólico. Monto real pagado: **${p.get('XML_PAGOS_MONTO', 0):,.2f}** "
                        f"(IVA del pago: ${p.get('XML_PAGOS_IVA', 0):,.2f}). "
                        f"Documentos relacionados (UUID): {p.get('XML_DR_UUIDS', '') or '(ninguno)'}."
                    )

                st.markdown(
                    f"**RFC emisor:** `{cab.get('Cd_RFC_Emisor', '') or '—'}` &nbsp;·&nbsp; "
                    f"**Uso CFDI:** {p.get('XML_USO_CFDI', '') or '—'} &nbsp;·&nbsp; "
                    f"**Método/Forma de pago:** {p.get('XML_METODO_PAGO', '') or '—'} / "
                    f"{p.get('XML_FORMA_PAGO', '') or '—'} &nbsp;·&nbsp; "
                    f"**N° conceptos:** {p.get('XML_N_CONCEPTOS', '') or '—'} &nbsp;·&nbsp; "
                    f"**Complementos:** {p.get('XML_COMPLEMENTOS', '') or '(ninguno)'}"
                )

                st.markdown("**Ligado en MPro a:**")
                st.dataframe(pd.DataFrame(cfdi["ligado_a"]), width="stretch", hide_index=True)

                with st.expander("Ver XML crudo (avanzado)"):
                    st.code(cfdi["xml_crudo"], language="xml")

    with tab_docs:
        st.markdown(
            "**Metodología completa:** `adjuntar-xml/README.md`, `adjuntar-xml/docs/metodologia.md` "
            "y `PROGRESS.md` de este directorio (entrada 2026-09-08/09) -- este reporte reusa "
            "`adjuntar-xml/04_conciliacion_mpro_vs_xml.py`, restringido a `origenes=["
            "'GASTO_REGISTRO']` (el universo de CONT-1/CONT-2 -- ver `xml_documento_lib.py`).\n\n"
            "**Por qué no trae Póliza/Cuenta/CECO como CONT-1/CONT-2:** ese detalle contable "
            "vive en `Poliza_Detalle`, a grano `(FOLIO, CECO, TIPO_GASTO)` -- más fino que "
            "este reporte, que se queda en `(FOLIO, DOC_ID)` (`Gasto_Registro_Documento`, "
            "donde se pega el XML). Para ver Póliza/Cuenta/CECO de este mismo folio, usar "
            "CONT-1/CONT-2.\n\n"
            "**Por qué el cuadre es a nivel GRUPO, no documento:** un mismo CFDI puede repartirse "
            "entre varios documentos (factura consolidada de proveedor) y un documento puede tener "
            "más de un CFDI -- comparar documento por documento descuadra en falso. El grupo es la "
            "componente conexa del grafo bipartito documento↔XML (unión de todos los documentos y "
            "XML transitivamente conectados).\n\n"
            "**`UUID`:** hasta 6 UUID por documento (separados por `;`) -- casi siempre es solo 1. "
            "Usar la pestaña **Ver CFDI** para ver el contenido parseado y legible de cualquiera.\n\n"
            "**`IMPORTE_XML`:** `XML_TOTAL` del CFDI, salvo `XML_TIPO='P'` (REP/complemento de "
            "pago) -- ahí el Total del comprobante es simbólico y se usa `XML_PAGOS_MONTO` (el "
            "monto real del complemento de pagos).\n\n"
            "**Deduplicación:** un mismo UUID puede aparecer 2 veces en `Comprobante_Digital` "
            "(dos formatos de longitud de `Cd_Documento`, ver `calidad-de-datos.md` en "
            "trivasa-context) -- se deduplica por `(GRUPO, UUID)` antes de sumar.\n\n"
            "**Clases** (columna `CLASE`):\n\n"
            "- `CON_XML_CONCILIA` / `CON_XML_DIF_CENTAVOS` -- cuadra dentro de tolerancia "
            "($0.05 / $1.00).\n"
            "- `CON_XML_IMPORTE_EN_COMPLEMENTO` -- diferencia mayor pero explicada por un "
            "complemento (ej. vales de despensa) que dispersa el importe fuera del Total.\n"
            "- `CON_XML_DIF_MATERIAL` -- tiene XML pero la diferencia no se explica -- **residual "
            "real** (~49% de su importe ya tiene causa identificada -- componente conexa que no "
            "cruza meses/módulos, ver `PROGRESS.md`).\n"
            "- `SIN_XML_ORIGEN_INTERNO` -- `CONSUMO_INTERNO`/`GASTO_RECLASIFICACION`/nómina, no "
            "generan CFDI de proveedor por diseño.\n"
            "- `SIN_XML_CFDI_EN_ORIGEN` -- el CFDI existe pero cuelga del documento que originó "
            "este (cadena `Cuenta_X_Pagar` -> `Gasto_Registro`) -- puede no aparecer en este "
            "reporte porque `Cuenta_X_Pagar` está fuera del universo (solo `GASTO_REGISTRO`).\n"
            "- `SIN_XML_CANCELADO` / `SIN_XML_IMPORTE_NEGATIVO` / `SIN_XML_TRASPASO_INTERNO` / "
            "`SIN_XML_IMPORTE_CERO` -- explicados por estado/naturaleza del documento.\n"
            "- `SIN_XML_PENDIENTE` -- el hueco real, sin explicación estructural.\n\n"
            "**Resultado de referencia** (enero/febrero 2026, solo `GASTO_REGISTRO`, ver "
            "`PROGRESS.md`): 19.2% de los documentos tienen XML; de esos, ~50% son "
            "correspondencia 1:1 limpia (varía mucho por origen: `ORDEN_COMPRA`/`VIAJE` "
            "arriba de 70-94%, `CONTROL_COMBUSTIBLE` casi 0% por facturas consolidadas)."
        )
