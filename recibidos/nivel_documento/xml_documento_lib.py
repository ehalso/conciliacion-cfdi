"""
xml_documento_lib.py -- logica de negocio de CONT-6: version de CONT-1/
CONT-2 (mismo universo -- 6-7 origenes de `Gasto_Registro` via `Gr_Tabla`,
incluyendo NOMINA) pero a grano `(FOLIO, DOC_ID=Grd_ID)` en vez de
`(FOLIO, CECO, TIPO_GASTO)`, y con el CFDI (UUID/XML) adjunto en vez de
Poliza/Cuenta -- ese detalle contable no aplica a este grano mas grueso
(vive del lado de `Poliza_Detalle`, no de `Gasto_Registro_Documento`).

Reusa `conciliacion_xml_lib.py` de `adjuntar-xml/` (proyecto hermano,
metodologia mas madura para XML/CFDI -- resuelve por componente conexa en
vez de par (FOLIO,GRD_ID)<->UUID, y en general cubre los 7 modulos de MPro
que reciben CFDI, no solo Gasto_Registro) en vez de duplicar ~850 lineas
de parseo de CFDI/agrupamiento -- import cruzado por sys.path, no copia
(ver adjuntar-xml/README.md "Limitaciones").

`reporte_completo(fi, ff, origenes=["GASTO_REGISTRO"])` es `construir()`
de `adjuntar-xml/04_conciliacion_mpro_vs_xml.py`, con el parametro
`origenes` agregado para poder restringir el universo (CONT-6 solo pide
`GASTO_REGISTRO`; el script `04` original sigue usando los 7 por default).
Ver ese script y `PROGRESS.md` (entrada 2026-09-08/09) para el detalle
completo de la metodologia, el % de cuadre medido y el residual conocido
(`CON_XML_DIF_MATERIAL`, ~4-6% de los documentos con XML).
"""
import numpy as np
import pandas as pd
from sqlalchemy import text

# conciliacion_xml_lib.py ya es un sibling directo en esta carpeta desde la
# consolidación 2026-09-10 (antes vivía en un repo/carpeta aparte,
# "adjuntar-xml") -- ya no hace falta el sys.path hack para encontrarlo.
import conciliacion_xml_lib as L  # noqa: E402

MODULOS = ["GASTO_REGISTRO", "COMPRA", "CUENTA_X_PAGAR", "CHEQUE",
           "ANTICIPO_CXP", "COMPRA_INDIRECTO", "NOTA_CREDITO_PROVEEDOR"]

# Suborigenes que por construccion no traen CFDI de proveedor. La corrida
# imprime su cobertura real para que la etiqueta se pueda auditar.
ORIGEN_INTERNO = {"CONSUMO_INTERNO", "GASTO_RECLASIFICACION", "GASTO_REGISTRO_NOMINA",
                  "GASTO_REGISTRO_NOMINA_CXP", "Recibo_Pago"}

CADENA_SQL = """
SELECT cx.Cxp_Folio FOLIO, cx.Cxp_Tabla TABLA, ISNULL(cx.Cxp_Documento,'') DOCUMENTO
FROM Cuenta_X_Pagar cx
WHERE cx.Cxp_Fecha >= :fi AND cx.Cxp_Fecha < :ff
"""


def _resolver_cadena(fi, ff):
    """CXP -> documento que la origino. `Cxp_Tabla` trae el modulo y, cuando
    el origen es un gasto, tambien el folio ('Gasto_Registro:01-0034686');
    `Cxp_Documento` trae el Grd_ID en ese caso y el folio de compra en el
    caso de 'Compra'."""
    d = pd.read_sql(text(CADENA_SQL), L.engine, params={"fi": fi, "ff": ff})
    for c in ("FOLIO", "TABLA", "DOCUMENTO"):
        d[c] = d[c].astype("string").fillna("").str.strip()
    pref = d.TABLA.str.split(":").str[0]
    resto = d.TABLA.str.split(":").str[1].fillna("")
    d["ORIGEN_DOC"] = ""
    d["FOLIO_DOC"] = ""
    d["DOC_ID_DOC"] = ""
    es_gasto = pref.str.lower() == "gasto_registro"
    d.loc[es_gasto, "ORIGEN_DOC"] = "GASTO_REGISTRO"
    d.loc[es_gasto, "FOLIO_DOC"] = resto[es_gasto]
    d.loc[es_gasto, "DOC_ID_DOC"] = d.loc[es_gasto, "DOCUMENTO"]
    es_compra = pref.str.lower() == "compra"
    d.loc[es_compra, "ORIGEN_DOC"] = "COMPRA"
    d.loc[es_compra, "FOLIO_DOC"] = d.loc[es_compra, "DOCUMENTO"]
    es_ci = pref.str.lower() == "compra_indirecto"
    d.loc[es_ci, "ORIGEN_DOC"] = "COMPRA_INDIRECTO"
    d.loc[es_ci, "FOLIO_DOC"] = d.loc[es_ci, "DOCUMENTO"]
    d["ORIGEN"] = "CUENTA_X_PAGAR"
    d["DOC_ID"] = ""
    return d[["ORIGEN", "FOLIO", "DOC_ID", "ORIGEN_DOC", "FOLIO_DOC", "DOC_ID_DOC"]]


