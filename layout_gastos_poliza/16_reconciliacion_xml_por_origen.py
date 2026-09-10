"""
HITO: primer panorama honesto de conciliacion XML (CFDI) por origen, para
los 4 origenes de Gasto_Registro que SI deberian llevar XML segun la
logica del negocio -- GASTO_DIRECTO, VIAJE, ORDEN_COMPRA, CONTROL_
COMBUSTIBLE. Quedan fuera a proposito (nunca facturan CFDI por diseno,
confirmado en sesiones anteriores, ver PROGRESS.md):
  - CONSUMO_INTERNO: movimiento interno de inventario, no hay proveedor.
  - GASTO_REGISTRO_NOMINA: nomina no factura.
  - GASTO_RECLASIFICACION: ajuste contable derivado, no una compra nueva.

Llegar a un numero confiable aqui costo encontrar y corregir TRES bugs
reales en la misma sesion (2026-09-05) -- documentados en detalle en
PROGRESS.md, resumen aqui porque este script es el que los junta todos:

1. `Comprobante_Digital.Cd_Documento` (Cd_Tabla='GASTO_REGISTRO') viene en
   DOS formatos -- LEN 18 (Gr_Folio+Grd_ID+sufijo fijo '0001') y LEN 14
   (Gr_Folio+Grd_ID, sin el sufijo). El codigo anterior (`poliza_
   configuracion_lib.xml_gasto_registro()`, script `15`) solo aceptaba
   LEN 18 -- perdia ~23% de los XML ligados historicos (441 de 1,510
   documentos solo en enero 2026). Confirmado con drill-down real de
   ORDEN_COMPRA: 17 folios "sin XML" en realidad SI tenian, en formato 14.

2. Al aceptar ambos formatos, un mismo (FOLIO, GRD_ID) puede traer 2 filas
   en Comprobante_Digital -- casi siempre el MISMO XML capturado 2 veces
   (mismo Cd_Timbre_UUID), lo que duplica el importe del documento si no
   se deduplica antes de sumar por UUID.

3. `Comprobante_Digital.Cd_Monto` viene en la MONEDA ORIGINAL del CFDI, no
   convertida a MXN -- comparar el importe ya convertido (Grd_Precio_Neto_
   Importe * Grd_Tipo_Cambio, formula correcta para el total en MXN de
   `layout_gastos_lib.IMPORTE_FOLIO_SQL`) contra Cd_Monto daba diferencias
   de hasta 18x en documentos USD. Confirmado con datos reales: comparar
   SIN convertir (Grd_Precio_Neto_Importe solo) cuadra exacto. Seguro
   tambien para MXN (Grd_Tipo_Cambio siempre 1.0 ahi, verificado).

Cuarto hallazgo, no un bug sino un limite de alcance a tener presente: el
cuadre de monto por XML_UUID solo es correcto si se suma TODOS los folios
reales que comparten ese UUID -- una factura consolidada (tipico en
CONTROL_COMBUSTIBLE) puede repartirse entre folios de VARIAS Poliza_
Configuracion distintas. Por eso este script NO pasa por
`reconstruir_config()` (limitado a una sola config, como 14/15) -- trae
los documentos directo de Gasto_Registro/Gasto_Registro_Documento, y para
el cuadre de monto expande cada XML_UUID a TODOS los folios que lo usan
en todo el sistema, sin restringir a fecha ni origen del universo inicial.

Cobertura: solo enero 2026 en las corridas de esta sesion (2026-09-05),
sin generalizar todavia a enero-marzo -- ver Pendiente en PROGRESS.md.

Uso:
    python3 16_reconciliacion_xml_por_origen.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
"""
import argparse
import sys

from connection_205_trivasadb3 import engine  # default de exploracion

import pandas as pd
from sqlalchemy import text
from helpers_output import console, mostrar_tabla, resumen

# Origenes donde SI se espera XML por logica de negocio -- ver docstring.
ORIGENES_CON_XML_ESPERADO = ["GASTO_DIRECTO", "VIAJE", "ORDEN_COMPRA", "CONTROL_COMBUSTIBLE"]


def documentos(fecha_ini: str, fecha_fin: str, empresa: str) -> pd.DataFrame:
    """Documentos (FOLIO, GRD_ID) de los 4 origenes con XML esperado,
    importe nativo SIN convertir a MXN (bug #3 del docstring -- se compara
    contra Cd_Monto, que viene en moneda original)."""
    origenes_sql = ",".join(f"'{o}'" for o in ORIGENES_CON_XML_ESPERADO)
    df = pd.read_sql(text(f"""
        SELECT
            gr.Gr_Folio AS FOLIO,
            CASE WHEN ISNULL(gr.Gr_Tabla,'')='' THEN 'GASTO_DIRECTO' ELSE gr.Gr_Tabla END AS ORIGEN,
            RIGHT('0000' + CAST(grd.Grd_ID AS varchar(10)), 4) AS GRD_ID,
            grd.Grd_Precio_Neto_Importe AS IMPORTE_DOC
        FROM Gasto_Registro gr
        JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
        JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
        WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
          AND gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = :emp
          AND (CASE WHEN ISNULL(gr.Gr_Tabla,'')='' THEN 'GASTO_DIRECTO' ELSE gr.Gr_Tabla END) IN ({origenes_sql})
    """), engine, params={"fi": fecha_ini, "ff": fecha_fin, "emp": empresa})
    df["FOLIO"] = df.FOLIO.str.strip()
    return df


