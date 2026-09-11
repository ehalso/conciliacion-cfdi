"""
Layout de gastos - v0.3: como v0.2, pero resuelve el problema de fondo de los folios con
2+ Grd_ID (v0.2 pegaba todo el Cargo/Abono del folio al ULTIMO Grd_ID, dejando el resto en
None -- ver docs/12_hito_v0_2.md). Se encontro una tabla que v0.1/v0.2 no usaban:
Gasto_Registro_Control (Gr_Folio + Grd_ID + Cc_Cve_Centro_Costo + Grc_Importe), que
desglosa CADA documento por centro de costo. Poliza_Detalle tambien trae centro de costo
(Pd_Centro_Costo) -- verificado con datos reales que, dentro de un mismo (folio, centro de
costo), las lineas de Gasto_Registro_Control (ordenadas por Grd_ID) y las de Poliza_Detalle
(ordenadas por Pd_ID) coinciden POSICION A POSICION en el importe exacto (diferencia $0.00
en las 76 lineas probadas del folio 13-0001279, incluyendo casos con 8-10 documentos
identicos del folio 05-0176298) -- asi se generan ambas tablas en MPRO, en el mismo orden.
Eso da una atribucion Grd_ID <-> linea de poliza exacta, no una suposicion.

Regla nueva para "el resto" (blanco, VIAJE, ORDEN_COMPRA, CONTROL_COMBUSTIBLE):
  1. Lineas de Poliza_Detalle CON Pd_Centro_Costo poblado: se emparejan con
     Gasto_Registro_Control por posicion dentro de (folio, centro_costo) -- RANK por
     Pd_ID de un lado, por (Grd_ID, Grc_ID) del otro. Si el conteo de lineas no coincide
     en algun (folio, centro_costo) especifico (caso raro, ver validacion), ese grupo cae
     al metodo de respaldo en vez de forzar un emparejamiento posiblemente incorrecto.
  2. Lineas SIN Pd_Centro_Costo (la mayoria son de Abono, ~82% de esos casos -- ver
     docs/13_hito_v0_3.md) y los grupos con conteo desigual: metodo de respaldo de v0.2,
     se pegan al ULTIMO Grd_ID del folio (marcado con metodo_atribucion="folio_completo").

CONSUMO_INTERNO/GASTO_REGISTRO_NOMINA y GASTO_RECLASIFICACION: identico a v0.2 (ver ahi).

Uso: python3 scripts/layout_gastos_v0_3.py 2026-01-01 2026-02-01
"""
import sys

import pandas as pd

from db import q

TOLERANCIA = 0.5

ORIGENES_SIN_JOIN = {"CONSUMO_INTERNO", "GASTO_REGISTRO_NOMINA"}
ORIGEN_RECLASIFICACION = "GASTO_RECLASIFICACION"

