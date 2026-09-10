"""
layout_gastos_config_lib.py -- logica de negocio para CONT-4 y CONT-5,
los reportes exploratorios (2026-09-04) que reemplazan rank-pairing por
la reconstruccion real via Poliza_Configuracion (ver poliza_configuracion_
lib.py, 14/15, y PROGRESS.md "Rank-pairing vs. reconstruccion real via
Poliza_Configuracion").

Cobertura: SOLO config 0450 (GASTO_DIRECTO/CONTROL_COMBUSTIBLE/VIAJE/
ORDEN_COMPRA cuando su poliza vino de esa config -- ~95% de esos 4
origenes, ver PROGRESS.md). NO cubre CONSUMO_INTERNO, GASTO_RECLASIFICACION
ni GASTO_REGISTRO_NOMINA -- esos siguen su propio mecanismo ya resuelto en
layout_gastos_lib.py (CONT-1/CONT-2). Estos dos reportes son un
complemento exploratorio, no un reemplazo de CONT-1/CONT-2.

CONT-4: grano (FOLIO, GRD_ID, CUENTA) -- el documento, mismo grano que usa
Comprobante_Digital para el XML. 1 fila = 1 documento x cuenta (casi
siempre 1 documento = 1 cuenta, ver PROGRESS.md, 91.95% de los casos).

CONT-5: grano (FOLIO, CUENTA) -- colapsa GRD_ID. Deliberadamente "el grano
equivocado" para XML (ver PROGRESS.md: coincide con el documento en 86.28%
de los folios, pero falla en el grupo que MAS importa -- el que tiene mas
XML ligado, 81.77% vs 61.92%). Construido a proposito junto a CONT-4 para
que se pueda comparar lado a lado y ver la diferencia con datos reales, no
en abstracto.

En ambos, CARGO/ABONO se conservan como columnas separadas -- mismo
formato que layout_gastos_lib.reporte_completo(). ABONO sale en 0 para
todo config 0450 (ver poliza_configuracion_lib.abono_via_referencia): no
es un bug, esa config consolida el Abono a nivel proveedor dentro de una
poliza que a su vez consolida varios folios -- su Pd_Referencia no es
Gr_Folio. Se deja la columna igual (honesto, no oculto) por si se
generaliza a otra config donde si aplique.

La pestana de Reconciliacion reusa TAL CUAL resumen_por_folio()/
resumen_qa() de layout_gastos_lib.py -- opera a nivel FOLIO (Cargo-Abono
vs Importe Folio), igual que CONT-1/CONT-2, sin importar el grano mas fino
de la tabla de datos.
"""
import sys

import pandas as pd
from sqlalchemy import text

sys.path.insert(0, "/home/esteban/trivasa/connections")
from connection_205_trivasadb3 import engine  # default de exploracion

from layout_gastos_lib import IMPORTE_FOLIO_SQL  # reusado tal cual, ya validado
from poliza_configuracion_lib import reconstruir_config, abono_via_referencia, xml_gasto_registro


ORIGEN_SQL = """
SELECT DISTINCT
    gr.Gr_Folio AS FOLIO,
    CASE WHEN ISNULL(gr.Gr_Tabla, '') = '' THEN 'GASTO_DIRECTO' ELSE gr.Gr_Tabla END AS ORIGEN
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc ON plc.Pc_Tabla = 'GASTO_REGISTRO' AND plc.Pc_Documento = gr.Gr_Folio AND plc.Es_Cve_Estado <> 'CA'
JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = :empresa AND pl.Es_Cve_Estado <> 'CA'
  AND pl.Pl_Configuracion = :config
"""

CUENTA_DESCRIPCION_SQL = "SELECT Cc_Cve_Cuenta_Contable AS CUENTA, Cc_Descripcion AS CUENTA_DESCRIPCION FROM Cuenta_Contable"


