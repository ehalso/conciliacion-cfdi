"""
Layout de gastos - v0.2: como v0.1 (una fila por Gasto_Registro_Documento, todos los
origenes de Gr_Tabla incluidos), pero agrega Cargo/Abono/Cuenta Registro -- SOLO del lado
del importe (subtotal), sin impuestos.

Reglas por origen (Gr_Tabla), verificadas una por una contra datos reales de enero 2026
antes de escribir el query (ver docs/12_hito_v0_2.md para el detalle completo y las
validaciones origen por origen):

  - CONSUMO_INTERNO / GASTO_REGISTRO_NOMINA: Cargo/Abono/Cuenta Registro quedan VACIOS
    a proposito (pedido explicito del usuario) -- no se intenta ningun join de poliza
    para estos.
  - GASTO_RECLASIFICACION: NO tiene poliza propia (Poliza_Control da 0 resultados para
    estos folios -- verificado). El cargo/abono real vive directamente en
    Gasto_Registro_Documento: cada folio trae N filas "Reclasificación de gastos
    (Cargos)" (importe positivo) + las mismas N en espejo "(Abonos)" (importe negativo),
    cada una con su propio Tg_Cve_Tipo_Gasto. Cargo/Abono se derivan del signo de
    Grd_Precio_Descontado_Importe; Cuenta Registro sale de Tipo_Gasto.Tg_Cuenta_Contable
    (puede venir vacia si ese tipo de gasto no tiene cuenta mapeada).
  - Todo lo demas (blanco, VIAJE, ORDEN_COMPRA, CONTROL_COMBUSTIBLE): join normal contra
    Poliza_Detalle (via Poliza_Control, Pd_Referencia=Gr_Folio) -- Pd_Tipo=1 es Cargo;
    Pd_Tipo=2 solo si la cuenta es de grupo 'F' (Gastos, reclasificacion dentro de una
    poliza real) cuenta como Abono. Esto excluye impuestos porque las lineas de IVA no
    tienen Pd_Referencia poblado (agregado a nivel poliza, no por folio) -- confirmado en
    layout_gastos_v1.py.

Validacion: por fila, Cargo - Abono debe igualar el importe (Grd_Precio_Descontado_Importe,
la fila puede representar mas de una linea de poliza si el folio tiene mas de una cuenta
contable -- se agrupa por Grd_ID antes de comparar).

Uso: python3 scripts/layout_gastos_v0_2.py 2026-01-01 2026-02-01
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
     -- fallback: cuentas de gasto (prefijo 6xxx) sin Cc_Grupo_Cuenta_Contable asignado
     -- en el catalogo (hueco de dato confirmado solo en 6200.001.007.016 -- ver
     -- docs/12_hito_v0_2.md, folio 05-0181359) se tratan como Gastos (F) igual que sus
     -- cuentas hermanas del mismo folio que si tienen grupo.
     OR (pd.Pd_Tipo = 2 AND ga.raiz IS NULL AND LEFT(pd.Cc_Cve_Cuenta_Contable, 1) = '6')
      )
  AND pl.Es_Cve_Estado <> 'CA'
ORDER BY gr.Gr_Folio, pd.Pd_ID
"""


def extract(fecha_ini: str, fecha_fin_excl: str):
    base = q(BASE_SQL.format(fecha_ini=fecha_ini, fecha_fin_excl=fecha_fin_excl))
    poliza = q(POLIZA_SQL.format(fecha_ini=fecha_ini, fecha_fin_excl=fecha_fin_excl))
    return armar(base, poliza)