BASE_SQL = """
SELECT
    gr.Gr_Folio                          AS folio,
    grd.Grd_ID                           AS grd_id,
    gr.Gr_Fecha                          AS fecha_registro,
    grd.Grd_Fecha                        AS fecha_documento,
    grd.Grd_Referencia                   AS referencia,
    grd.Pv_Cve_Proveedor                 AS proveedor_clave,
    pv.Pv_Descripcion                    AS proveedor_nombre,
    grd.Grd_Comentario                   AS comentario,
    grd.Mn_Cve_Moneda                    AS moneda,
    grd.Grd_Tipo_Cambio                  AS tipo_cambio,
    grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio AS importe,
    grd.Grd_Impuesto_Importe * grd.Grd_Tipo_Cambio           AS impuestos,
    grd.Grd_Precio_Neto_Importe * grd.Grd_Tipo_Cambio        AS total,
    gr.Gr_Tabla                          AS origen,
    grd.Tg_Cve_Tipo_Gasto                AS tipo_gasto_clave,
    tg.Tg_Cuenta_Contable                AS tipo_gasto_cuenta_contable,
    CASE WHEN cd.Cd_Documento IS NOT NULL THEN 1 ELSE 0 END AS tiene_comprobante,
    cd.Cd_Timbre_UUID                    AS uuid
FROM Gasto_Registro gr
JOIN Gasto_Registro_Documento grd
    ON grd.Gr_Folio = gr.Gr_Folio
INNER JOIN Sucursal sc
    ON sc.Sc_Cve_Sucursal = gr.Sc_Cve_Sucursal
LEFT JOIN Proveedor pv
    ON pv.Pv_Cve_Proveedor = grd.Pv_Cve_Proveedor
LEFT JOIN Tipo_Gasto tg
    ON tg.Tg_Cve_Tipo_Gasto = grd.Tg_Cve_Tipo_Gasto
OUTER APPLY (
    SELECT TOP 1 Cd_Documento, Cd_Timbre_UUID
    FROM Comprobante_Digital
    WHERE Cd_Tabla = 'GASTO_REGISTRO'
      AND Cd_Documento LIKE gr.Gr_Folio + grd.Grd_ID + '%'
    ORDER BY Cd_Documento
) cd
WHERE sc.Em_Cve_Empresa = '0001'
  AND gr.Gr_Fecha >= '{fecha_ini}' AND gr.Gr_Fecha < '{fecha_fin_excl}'
  AND gr.Es_Cve_Estado <> 'CA'
"""

POLIZA_SQL = """
WITH grupo_arbol AS (
    SELECT Gcc_Cve_Grupo_Cuenta_Contable, Gcc_Padre, Gcc_Cve_Grupo_Cuenta_Contable AS raiz
    FROM Grupo_Cuenta_Contable
    WHERE Gcc_Padre = '0' OR Gcc_Padre = '' OR Gcc_Padre IS NULL
    UNION ALL
    SELECT g.Gcc_Cve_Grupo_Cuenta_Contable, g.Gcc_Padre, t.raiz
    FROM Grupo_Cuenta_Contable g
    JOIN grupo_arbol t ON g.Gcc_Padre = t.Gcc_Cve_Grupo_Cuenta_Contable
)
SELECT
    gr.Gr_Folio                AS folio,
    pd.Pd_ID                   AS pd_id,
    pd.Pd_Centro_Costo         AS centro_costo,
    pd.Cc_Cve_Cuenta_Contable  AS cuenta_registro,
    cc.Cc_Descripcion          AS nombre_cuenta_registro,
    CASE WHEN pd.Pd_Tipo = 1 THEN pd.Pd_Importe ELSE 0 END AS cargo,
    CASE WHEN pd.Pd_Tipo = 2 THEN pd.Pd_Importe ELSE 0 END AS abono
FROM Gasto_Registro gr
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
JOIN Poliza pl
    ON pl.Pl_Folio = plc.Pl_Folio
JOIN Poliza_Detalle pd
    ON pd.Pl_Folio = plc.Pl_Folio
   AND pd.Pd_Referencia = gr.Gr_Folio
LEFT JOIN Cuenta_Contable cc
    ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable
LEFT JOIN grupo_arbol ga
    ON ga.Gcc_Cve_Grupo_Cuenta_Contable = cc.Cc_Grupo_Cuenta_Contable
INNER JOIN Sucursal sc
    ON sc.Sc_Cve_Sucursal = gr.Sc_Cve_Sucursal
WHERE sc.Em_Cve_Empresa = '0001'
  AND gr.Gr_Fecha >= '{fecha_ini}' AND gr.Gr_Fecha < '{fecha_fin_excl}'
  AND gr.Es_Cve_Estado <> 'CA'
  AND gr.Gr_Tabla NOT IN ('CONSUMO_INTERNO', 'GASTO_REGISTRO_NOMINA', 'GASTO_RECLASIFICACION')
  AND (
        pd.Pd_Tipo = 1
     OR (pd.Pd_Tipo = 2 AND ga.raiz = 'F')
     OR (pd.Pd_Tipo = 2 AND ga.raiz IS NULL AND LEFT(pd.Cc_Cve_Cuenta_Contable, 1) = '6')
      )
  AND pl.Es_Cve_Estado <> 'CA'
ORDER BY gr.Gr_Folio, pd.Pd_ID
"""

