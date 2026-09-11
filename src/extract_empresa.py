"""Filtro de ruido intercompañía en `Comprobante_Digital`.

`Comprobante_Digital` es una tabla ÚNICA compartida por TODAS las empresas
que corren en el mismo servidor mpro (Trivasa Em_Cve_Empresa=0001, pero
también Facilitadores de la Construcción 0002, Flexbeel 0003, Triturados de
Valladolid 0004, y los backups 0097/0098/0099). Un CFDI que Trivasa recibe
de un proveedor que TAMBIÉN es una empresa del mismo mpro puede quedar
etiquetado con el módulo de VENTAS de ESE proveedor (su propia captura de la
venta), no con el módulo de compras de Trivasa — confirmado en vivo
2026-09-11: el CFDI 34FC72B1-23B4-4804-96DC-A87A3FDFD19D (anticipo pagado a
Triturados de Valladolid) aparecía SOLO con origen `FACTURA`, folio
`76-0000597`, capturado en la sucursal `0076` = Triturados (empresa 0004),
no en ninguna sucursal de Trivasa. En el universo I/E de febrero 2026, el
100% de las filas `FACTURA` (5/5) y `NOTA_CREDITO` (1/1) resultaron ser este
mismo ruido — ningún CFDI perdió TODAS sus etiquetas al filtrarlas (siempre
tenían además COMPRA/GASTO_REGISTRO propios de Trivasa), salvo el caso del
anticipo.

Ninguna tabla de origen comparte columna de folio, pero SÍ comparten
`Sc_Cve_Sucursal` (confirmado vía INFORMATION_SCHEMA en las 9 tablas
relevantes). `GASTO_REGISTRO` es la excepción: la sucursal vive en el
encabezado `Gasto_Registro` (`Gr_Folio`), no en `Gasto_Registro_Documento`.
"""
from __future__ import annotations

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET

EMPRESA_TRIVASA = "0001"
BATCH_SIZE = 150

# origen (Cd_Tabla) -> (tabla, columna de folio) -- mismas tablas que
# extract_moneda.FUENTES, más ANTICIPO_CXP (sin FUENTES propio ahí).
TABLA_FOLIO = {
    "COMPRA": ("Compra_Encabezado", "Co_Folio"),
    "COMPRA_INDIRECTO": ("Compra_Indirecto", "Ci_Folio"),
    "CUENTA_X_PAGAR": ("Cuenta_X_Pagar", "Cxp_Folio"),
    "NOTA_CREDITO_PROVEEDOR": ("Nota_Credito_Proveedor", "Nc_Folio"),
    "CHEQUE": ("Cheque", "Ch_Folio"),
    "FACTURA": ("Factura_Encabezado", "Fc_Folio"),
    "ANTICIPO_CXP": ("Anticipo_CXP", "An_Folio"),
    "NOTA_CREDITO": ("Nota_Credito", "Nc_Folio"),
}


def _sucursales_empresa(empresa: str = EMPRESA_TRIVASA) -> set[str]:
    sql = f"SELECT Sc_Cve_Sucursal FROM Sucursal WHERE Em_Cve_Empresa = {sql_quote(empresa)}"
    r = run_query(MPRO_TARGET, sql)
    return {row["Sc_Cve_Sucursal"] for row in rows_as_dicts(r)}


def _sucursal_por_folio(tabla: str, col_folio: str, folios: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    folios = sorted({f for f in folios if f})
    for i in range(0, len(folios), BATCH_SIZE):
        lote = folios[i:i + BATCH_SIZE]
        in_list = ", ".join(sql_quote(f) for f in lote)
        sql = (f"SELECT DISTINCT {col_folio} AS folio, Sc_Cve_Sucursal "
               f"FROM {tabla} WHERE {col_folio} IN ({in_list})")
        for row in rows_as_dicts(run_query(MPRO_TARGET, sql)):
            out[row["folio"]] = row["Sc_Cve_Sucursal"]
    return out


def _sucursal_gasto_registro(folios14: list[str]) -> dict[str, str]:
    """folios14 = documento de GASTO_REGISTRO (folio(10)+Grd_ID(4), o más
    largo). La sucursal vive en el encabezado `Gasto_Registro`, a nivel
    Gr_Folio (primeros 10 caracteres)."""
    folios14 = sorted({f for f in folios14 if f})
    gr_folios = sorted({f[:10] for f in folios14 if len(f) >= 10})
    por_gr_folio: dict[str, str] = {}
    for i in range(0, len(gr_folios), BATCH_SIZE):
        lote = gr_folios[i:i + BATCH_SIZE]
        in_list = ", ".join(sql_quote(f) for f in lote)
        sql = f"SELECT Gr_Folio, Sc_Cve_Sucursal FROM Gasto_Registro WHERE Gr_Folio IN ({in_list})"
        for row in rows_as_dicts(run_query(MPRO_TARGET, sql)):
            por_gr_folio[row["Gr_Folio"]] = row["Sc_Cve_Sucursal"]
    return {f: por_gr_folio.get(f[:10], "") for f in folios14}


def filtra_empresa_trivasa(origenes: pd.DataFrame, empresa: str = EMPRESA_TRIVASA) -> pd.DataFrame:
    """Recibe el DataFrame de `extract_origenes_por_uuids` ya con
    `documento_real` y `origen_up` calculados (columnas de
    `baseline_universal.calcular()`), y devuelve el mismo DataFrame con una
    columna `sucursal` agregada, quedándose solo con las filas capturadas en
    una sucursal de `empresa` (default: Trivasa, 0001).

    Orígenes sin tabla mapeada (ninguno hoy, pero por si acaso) pasan sin
    filtrar -- mejor un falso negativo ocasional que perder cobertura por un
    origen nuevo no contemplado aquí.
    """
    if origenes.empty:
        return origenes.assign(sucursal=pd.Series(dtype=str))

    sucursales_ok = _sucursales_empresa(empresa)
    partes = []

    for origen_up, (tabla, col_folio) in TABLA_FOLIO.items():
        sub = origenes[origenes["origen_up"] == origen_up]
        if sub.empty:
            continue
        mapa = _sucursal_por_folio(tabla, col_folio, sub["documento_real"].tolist())
        sub = sub.copy()
        sub["sucursal"] = sub["documento_real"].map(mapa)
        partes.append(sub)

    gasto = origenes[origenes["origen_up"] == "GASTO_REGISTRO"]
    if not gasto.empty:
        mapa = _sucursal_gasto_registro(gasto["documento"].tolist())
        gasto = gasto.copy()
        gasto["sucursal"] = gasto["documento"].map(mapa)
        partes.append(gasto)

    # Orígenes sin mapeo (no debería haber ninguno en la práctica): se
    # conservan tal cual, sin columna de sucursal resuelta.
    mapeados = set(TABLA_FOLIO) | {"GASTO_REGISTRO"}
    resto = origenes[~origenes["origen_up"].isin(mapeados)]
    if not resto.empty:
        resto = resto.copy()
        resto["sucursal"] = None
        partes.append(resto)

    todo = pd.concat(partes, ignore_index=True) if partes else origenes.assign(sucursal=None)
    es_trivasa = todo["sucursal"].isin(sucursales_ok) | todo["sucursal"].isna()
    return todo[es_trivasa].drop(columns=["sucursal"])