def _base(fecha_ini: str, fecha_fin: str, config: str = "0450", empresa: str = "0001"):
    """Piezas comunes a CONT-4 y CONT-5: cargo reconstruido, abono, XML,
    origen y descripcion de cuenta -- cada reporte las agrega distinto."""
    p = {"fecha_ini": fecha_ini, "fecha_fin": fecha_fin, "empresa": empresa, "config": config}

    recon = reconstruir_config(config, empresa, fecha_ini, fecha_fin)
    cargo = recon.groupby(["FOLIO", "GRD_ID", "CUENTA"], as_index=False).IMPORTE.sum().rename(columns={"IMPORTE": "CARGO"})
    folios = sorted(cargo.FOLIO.unique().tolist())

    origen = pd.read_sql(text(ORIGEN_SQL), engine, params=p)
    origen["FOLIO"] = origen.FOLIO.str.strip()

    cuentas = pd.read_sql(text(CUENTA_DESCRIPCION_SQL), engine)

    abono = abono_via_referencia(config, empresa, fecha_ini, fecha_fin)
    abono_folio = abono.groupby("FOLIO", as_index=False).ABONO.sum()

    xml = xml_gasto_registro(folios)

    imp = pd.read_sql(text(IMPORTE_FOLIO_SQL.replace(
        "AND ISNULL(gr.Gr_Tabla, '') <> 'GASTO_REGISTRO_NOMINA'",
        "AND gr.Gr_Folio IN (" + ",".join(f"'{f}'" for f in folios) + ")",
    )), engine, params=p) if folios else pd.DataFrame(columns=["FOLIO", "IMPORTE_FOLIO"])
    imp["FOLIO"] = imp["FOLIO"].str.strip()

    return cargo, origen, cuentas, abono_folio, xml, imp


def reporte_cont4(fecha_ini: str, fecha_fin: str, config: str = "0450", empresa: str = "0001") -> pd.DataFrame:
    """CONT-4: grano (FOLIO, GRD_ID, CUENTA) -- 1 fila por documento x
    cuenta, XML ligado 1:1 (el grano correcto, ver docstring del modulo)."""
    cargo, origen, cuentas, abono_folio, xml, imp = _base(fecha_ini, fecha_fin, config, empresa)

    df = cargo.merge(xml, on=["FOLIO", "GRD_ID"], how="left")
    df = df.merge(cuentas, on="CUENTA", how="left")
    df = df.merge(origen, on="FOLIO", how="left")
    df = df.merge(abono_folio, on="FOLIO", how="left")
    df["ABONO"] = df["ABONO"].fillna(0)
    df = df.merge(imp, on="FOLIO", how="left")
    df["TIENE_XML"] = df["XML_UUID"].notna()

    return df[[
        "FOLIO", "ORIGEN", "GRD_ID", "CUENTA", "CUENTA_DESCRIPCION",
        "CARGO", "ABONO", "TIENE_XML", "XML_UUID", "XML_MONTO", "XML_RFC_EMISOR", "XML_FACTURA",
        "IMPORTE_FOLIO",
    ]].reset_index(drop=True)


def reporte_cont5(fecha_ini: str, fecha_fin: str, config: str = "0450", empresa: str = "0001") -> pd.DataFrame:
    """CONT-5: grano (FOLIO, CUENTA) -- colapsa GRD_ID. El XML adjunto se
    agrega (N_XML, XML_UUIDS concatenados) en vez de ser 1:1 -- a proposito
    para exponer donde ese colapso deja de corresponder a un solo
    documento (ver docstring del modulo)."""
    cargo, origen, cuentas, abono_folio, xml, imp = _base(fecha_ini, fecha_fin, config, empresa)

    con_xml = cargo.merge(xml, on=["FOLIO", "GRD_ID"], how="left")

    agg = con_xml.groupby(["FOLIO", "CUENTA"], as_index=False).agg(
        CARGO=("CARGO", "sum"),
        N_DOCUMENTOS=("GRD_ID", "nunique"),
        N_XML=("XML_UUID", "nunique"),
        XML_UUIDS=("XML_UUID", lambda s: ", ".join(sorted(s.dropna().unique()))),
        XML_MONTO_TOTAL=("XML_MONTO", lambda s: s.drop_duplicates().sum()),  # evita doble-contar si un UUID se repite en >1 Grd_ID de esta misma cuenta
    )
    agg["AMBIGUO"] = agg["N_DOCUMENTOS"] != agg["N_XML"]  # el grano cuenta != grano documento aqui

    agg = agg.merge(cuentas, on="CUENTA", how="left")
    agg = agg.merge(origen, on="FOLIO", how="left")
    agg = agg.merge(abono_folio, on="FOLIO", how="left")
    agg["ABONO"] = agg["ABONO"].fillna(0)
    agg = agg.merge(imp, on="FOLIO", how="left")

    return agg[[
        "FOLIO", "ORIGEN", "CUENTA", "CUENTA_DESCRIPCION",
        "CARGO", "ABONO", "N_DOCUMENTOS", "N_XML", "AMBIGUO", "XML_UUIDS", "XML_MONTO_TOTAL",
        "IMPORTE_FOLIO",
    ]].reset_index(drop=True)
