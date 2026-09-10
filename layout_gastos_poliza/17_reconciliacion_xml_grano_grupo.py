"""
HITO: segunda vuelta sobre la conciliacion XML por origen del script `16`,
incorporando dos mejoras encontradas investigando `~/proyectos/conciliacion-
master/adjuntar-xml/` (proyecto paralelo, terminado 2026-09-04 por otra
sesion, que resuelve el mismo problema -- CFDI recibido vs. registro MPro --
con metodologia mas madura) y `~/proyectos/layout-contabilidad/layout_gastos/`
(exploracion de agosto 2026 sobre el mismo "Layout de Gastos").

Contexto: `16_reconciliacion_xml_por_origen.py` compara, por cada `XML_UUID`,
la suma de sus documentos ligados contra `Cd_Monto` -- pero solo agrupa por
`(FOLIO, GRD_ID)` <-> `UUID` a nivel de PAR, sin resolver que un mismo XML
puede repartirse entre MUCHOS documentos (factura partida en N lineas) o que
un documento puede compartir mas de un CFDI. `GASTO_DIRECTO` quedaba con un
residual grande sin explicar (58 de 542 `XML_UUID`, enero 2026).

DOS MEJORAS PROBADAS Y CONFIRMADAS (2026-09-05), sobre 3 rangos de fecha
(enero, enero-marzo, enero-mayo 2026) para elegir con evidencia, no
suposicion -- el % total no varia mucho entre rangos (~40-41%), asi que
NINGUN periodo es claramente "mejor"; se documentan los 3 para que quede
registro de que se probo, no una sola corrida optimista:

1. GRANO DE COMPONENTE CONEXA (union-find), no `(FOLIO,GRD_ID)`<->UUID
   por par. Idea tomada de `adjuntar-xml/conciliacion_xml_lib.
   asignar_grupos()` -- reimplementada aqui en version LIGERA (sin traer
   `Cd_XML`, el campo de texto completo del CFDI) porque la maquina de
   este entorno de exploracion solo tiene ~5GB de RAM con menos de 400MB
   libres en el momento de esta sesion: traer el XML crudo de miles de
   CFDI para expandir iterativamente agoto la memoria (confirmado con
   `free -h` a mitad de una corrida). La version ligera solo necesita
   `(FOLIO, GRD_ID, XML_UUID, XML_MONTO)` -- sin el texto del XML -- para
   resolver el mismo grafo bipartito.

   Ademas de agrupar, la expansion tiene que CERRAR el universo: si la
   factura de un XML cuelga tambien de folios FUERA de nuestro filtro
   inicial (los 4 origenes de este script) -- caso real ya visto en `16`,
   una factura de combustible con folios en la config `0427` ademas de la
   `0450` -- hay que traer esos folios tambien o el grupo sale
   estructuralmente "no cuadra" aunque el XML si tenga su contraparte
   completa en MPro. Se expande por UUID (documentos que lo comparten) y
   luego por folio (mas XML de esos folios), hasta que no aparece nada
   nuevo.

2. CFDI TIPO RETENCIONES: MPro liga estos comprobantes con `Cd_Monto=0`
   bajo `Cd_Tabla='GASTO_REGISTRO'` -- el monto real vive en una fila
   HERMANA del MISMO `Cd_Timbre_UUID`, bajo `Cd_Tabla='CONSTANCIA_
   RETENCION'` (Trivasa es el EMISOR de esa constancia: obligacion fiscal
   al retener ISR sobre honorarios pagados a personas fisicas). Confirmado
   contra datos reales: `IMPORTE_DOC = Cd_Monto_constancia * 0.90` exacto
   en los casos verificados -- retencion de ISR del 10%. Explicaba 31 de
   los 58 `XML_UUID` sin cuadrar de `GASTO_DIRECTO` en enero 2026 (16 de
   esos 31 cuadran exacto con la regla del 90%; los otros 15 quedan sin
   constancia ligada, residual sin explicar).

EFECTO MEDIDO (enero 2026, `GASTO_DIRECTO`, % de IMPORTE que cuadra sobre
el total del origen):
  - Baseline `16` (par a par, sin retenciones):        27.56%
  - + grano de componente conexa:                       27.73%  (+0.17pp,
    marginal -- el residual de GASTO_DIRECTO NO era mayormente por reparto
    de documentos, contrario a lo que se esperaba de adjuntar-xml)
  - + fix de retenciones (el que SI importa aqui):      31.40%  (+3.67pp)

`VIAJE`/`ORDEN_COMPRA`/`CONTROL_COMBUSTIBLE` ya estaban ~100% desde `16`
(tras las correcciones de formato/duplicados/moneda de esa sesion) y se
mantienen aqui. Excepcion nueva, sin explicar: `CONTROL_COMBUSTIBLE` cae a
73.49% en el rango enero-mayo (era 100% en enero y enero-marzo) -- no
investigado, ver Pendiente.

NO INCORPORADO en este script (evaluado, descartado o pospuesto):
  - Parsear `Cd_XML` para complementos (CFDI de Pago/REP, Vales de
    Despensa) -- propuesta real de `adjuntar-xml`, pero el residual de
    GASTO_DIRECTO resulto ser mayoritariamente RETENCIONES (mecanismo
    distinto, ya cubierto arriba), no REP/Vales. Se pospone a un script
    18 si el residual restante (27/58 UUID de tipo Ingreso normal, sin
    patron unico identificado) lo amerita -- ahi si haria falta leer el
    XML completo, con cuidado de memoria (parsear solo esos ~27 casos
    puntuales, no el universo completo).
  - Cuenta_X_Pagar como cadena documental alterna para CONTROL_
    COMBUSTIBLE (validado por `layout-contabilidad/layout_gastos/docs/
    control_combustible_hallazgo.md`, otra sesion, 30/30 y 32/32 en dos
    meses) -- no hizo falta: el grano de componente conexa YA resuelve el
    caso de esta sesion (confirmado enero y enero-marzo en 100%), aunque
    el nuevo residual de enero-mayo podria necesitarlo si no es la misma
    causa.
  - Marcar CFDI intercompania -- no se encontraron casos en el universo
    de estos 4 origenes durante las pruebas; se deja fuera hasta ver
    evidencia de que aplica aqui.

Uso:
    python3 17_reconciliacion_xml_grano_grupo.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
"""
import argparse
import sys