GRC_SQL = """
SELECT
    gr.Gr_Folio             AS folio,
    grc.Grd_ID               AS grd_id,
    grc.Grc_ID                AS grc_id,
    grc.Cc_Cve_Centro_Costo    AS centro_costo
FROM Gasto_Registro gr
JOIN Gasto_Registro_Control grc
    ON grc.Gr_Folio = gr.Gr_Folio
INNER JOIN Sucursal sc
    ON sc.Sc_Cve_Sucursal = gr.Sc_Cve_Sucursal
WHERE sc.Em_Cve_Empresa = '0001'
  AND gr.Gr_Fecha >= '{fecha_ini}' AND gr.Gr_Fecha < '{fecha_fin_excl}'
  AND gr.Es_Cve_Estado <> 'CA'
  AND gr.Gr_Tabla NOT IN ('CONSUMO_INTERNO', 'GASTO_REGISTRO_NOMINA', 'GASTO_RECLASIFICACION')
  AND grc.Cc_Cve_Centro_Costo IS NOT NULL AND grc.Cc_Cve_Centro_Costo <> ''
ORDER BY gr.Gr_Folio, grc.Cc_Cve_Centro_Costo, grc.Grd_ID, grc.Grc_ID
"""


def extract(fecha_ini: str, fecha_fin_excl: str):
    base = q(BASE_SQL.format(fecha_ini=fecha_ini, fecha_fin_excl=fecha_fin_excl))
    poliza = q(POLIZA_SQL.format(fecha_ini=fecha_ini, fecha_fin_excl=fecha_fin_excl))
    grc = q(GRC_SQL.format(fecha_ini=fecha_ini, fecha_fin_excl=fecha_fin_excl))
    return armar(base, poliza, grc)


def _atribuir_por_centro_costo(poliza_cc: pd.DataFrame, grc: pd.DataFrame):
    """Empareja lineas de poliza (con centro de costo) contra Gasto_Registro_Control por
    posicion dentro de (folio, centro_costo). Devuelve (emparejadas, sin_emparejar) --
    sin_emparejar son las que caen en un grupo cuyo conteo de lineas no coincide entre
    ambas tablas (no se fuerza un emparejamiento dudoso, se manda a metodo de respaldo)."""
    if poliza_cc.empty or grc.empty:
        return poliza_cc.iloc[0:0], poliza_cc

    poliza_cc = poliza_cc.sort_values(["folio", "centro_costo", "pd_id"]).copy()
    poliza_cc["rn"] = poliza_cc.groupby(["folio", "centro_costo"]).cumcount() + 1

    grc = grc.sort_values(["folio", "centro_costo", "grd_id", "grc_id"]).copy()
    grc["rn"] = grc.groupby(["folio", "centro_costo"]).cumcount() + 1

    n_pd = poliza_cc.groupby(["folio", "centro_costo"]).size().rename("n_pd")
    n_grc = grc.groupby(["folio", "centro_costo"]).size().rename("n_grc")
    conteo = pd.concat([n_pd, n_grc], axis=1).fillna(0)
    grupos_ok = conteo[conteo["n_pd"] == conteo["n_grc"]].index

    idx = poliza_cc.set_index(["folio", "centro_costo"]).index
    es_ok = idx.isin(grupos_ok)

    ok = poliza_cc[es_ok]
    no_ok = poliza_cc[~es_ok].drop(columns=["rn"])

    emparejadas = ok.merge(
        grc[["folio", "centro_costo", "rn", "grd_id"]],
        on=["folio", "centro_costo", "rn"], how="left",
    ).drop(columns=["rn"])
    return emparejadas, no_ok


