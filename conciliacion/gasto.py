"""Documentos de Gasto: una fila por línea de póliza con CECO, con importes prorrateados por reparto de CECO."""
import numpy as np
import pandas as pd
from sqlalchemy.engine import Connection

from . import sql
from .atribucion import VARIOS, atribuir_documento
from .db import consultar

NO_APLICA = "N/A"
COLS_POLIZA = ["POLIZA", "FECHA_POLIZA", "TIPO_POLIZA", "NUMERO_POLIZA", "CONCEPTO_POLIZA"]
COLS_LINEA = COLS_POLIZA + ["CUENTA_REGISTRO", "NOMBRE_CUENTA_REGISTRO", "CARGO", "ABONO"]
COLS_DOC = ["SUBTOTAL_16", "SUBTOTAL_0", "SUBTOTAL_EXENTA", "SUBTOTAL_NETO"]
COLS_POLIZA_AF = ["FOLIO", "ORIGEN", *COLS_POLIZA, "CUENTA_REGISTRO", "NOMBRE_CUENTA_REGISTRO",
                  "CECO", "CECO_DESCRIPCION", "CARGO", "ABONO"]
TOLERANCIA_SIN_CECO = 0.05


def pesos(reparto: pd.DataFrame) -> pd.DataFrame:
    """Peso de cada (FOLIO, Grd_ID, CECO) dentro de su documento: `Grc_Factor`, o |Grc_Importe| si el factor suma < 0.01."""
    r = reparto.copy()
    r["ABS"] = r.Grc_Importe.abs()
    r["PESO"] = r.Grc_Factor.fillna(0)
    llave = ["FOLIO", "Grd_ID"]
    sin_factor = r.groupby(llave).PESO.transform("sum") < 0.01
    r.loc[sin_factor, "PESO"] = (r.ABS / r.groupby(llave).ABS.transform("sum"))[sin_factor]
    r["PESO"] = r.PESO.fillna(0)
    return r


def impuestos_por_ceco(reparto: pd.DataFrame, subtotales: pd.DataFrame):
    """Subtotales por (FOLIO, CECO) repartidos con los pesos del reparto."""
    m = reparto.merge(subtotales, on=["FOLIO", "Grd_ID"], how="left")
    for c in COLS_DOC:
        m[c] = m[c] * m.PESO
    return m.groupby(["FOLIO", "CECO"], as_index=False)[COLS_DOC].sum()


def impuestos_clave_por_ceco(reparto: pd.DataFrame, por_clave: pd.DataFrame) -> pd.DataFrame:
    x = reparto.merge(por_clave, on=["FOLIO", "Grd_ID"], how="inner")
    x["V"] = x.IMPORTE * x.PESO
    p = x.groupby(["FOLIO", "CECO", "CLAVE"]).V.sum().unstack("CLAVE").fillna(0).round(2)
    p.columns = ["IMP_" + c for c in p.columns]
    return p.reset_index()