def reporte_completo(fecha_ini: str, fecha_fin: str, origenes: list | None = None) -> pd.DataFrame:
    """Un documento de MPro por fila (grano `(ORIGEN, FOLIO, DOC_ID)` --
    `DOC_ID` es `Grd_ID` para `GASTO_REGISTRO`), con su XML adjunto si lo
    tiene. El cuadre de importe (`FORMA`/`DIF_GRUPO`/`CLASE`) se calcula a
    nivel de GRUPO -- componente conexa documento<->XML, no documento
    suelto, porque un CFDI puede repartirse en N documentos o un documento
    tener mas de un CFDI (ver docstring del modulo).

    `origenes` restringe el universo de modulos de MPro consultados (por
    default los 7 de `MODULOS`) -- pasar `["GASTO_REGISTRO"]` para el
    universo de CONT-1/CONT-2 (solo registro de gasto, sin Compra/Cheque/
    CXP/etc.)."""
    fi, ff = fecha_ini, fecha_fin
    origenes = origenes if origenes is not None else MODULOS

    reg = L.registros_mpro_por_mes(fi, ff, origenes=origenes)
    folios = {o: sorted(g.FOLIO.unique()) for o, g in reg.groupby("ORIGEN")}
    x = L.xml_por_folios(folios)

    x = x.copy()
    x["IMPORTE_XML"] = np.where(x.XML_TIPO == "P", x.XML_PAGOS_MONTO, x.XML_TOTAL)
    xu = x.drop_duplicates(["ORIGEN", "FOLIO", "DOC_ID", "UUID"])
    agg = xu.groupby(["ORIGEN", "FOLIO", "DOC_ID"]).agg(
        N_XML=("UUID", "size"),
        UUIDS=("UUID", lambda s: ";".join(sorted(set(s))[:6])),
        XML_TOTAL=("XML_TOTAL", "sum"),
        XML_IMPORTE=("IMPORTE_XML", "sum"),
        XML_IVA=("XML_IVA_TRASLADADO", "sum"),
        XML_TIPOS=("XML_TIPO", lambda s: ";".join(sorted(set(s)))),
        XML_RFC_EMISOR=("RFC_EMISOR", lambda s: ";".join(sorted(set(s))[:4])),
        XML_FECHA_MIN=("XML_FECHA", "min"),
        XML_FECHA_MAX=("XML_FECHA", "max"),
        XML_TIMBRADO_MIN=("FECHA_TIMBRADO", "min"),
    ).reset_index()

    # --- grupo de conciliacion (misma componente conexa que el 02 de
    # adjuntar-xml): a grano documento un CFDI repartido en N documentos
    # descuadraria contra cada uno por separado. La comparacion valida es
    # la del grupo.
    xg, mapa_doc = L.asignar_grupos(x)
    grupo_x = xg.drop_duplicates(["GRUPO", "UUID"]).groupby("GRUPO").agg(
        XML_GRUPO=("IMPORTE_XML", "sum"), N_XML_GRUPO=("UUID", "size"),
        XML_COMPLEMENTO=("XML_VALES_DESPENSA", "sum")).reset_index()

    reg["DOC"] = reg.FOLIO + "|" + reg.DOC_ID
    reg["GRUPO"] = [mapa_doc.get((o, d), "") for o, d in zip(reg.ORIGEN, reg.DOC)]
    grupo_r = (reg[reg.GRUPO != ""].groupby("GRUPO")
               .agg(MPRO_GRUPO=("TOTAL", "sum"), N_DOC_GRUPO=("DOC", "size")).reset_index())
    grp = grupo_x.merge(grupo_r, on="GRUPO", how="outer")
    grp["N_DOC_GRUPO"] = grp.N_DOC_GRUPO.fillna(0).astype(int)
    grp["N_XML_GRUPO"] = grp.N_XML_GRUPO.fillna(0).astype(int)
    grp["MPRO_GRUPO"] = grp.MPRO_GRUPO.fillna(0.0)
    grp["XML_GRUPO"] = grp.XML_GRUPO.fillna(0.0)
    grp["DIF_GRUPO"] = (grp.XML_GRUPO - grp.MPRO_GRUPO).round(2)
    grp["FORMA"] = np.where((grp.N_XML_GRUPO == 1) & (grp.N_DOC_GRUPO == 1), "1:1",
                    np.where(grp.N_DOC_GRUPO == 0, "SIN_REGISTRO_EN_EL_MES",
                    np.where(grp.N_XML_GRUPO == 1, "1:N",
                    np.where(grp.N_DOC_GRUPO == 1, "N:1", "N:M"))))

    r = reg.merge(agg, on=["ORIGEN", "FOLIO", "DOC_ID"], how="left").merge(
        grp, on="GRUPO", how="left")
    r["N_XML_GRUPO"] = r.N_XML_GRUPO.fillna(0).astype(int)
    r["N_DOC_GRUPO"] = r.N_DOC_GRUPO.fillna(0).astype(int)
    for c in ("XML_GRUPO", "MPRO_GRUPO", "DIF_GRUPO", "XML_COMPLEMENTO"):
        r[c] = r[c].fillna(0.0)
    r["FORMA"] = r.FORMA.fillna("")
    r["N_XML"] = r.N_XML.fillna(0).astype(int)
    for c in ("XML_TOTAL", "XML_IMPORTE", "XML_IVA"):
        r[c] = r[c].fillna(0.0)
    for c in ("UUIDS", "XML_TIPOS", "XML_RFC_EMISOR"):
        r[c] = r[c].fillna("")
    r["TIENE_XML"] = r.N_XML > 0
    r["DIF"] = np.where(r.TIENE_XML, (r.XML_IMPORTE - r.TOTAL).round(2), np.nan)  # a nivel fila, informativa
    r["DIF_PCT"] = np.where(r.TIENE_XML & (r.XML_IMPORTE.abs() > 0.005),
                            (100 * r.DIF / r.XML_IMPORTE).round(2), np.nan)
    r["XML_MISMO_MES"] = np.where(
        r.TIENE_XML,
        (pd.to_datetime(r.XML_TIMBRADO_MIN, errors="coerce") >= pd.Timestamp(fi))
        & (pd.to_datetime(r.XML_TIMBRADO_MIN, errors="coerce") < pd.Timestamp(ff)),
        False)

    # --- cadena CXP -> documento origen, para no contar huecos falsos
    cad = _resolver_cadena(fi, ff)
    con_xml = set(zip(agg.ORIGEN, agg.FOLIO, agg.DOC_ID))
    cad["TIENE_XML_ORIGEN"] = [
        (o, f, d) in con_xml or (o, f, "") in con_xml
        for o, f, d in zip(cad.ORIGEN_DOC, cad.FOLIO_DOC, cad.DOC_ID_DOC)]
    cad["ORIGEN_RESUELTO"] = np.where(
        cad.ORIGEN_DOC != "", cad.ORIGEN_DOC + ":" + cad.FOLIO_DOC
        + np.where(cad.DOC_ID_DOC != "", "/" + cad.DOC_ID_DOC, ""), "")
    r = r.merge(cad[["ORIGEN", "FOLIO", "DOC_ID", "ORIGEN_RESUELTO", "TIENE_XML_ORIGEN"]],
                on=["ORIGEN", "FOLIO", "DOC_ID"], how="left")
    r["TIENE_XML_ORIGEN"] = r.TIENE_XML_ORIGEN.fillna(False).astype(bool)
    r["ORIGEN_RESUELTO"] = r.ORIGEN_RESUELTO.fillna("")

    def clase(f):
        if f.TIENE_XML:
            # a nivel grupo: un CFDI repartido en N documentos solo cuadra
            # sumandolos, nunca contra un documento suelto
            d = abs(f.DIF_GRUPO)
            if d <= L.TOL_CENTAVOS:
                return "CON_XML_CONCILIA"
            if d <= L.TOL_MENOR:
                return "CON_XML_DIF_CENTAVOS"
            # El CFDI se timbra por la comision y la dispersion real vive en
            # el complemento (vales de despensa): MPro registra el Total del
            # comprobante y hace bien.
            if f.XML_COMPLEMENTO > L.TOL_MENOR:
                return "CON_XML_IMPORTE_EN_COMPLEMENTO"
            return "CON_XML_DIF_MATERIAL"
        if f.ESTADO == "CA":
            return "SIN_XML_CANCELADO"
        if pd.isna(f.TOTAL) or abs(f.TOTAL) <= L.TOL_CENTAVOS:
            return "SIN_XML_IMPORTE_CERO"
        if f.TOTAL < 0:
            return "SIN_XML_IMPORTE_NEGATIVO"
        if f.ORIGEN == "CHEQUE" and "TRIVASA" in str(f.PROVEEDOR).upper():
            return "SIN_XML_TRASPASO_INTERNO"
        if f.SUBORIGEN in ORIGEN_INTERNO:
            return "SIN_XML_ORIGEN_INTERNO"
        if f.TIENE_XML_ORIGEN:
            return "SIN_XML_CFDI_EN_ORIGEN"
        return "SIN_XML_PENDIENTE"

    r["CLASE"] = r.apply(clase, axis=1)

    cols = ["ORIGEN", "SUBORIGEN", "FOLIO", "DOC_ID", "FECHA", "ESTADO", "PROVEEDOR", "CONCEPTO",
            "MONEDA", "TIPO_CAMBIO", "SUBTOTAL", "IMPUESTOS", "TOTAL",
            "CLASE", "GRUPO", "FORMA", "N_XML_GRUPO", "N_DOC_GRUPO",
            "XML_GRUPO", "MPRO_GRUPO", "DIF_GRUPO", "XML_COMPLEMENTO",
            "N_XML", "XML_TOTAL", "XML_IMPORTE", "XML_IVA", "DIF", "DIF_PCT",
            "XML_TIPOS", "XML_RFC_EMISOR", "XML_FECHA_MIN", "XML_FECHA_MAX",
            "XML_TIMBRADO_MIN", "XML_MISMO_MES", "ORIGEN_RESUELTO", "TIENE_XML_ORIGEN",
            "UUIDS"]
    for c in ("SUBTOTAL", "IMPUESTOS", "TOTAL", "XML_TOTAL", "XML_IMPORTE", "XML_IVA",
              "XML_GRUPO", "MPRO_GRUPO", "DIF_GRUPO", "XML_COMPLEMENTO"):
        r[c] = pd.to_numeric(r[c], errors="coerce").round(2)
    return r[cols].sort_values(["ORIGEN", "CLASE", "TOTAL"], ascending=[True, True, False]).reset_index(drop=True)