def xml_ligado(folios: list) -> pd.DataFrame:
    """XML (CFDI) ligado a documentos GASTO_REGISTRO -- ambos formatos de
    Cd_Documento (bug #1), deduplicado por (FOLIO, GRD_ID, XML_UUID)
    (bug #2)."""
    if not folios:
        return pd.DataFrame(columns=["FOLIO", "GRD_ID", "XML_UUID", "XML_MONTO"])
    partes = []
    for i in range(0, len(folios), 900):
        chunk = folios[i:i + 900]
        in_list = ",".join(f"'{f}'" for f in chunk)
        partes.append(f"""
        SELECT LEFT(Cd_Documento, 10) AS FOLIO, SUBSTRING(Cd_Documento, 11, 4) AS GRD_ID,
               Cd_Timbre_UUID AS XML_UUID, Cd_Monto AS XML_MONTO
        FROM Comprobante_Digital
        WHERE Cd_Tabla = 'GASTO_REGISTRO' AND LEN(Cd_Documento) IN (14, 18)
          AND LEFT(Cd_Documento, 10) IN ({in_list})
        """)
    df = pd.read_sql(text(" UNION ALL ".join(partes)), engine)
    df["FOLIO"] = df.FOLIO.str.strip()
    return df.drop_duplicates(subset=["FOLIO", "GRD_ID", "XML_UUID"])


def expandir_uuid_a_universo_completo(uuids: list) -> pd.DataFrame:
    """Para cuadrar el MONTO de un XML_UUID hay que sumar TODOS los folios
    reales que lo comparten -- sin restringir a fecha ni origen del
    universo inicial (bug/limite #4 del docstring: una factura consolidada
    puede cruzar a folios de otra fecha, otro origen, u otra config de
    poliza). Devuelve (FOLIO, GRD_ID, XML_UUID, XML_MONTO, IMPORTE_DOC)
    para cada documento real ligado a cualquiera de los UUID pedidos,
    dondequiera que este en el sistema."""
    if not uuids:
        return pd.DataFrame(columns=["FOLIO", "GRD_ID", "XML_UUID", "XML_MONTO", "IMPORTE_DOC"])
    partes = []
    for i in range(0, len(uuids), 900):
        chunk = uuids[i:i + 900]
        in_list = ",".join(f"'{u}'" for u in chunk)
        partes.append(f"""
        SELECT LEFT(Cd_Documento, 10) AS FOLIO, SUBSTRING(Cd_Documento, 11, 4) AS GRD_ID,
               Cd_Timbre_UUID AS XML_UUID, Cd_Monto AS XML_MONTO
        FROM Comprobante_Digital
        WHERE Cd_Tabla = 'GASTO_REGISTRO' AND LEN(Cd_Documento) IN (14, 18)
          AND Cd_Timbre_UUID IN ({in_list})
        """)
    xml = pd.read_sql(text(" UNION ALL ".join(partes)), engine).drop_duplicates(subset=["FOLIO", "GRD_ID", "XML_UUID"])
    xml["FOLIO"] = xml.FOLIO.str.strip()

    folios = xml.FOLIO.unique().tolist()
    partes2 = []
    for i in range(0, len(folios), 900):
        chunk = folios[i:i + 900]
        in_list = ",".join(f"'{f}'" for f in chunk)
        partes2.append(f"""
        SELECT Gr_Folio AS FOLIO, RIGHT('0000' + CAST(Grd_ID AS varchar(10)), 4) AS GRD_ID,
               Grd_Precio_Neto_Importe AS IMPORTE_DOC
        FROM Gasto_Registro_Documento WHERE Gr_Folio IN ({in_list})
        """)
    importe = pd.read_sql(text(" UNION ALL ".join(partes2)), engine)
    importe["FOLIO"] = importe.FOLIO.str.strip()

    return xml.merge(importe, on=["FOLIO", "GRD_ID"], how="left")