def emparejar_activo_fijo(folios: pd.DataFrame, lineas: pd.DataFrame) -> pd.DataFrame:
    """Asigna a cada folio CONSUMO_INTERNO de activo fijo sus líneas de póliza, por (POLIZA, REFERENCIA).

    `Gr_Referencia` no es único dentro de una póliza: con varios folios se empareja por rango de importe,
    salvo que la póliza los agrupe en menos líneas, caso en que cada folio recibe la parte proporcional a su valor.
    """
    g = folios.sort_values(["POLIZA", "REFERENCIA", "VALOR_CMP"]).reset_index(drop=True)
    p = lineas.sort_values(["POLIZA", "REFERENCIA", "IMPORTE_PD"]).reset_index(drop=True)
    g["rank"] = g.groupby(["POLIZA", "REFERENCIA"]).cumcount()
    p["rank"] = p.groupby(["POLIZA", "REFERENCIA"]).cumcount()
    llave = ["POLIZA", "REFERENCIA"]
    g = g.merge(p.groupby(llave).IMPORTE_PD.agg(n_lin="size", s_lin="sum").reset_index(), on=llave, how="left")
    g = g.merge(g.groupby(llave).VALOR_CMP.sum().rename("s_val").reset_index(), on=llave, how="left")
    n_folios = g.groupby(llave).FOLIO.transform("size")
    agregada = (n_folios > 1) & (g.n_lin < n_folios) & (g.s_val > 0) & ((g.s_lin - g.s_val).abs() <= 0.5)
    aux = ["n_lin", "s_lin", "s_val"]
    p_sin_rank = p.drop(columns="rank")
    unicos = g[n_folios == 1].drop(columns=["rank"] + aux)
    agreg = g[agregada].drop(columns="rank").merge(p_sin_rank, on=llave, how="inner")
    agreg["IMPORTE_PD"] = agreg.IMPORTE_PD * agreg.VALOR_CMP / agreg.s_val
    resto = g[(n_folios > 1) & ~agregada].drop(columns=aux)
    m = pd.concat([
        unicos.merge(p_sin_rank, on=llave, how="inner"),
        agreg.drop(columns=aux),
        resto.merge(p, on=llave + ["rank"], how="inner"),
    ], ignore_index=True)
    m["ORIGEN"] = "CONSUMO_INTERNO"
    m["CARGO"] = m["IMPORTE_PD"]
    m["ABONO"] = 0.0
    return m[COLS_POLIZA_AF]


def atribuir_sin_ceco(filas: pd.DataFrame, subtotales: pd.DataFrame, sin_ceco: pd.DataFrame) -> pd.DataFrame:
    """Carga a las filas completadas la línea de póliza sin CECO del mismo folio cuyo importe iguala el
    subtotal neto de su (FOLIO, CECO); cada línea se usa una sola vez."""
    lin = sin_ceco[sin_ceco.FOLIO.isin(filas.FOLIO)].copy()
    if lin.empty:
        return filas
    lin["NET"] = lin.CARGO - lin.ABONO
    por_folio = {f: list(g.index) for f, g in lin.groupby("FOLIO")}
    objetivo = subtotales.groupby(["FOLIO", "CECO"]).SUBTOTAL_NETO.sum()
    libres = set(lin.index)
    filas = filas.copy()
    for i, r in filas.iterrows():
        t = objetivo.get((r.FOLIO, r.CECO))
        if t is None or pd.isna(t):
            continue
        for j in por_folio.get(r.FOLIO, []):
            if j in libres and abs(lin.at[j, "NET"] - t) <= TOLERANCIA_SIN_CECO:
                for c in COLS_LINEA:
                    filas.at[i, c] = lin.at[j, c]
                libres.discard(j)
                break
    return filas


def completar(base, subtotales, por_clave_ceco, reparto, doc, por_clave, origen, ceco_desc, sin_ceco):
    """Agrega filas con CARGO = ABONO = 0 para los (FOLIO, CECO) del reparto que la póliza no cubre y para los
    documentos sin reparto ni póliza con CECO, de modo que el layout totalice igual que el reporte nativo RPAG008."""
    cubiertos = set(zip(base.FOLIO, base.CECO))
    a = reparto[["FOLIO", "CECO"]].drop_duplicates()
    a = a[[k not in cubiertos for k in zip(a.FOLIO, a.CECO)]].copy()
    sin_reparto = sorted(set(doc.FOLIO) - set(reparto.FOLIO) - set(base.FOLIO))
    extra = pd.concat([a, pd.DataFrame({"FOLIO": sin_reparto, "CECO": ""})], ignore_index=True)
    if extra.empty:
        return base, subtotales, por_clave_ceco
    extra = extra.merge(origen, on="FOLIO", how="left").merge(
        ceco_desc.assign(CECO=lambda t: t.CECO.str.strip()), on="CECO", how="left")
    poliza = base.drop_duplicates("FOLIO").set_index("FOLIO")[COLS_POLIZA]
    extra = extra.join(poliza, on="FOLIO")
    extra["CARGO"] = 0.0
    extra["ABONO"] = 0.0
    if sin_reparto:
        d = doc[doc.FOLIO.isin(sin_reparto)]
        v = d.groupby("FOLIO")[COLS_DOC].sum().reset_index()
        v["CECO"] = ""
        subtotales = pd.concat([subtotales, v], ignore_index=True, sort=False)
        w = (por_clave[por_clave.FOLIO.isin(sin_reparto)].groupby(["FOLIO", "CLAVE"]).IMPORTE.sum()
             .unstack("CLAVE").fillna(0).round(2))
        w.columns = ["IMP_" + c for c in w.columns]
        w = w.reset_index()
        w["CECO"] = ""
        por_clave_ceco = pd.concat([por_clave_ceco, w], ignore_index=True, sort=False)
    extra = atribuir_sin_ceco(extra, subtotales, sin_ceco)
    return pd.concat([base, extra], ignore_index=True, sort=False), subtotales, por_clave_ceco


