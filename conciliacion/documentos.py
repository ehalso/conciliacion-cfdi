"""Compras, compras indirectas, notas de crédito de proveedor y cuentas por pagar.

Cada bloque (cabecera, impuestos, XML, pago, póliza) se consulta a grano documento y se une por folio.
Devuelve una fila por línea de póliza (o una sola si el documento no tiene póliza), con la columna `Tipo`.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy.engine import Connection

from .dialecto import sql
from .db import consultar, tablas_temporales

_IMP_JOIN_ESTANDAR = "i.{p}_Folio=c.{p}_Folio AND i.{p}_ID=c.{p}_ID"
_IMP_JOIN_CXP = "i.Cxp_Folio=c.Cxp_Folio"  # Cuenta_X_Pagar no tiene ID: Cxp_Folio es único
_POL_REF_CXP = "(pd.Pd_Referencia=d.FOLIO OR (COALESCE(d.REF,'')<>'' AND pd.Pd_Referencia=d.REF))"


@dataclass(frozen=True)
class TipoDocumento:
    tipo: str
    p: str              # prefijo de columnas
    tabla: str
    impuesto: str       # tabla de impuestos
    origen_xml: str     # Comprobante_Digital.Cd_Tabla y Poliza_Control.Pc_Tabla
    neto: str           # expresión SQL del subtotal neto (alias c)
    cxp: str | None     # Cxp_Tabla de su cuenta por pagar; 'SELF' si el documento es la CxP; None si no tiene pago
    c05: bool = False   # excluye cuentas contables con título '05'
    signo: int = 1
    cxp_tabla: str = ""  # solo CxP: valor de Cxp_Tabla que identifica el tipo

    @property
    def es_cxp(self) -> bool:
        return self.cxp == "SELF"


def _neto(p: str) -> str:
    return (f"(c.{p}_Precio_Lista_Importe - CASE WHEN c.{p}_Descuento_Global_Factor<>0 "
            f"THEN c.{p}_Descuento_Global_Importe ELSE c.{p}_Descuento_Importe END)*c.{p}_Tipo_Cambio")


TIPOS = [
    TipoDocumento("Compra", "Co", "Compra", "Compra_Impuesto", "COMPRA", _neto("Co"), cxp="Compra", c05=True),
    TipoDocumento("Indirecto", "Ci", "Compra_Indirecto", "Compra_Indirecto_Impuesto", "COMPRA_INDIRECTO",
                  _neto("Ci"), cxp="Compra_Indirecto", c05=True),
    TipoDocumento("NC proveedor", "Nc", "Nota_Credito_Proveedor", "Nota_Credito_Proveedor_Impuesto",
                  "NOTA_CREDITO_PROVEEDOR", "(c.Nc_Precio_Descontado_Importe - c.Nc_Descuento_Global_Importe)*c.Nc_Tipo_Cambio",
                  cxp=None, signo=-1),
    TipoDocumento("CxP libre", "Cxp", "Cuenta_X_Pagar", "Cuenta_X_Pagar_Impuesto", "Cuenta_X_Pagar",
                  "c.Cxp_Precio_Descontado_Importe*c.Cxp_Tipo_Cambio", cxp="SELF", cxp_tabla="Cuenta_X_Pagar"),
    TipoDocumento("CxP orden compra", "Cxp", "Cuenta_X_Pagar", "Cuenta_X_Pagar_Impuesto", "Cuenta_X_Pagar",
                  "c.Cxp_Precio_Descontado_Importe*c.Cxp_Tipo_Cambio", cxp="SELF", cxp_tabla="ORDEN_COMPRA"),
]


_SIN_INTERFAZ_GASOMATIC = "AND NOT EXISTS (SELECT 1 FROM Zfb_Interface_Gasomatic g WHERE g.Cxp_Folio = c.Cxp_Folio)"


def _filtro_doc(t: TipoDocumento) -> str:
    if not t.es_cxp:
        return ""
    f = f"AND c.Cxp_Tabla='{t.cxp_tabla}'"
    # CxP libres que genera la interfaz Gasomatic: duplican al gasto de control_combustible
    return f + " " + _SIN_INTERFAZ_GASOMATIC if t.cxp_tabla == "Cuenta_X_Pagar" else f


def _plantillas(t: TipoDocumento) -> dict:
    return dict(
        p=t.p, tabla=t.tabla, imp=t.impuesto, origen=t.origen_xml.upper(), pc=t.origen_xml.upper(), neto=t.neto, cxp=t.cxp,
        imp_join=(_IMP_JOIN_CXP if t.es_cxp else _IMP_JOIN_ESTANDAR).format(p=t.p),
        imp_col="Cxpi_Importe" if t.es_cxp else "Im_Importe",
        filtro_doc=_filtro_doc(t),
        pol_ref=_POL_REF_CXP if t.es_cxp else "pd.Pd_Referencia=d.FOLIO",
        excl_pol=",'2130'" if t.es_cxp else "",
        filtro05="AND COALESCE(cc.cc_titulo,'')<>'05'" if t.c05 else "",
    )


def _crear_temporales(t: TipoDocumento, f: dict) -> str:
    s = sql.DOC_SETUP.format(**f)
    if t.es_cxp:
        return s + sql.DOC_CXP_PROPIA
    return s + (sql.DOC_CXP_DE_DOCUMENTO.format(**f) if t.cxp else sql.DOC_SIN_PAGO)


def construir_tipo(con: Connection, t: TipoDocumento, p: dict, proveedores: pd.DataFrame) -> pd.DataFrame:
    f = _plantillas(t)
    with tablas_temporales(con, _crear_temporales(t, f), p, *sql.TEMPORALES):
        cabecera = consultar(con, sql.DOC_CABECERA_SQL.format(**f), p)
        impuestos = consultar(con, sql.DOC_IMPUESTO_SQL.format(**f), p)
        xml = consultar(con, sql.XML_SQL.format(**f))
        poliza = consultar(con, sql.DOC_POLIZA_SQL.format(**f), p)
        vacias = consultar(con, sql.DOC_POLIZA_SIN_LINEAS_SQL.format(**f), p)
        poliza = pd.concat([poliza, vacias[~vacias.FOLIO.isin(poliza.FOLIO)]], ignore_index=True, sort=False)
        pago = consultar(con, sql.PAGOS_SQL).drop(columns="REFERENCIA") if t.cxp else None

    cabecera["CLAVE_PROVEEDOR"] = cabecera.CLAVE_PROVEEDOR.astype(str).str.strip()
    impuestos["CLAVE"] = impuestos.CLAVE.astype(str).str.strip()
    por_clave = impuestos.pivot_table(index="FOLIO", columns="CLAVE", values="IMPORTE", aggfunc="sum")
    por_clave.columns = ["IMP_" + k for k in por_clave.columns]
    por_clave = por_clave.reset_index()

    cols_subtotal = [c for c in cabecera.columns if c.startswith("SUBTOTAL_") or c == "TOTAL_SQL"]
    cols_imp = [c for c in por_clave.columns if c.startswith("IMP_")]
    for c in cols_subtotal:
        cabecera[c] = pd.to_numeric(cabecera[c], errors="coerce").astype(float)
    for c in cols_imp:
        por_clave[c] = pd.to_numeric(por_clave[c], errors="coerce").astype(float)

    d = (cabecera.merge(proveedores, on="CLAVE_PROVEEDOR", how="left")
                 .merge(por_clave, on="FOLIO", how="left")
                 .merge(xml, on="FOLIO", how="left"))
    if pago is not None:
        d = d.merge(pago, on="FOLIO", how="left")
    d[cols_imp] = d[cols_imp].fillna(0.0)
    d[cols_subtotal + cols_imp] = d[cols_subtotal + cols_imp] * float(t.signo)
    d = d.sort_values(["FECHA", "FOLIO"], kind="stable").reset_index(drop=True)
    poliza["_ord"] = np.arange(len(poliza))
    d = (d.merge(poliza, on="FOLIO", how="left")
          .sort_values(["FECHA", "FOLIO", "_ord"], kind="stable").drop(columns="_ord").reset_index(drop=True))
    d["Tipo"] = t.tipo
    d["ORIGEN"] = None
    return d


def consultar_proveedores(con: Connection) -> pd.DataFrame:
    prov = consultar(con, sql.PROVEEDORES_SQL)
    prov["CLAVE_PROVEEDOR"] = prov.CLAVE_PROVEEDOR.astype(str).str.strip()
    prov["RFC_PROVEEDOR"] = prov.RFC_PROVEEDOR.astype(str).str.strip()
    return prov.drop_duplicates("CLAVE_PROVEEDOR")
