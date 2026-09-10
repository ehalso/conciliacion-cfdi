"""Cruce de existencia, SAT (`raw_sat.cfdi_recibidos`/`cfdi_emitidos`) vs
MPRO (`Comprobante_Digital`), en las dos direcciones: qué está en MPRO y no
en el SAT, y qué está en el SAT y no en MPRO.

Compartido entre `recibidos/cruce_sat/` y `emitidos/cruce_sat/` -- la única
diferencia entre ambas direcciones es qué tabla de `raw_sat` y qué columna
de RFC (`Cd_RFC_Receptor` para recibido, `Cd_RFC_Emisor` para emitido) usar,
parametrizado aquí en vez de duplicar la query.

A diferencia de `extract_origen.py`/`extract_mpro.py` (que parten de una
lista de UUID ya conocida, típicamente del lado SAT), este módulo censa
`Comprobante_Digital` de forma INDEPENDIENTE por rango de fecha -- necesario
para poder detectar el caso "está en MPRO pero el SAT no lo tiene", que por
construcción no puede verse arrancando de una lista de UUID del SAT.
"""
from __future__ import annotations

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET
from extract_sat import extract_sat_cfdi

RFC_TRIVASA = "TRI970922TL2"

DIRECCIONES = {
    "recibido": dict(tabla_sat="cfdi_recibidos", rfc_propio="Cd_RFC_Receptor"),
    "emitido": dict(tabla_sat="cfdi_emitidos", rfc_propio="Cd_RFC_Emisor"),
}


def _rango(periodo: str) -> tuple[str, str]:
    y, m = int(periodo[:4]), int(periodo[5:7])
    fi = f"{y:04d}-{m:02d}-01"
    y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
    return fi, f"{y2:04d}-{m2:02d}-01"