def resumen_reconciliacion(df: pd.DataFrame) -> pd.DataFrame:
    """Cobertura y correspondencia 1:1 por (ORIGEN, SUBORIGEN), a grano
    (FOLIO, DOC_ID) -- la tabla base de la pestaña Reconciliacion. 'Uno a
    uno' = FORMA=='1:1' (exactamente 1 documento con exactamente 1 XML del
    lado del grupo -- sin facturas partidas ni consolidadas). No confundir
    con CON_XML (que incluye tambien 1:N/N:1/N:M, XML compartido)."""
    d = df.copy()
    d["CON_XML"] = d.N_XML > 0
    d["UNO_A_UNO"] = d.FORMA == "1:1"
    g = d.groupby(["ORIGEN", "SUBORIGEN"]).agg(
        N=("FOLIO", "size"), CON_XML=("CON_XML", "sum"), UNO_A_UNO=("UNO_A_UNO", "sum"),
        IMPORTE=("TOTAL", "sum"),
    ).reset_index()
    g["PCT_CON_XML"] = (100 * g.CON_XML / g.N).round(1)
    g["PCT_SIN_XML"] = (100 - g.PCT_CON_XML).round(1)
    g["PCT_1A1_TOTAL"] = (100 * g.UNO_A_UNO / g.N).round(1)
    g["PCT_1A1_CON_XML"] = np.where(g.CON_XML > 0, (100 * g.UNO_A_UNO / g.CON_XML).round(1), np.nan)
    return g.sort_values("N", ascending=False).reset_index(drop=True)


def buscar_cfdi(uuid: str):
    """Busca un CFDI por su Timbre_UUID y regresa sus campos parseados --
    legibles para humano, no el XML crudo (aunque tambien se incluye por si
    hace falta). None si el UUID no existe en Comprobante_Digital."""
    uuid = (uuid or "").strip().upper()
    if not uuid:
        return None
    filas = pd.read_sql(text(
        "SELECT Cd_Tabla, Cd_Documento, Cd_Timbre_UUID, Cd_Monto, "
        "Cd_RFC_Emisor, Cd_Factura, Cd_Timbre_Fecha, Cd_XML "
        "FROM Comprobante_Digital WHERE Cd_Timbre_UUID = :u"
    ), L.engine, params={"u": uuid})
    if filas.empty:
        return None
    xml_str = filas.Cd_XML.iloc[0]
    parsed = L.parsear_cfdi(xml_str)
    ligado_a = filas[["Cd_Tabla", "Cd_Documento", "Cd_Monto"]].drop_duplicates().to_dict("records")
    return {"parsed": parsed, "cabecera": filas.iloc[0].to_dict(), "ligado_a": ligado_a, "xml_crudo": xml_str}