def construir_gasto(con: Connection, p: dict) -> pd.DataFrame:
    """Gasto previo a `posproceso.post`. Requiere las tablas temporales de `sql.GASTO_DOCS_SETUP`."""
    lineas = consultar(con, sql.GASTO_POLIZA_SQL, p)
    af_lineas = consultar(con, sql.GASTO_ACTIVO_FIJO_POLIZA_SQL, p)
    af_lineas["REFERENCIA"] = af_lineas.REFERENCIA.str.strip()
    af_folios = consultar(con, sql.GASTO_ACTIVO_FIJO_FOLIOS_SQL, p)
    af_folios["REFERENCIA"] = af_folios.REFERENCIA.str.strip()
    base = pd.concat([lineas, emparejar_activo_fijo(af_folios, af_lineas)], ignore_index=True)

    subtotales_doc = consultar(con, sql.GASTO_SUBTOTALES_SQL, p)
    reparto = pesos(consultar(con, sql.GASTO_REPARTO_SQL, p))
    por_clave = consultar(con, sql.GASTO_IMPUESTO_CLAVE_SQL, p)
    subtotales = impuestos_por_ceco(reparto, subtotales_doc)
    por_clave_ceco = impuestos_clave_por_ceco(reparto, por_clave)

    base, subtotales, por_clave_ceco = completar(
        base, subtotales, por_clave_ceco, reparto, subtotales_doc, por_clave,
        origen=consultar(con, sql.GASTO_ORIGEN_SQL),
        ceco_desc=consultar(con, sql.CENTRO_COSTO_SQL),
        sin_ceco=consultar(con, sql.GASTO_POLIZA_SIN_CECO_SQL, p))

    docs = consultar(con, sql.GASTO_DOCUMENTOS_SQL)
    xml_doc = consultar(con, sql.GASTO_XML_DOCUMENTO_SQL)
    for t in (docs, xml_doc, reparto, subtotales_doc, por_clave):
        for c in ("DOC_ID", "Grd_ID"):
            if c in t:
                t[c] = t[c].str.strip() if t[c].dtype == object else t[c]
    docs["DOC_ID"] = docs.DOC_ID.astype(str).str.strip()
    firmas = _firmas(docs, xml_doc)
    base = atribuir_documento(base, reparto, docs[["FOLIO", "DOC_ID"]], firmas)

    proveedor = consultar(con, sql.GASTO_PROVEEDOR_SQL)
    pagos = consultar(con, sql.PAGOS_SQL)
    pagos_doc = consultar(con, sql.PAGOS_DOC_SQL).drop(columns="REFERENCIA")
    pagos_doc[["FOLIO", "DOC_ID"]] = pagos_doc.FOLIO.str.split("|", n=1, expand=True)
    xml = consultar(con, sql.XML_SQL.format(origen="GASTO_REGISTRO"))
    retenciones = consultar(con, sql.GASTO_RETENCIONES_SQL).add_prefix("R_").rename(columns={"R_FOLIO": "FOLIO"})
    out = (base.merge(subtotales, on=["FOLIO", "CECO"], how="left")
               .merge(por_clave_ceco, on=["FOLIO", "CECO"], how="left")
               .merge(proveedor, on="FOLIO", how="left")
               .merge(pagos, on="FOLIO", how="left")
               .merge(xml, on="FOLIO", how="left")
               .merge(retenciones, on="FOLIO", how="left"))
    out = _pago_por_documento(out, pagos_doc)
    return _por_documento(out, docs, xml_doc, subtotales_doc, por_clave)


