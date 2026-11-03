"""Compras, compras indirectas, notas de crédito de proveedor y cuentas por pagar (recibidos); ventas y notas de crédito
de cliente (emitidos; solo Mpro/SQL Server).

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
# Las líneas de ingreso de ventas y devoluciones referencian el folio o "<serie><folio de serie>" a 10 caracteres (M000020634, AME0000793); las de IVA solo traen la fecha
_POL_REF_SERIE = "(pd.Pd_Referencia=d.FOLIO OR pd.Pd_Referencia=d.SF)"
_POL_REF_CXP = "(pd.Pd_Referencia=d.FOLIO OR (COALESCE(d.REF,'')<>'' AND pd.Pd_Referencia=d.REF))"


@dataclass(frozen=True)
class TipoDocumento:
    tipo: str
    p: str              # prefijo de columnas
    tabla: str
    impuesto: str       # tabla de impuestos
    origen_xml: str     # Comprobante_Digital.Cd_Tabla (y Poliza_Control.Pc_Tabla, salvo pc_tabla)
    neto: str           # expresión SQL del subtotal neto (alias c)
    cxp: str | None     # Cxp_Tabla de su cuenta por pagar; 'SELF' si el documento es la CxP; None si no tiene pago
    c05: bool = False   # excluye cuentas contables con título '05'
    signo: int = 1
    cxp_tabla: str = ""  # solo CxP: valor de Cxp_Tabla que identifica el tipo
    tercero: str = "Pv_Cve_Proveedor"  # columna de la clave del proveedor/cliente
    exento: str = "0004"  # clave de impuesto exento
    cero: str = "0003"    # clave de impuesto tasa 0
    pc_tabla: str = ""    # Poliza_Control.Pc_Tabla si difiere de origen_xml (Factura → VENTA)
    pol_doc: str = ""     # columna del documento con que la póliza lo referencia (por omisión, su folio)
    ventana_pol: int = 0  # días de tolerancia entre la fecha del documento y la de su póliza (folios reciclados); 0 = sin límite
    excl_cuentas: str = ""  # prefijos extra de cuenta contable (4 dígitos) a omitir de la póliza, p. ej. ",'1120'"
    serie: str = ""       # prefijo de las columnas <serie> y <serie>_Folio con que la póliza referencia al documento (emitidos)

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

# Emitidos. La póliza de Factura cuelga del folio de la Venta (Fc_Documento) y sus líneas referencian el folio de la
# factura; los folios se reciclan entre años, de ahí la ventana de fechas. Las líneas de cliente (1120) se omiten,
# igual que las de proveedor en recibidos. Facturas sin Venta (refacturación de CxC) se ligan por su propio folio.
TIPOS_CLIENTE = [
    TipoDocumento("Venta", "Fc", "Factura", "Factura_Impuesto", "FACTURA", _neto("Fc"), cxp=None, tercero="Cl_Cve_Cliente",
                  exento="0008", cero="0007", pc_tabla="VENTA", pol_doc="COALESCE(NULLIF(c.Fc_Documento,''),c.Fc_Folio)", ventana_pol=45, excl_cuentas=",'1120','2140','1140','5100'",
                  serie="Fc_Serie"),
    TipoDocumento("NC cliente", "Nc", "Nota_Credito", "Nota_Credito_Impuesto", "NOTA_CREDITO", _neto("Nc"), cxp=None, signo=-1,
                  tercero="Cl_Cve_Cliente", exento="0008", cero="0007", excl_cuentas=",'1120','2140','1140','5100'",
                  serie="Nc_Serie"),
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
        p=t.p, tabla=t.tabla, imp=t.impuesto, origen=t.origen_xml.upper(), pc=(t.pc_tabla or t.origen_xml).upper(), neto=t.neto, cxp=t.cxp,
        imp_join=(_IMP_JOIN_CXP if t.es_cxp else _IMP_JOIN_ESTANDAR).format(p=t.p),
        imp_col="Cxpi_Importe" if t.es_cxp else "Im_Importe",
        imp_cols_k="i.Cxp_Folio" if t.es_cxp else f"i.{t.p}_Folio, i.{t.p}_ID",
        imp_on_k="k.Cxp_Folio=c.Cxp_Folio" if t.es_cxp else f"k.{t.p}_Folio=c.{t.p}_Folio AND k.{t.p}_ID=c.{t.p}_ID",
        filtro_doc=_filtro_doc(t),
        pol_ref=_POL_REF_CXP if t.es_cxp else _POL_REF_SERIE if t.serie else "pd.Pd_Referencia=d.FOLIO",
        serie=(f"c.{t.serie}+RIGHT('0000000000'+RTRIM(c.{t.serie}_Folio),10-LEN(c.{t.serie}))" if t.serie
               else "CAST(NULL AS varchar(30))"),
        excl_pol=(",'2130'" if t.es_cxp else "") + t.excl_cuentas,
        tercero=t.tercero, exento=t.exento, cero=t.cero,
        pol_doc=(t.pol_doc or "c.{p}_Folio").format(p=t.p),
        pol_fecha=(f"AND pl.Pl_Fecha>=DATEADD(day,-{t.ventana_pol},d.FDOC) AND pl.Pl_Fecha<DATEADD(day,{t.ventana_pol + 1},d.FDOC)"
                   if t.ventana_pol else ""),
        filtro05="AND COALESCE(cc.cc_titulo,'')<>'05'" if t.c05 else "",
    )


def _crear_temporales(t: TipoDocumento, f: dict) -> str:
    s = sql.DOC_SETUP.format(**f)
    if t.es_cxp:
        return s + sql.DOC_CXP_PROPIA
    return s + (sql.DOC_CXP_DE_DOCUMENTO.format(**f) if t.cxp else sql.DOC_SIN_PAGO)


def construir_tipo(con: Connection, t: TipoDocumento, p: dict, terceros: pd.DataFrame) -> pd.DataFrame:
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

    d = (cabecera.merge(terceros, on="CLAVE_PROVEEDOR", how="left")
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


def consultar_clientes(con: Connection) -> pd.DataFrame:
    """Mismas columnas que consultar_proveedores (CLAVE/RFC/NOMBRE_PROVEEDOR); en emitidos significan cliente."""
    cli = consultar(con, sql.CLIENTES_SQL)
    cli["CLAVE_PROVEEDOR"] = cli.CLAVE_PROVEEDOR.astype(str).str.strip()
    cli["RFC_PROVEEDOR"] = cli.RFC_PROVEEDOR.astype(str).str.strip()
    return cli.drop_duplicates("CLAVE_PROVEEDOR")