from connection_205_trivasadb3 import engine  # default de exploracion

import pandas as pd
from sqlalchemy import text
from helpers_output import console, mostrar_tabla, resumen

ORIGENES_CON_XML_ESPERADO = ["GASTO_DIRECTO", "VIAJE", "ORDEN_COMPRA", "CONTROL_COMBUSTIBLE"]


def documentos(fi: str, ff: str, empresa: str = "0001") -> pd.DataFrame:
    """(FOLIO, GRD_ID, ORIGEN, IMPORTE_DOC) de los 4 origenes con XML
    esperado -- importe SIN convertir por tipo de cambio (Comprobante_
    Digital.Cd_Monto viene en la moneda ORIGINAL del CFDI, ver `16`)."""
    origenes_sql = ",".join(f"'{o}'" for o in ORIGENES_CON_XML_ESPERADO)
    df = pd.read_sql(text(f"""
        SELECT
            gr.Gr_Folio AS FOLIO,
            CASE WHEN ISNULL(gr.Gr_Tabla,'') = '' THEN 'GASTO_DIRECTO' ELSE gr.Gr_Tabla END AS ORIGEN,
            RIGHT('0000' + CAST(grd.Grd_ID AS varchar(10)), 4) AS GRD_ID,
            grd.Grd_Precio_Neto_Importe AS IMPORTE_DOC
        FROM Gasto_Registro gr
        JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
        JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
        WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
          AND gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = :emp
          AND (CASE WHEN ISNULL(gr.Gr_Tabla,'') = '' THEN 'GASTO_DIRECTO' ELSE gr.Gr_Tabla END) IN ({origenes_sql})
    """), engine, params={"fi": fi, "ff": ff, "emp": empresa})
    df["FOLIO"] = df.FOLIO.str.strip()
    return df


