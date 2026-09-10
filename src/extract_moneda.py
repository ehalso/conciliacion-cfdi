"""Moneda y tipo de cambio del documento de mpro, por origen.

Motivación (2026-09-09, sesión nocturna): el subtotal/total que trae
`raw_sat.cfdi_recibidos` está en la **moneda original del CFDI** (igual que
`Comprobante_Digital.Cd_Monto`, gotcha ya documentado en trivasa-context),
pero la póliza de mpro postea en **MXN**. Comparar cargo(MXN) contra
subtotal(USD) da una diferencia igual al tipo de cambio — 43 de los 149
pendientes de feb-2026 son CFDI en USD.

Cada tabla de origen trae su propio par `Mn_Cve_Moneda` / `Xx_Tipo_Cambio`
(confirmado vía INFORMATION_SCHEMA): ese es el factor con el que mpro
convirtió, y es el que hay que usar — no un tipo de cambio de mercado ni el
`Cd_Tipo_Cambio` de `Comprobante_Digital` (que a veces difiere del que se
usó para postear).
"""
from __future__ import annotations

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET

BATCH_SIZE = 150

# origen (Cd_Tabla) -> (tabla, columna folio, columna tipo de cambio, tiene Mn_Cve_Moneda)
# OJO: `Cheque` NO tiene columna de moneda (solo `Ch_Tipo_Cambio`) —
# confirmado vía INFORMATION_SCHEMA. Pedirla igual devuelve HTTP 502
# genérico, no un error de SQL legible (gotcha ya documentado).
FUENTES = {
    "COMPRA": ("Compra_Encabezado", "Co_Folio", "Co_Tipo_Cambio", True),
    "COMPRA_INDIRECTO": ("Compra_Indirecto", "Ci_Folio", "Ci_Tipo_Cambio", True),
    "CUENTA_X_PAGAR": ("Cuenta_X_Pagar", "Cxp_Folio", "Cxp_Tipo_Cambio", True),
    "NOTA_CREDITO_PROVEEDOR": ("Nota_Credito_Proveedor", "Nc_Folio", "Nc_Tipo_Cambio", True),
    "CHEQUE": ("Cheque", "Ch_Folio", "Ch_Tipo_Cambio", False),
    "FACTURA": ("Factura_Encabezado", "Fc_Folio", "Fc_Tipo_Cambio", True),
    # Emitidos (ventas) — confirmado en vivo 2026-09-10, mismo patrón que COMPRA.
    "NOTA_CREDITO": ("Nota_Credito", "Nc_Folio", "Nc_Tipo_Cambio", True),
}


def extract_moneda_documento(origen: str, documentos: list[str]) -> pd.DataFrame:
    """Devuelve documento / moneda / tipo_cambio para un origen con folio de
    10 caracteres. Para GASTO_REGISTRO usar `extract_moneda_gasto_registro`
    (la moneda vive a nivel Grd_ID, no de folio)."""
    fuente = FUENTES.get(origen.upper())
    if fuente is None:
        return pd.DataFrame(columns=["documento", "moneda", "tipo_cambio"])
    tabla, col_folio, col_tc, tiene_moneda = fuente

    documentos = sorted({d for d in documentos if d})
    filas: list[dict] = []
    col_moneda = "Mn_Cve_Moneda AS moneda" if tiene_moneda else "'' AS moneda"
    for i in range(0, len(documentos), BATCH_SIZE):
        in_list = ", ".join(sql_quote(d) for d in documentos[i : i + BATCH_SIZE])
        sql = (
            f"SELECT DISTINCT {col_folio} AS documento, {col_moneda}, "
            f"{col_tc} AS tipo_cambio FROM {tabla} WHERE {col_folio} IN ({in_list})"
        )
        filas.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))

    df = pd.DataFrame(filas, columns=["documento", "moneda", "tipo_cambio"])
    if df.empty:
        return df
    df["tipo_cambio"] = pd.to_numeric(df["tipo_cambio"], errors="coerce").fillna(1.0)
    df.loc[df["tipo_cambio"] <= 0, "tipo_cambio"] = 1.0
    # Un folio puede traer varias líneas; nos quedamos con un TC por documento.
    return df.groupby(["documento"], as_index=False).agg(
        moneda=("moneda", "first"), tipo_cambio=("tipo_cambio", "max"))


def extract_moneda_gasto_registro(documentos: list[str]) -> pd.DataFrame:
    """documentos = `Cd_Documento` completo (folio 10 + Grd_ID 4 [+ sufijo]).
    Devuelve documento / moneda / tipo_cambio a nivel (Gr_Folio, Grd_ID)."""
    llaves = sorted({d[:14] for d in documentos if d and len(d) >= 14})
    folios = sorted({k[:10] for k in llaves})
    filas: list[dict] = []
    for i in range(0, len(folios), BATCH_SIZE):
        in_list = ", ".join(sql_quote(f) for f in folios[i : i + BATCH_SIZE])
        sql = (
            "SELECT Gr_Folio, Grd_ID, Mn_Cve_Moneda AS moneda, "
            "Grd_Tipo_Cambio AS tipo_cambio FROM Gasto_Registro_Documento "
            f"WHERE Gr_Folio IN ({in_list})"
        )
        filas.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))

    df = pd.DataFrame(filas)
    if df.empty:
        return pd.DataFrame(columns=["documento", "moneda", "tipo_cambio"])
    df["Grd_ID"] = df["Grd_ID"].astype(str).str.zfill(4)
    df["documento"] = df["Gr_Folio"].astype(str) + df["Grd_ID"]
    df["tipo_cambio"] = pd.to_numeric(df["tipo_cambio"], errors="coerce").fillna(1.0)
    df.loc[df["tipo_cambio"] <= 0, "tipo_cambio"] = 1.0
    return df[["documento", "moneda", "tipo_cambio"]]