def armar(base: pd.DataFrame, poliza: pd.DataFrame) -> pd.DataFrame:
    """Combina base (grano Grd_ID) con poliza (grano Pd_ID, colapsado a nivel folio+cuenta
    para no romper el grano de la fila) segun la regla de cada origen."""
    es_sin_join = base["origen"].isin(ORIGENES_SIN_JOIN)
    es_reclasificacion = base["origen"] == ORIGEN_RECLASIFICACION
    es_normal = ~es_sin_join & ~es_reclasificacion

    filas = []

    # --- sin join (consumo interno / nomina): cargo, abono, cuenta registro vacios ---
    sin_join = base[es_sin_join].copy()
    sin_join["cargo"] = None
    sin_join["abono"] = None
    sin_join["cuenta_registro"] = None
    sin_join["nombre_cuenta_registro"] = None
    filas.append(sin_join)

    # --- reclasificacion: cargo/abono por signo del importe, cuenta = Tipo_Gasto ---
    recl = base[es_reclasificacion].copy()
    recl["cargo"] = recl["importe"].clip(lower=0)
    recl["abono"] = (-recl["importe"]).clip(lower=0)
    recl["cuenta_registro"] = recl["tipo_gasto_cuenta_contable"]
    recl["nombre_cuenta_registro"] = None
    filas.append(recl)

    # --- resto: join de poliza ---
    # Poliza_Detalle.Pd_Referencia = Gr_Folio, NUNCA Grd_ID -- cuando un folio tiene un
    # solo Grd_ID el join es 1:1 sin ambiguedad. Cuando tiene 2+ (Z_Grd_Multiple, ~7.5%
    # de los folios de "el resto" en enero 2026 -- ver docs/12_hito_v0_2.md), no hay forma
    # de saber a cual Grd_ID especifico corresponde cada linea de poliza -- es un dato a
    # nivel FOLIO, no por documento. Repartirlo (aunque sea sumado) en cada Grd_ID del
    # folio duplicaba el cargo N veces al sumar la columna (bug detectado y corregido
    # aqui). Se opta por: cargo/abono/cuenta se ponen SOLO en el ULTIMO Grd_ID del folio
    # (orden por Grd_ID), las demas filas del mismo folio quedan en 0/vacio, y se agrega
    # `cargo_abono_a_nivel_folio=True` para dejarlo visible. La comprobacion (Cargo-Abono
    # == Importe) para estos casos se hace a nivel folio (suma de Importe de todos sus
    # Grd_ID), no por fila -- ver validar().
    normal = base[es_normal].copy()
    normal["cuenta_registro"] = None
    normal["nombre_cuenta_registro"] = None
    normal["cargo"] = 0.0
    normal["abono"] = 0.0
    normal["cargo_abono_a_nivel_folio"] = False

    if not poliza.empty:
        poliza_agg = poliza.groupby(["folio", "cuenta_registro", "nombre_cuenta_registro"], as_index=False)[
            ["cargo", "abono"]
        ].sum()
        # una fila de poliza_agg por (folio, cuenta) -- si un folio usa 2+ cuentas
        # contables, genera 2+ filas de poliza para ese folio.
        n_grd_por_folio = normal.groupby("folio")["grd_id"].transform("nunique")
        es_multi_grd = n_grd_por_folio > 1

        folios_multi = normal.loc[es_multi_grd, "folio"].unique().tolist()
        folios_single = normal.loc[~es_multi_grd, "folio"].unique().tolist()

        # folios de un solo Grd_ID: merge 1:1 normal (puede generar 2+ filas si el folio
        # usa 2+ cuentas contables -- caso ya documentado en v1, "excepcion de dos cuentas").
        single = normal[normal["folio"].isin(folios_single)].drop(
            columns=["cuenta_registro", "nombre_cuenta_registro", "cargo", "abono"]
        ).merge(poliza_agg, on="folio", how="left")
        single["cargo"] = single["cargo"].fillna(0)
        single["abono"] = single["abono"].fillna(0)
        single["cargo_abono_a_nivel_folio"] = False

        # folios multi-Grd_ID: la poliza solo se pega al ULTIMO Grd_ID; el resto queda en 0.
        base_multi = normal[normal["folio"].isin(folios_multi)].copy()
        es_ultimo = base_multi["grd_id"] == base_multi["folio"].map(
            base_multi.groupby("folio")["grd_id"].max()
        )
        resto_multi = base_multi[~es_ultimo]
        ultimo_multi = base_multi[es_ultimo].drop(
            columns=["cuenta_registro", "nombre_cuenta_registro", "cargo", "abono"]
        ).merge(poliza_agg, on="folio", how="left")
        ultimo_multi["cargo"] = ultimo_multi["cargo"].fillna(0)
        ultimo_multi["abono"] = ultimo_multi["abono"].fillna(0)
        ultimo_multi["cargo_abono_a_nivel_folio"] = True
        resto_multi["cargo_abono_a_nivel_folio"] = True

        normal = pd.concat([single, resto_multi, ultimo_multi], ignore_index=True)

    filas.append(normal)

    resultado = pd.concat(filas, ignore_index=True)
    return resultado.sort_values(["folio", "grd_id"])


