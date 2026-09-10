"""
poliza_configuracion_lib.py -- reconstruccion de la query real que genera
una Poliza_Configuracion (pantalla CT001), extraida de
14_reconstruccion_via_poliza_configuracion.py para reusarla en el 15 y en
los reportes Streamlit CONT-4/CONT-5.

Ver PROGRESS.md (entrada "Rank-pairing vs. reconstruccion real via
Poliza_Configuracion") y trivasa-context/docs/proyectos/poliza-explor/
configuracion-polizas.md para la metodologia completa: Poliza_
Configuracion_Detalle.Pcd_Relacion ya hace el JOIN real a Gasto_Registro_
Control por (Gr_Folio, Grd_ID) que usa el motor de MPRO -- reconstruirlo
tal cual da una llave real, no rank-pairing.

Alcance: solo config 0450 probada/validada hasta ahora (100.00% contra
Poliza_Detalle real, 99.61% sin ambiguedad -- ver PROGRESS.md). Generalizar
a otras configs es cuestion de llamar reconstruir_config(cve, ...) con otro
valor de cve, pero solo 0450 tiene el escrutinio completo hecho.
"""
import sys

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, "/home/esteban/trivasa/connections")
from connection_205_trivasadb3 import engine  # default de exploracion


def reconstruir_config(cve: str, empresa: str, fecha_ini: str, fecha_fin: str) -> pd.DataFrame:
    """Reconstruye, linea por linea (sin SUM, sin colapsar), todos los
    renglones de Cargo+Centro_Costo de una Poliza_Configuracion -- el join
    real Gasto_Registro_Control <-> renglon que usa el motor.
    Devuelve (RENGLON, FOLIO, CECO, TIPO_GASTO, CUENTA, IMPORTE, GRD_ID)."""
    cab = pd.read_sql(text(
        "SELECT CAST(Pc_Relacion AS varchar(max)) rel FROM Poliza_Configuracion "
        "WHERE Pc_Cve_Poliza_Configuracion = :c"
    ), engine, params={"c": cve})
    if cab.empty:
        raise ValueError(f"Config {cve} no existe")
    rel_cab = cab.rel[0]

    globales = pd.read_sql(text(
        "SELECT CAST(Pcc_Valor AS varchar(max)) v FROM Poliza_Configuracion_Condicion "
        "WHERE Pc_Cve_Poliza_Configuracion = :c ORDER BY Pcc_ID"
    ), engine, params={"c": cve}).v.dropna()
    globales = [g.replace("<EMPRESA>", empresa) for g in globales if g.strip()]
    where_glob = " AND ".join(f"({g})" for g in globales) if globales else "1=1"

    det = pd.read_sql(text("""
        SELECT Pcd_ID,
               CAST(Pcd_Condicion AS varchar(max)) cond,
               CAST(Pcd_Cuenta_Contable AS varchar(max)) cuenta,
               CAST(Pcd_Cargo AS varchar(max)) cargo,
               CAST(Pcd_Relacion AS varchar(max)) rel
        FROM Poliza_Configuracion_Detalle
        WHERE Pc_Cve_Poliza_Configuracion = :c ORDER BY Pcd_ID
    """), engine, params={"c": cve})

    # Solo renglones de CARGO que resuelven por Centro_Costo -- mismo
    # filtro que poliza-explor/scripts/05_huecos_ceco_configuracion.py.
    cargos = det[
        (det.cargo.fillna("").str.strip() != "")
        & det.rel.fillna("").str.contains("Centro_Costo", na=False)
    ]
    if cargos.empty:
        raise ValueError(f"Config {cve}: sin renglones de Cargo+Centro_Costo")

    partes = []
    for _, r in cargos.iterrows():
        partes.append(f"""
        SELECT '{r.Pcd_ID}' AS RENGLON,
               Gasto_Registro.Gr_Folio AS FOLIO,
               Centro_Costo.Cc_Cve_Centro_Costo AS CECO,
               Tipo_Gasto.Tg_Cve_Tipo_Gasto AS TIPO_GASTO,
               {r.cuenta} AS CUENTA,
               Gasto_Registro_Control.Grc_Importe AS IMPORTE,
               Gasto_Registro_Control.Grd_ID AS GRD_ID
        FROM {rel_cab}
        {r.rel}
        WHERE {where_glob} AND ({r.cond})
          AND Gasto_Registro.Gr_Fecha >= '{fecha_ini}' AND Gasto_Registro.Gr_Fecha < '{fecha_fin}'
          AND Gasto_Registro.Es_Cve_Estado <> 'CA'
        """)

    sql = " UNION ALL ".join(partes)
    df = pd.read_sql(text(sql), engine)
    df["FOLIO"] = df.FOLIO.str.strip()
    df["IMPORTE"] = df["IMPORTE"].abs()
    return df