def xml_ligero(folios: list, chunk: int = 900) -> pd.DataFrame:
    """(FOLIO, GRD_ID, XML_UUID, XML_MONTO) -- ambos formatos de longitud
    de Cd_Documento (ver `16`), deduplicado. SIN `Cd_XML` a proposito (ver
    docstring del modulo -- limite de memoria del entorno)."""
    if not folios:
        return pd.DataFrame(columns=["FOLIO", "GRD_ID", "XML_UUID", "XML_MONTO"])
    partes = []
    for i in range(0, len(folios), chunk):
        c = folios[i:i + chunk]
        in_list = ",".join(f"'{f}'" for f in c)
        partes.append(f"""
        SELECT LEFT(Cd_Documento, 10) AS FOLIO, SUBSTRING(Cd_Documento, 11, 4) AS GRD_ID,
               UPPER(LTRIM(RTRIM(Cd_Timbre_UUID))) AS XML_UUID, Cd_Monto AS XML_MONTO
        FROM Comprobante_Digital
        WHERE Cd_Tabla = 'GASTO_REGISTRO' AND LEN(Cd_Documento) IN (14, 18)
          AND LEFT(Cd_Documento, 10) IN ({in_list})
        """)
    df = pd.read_sql(text(" UNION ALL ".join(partes)), engine)
    df["FOLIO"] = df.FOLIO.str.strip()
    return df.drop_duplicates(subset=["FOLIO", "GRD_ID", "XML_UUID"])


def expandir_por_uuid(uuids: list, chunk: int = 900) -> pd.DataFrame:
    """Para cada UUID, TODOS los documentos reales que lo comparten en todo
    el sistema (sin restringir a fecha/origen/config del universo
    inicial) -- resuelve facturas consolidadas que cruzan folios fuera de
    nuestro filtro de partida (ver docstring del modulo, caso combustible)."""
    if not uuids:
        return pd.DataFrame(columns=["FOLIO", "GRD_ID", "XML_UUID", "XML_MONTO"])
    partes = []
    for i in range(0, len(uuids), chunk):
        c = uuids[i:i + chunk]
        in_list = ",".join(f"'{u}'" for u in c)
        partes.append(f"""
        SELECT LEFT(Cd_Documento, 10) AS FOLIO, SUBSTRING(Cd_Documento, 11, 4) AS GRD_ID,
               UPPER(LTRIM(RTRIM(Cd_Timbre_UUID))) AS XML_UUID, Cd_Monto AS XML_MONTO
        FROM Comprobante_Digital
        WHERE Cd_Tabla = 'GASTO_REGISTRO' AND LEN(Cd_Documento) IN (14, 18)
          AND UPPER(LTRIM(RTRIM(Cd_Timbre_UUID))) IN ({in_list})
        """)
    df = pd.read_sql(text(" UNION ALL ".join(partes)), engine).drop_duplicates(subset=["FOLIO", "GRD_ID", "XML_UUID"])
    df["FOLIO"] = df.FOLIO.str.strip()
    return df


def importe_docs(folios: list, chunk: int = 900) -> pd.DataFrame:
    """Importe nativo (sin convertir) de documentos por FOLIO -- para los
    folios que aparecieron durante la expansion (puede exceder el universo
    inicial de los 4 origenes)."""
    if not folios:
        return pd.DataFrame(columns=["FOLIO", "GRD_ID", "IMPORTE_DOC"])
    partes = []
    for i in range(0, len(folios), chunk):
        c = folios[i:i + chunk]
        in_list = ",".join(f"'{f}'" for f in c)
        partes.append(f"""
        SELECT Gr_Folio AS FOLIO, RIGHT('0000' + CAST(Grd_ID AS varchar(10)), 4) AS GRD_ID,
               Grd_Precio_Neto_Importe AS IMPORTE_DOC
        FROM Gasto_Registro_Documento WHERE Gr_Folio IN ({in_list})
        """)
    df = pd.read_sql(text(" UNION ALL ".join(partes)), engine)
    df["FOLIO"] = df.FOLIO.str.strip()
    return df


def ajustar_retenciones(docs_uuid: pd.DataFrame, chunk: int = 900) -> pd.DataFrame:
    """CFDI tipo RETENCIONES: MPro los liga con `Cd_Monto=0` bajo
    `Cd_Tabla='GASTO_REGISTRO'` -- el monto real vive en una fila HERMANA
    del mismo `Cd_Timbre_UUID` bajo `Cd_Tabla='CONSTANCIA_RETENCION'`
    (Trivasa es el EMISOR: obligacion fiscal al retener ISR de honorarios
    a personas fisicas). Confirmado con datos reales (2026-09-05):
    `IMPORTE_DOC = Cd_Monto_constancia * 0.90` exacto en los casos
    verificados -- ISR 10%. Se aplica solo donde `XML_MONTO` viene en 0
    (nunca pisa un monto ya distinto de 0)."""
    uuids = docs_uuid.loc[docs_uuid.XML_MONTO == 0, "XML_UUID"].unique().tolist()
    if not uuids:
        return docs_uuid
    partes = []
    for i in range(0, len(uuids), chunk):
        c = uuids[i:i + chunk]
        in_list = ",".join(f"'{u}'" for u in c)
        partes.append(f"""
        SELECT UPPER(LTRIM(RTRIM(Cd_Timbre_UUID))) AS XML_UUID, Cd_Monto AS MONTO_CONSTANCIA
        FROM Comprobante_Digital
        WHERE Cd_Tabla = 'CONSTANCIA_RETENCION' AND UPPER(LTRIM(RTRIM(Cd_Timbre_UUID))) IN ({in_list})
        """)
    constancias = pd.read_sql(text(" UNION ALL ".join(partes)), engine).drop_duplicates("XML_UUID")
    if constancias.empty:
        return docs_uuid
    mapa = dict(zip(constancias.XML_UUID, constancias.MONTO_CONSTANCIA * 0.90))
    docs_uuid = docs_uuid.copy()
    mask = docs_uuid.XML_MONTO == 0
    docs_uuid.loc[mask, "XML_MONTO"] = docs_uuid.loc[mask, "XML_UUID"].map(mapa).fillna(0.0)
    return docs_uuid