def validar(df: pd.DataFrame):
    """Por origen: para folios de un solo Grd_ID, compara Cargo-Abono vs Importe a nivel
    fila. Para folios multi-Grd_ID (poliza solo a nivel folio, ver armar()), agrupa a
    nivel FOLIO antes de comparar -- comparar fila por fila ahi no tiene sentido porque
    el cargo real es del folio completo, no de un Grd_ID en particular."""
    df = df.copy()
    df["cargo"] = df["cargo"].fillna(0)
    df["abono"] = df["abono"].fillna(0)

    es_multi = df.get("cargo_abono_a_nivel_folio", False) == True  # noqa: E712

    # ojo: dentro de un folio multi-Grd_ID, la fila del "ultimo" Grd_ID puede venir
    # replicada N veces (una por cada cuenta contable distinta de su poliza) -- "importe"
    # es un dato POR DOCUMENTO (grd_id), no por linea de poliza, asi que sumarlo tal cual
    # lo infla x N. Se deduplica por (folio, grd_id) antes de sumarlo; cargo/abono si se
    # suman sobre todas las filas (fanned-out o no) porque cada una es una linea real de
    # poliza.
    multi = df[es_multi]
    importe_folio = (
        multi.drop_duplicates(subset=["origen", "folio", "grd_id"])
        .groupby(["origen", "folio"], as_index=False)["importe"].sum()
    )
    cargo_abono_folio = multi.groupby(["origen", "folio"], as_index=False)[["cargo", "abono"]].sum()
    nivel_folio = importe_folio.merge(cargo_abono_folio, on=["origen", "folio"])
    nivel_folio["grd_id"] = "(folio completo)"

    nivel_fila = df[~es_multi].groupby(["origen", "folio", "grd_id"], as_index=False, dropna=False).agg(
        importe=("importe", "first"), cargo=("cargo", "sum"), abono=("abono", "sum"),
    )

    agg = pd.concat([nivel_fila, nivel_folio], ignore_index=True)
    agg["neto"] = agg["cargo"] - agg["abono"]
    agg["diferencia"] = agg["neto"] - agg["importe"]

    resumen = []
    for origen, g in agg.groupby("origen", dropna=False):
        if origen in ORIGENES_SIN_JOIN:
            # no aplica comprobacion -- por diseno vienen vacios
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

    agg, resumen = validar(df)
    print("=== Validacion por origen (Cargo - Abono == Importe) ===")
    print(resumen.to_string(index=False))

    print("\n=== Top discrepancias (origenes que SI aplican comprobacion) ===")
    aplica = agg[agg["origen"].apply(lambda o: o not in ORIGENES_SIN_JOIN)]
    no_match = aplica[aplica["diferencia"].abs() > TOLERANCIA].sort_values("diferencia", key=abs, ascending=False)
    print(f"{len(no_match)} de {len(aplica)} filas con diferencia > {TOLERANCIA}")
    if len(no_match):
        print(no_match.head(20).to_string(index=False))

    out_path = f"output/layout_gastos_v0_2_{fecha_ini}_a_{fecha_fin_excl}.csv"
    df.to_csv(out_path, index=False)
    print(f"\nGuardado: {out_path}")
