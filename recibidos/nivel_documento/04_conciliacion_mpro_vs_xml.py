"""
04 -- Conciliacion al reves: base = registros de MPro del mes, XML donde lo hay.

Extension del reporte 02 con la base invertida. El 02 parte del CFDI y
busca su registro; este parte del registro y busca su CFDI, dejando vacio
donde no hay. Responde la pregunta complementaria: **que se contabilizo sin
respaldo de un XML recibido**.

Universo: todo documento fechado en el periodo en los modulos de MPro que
pueden recibir un CFDI de proveedor -- Gasto_Registro_Documento (grano
documento, que es donde se pega el XML, no el folio), Compra_Encabezado,
Cuenta_X_Pagar, Cheque, Anticipo_CXP, Compra_Indirecto,
Nota_Credito_Proveedor.

`Factura_Encabezado` NO entra: es el modulo de venta y su CFDI es EMITIDO,
fuera del alcance ("XML recibidos, no los emitidos"). Los pocos casos de
factura con CFDI recibido colgado (8 en enero 2026) si aparecen en el 02 y
estan reportados ahi como anomalia.

El join contra `Comprobante_Digital` NO se acota por fecha de timbrado: un
registro de enero puede traer su CFDI timbrado en diciembre o en febrero
(caso real verificado: compra 05-0029612 fechada 2025-12-31 con CFDI
timbrado en enero). Acotarlo inventaria huecos que no existen.

"Sin XML" no significa "sin respaldo fiscal". La columna CLASE separa, con
evidencia y no por supuesto:

  SIN_XML_CANCELADO           registro con Es_Cve_Estado = 'CA'.
  SIN_XML_IMPORTE_CERO        importe 0 -- nada que respaldar.
  SIN_XML_IMPORTE_NEGATIVO    importe < 0: aplicaciones y reversas de anticipo,
                              no operaciones nuevas (64 CXP en enero 2026,
                              -8.2 M, todas con Cxp_Tabla = 'Anticipo_Cxp').
  SIN_XML_TRASPASO_INTERNO    cheque cuyo beneficiario es la propia empresa --
                              traspaso entre cuentas bancarias de Trivasa, no
                              hay proveedor que emita CFDI (95 cheques, 56.9 M
                              en enero 2026).
  SIN_XML_ORIGEN_INTERNO      gasto de origen interno que no genera CFDI de
                              proveedor: CONSUMO_INTERNO, GASTO_RECLASIFICACION,
                              GASTO_REGISTRO_NOMINA(_CXP). Se verifica en la
                              corrida: su cobertura de XML es ~0%.
  SIN_XML_CFDI_EN_ORIGEN      documento derivado cuyo CFDI si existe, pero
                              colgado del documento que lo origino. La cadena
                              se resuelve de verdad: Cuenta_X_Pagar guarda
                              'Gasto_Registro:<folio>' + Grd_ID en
                              Cxp_Tabla/Cxp_Documento, y 'Compra' + Co_Folio.
                              Solo se marca asi cuando el documento origen
                              REALMENTE tiene un CFDI ligado.
  SIN_XML_PENDIENTE           el hueco real: importe registrado, no cancelado,
                              sin CFDI propio ni en su documento origen.

Resultado de enero 2026: 12,037 documentos, 21.7% con CFDI ligado (27.9%
del importe). De los 9,421 sin CFDI, 8,429 quedan explicados por las clases
de arriba y 992 caen en SIN_XML_PENDIENTE (66.7 M). Ese pendiente tampoco es
homogeneo -- desglosado:
  - 660 cheques (37.2 M): pagos sin REP del proveedor. 22.4 M van a nomina,
    fisco, seguridad social y amortizacion de credito bancario, que no
    generan CFDI de proveedor; ~12.8 M son pagos a proveedores donde si
    faltaria el REP.
  - 144 documentos de gasto (17.7 M): provisiones, depreciaciones y costo
    estandar -- asientos contables sin operacion con proveedor. Solo 13,951.51
    de IVA acreditable cuelga de todo ese bloque.
  - 63 anticipos (8.0 M) y 108 CxP (3.7 M).
  - 17 documentos de compra / compra indirecta / nota de credito (105 k):
    el unico bloque que es un pendiente de captura claro y acotado.

Salida: <script>_<fi>_<ff>.csv, una fila por documento de MPro.

Uso:
    python3 04_conciliacion_mpro_vs_xml.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
"""
import argparse

import numpy as np
import pandas as pd

import conciliacion_xml_lib as L
from helpers_output import console, mostrar_tabla, resumen

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