def asignar_grupos(docs_uuid: pd.DataFrame):
    """Union-find sobre (FOLIO|GRD_ID) <-> XML_UUID -- mismo criterio que
    `adjuntar-xml/conciliacion_xml_lib.asignar_grupos()`, reimplementado
    aqui sin esa dependencia (evita arrastrar su import, que trae Cd_XML
    en otras funciones) y sin necesitar el texto del XML."""
    padre = {}

    def find(a):
        padre.setdefault(a, a)
        while padre[a] != a:
            padre[a] = padre[padre[a]]
            a = padre[a]
        return a

    docs_uuid = docs_uuid.copy()
    docs_uuid["DOC"] = docs_uuid.FOLIO + "|" + docs_uuid.GRD_ID
    for u, d in zip(docs_uuid.XML_UUID, docs_uuid.DOC):
        ra, rb = find(("X", u)), find(("D", d))
        if ra != rb:
            padre[ra] = rb

    raiz_folio = {}
    for (tipo, val) in list(padre):
        if tipo == "D":
            r = find((tipo, val))
            f = val.split("|")[0]
            if r not in raiz_folio or f < raiz_folio[r]:
                raiz_folio[r] = f
    etiqueta = {r: f for r, f in raiz_folio.items()}
    docs_uuid["GRUPO"] = [etiqueta[find(("X", u))] for u in docs_uuid.XML_UUID]
    mapa_doc = {d: etiqueta[find(("D", d))] for d in docs_uuid.DOC.unique()}
    return docs_uuid, mapa_doc