def abono_via_referencia(cve: str, empresa: str, fecha_ini: str, fecha_fin: str) -> pd.DataFrame:
    """Abono real de Poliza_Detalle, mismo patron que POLIZA_SQL de
    layout_gastos_lib.py (Pd_Referencia = Gr_Folio, Pd_Tipo=2), filtrado a
    una config especifica. Para config 0450: da 0 filas -- el Abono de esa
    config queda consolidado a nivel proveedor dentro de la poliza (que a
    su vez consolida VARIOS folios bajo el mismo Pl_Folio), su Pd_Referencia
    es el folio/referencia de la factura del proveedor, no Gr_Folio (visto
    en PROGRESS.md, entrada de este mismo script). No es un bug de esta
    funcion -- es honesto reflejar que para esta config el Abono no es
    atribuible por folio. Se deja generica (no hardcodeada a 0) para que
    sirva igual si se generaliza a otra config donde si aplique."""
    q = """
    SELECT
        gr.Gr_Folio AS FOLIO,
        pd.Cc_Cve_Cuenta_Contable AS CUENTA,
        cc.Cc_Descripcion AS CUENTA_DESCRIPCION,
        SUM(pd.Pd_Importe) AS ABONO
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    JOIN Poliza_Control plc ON plc.Pc_Tabla='GASTO_REGISTRO' AND plc.Pc_Documento=gr.Gr_Folio AND plc.Es_Cve_Estado<>'CA'
    JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio
    JOIN Poliza_Detalle pd ON pd.Pl_Folio = plc.Pl_Folio AND pd.Pd_Referencia = gr.Gr_Folio
    LEFT JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable
    WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
      AND gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = :emp AND pl.Es_Cve_Estado <> 'CA'
      AND pl.Pl_Configuracion = :cve AND pd.Pd_Tipo = 2
    GROUP BY gr.Gr_Folio, pd.Cc_Cve_Cuenta_Contable, cc.Cc_Descripcion
    """
    df = pd.read_sql(text(q), engine, params={"fi": fecha_ini, "ff": fecha_fin, "emp": empresa, "cve": cve})
    df["FOLIO"] = df.FOLIO.str.strip()
    return df


def xml_gasto_registro(folios: list) -> pd.DataFrame:
    """XML (CFDI) ligado a documentos de GASTO_REGISTRO, a nivel (FOLIO,
    GRD_ID) -- el grano real que usa Comprobante_Digital.Cd_Documento, para
    una lista concreta de folios (no por rango de fecha propio: la fecha
    de timbrado/captura del XML no siempre coincide con Gr_Fecha, filtrar
    por folio evita perder XML por ese desfase).

    Cd_Documento para Cd_Tabla='GASTO_REGISTRO' viene en DOS formatos --
    corregido 2026-09-05, ver PROGRESS.md (el filtro anterior, LEN=18
    unicamente, excluia el segundo formato completo, ~23% de los 96,872
    registros historicos de esta Cd_Tabla, 441 de 1,510 documentos con XML
    solo en enero 2026 -- confirmado con drill-down real de ORDEN_COMPRA,
    que paso de 76.39% a 100.00% de cuadre al corregir esto):
    - LEN 18: Gr_Folio (10) + Grd_ID zero-padded (4) + sufijo casi siempre
      '0001' (4). 74,352 registros historicos.
    - LEN 14: Gr_Folio (10) + Grd_ID zero-padded (4), SIN el sufijo extra.
      22,520 registros historicos -- mismo mecanismo, decodifica igual de
      limpio (verificado contra datos reales), simplemente otra variante
      de captura. No es ruido ni un formato distinto de verdad: se ignora
      el sufijo de la variante LEN=18 igual que antes (no aporta), y se
      agrupa solo por (FOLIO, GRD_ID) en ambos casos.

    Al traer ambos formatos, un mismo (FOLIO, GRD_ID) puede aparecer en
    Comprobante_Digital dos veces (una por formato) -- confirmado
    2026-09-05, enero-marzo 2026: 27 pares con mas de 1 fila. 20 son el
    MISMO XML capturado dos veces (mismo Cd_Timbre_UUID en ambos formatos)
    -- sin deduplicar, el merge en el codigo que consume esta funcion
    duplica el documento y su importe se cuenta 2x contra ese UUID (visto
    en 15_reconciliacion_xml_via_poliza_configuracion.py: folio
    23-0006650 mostraba IMPORTE_DOC exactamente el doble de Cd_Monto).
    Se deduplica aqui por (FOLIO, GRD_ID, XML_UUID). Los otros 7 pares
    tienen un XML_UUID GENUINAMENTE distinto entre formatos (2 CFDI reales
    ligados al mismo documento, no un duplicado de captura) -- eso NO se
    resuelve aqui, queda como ambiguedad real: el merge posterior producira
    2 filas para ese documento (una por cada UUID real), y el importe de
    ese documento se atribuira completo a cada uno de los 2 UUID en vez de
    dividirse -- residual conocido, pendiente de decidir un criterio
    (ej. UUID mas reciente) si llega a afectar un caso concreto."""
    if not folios:
        return pd.DataFrame(columns=["FOLIO", "GRD_ID", "XML_UUID", "XML_MONTO", "XML_RFC_EMISOR", "XML_FACTURA", "XML_FECHA"])

    partes = []
    for i in range(0, len(folios), 900):  # limite de parametros/IN de SQL Server
        chunk = folios[i:i + 900]
        in_list = ",".join(f"'{f}'" for f in chunk)
        partes.append(f"""
        SELECT
            LEFT(Cd_Documento, 10) AS FOLIO,
            SUBSTRING(Cd_Documento, 11, 4) AS GRD_ID,
            Cd_Timbre_UUID AS XML_UUID,
            Cd_Monto AS XML_MONTO,
            Cd_RFC_Emisor AS XML_RFC_EMISOR,
            Cd_Factura AS XML_FACTURA,
            Cd_Timbre_Fecha AS XML_FECHA
        FROM Comprobante_Digital
        WHERE Cd_Tabla = 'GASTO_REGISTRO' AND LEN(Cd_Documento) IN (14, 18)
          AND LEFT(Cd_Documento, 10) IN ({in_list})
        """)
    sql = " UNION ALL ".join(partes)
    df = pd.read_sql(text(sql), engine)
    return df.drop_duplicates(subset=["FOLIO", "GRD_ID", "XML_UUID"])