def extract_mpro_universo(fi: str, ff: str, direccion: str) -> pd.DataFrame:
    """Todos los UUID timbrados en `Comprobante_Digital` en `[fi, ff)` con
    Trivasa del lado que le toca según `direccion` -- sin restringir a un
    `Cd_Tabla` en particular, porque el objetivo es "¿el ERP lo registró en
    ALGÚN módulo?", no una pregunta de módulo específico. Colapsa a una fila
    por UUID (un mismo CFDI puede tener varias filas, una por módulo)."""
    if direccion not in DIRECCIONES:
        raise ValueError(f"direccion debe ser una de {sorted(DIRECCIONES)}, se recibió {direccion!r}")
    cfg = DIRECCIONES[direccion]
    # Sin excluir el RFC contrario: validado en vivo (2026-09-10, recibido
    # feb-2026) que raw_sat.cfdi_recibidos SÍ incluye complementos
    # autoemitidos (TRASLADO, Cd_RFC_Emisor=Cd_RFC_Receptor=Trivasa, ~3,350
    # filas del periodo) -- excluirlos aquí habría dejado el censo de mpro
    # muy por debajo del universo real (2,179 vs 5,529 UUID), rompiendo el
    # cruce contra el SAT.
    sql = (
        "SELECT UPPER(LTRIM(RTRIM(Cd_Timbre_UUID))) AS uuid, Cd_Tabla AS origen, "
        "Cd_Documento AS documento, Cd_Monto AS cd_monto, Cd_Timbre_Fecha AS fecha, "
        "Es_Cve_Estado AS estado "
        "FROM Comprobante_Digital "
        f"WHERE Cd_Timbre_Fecha >= {sql_quote(fi)} AND Cd_Timbre_Fecha < {sql_quote(ff)} "
        f"AND LTRIM(RTRIM({cfg['rfc_propio']})) = {sql_quote(RFC_TRIVASA)} "
        "AND Cd_Timbre_UUID IS NOT NULL AND LTRIM(RTRIM(Cd_Timbre_UUID)) <> ''"
    )
    df = pd.DataFrame(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    if df.empty:
        return pd.DataFrame(columns=["uuid", "n_modulos_mpro", "modulos_mpro", "cd_monto_primero",
                                      "fecha_timbrado_mpro", "algun_cancelado"])
    df["uuid"] = df["uuid"].str.upper()
    df["cd_monto"] = pd.to_numeric(df["cd_monto"], errors="coerce")

    agg = (
        df.groupby("uuid")
        .agg(
            n_modulos_mpro=("origen", "nunique"),
            modulos_mpro=("origen", lambda s: ", ".join(sorted(set(s)))),
            cd_monto_primero=("cd_monto", "first"),
            fecha_timbrado_mpro=("fecha", "min"),
            algun_cancelado=("estado", lambda s: (s == "CA").any()),
        )
        .reset_index()
    )
    return agg


def reconcile_existencia(sat_df: pd.DataFrame, mpro_df: pd.DataFrame) -> pd.DataFrame:
    """Cruce por UUID (outer join): `EN_AMBOS`, `SOLO_SAT` (se timbró y el
    ERP no lo registró en ningún módulo) o `SOLO_MPRO` (el ERP tiene una
    etiqueta con ese UUID pero no aparece en la fuente independiente del
    SAT -- puede ser hueco de cobertura del backfill de `raw_sat`, no
    necesariamente un error del ERP; ver caveat de cobertura por tabla)."""
    sat = sat_df[["uuid", "fecha", "rfc_emisor", "nombre_emisor", "subtotal", "iva", "total"]].copy() \
        if not sat_df.empty else pd.DataFrame(columns=["uuid", "fecha", "rfc_emisor", "nombre_emisor",
                                                         "subtotal", "iva", "total"])
    sat["en_sat"] = True

    mpro = mpro_df.copy() if not mpro_df.empty else pd.DataFrame(
        columns=["uuid", "n_modulos_mpro", "modulos_mpro", "cd_monto_primero",
                 "fecha_timbrado_mpro", "algun_cancelado"])
    mpro["en_mpro"] = True

    detalle = sat.merge(mpro, on="uuid", how="outer")
    detalle["en_sat"] = detalle["en_sat"].fillna(False)
    detalle["en_mpro"] = detalle["en_mpro"].fillna(False)

    detalle["estatus"] = "EN_AMBOS"
    detalle.loc[detalle["en_sat"] & ~detalle["en_mpro"], "estatus"] = "SOLO_SAT"
    detalle.loc[~detalle["en_sat"] & detalle["en_mpro"], "estatus"] = "SOLO_MPRO"

    return detalle


def resumen(detalle: pd.DataFrame) -> pd.DataFrame:
    if detalle.empty:
        return pd.DataFrame(columns=["estatus", "conteo", "monto_total"])
    detalle = detalle.copy()
    detalle["monto"] = detalle["total"].where(detalle["en_sat"], detalle["cd_monto_primero"])
    return (
        detalle.groupby("estatus")
        .agg(conteo=("uuid", "count"), monto_total=("monto", "sum"))
        .reset_index()
    )


def calcular(periodo: str, direccion: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Un solo periodo ('YYYY-MM'): extrae ambos lados y concilia por
    existencia. Devuelve (detalle, resumen)."""
    cfg = DIRECCIONES[direccion]
    fi, ff = _rango(periodo)

    sat_df = extract_sat_cfdi(cfg["tabla_sat"], periodo=periodo)
    mpro_df = extract_mpro_universo(fi, ff, direccion)

    detalle = reconcile_existencia(sat_df, mpro_df)
    detalle["periodo"] = periodo
    detalle["direccion"] = direccion
    return detalle, resumen(detalle)


def calcular_periodos(periodos: list[str], direccion: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    partes_detalle = []
    for periodo in periodos:
        detalle, _ = calcular(periodo, direccion)
        partes_detalle.append(detalle)
    detalle = pd.concat(partes_detalle, ignore_index=True) if partes_detalle else pd.DataFrame()
    return detalle, resumen(detalle)