def armar(base: pd.DataFrame, poliza: pd.DataFrame, grc: pd.DataFrame) -> pd.DataFrame:
    es_sin_join = base["origen"].isin(ORIGENES_SIN_JOIN)
    es_reclasificacion = base["origen"] == ORIGEN_RECLASIFICACION
    es_normal = ~es_sin_join & ~es_reclasificacion

    filas = []

    sin_join = base[es_sin_join].copy()
    sin_join["cargo"] = None
    sin_join["abono"] = None
    sin_join["cuenta_registro"] = None
    sin_join["nombre_cuenta_registro"] = None
    sin_join["metodo_atribucion"] = "sin_join"
    filas.append(sin_join)

    recl = base[es_reclasificacion].copy()
    recl["cargo"] = recl["importe"].clip(lower=0)
    recl["abono"] = (-recl["importe"]).clip(lower=0)
    recl["cuenta_registro"] = recl["tipo_gasto_cuenta_contable"]
    recl["nombre_cuenta_registro"] = None
    recl["metodo_atribucion"] = "reclasificacion"
    filas.append(recl)

    normal_base = base[es_normal].copy()  # grano documento puro (1 fila por Grd_ID), sin fan-out

    if poliza.empty:
        normal_base["cuenta_registro"] = None
        normal_base["nombre_cuenta_registro"] = None
        normal_base["cargo"] = 0.0
        normal_base["abono"] = 0.0
        normal_base["metodo_atribucion"] = "sin_poliza"
        filas.append(normal_base)
        resultado = pd.concat(filas, ignore_index=True)
        return resultado.sort_values(["folio", "grd_id"])

    tiene_centro = poliza["centro_costo"].notna() & (poliza["centro_costo"] != "")
    poliza_cc = poliza[tiene_centro].copy()
    poliza_sc = poliza[~tiene_centro].copy()

    emparejadas, no_emparejadas = _atribuir_por_centro_costo(poliza_cc, grc)
    poliza_fallback = pd.concat([poliza_sc, no_emparejadas], ignore_index=True)

    # --- detalle 1: cargo/abono/cuenta atribuidos al Grd_ID real via centro de costo ---
    detalle_cols = ["folio", "grd_id", "cuenta_registro", "nombre_cuenta_registro", "cargo", "abono", "metodo_atribucion"]
    exacta = pd.DataFrame(columns=detalle_cols)
    if not emparejadas.empty:
        exacta = emparejadas.groupby(
            ["folio", "grd_id", "cuenta_registro", "nombre_cuenta_registro"], as_index=False, dropna=False
        )[["cargo", "abono"]].sum()
        exacta["metodo_atribucion"] = "centro_costo"

    # --- detalle 2: respaldo (v0.2) -- agregado por folio, atribuido SOLO al ultimo Grd_ID ---
    fallback = pd.DataFrame(columns=detalle_cols)
    if not poliza_fallback.empty:
        fallback_agg = poliza_fallback.groupby(
            ["folio", "cuenta_registro", "nombre_cuenta_registro"], as_index=False
        )[["cargo", "abono"]].sum()
        ultimo_grd_por_folio = normal_base.groupby("folio")["grd_id"].transform("max")
        mapa_ultimo = normal_base.loc[normal_base["grd_id"] == ultimo_grd_por_folio, ["folio", "grd_id"]] \
            .drop_duplicates(subset=["folio"])
        fallback = fallback_agg.merge(mapa_ultimo, on="folio", how="left")
        fallback["metodo_atribucion"] = "folio_completo"

    # las dos partes son ADITIVAS -- si el ultimo Grd_ID de un folio ya tenia atribucion
    # exacta (via centro de costo) para alguna de sus cuentas, el respaldo se AGREGA como
    # fila(s) adicional(es) en vez de sobreescribirla (bug detectado y corregido en el
    # primer intento de esta version).
    detalle = pd.concat([exacta, fallback], ignore_index=True)

    normal_final = normal_base.merge(detalle, on=["folio", "grd_id"], how="left")
    sin_detalle = normal_final["metodo_atribucion"].isna()
    normal_final.loc[sin_detalle, ["cargo", "abono"]] = normal_final.loc[sin_detalle, ["cargo", "abono"]].fillna(0.0)
    normal_final.loc[sin_detalle, "metodo_atribucion"] = "sin_poliza"

    filas.append(normal_final)

    resultado = pd.concat(filas, ignore_index=True)
    return resultado.sort_values(["folio", "grd_id"])