def cobertura_por_origen(docs: pd.DataFrame, xml: pd.DataFrame) -> pd.DataFrame:
    """¿El documento tiene ALGUN XML ligado? -- pregunta de existencia,
    no de cuadre de monto (esas son dos preguntas distintas, ver
    PROGRESS.md)."""
    m = docs.merge(xml.assign(TIENE_XML=True)[["FOLIO", "GRD_ID", "TIENE_XML"]], on=["FOLIO", "GRD_ID"], how="left")
    m["TIENE_XML"] = m["TIENE_XML"].fillna(False).astype(bool)
    r = m.groupby("ORIGEN").apply(lambda g: pd.Series({
        "documentos": len(g),
        "con_xml": int(g.TIENE_XML.sum()),
        "importe_total": g.IMPORTE_DOC.sum(),
        "importe_con_xml": g.loc[g.TIENE_XML, "IMPORTE_DOC"].sum(),
    }), include_groups=False).reset_index()
    r["pct_docs"] = (r.con_xml / r.documentos * 100).round(2)
    r["pct_importe"] = (r.importe_con_xml / r.importe_total * 100).round(2)
    return r.sort_values("importe_total", ascending=False)


def cuadre_monto_por_origen(docs: pd.DataFrame, xml: pd.DataFrame) -> pd.DataFrame:
    """De los documentos que SI tienen XML, ¿el monto coincide? Se agrupa
    por XML_UUID sobre el universo COMPLETO de folios que lo comparten
    (ver expandir_uuid_a_universo_completo) -- sin esto, una factura
    consolidada que cruza fecha/origen/config sale "no cuadra" por
    definicion, sin ser un problema real (ver CONTROL_COMBUSTIBLE en
    PROGRESS.md)."""
    uuids = xml.XML_UUID.unique().tolist()
    completo = expandir_uuid_a_universo_completo(uuids)

    por_uuid = completo.groupby("XML_UUID", as_index=False).agg(
        IMPORTE_DOC=("IMPORTE_DOC", "sum"), XML_MONTO=("XML_MONTO", "first")
    )
    por_uuid["CUADRA"] = (por_uuid.IMPORTE_DOC - por_uuid.XML_MONTO).abs() < 1

    # Origen: el mas frecuente entre los folios DENTRO de nuestro universo
    # inicial (docs) que usan cada UUID -- un UUID puede tener folios de
    # mas de un origen en casos raros, se usa moda para asignar uno solo.
    xml_con_origen = xml.merge(docs[["FOLIO", "GRD_ID", "ORIGEN"]], on=["FOLIO", "GRD_ID"], how="left")
    origen_por_uuid = xml_con_origen.groupby("XML_UUID")["ORIGEN"].agg(lambda s: s.mode().iloc[0])
    por_uuid["ORIGEN"] = por_uuid.XML_UUID.map(origen_por_uuid)

    r = por_uuid.groupby("ORIGEN").agg(xml_uuid=("CUADRA", "size"), cuadran=("CUADRA", "sum")).reset_index()
    r["pct"] = (r.cuadran / r.xml_uuid * 100).round(2)
    return r.sort_values("xml_uuid", ascending=False), por_uuid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    ap.add_argument("--empresa", default="0001")
    args = ap.parse_args()

    console.print(f"[bold]16 -- Conciliacion XML por origen (con XML esperado): {ORIGENES_CON_XML_ESPERADO}[/bold]")

    docs = documentos(args.fecha_ini, args.fecha_fin, args.empresa)
    xml = xml_ligado(docs.FOLIO.unique().tolist())

    cobertura = cobertura_por_origen(docs, xml)
    mostrar_tabla(cobertura, "Cobertura -- ¿el documento tiene XML ligado? (existencia, no monto)")

    cuadre, por_uuid = cuadre_monto_por_origen(docs, xml)
    mostrar_tabla(cuadre, "Cuadre de MONTO -- de los que tienen XML, ¿el importe coincide con Cd_Monto?")

    tot_imp = cobertura.importe_total.sum()
    tot_con_xml = cobertura.importe_con_xml.sum()
    tot_uuid = cuadre.xml_uuid.sum()
    tot_cuadran = cuadre.cuadran.sum()
    resumen(
        importe_total=f"{tot_imp:,.2f}",
        importe_con_xml=f"{tot_con_xml:,.2f} ({100*tot_con_xml/tot_imp:.2f}%)",
        xml_uuid=f"{tot_uuid}",
        cuadran_monto=f"{tot_cuadran} ({100*tot_cuadran/tot_uuid:.2f}%)",
    )

    if (~por_uuid.CUADRA).any():
        mostrar_tabla(
            por_uuid[~por_uuid.CUADRA].assign(DIFERENCIA=lambda d: (d.IMPORTE_DOC - d.XML_MONTO).abs())
                                       .sort_values("DIFERENCIA", ascending=False).head(20),
            "XML_UUID que NO cuadran en monto (residual, ver Pendiente en PROGRESS.md)",
        )

    out = f"16_reconciliacion_xml_por_origen_{args.fecha_ini}_{args.fecha_fin}.csv"
    por_uuid.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]")


if __name__ == "__main__":
    main()