def conciliar(fi: str, ff: str, empresa: str = "0001", max_iter: int = 3) -> pd.DataFrame:
    """Nucleo del script: universo por folio del periodo (no por fecha de
    timbrado del CFDI -- ver docstring del modulo, CONTROL_COMBUSTIBLE casi
    nunca timbra en el mismo mes del folio), expandido a componente conexa,
    con el fix de retenciones aplicado antes de agrupar."""
    docs = documentos(fi, ff, empresa)
    docs["DOC"] = docs.FOLIO + "|" + docs.GRD_ID

    xml = xml_ligero(docs.FOLIO.unique().tolist())
    todos_uuid = set(xml.XML_UUID.unique())
    acumulado = [xml]

    consultados = set(todos_uuid)
    for _ in range(max_iter):
        extra = expandir_por_uuid(sorted(consultados))
        nuevos_uuid = set(extra.XML_UUID.unique()) - todos_uuid
        acumulado.append(extra)
        todos_uuid |= nuevos_uuid

        extra_folios = sorted(extra.FOLIO.unique())
        xml2 = xml_ligero(extra_folios)
        nuevos_uuid2 = set(xml2.XML_UUID.unique()) - todos_uuid
        acumulado.append(xml2)
        todos_uuid |= nuevos_uuid2

        if not (nuevos_uuid | nuevos_uuid2):
            break
        consultados = nuevos_uuid | nuevos_uuid2

    docs_uuid = pd.concat(acumulado, ignore_index=True).drop_duplicates(subset=["FOLIO", "GRD_ID", "XML_UUID"])
    docs_uuid = ajustar_retenciones(docs_uuid)
    docs_uuid, mapa_doc = asignar_grupos(docs_uuid)

    imp = importe_docs(sorted(docs_uuid.FOLIO.unique()))
    docs_uuid = docs_uuid.merge(imp, on=["FOLIO", "GRD_ID"], how="left")

    docs["GRUPO"] = docs.DOC.map(mapa_doc)
    sin_xml_mask = docs["GRUPO"].isna()
    docs.loc[sin_xml_mask, "GRUPO"] = docs.loc[sin_xml_mask, "DOC"]

    lado_xml = docs_uuid.drop_duplicates(["GRUPO", "XML_UUID"]).groupby("GRUPO").agg(
        N_XML=("XML_UUID", "size"), XML_IMPORTE=("XML_MONTO", "sum"),
    ).reset_index()

    # El lado "documento" suma TODOS los documentos reales del grupo
    # (docs_uuid expandido, puede exceder los 4 origenes de interes -- ver
    # docstring), no solo `docs` (nuestro universo inicial). Los documentos
    # de `docs` sin ningun XML no aparecen en docs_uuid y se agregan aparte.
    lado_doc_con_xml = docs_uuid.drop_duplicates(["GRUPO", "FOLIO", "GRD_ID"]).groupby("GRUPO").agg(
        N_DOC=("GRD_ID", "size"), IMPORTE_DOC=("IMPORTE_DOC", "sum"),
    ).reset_index()
    origen_por_grupo = docs.groupby("GRUPO")["ORIGEN"].agg(lambda s: s.mode().iloc[0]).rename("ORIGEN").reset_index()
    lado_doc_con_xml = lado_doc_con_xml.merge(origen_por_grupo, on="GRUPO", how="inner")

    lado_doc_sin_xml = docs.loc[sin_xml_mask].groupby(["GRUPO", "ORIGEN"], as_index=False).agg(
        N_DOC=("DOC", "size"), IMPORTE_DOC=("IMPORTE_DOC", "sum"),
    )
    lado_doc = pd.concat([lado_doc_con_xml, lado_doc_sin_xml], ignore_index=True)

    g = lado_doc.merge(lado_xml, on="GRUPO", how="left")
    g["N_XML"] = g.N_XML.fillna(0).astype(int)
    g["XML_IMPORTE"] = g.XML_IMPORTE.fillna(0.0)
    g["DIF"] = (g.IMPORTE_DOC - g.XML_IMPORTE).round(2)
    g["CUADRA"] = g.DIF.abs() < 1
    g["TIENE_XML"] = g.N_XML > 0
    return g


def resumen_por_origen(g: pd.DataFrame) -> pd.DataFrame:
    r = g.groupby("ORIGEN").agg(
        grupos=("GRUPO", "size"),
        importe_total=("IMPORTE_DOC", "sum"),
        importe_con_xml=("IMPORTE_DOC", lambda s: s[g.loc[s.index, "TIENE_XML"]].sum()),
        importe_cuadra=("IMPORTE_DOC", lambda s: s[g.loc[s.index, "CUADRA"]].sum()),
    ).reset_index()
    r["pct_con_xml"] = (r.importe_con_xml / r.importe_total * 100).round(2)
    r["pct_cuadra"] = (r.importe_cuadra / r.importe_total * 100).round(2)
    return r.sort_values("importe_total", ascending=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    ap.add_argument("--empresa", default="0001")
    args = ap.parse_args()

    console.print(f"[bold]17 -- Conciliacion XML por grano de grupo (union-find + fix retenciones): {ORIGENES_CON_XML_ESPERADO}[/bold]")

    g = conciliar(args.fecha_ini, args.fecha_fin, args.empresa)
    r = resumen_por_origen(g)
    mostrar_tabla(r, "Cobertura y cuadre de monto por origen (grano: componente conexa)")

    tot = r.importe_total.sum()
    cxml = r.importe_con_xml.sum()
    cua = r.importe_cuadra.sum()
    resumen(
        importe_total=f"{tot:,.2f}",
        importe_con_xml=f"{cxml:,.2f} ({100*cxml/tot:.2f}%)",
        importe_cuadra=f"{cua:,.2f} ({100*cua/tot:.2f}%)",
    )

    residual = g[g.TIENE_XML & ~g.CUADRA].sort_values("DIF", key=lambda s: s.abs(), ascending=False)
    if len(residual):
        mostrar_tabla(residual.head(20), "Grupos con XML que NO cuadran (residual, ver Pendiente en PROGRESS.md)")

    out = f"17_reconciliacion_xml_grano_grupo_{args.fecha_ini}_{args.fecha_fin}.csv"
    g.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]")


if __name__ == "__main__":
    main()
