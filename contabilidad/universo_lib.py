"""Universo de CFDI recibidos de un periodo y su mapeo a documentos de mpro.

Extrae a una sola pieza reutilizable la lógica de armado del universo que
vivía inline en `recibidos/nivel_poliza/baseline_universal.py` (pasos [1/5]
y [2/5]), para que todos los reportes de `contabilidad/` partan exactamente
del mismo universo que el baseline y los números sean comparables entre sí.

Incluye el dedup origin-aware, que NO es cosmético: `Comprobante_Digital`
guarda el mismo `(Gr_Folio, Grd_ID)` de GASTO_REGISTRO dos veces, en formato
de 14 y de 18 caracteres, con el mismo UUID y el mismo monto. Deduplicar por
el `Cd_Documento` completo deja pasar las dos filas y **duplica el cargo** —
eso hacía ver 7 CFDI de feb-2026 con exactamente 2x su importe, que parecían
doble captura del cliente y era doble conteo nuestro (`docs/hallazgos.md`
punto 24).
"""
from __future__ import annotations

import pandas as pd

from extract_sat import extract_sat_cfdi, COLUMNS_XML_EXTRA
from extract_origen import extract_origenes_por_uuids

# Mismos conjuntos que baseline_universal.py — se importan de aquí para que
# no se desincronicen si uno de los dos cambia.
TIPOS_CON_VALOR = {"I", "E"}
ORIGEN_MONTO_ESPECIAL = {"CHEQUE"}
ORIGEN_GRANULAR = {"GASTO_REGISTRO"}
ORIGEN_SIN_VALOR = {"TRASLADO", "COMPROBANTE_PAGO"}


def cfdi_del_periodo(periodo=None, periodos=None, tabla: str = "cfdi_recibidos",
                      con_extras: bool = True) -> pd.DataFrame:
    """CFDI de `raw_sat` del periodo, con las columnas de impuestos parseadas
    (`ret_iva`, `ret_isr`, `ieps_trasladado`, ...) si `con_extras`."""
    extras = COLUMNS_XML_EXTRA if con_extras else None
    return extract_sat_cfdi(tabla, periodo=periodo, periodos=periodos,
                             extra_columns=extras)


def mapeo_documentos(uuids: list[str]) -> pd.DataFrame:
    """CFDI -> (origen, documento) desde `Comprobante_Digital`, deduplicado.

    Columnas: uuid, origen, origen_up, documento, documento_real,
    tipo_comprobante_mpro, cd_monto.

    `documento_real` = primeros 10 caracteres (el folio de verdad; el resto
    de `Cd_Documento` es sufijo). `documento` conserva la llave completa, que
    para GASTO_REGISTRO es folio(10)+Grd_ID(4) y sí importa.
    """
    origenes = extract_origenes_por_uuids(list(uuids))
    if origenes.empty:
        return pd.DataFrame(columns=["uuid", "origen", "origen_up", "documento",
                                      "documento_real", "tipo_comprobante_mpro", "cd_monto"])
    origenes = origenes.dropna(subset=["documento"]).copy()
    origenes["documento"] = origenes["documento"].astype(str)
    origenes["documento_real"] = origenes["documento"].str.slice(0, 10)
    origenes["origen_up"] = origenes["origen"].str.upper()
    # Dedup origin-aware: folio corto para orígenes normales; folio+Grd_ID
    # (14 chars) para GASTO_REGISTRO. Ver docstring del módulo.
    origenes["_dedup"] = origenes["documento_real"].where(
        ~origenes["origen_up"].isin(ORIGEN_GRANULAR),
        origenes["documento"].str.slice(0, 14))
    origenes = (origenes.drop_duplicates(subset=["uuid", "origen_up", "_dedup"])
                .drop(columns=["_dedup"]).reset_index(drop=True))
    return origenes


def universo(periodo=None, periodos=None, tabla: str = "cfdi_recibidos",
              solo_monetarios: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve `(sat, origenes)` ya filtrados y ligados.

    `solo_monetarios=True` deja solo tipo Ingreso/Egreso — Traslado (Carta
    Porte) y Pago (REP) traen SubTotal/Total en $0 por diseño del SAT, así
    que compararlos contra un importe contable no significa nada. Poner
    `False` para estudiarlos justamente por eso (ver `06_recibidos_no_ie.py`).
    """
    sat = cfdi_del_periodo(periodo=periodo, periodos=periodos, tabla=tabla)
    if solo_monetarios:
        sat = sat[sat["tipo_comprobante"].isin(TIPOS_CON_VALOR)].copy()
    origenes = mapeo_documentos(sat["uuid"].tolist())
    return sat.reset_index(drop=True), origenes


def origenes_con_cargo(origenes: pd.DataFrame) -> list[str]:
    """Orígenes que aportan cargo por la vía genérica de `Pd_Referencia`
    (excluye CHEQUE, que se aísla por monto, y los complementos sin valor)."""
    return sorted(o for o in origenes["origen"].unique()
                  if o.upper() not in ORIGEN_MONTO_ESPECIAL | ORIGEN_SIN_VALOR)