def _pago_por_documento(d, pagos_doc):
    """En los folios con DOC_ID el pago es el de la cuenta por pagar de cada documento (VARIOS queda sin pago)."""
    m = d.DOC_ID.notna()
    if not m.any():
        return d
    cols = [c for c in pagos_doc if c not in ("FOLIO", "DOC_ID")]
    d = d.copy()
    d[cols] = d[cols].astype(object)
    d.loc[m, cols] = d.loc[m, ["FOLIO", "DOC_ID"]].merge(pagos_doc, on=["FOLIO", "DOC_ID"], how="left")[cols].to_numpy()
    return d


def _firmas(docs: pd.DataFrame, xml_doc: pd.DataFrame) -> dict:
    """(FOLIO, DOC_ID) → (clave de proveedor, UUID); el XML sin DOC_ID aplica a todos los documentos del folio."""
    por_doc = {(r.FOLIO, r.DOC_ID): r.UUID for r in xml_doc.itertuples() if r.DOC_ID is not None and pd.notna(r.DOC_ID)}
    por_folio = {r.FOLIO: r.UUID for r in xml_doc.itertuples() if r.DOC_ID is None or pd.isna(r.DOC_ID)}
    return {(r.FOLIO, r.DOC_ID): (r.CLAVE_PROVEEDOR, por_doc.get((r.FOLIO, r.DOC_ID), por_folio.get(r.FOLIO)))
            for r in docs.itertuples()}


def _por_documento(d, docs, xml_doc, subtotales_doc, por_clave):
    """En los folios con DOC_ID sustituye proveedor, XML y cifras por los del documento (N/A en la línea VARIOS, que suma varios documentos)."""
    m = d.DOC_ID.notna()
    if not m.any():
        return d
    d = d.copy()
    prov = docs.drop(columns="CONCEPTO_GASTO").set_index(["FOLIO", "DOC_ID"])
    cols_prov = ["CLAVE_PROVEEDOR", "RFC_PROVEEDOR", "NOMBRE_PROVEEDOR"]
    folio_xml = xml_doc[xml_doc.DOC_ID.isna()].drop(columns="DOC_ID").set_index("FOLIO")
    doc_xml = xml_doc[xml_doc.DOC_ID.notna()].set_index(["FOLIO", "DOC_ID"])
    cols_xml = [c for c in xml_doc.columns if c not in ("FOLIO", "DOC_ID")]
    for i in d.index[m]:
        k = (d.at[i, "FOLIO"], d.at[i, "DOC_ID"])
        if k[1] == VARIOS:
            for c in cols_prov + [c for c in cols_xml if c != "XML_MONTO"]:
                d.at[i, c] = NO_APLICA
            d.at[i, "XML_MONTO"] = np.nan
            continue
        if k in prov.index:
            for c in cols_prov:
                d.at[i, c] = prov.at[k, c]
        if k in doc_xml.index:
            fila = doc_xml.loc[k]
        elif k[0] in folio_xml.index:
            fila = folio_xml.loc[k[0]]
        else:
            fila = None
        if fila is not None:
            for c in cols_xml:
                d.at[i, c] = fila[c]
        else:
            for c in cols_xml:
                d.at[i, c] = None

    sub = subtotales_doc.rename(columns={"Grd_ID": "DOC_ID"})
    sub = sub.rename(columns={c: "DX_" + c for c in COLS_DOC})
    imp = por_clave.pivot_table(index=["FOLIO", "Grd_ID"], columns="CLAVE", values="IMPORTE", aggfunc="sum").fillna(0).round(2)
    imp.columns = ["DX_IMP_" + c for c in imp.columns]
    imp = imp.reset_index().rename(columns={"Grd_ID": "DOC_ID"})
    return d.merge(sub, on=["FOLIO", "DOC_ID"], how="left").merge(imp, on=["FOLIO", "DOC_ID"], how="left")