def resolver_cadena(fi, ff):
    """CXP -> documento que la origino. `Cxp_Tabla` trae el modulo y, cuando
    el origen es un gasto, tambien el folio ('Gasto_Registro:01-0034686');
    `Cxp_Documento` trae el Grd_ID en ese caso y el folio de compra en el
    caso de 'Compra'."""
    from sqlalchemy import text
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


def construir(fi, ff):
    console.print("[bold]04 -- Registros de MPro del mes y su CFDI recibido (vacio donde no hay)[/bold]")
    console.print(f"[dim]Periodo (fecha del registro): {fi} a {ff} -- .205/TRIVASADB3[/dim]\n")

    reg = L.registros_mpro_por_mes(fi, ff, origenes=MODULOS)
    console.print(f"Documentos de MPro en el periodo: [bold]{len(reg)}[/bold]")

    folios = {o: sorted(g.FOLIO.unique()) for o, g in reg.groupby("ORIGEN")}
    x = L.xml_por_folios(folios)
    console.print(f"CFDI recibidos colgados de esos folios (sin filtro de fecha): "
                  f"[bold]{len(x)}[/bold] vinculos, {x.UUID.nunique() if len(x) else 0} UUID\n")

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

    # --- grupo de conciliacion (misma componente conexa que el 02): a grano
    # documento un CFDI repartido en N documentos descuadraria contra cada
    # uno por separado. La comparacion valida es la del grupo.
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
    cad = resolver_cadena(fi, ff)
    con_xml = set(zip(agg.ORIGEN, agg.FOLIO, agg.DOC_ID))
    # el CFDI del gasto cuelga del documento; el de compra, del folio
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
    return r[cols].sort_values(["ORIGEN", "CLASE", "TOTAL"], ascending=[True, True, False])


def reportar(r):
    n = len(r)
    con = r.N_XML > 0
    resumen(
        documentos=n,
        con_XML=f"{con.sum()} ({100*con.mean():.1f}%)",
        sin_XML=f"{(~con).sum()} ({100*(~con).mean():.1f}%)",
        importe_total=f"{r.TOTAL.sum():,.2f}",
        importe_con_XML=f"{r.loc[con,'TOTAL'].sum():,.2f} ({100*r.loc[con,'TOTAL'].sum()/r.TOTAL.sum():.1f}%)",
    )
    t = r.groupby(["ORIGEN", "CLASE"]).agg(DOCS=("FOLIO", "size"),
                                           IMPORTE=("TOTAL", "sum")).reset_index()
    t["IMPORTE"] = t.IMPORTE.map(lambda v: f"{v:,.2f}")
    mostrar_tabla(t, "Cobertura de XML por origen", max_filas=50)

    cob = r.groupby(["ORIGEN", "SUBORIGEN"]).agg(
        DOCS=("FOLIO", "size"), CON_XML=("N_XML", lambda s: int((s > 0).sum())),
        IMPORTE=("TOTAL", "sum")).reset_index()
    cob["PCT"] = (100 * cob.CON_XML / cob.DOCS).round(1)
    cob["IMPORTE"] = cob.IMPORTE.map(lambda v: f"{v:,.2f}")
    mostrar_tabla(cob.sort_values("DOCS", ascending=False),
                  "Cobertura por suborigen (evidencia para la etiqueta ORIGEN_INTERNO)",
                  max_filas=40)

    pend = r[r.CLASE == "SIN_XML_PENDIENTE"].copy()
    if len(pend):
        mostrar_tabla(pend.groupby(["ORIGEN", "SUBORIGEN"]).agg(
            DOCS=("FOLIO", "size"), IMPORTE=("TOTAL", "sum")).reset_index()
            .assign(IMPORTE=lambda d: d.IMPORTE.map(lambda v: f"{v:,.2f}"))
            .sort_values("DOCS", ascending=False),
            "SIN_XML_PENDIENTE -- los huecos reales", max_filas=25)
        mostrar_tabla(pend.nlargest(15, "TOTAL")[
            ["ORIGEN", "SUBORIGEN", "FOLIO", "DOC_ID", "FECHA", "PROVEEDOR", "TOTAL"]]
            .assign(CONCEPTO=lambda d: pend.nlargest(15, "TOTAL").CONCEPTO.str[:34]),
            "Mayores documentos sin CFDI", max_filas=15)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    args = ap.parse_args()
    r = construir(args.fecha_ini, args.fecha_fin)
    reportar(r)
    out = f"04_conciliacion_mpro_vs_xml_{args.fecha_ini}_{args.fecha_fin}.csv"
    r.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]  ({len(r)} filas)")


if __name__ == "__main__":
    main()