def validar(df: pd.DataFrame):
    """Por origen: si un folio tiene AL MENOS una fila atribuida por respaldo
    ('folio_completo'), TODO el folio se valida a nivel folio completo (aunque otros de
    sus documentos si hayan quedado atribuidos con precision por centro de costo) --
    mezclar los dos niveles dentro del mismo folio da comparaciones sin sentido (el
    residual del respaldo no necesariamente es del ultimo documento). Folios enteramente
    resueltos por centro de costo (sin ninguna fila de respaldo) se validan documento por
    documento -- la comprobacion real que se buscaba."""
    df = df.copy()
    df["cargo"] = df["cargo"].fillna(0)
    df["abono"] = df["abono"].fillna(0)

    folio_tiene_respaldo = df.groupby("folio")["metodo_atribucion"].transform(lambda s: (s == "folio_completo").any())

    multi = df[folio_tiene_respaldo]
    importe_folio = (
        multi.drop_duplicates(subset=["origen", "folio", "grd_id"])
        .groupby(["origen", "folio"], as_index=False)["importe"].sum()
    )
    cargo_abono_folio = multi.groupby(["origen", "folio"], as_index=False)[["cargo", "abono"]].sum()
    nivel_folio = importe_folio.merge(cargo_abono_folio, on=["origen", "folio"])
    nivel_folio["grd_id"] = "(folio completo)"

    nivel_fila = df[~folio_tiene_respaldo].groupby(["origen", "folio", "grd_id"], as_index=False, dropna=False).agg(
        importe=("importe", "first"), cargo=("cargo", "sum"), abono=("abono", "sum"),
    )

    agg = pd.concat([nivel_fila, nivel_folio], ignore_index=True)
    agg["neto"] = agg["cargo"] - agg["abono"]
    agg["diferencia"] = agg["neto"] - agg["importe"]

    resumen = []
    for origen, g in agg.groupby("origen", dropna=False):
        if origen in ORIGENES_SIN_JOIN:
            resumen.append({"origen": origen or "(vacío)", "n": len(g), "aplica": False,
                             "match": None, "pct_match": None})
            continue
        match = (g["diferencia"].abs() <= TOLERANCIA).sum()
        resumen.append({
            "origen": origen or "(vacío)", "n": len(g), "aplica": True,
            "match": match, "pct_match": round(match / len(g) * 100, 2),
        })
    return agg, pd.DataFrame(resumen)


if __name__ == "__main__":
    fecha_ini = sys.argv[1] if len(sys.argv) > 1 else "2026-01-01"
    fecha_fin_excl = sys.argv[2] if len(sys.argv) > 2 else "2026-02-01"

    df = extract(fecha_ini, fecha_fin_excl)
    print(f"{len(df)} filas totales\n")
    print("Por metodo de atribucion:")
    print(df["metodo_atribucion"].value_counts())
    print()

    agg, resumen = validar(df)
    print("=== Validacion por origen (Cargo - Abono == Importe) ===")
    print(resumen.to_string(index=False))

    print("\n=== Top discrepancias (origenes que SI aplican comprobacion) ===")
    aplica = agg[agg["origen"].apply(lambda o: o not in ORIGENES_SIN_JOIN)]
    no_match = aplica[aplica["diferencia"].abs() > TOLERANCIA].sort_values("diferencia", key=abs, ascending=False)
    print(f"{len(no_match)} de {len(aplica)} filas con diferencia > {TOLERANCIA}")
    if len(no_match):
        print(no_match.head(20).to_string(index=False))

    out_path = f"output/layout_gastos_v0_3_{fecha_ini}_a_{fecha_fin_excl}.csv"
    df.to_csv(out_path, index=False)
    print(f"\nGuardado: {out_path}")
