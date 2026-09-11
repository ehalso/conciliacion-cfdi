"""
Layout de gastos - v0.4.2: identico a v0.4.1 (atribucion exacta por documento via centro
de costo + reparto proporcional + salvaguarda de cuadre por documento -- ver ese archivo
para el detalle completo), MAS un ajuste final para reversiones contables reales.

Ajuste v0.4.2 (ver docs/15_hito_v0_4_reversiones.md): regla mas simple posible, propuesta
por el usuario -- si el Importe de un folio (sumado por documento) es negativo, se usa
su Abono (no su Cargo): se pone en 0 el Cargo de ese folio (columna nueva
`ajuste_reversion` marca cuales). El lado "Cargo" de estos folios cae en una cuenta de
Provision/Pasivo por pagar -- NO es un gasto real, es la contrapartida de la reversion.
El Abono si es la cuenta de Gastos real, y por si solo ya es igual al Importe (con
signo) -- garantia de partida doble (una reversion siempre tiene Cargo==Abono==monto
revertido). Resultado: 99.94% de comprobacion en todo 2025, solo 10 de 18,046 filas sin
cuadrar (7 de redondeo + 3 de un unico folio sin ninguna poliza capturada en MPRO,
05-0164271 -- ni con esta regla se puede arreglar, no hay Abono que usar).

Se probo primero excluir por NOMBRE de cuenta ("Provision"/"por pagar") pero esa regla
rompia 59 folios de Importe POSITIVO que usan esas mismas cuentas legitimamente (costeo
estandar). Tambien se probo exigir ademas Cargo~Abono a nivel folio (71 de 84 folios) --
innecesario, la condicion sola Importe<=-$1 ya cubre 83 de 84 sin falsos positivos porque
nunca toca folios de Importe positivo.

Uso: python3 scripts/layout_gastos_v0_4_2.py 2026-01-01 2026-02-01
"""
import sys

import pandas as pd

from db import q

TOLERANCIA = 0.5
UMBRAL_REDONDEO = 5.0  # diferencias hasta este monto se explican como ruido de redondeo

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
     -- fallback 2: "Gastos a cuenta de costo estandar" (familia 2120.010.xxx, sufijo
     -- .002) es el lado REAL de gasto de un sistema de costeo estandar de 2 cuentas
     -- (la otra, sufijo .001 "Provision de costo estandar", es la contrapartida/pasivo,
     -- correctamente excluida) -- verificado: solo 2 lineas en todo 2025+2026 caen aqui
     -- (folio 05-0164271, $108,302.59), el resto de cuentas sin grupo NO son gasto
     -- (prestamos, arrendamientos, proveedores, fondos fijos -- ver docs/16).
     OR (pd.Pd_Tipo = 2 AND ga.raiz IS NULL
         AND LOWER(cc.Cc_Descripcion) LIKE '%gastos a cuenta de costo estandar%')
      )
  AND pl.Es_Cve_Estado <> 'CA'
ORDER BY gr.Gr_Folio, pd.Pd_ID
"""

GRC_SQL = """
SELECT
    gr.Gr_Folio             AS folio,
    grc.Grd_ID               AS grd_id,
    grc.Grc_ID                AS grc_id,
    grc.Cc_Cve_Centro_Costo    AS centro_costo,
    grc.Grc_Importe            AS grc_importe
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
    """3 metodos, de mas a menos preciso. Devuelve (exacta, proporcional, sin_grupo):
      - exacta: grupos (folio,centro_costo) con el MISMO conteo de DOCUMENTOS en ambos
        lados -- emparejamiento posicional (mismo orden de creacion en MPRO).
      - proporcional: grupos con conteo DISTINTO pero datos en ambos lados -- el total
        de poliza de ese grupo se reparte entre los documentos de Gasto_Registro_Control
        de ese grupo, en proporcion a lo que cada uno aporto (Grc_Importe).
      - sin_grupo: lineas de poliza cuyo centro de costo no aparece del todo en
        Gasto_Registro_Control para ese folio -- no hay base para repartir, van a
        metodo de respaldo (folio_completo).

    Antes de contar/emparejar, Gasto_Registro_Control se COLAPSA a 1 fila por
    (folio, centro_costo, Grd_ID) sumando Grc_Importe -- Grc_ID no identifica un
    documento distinto, identifica una sub-linea DENTRO del mismo documento y mismo
    centro de costo (ej. varios activos fijos de un mismo documento de depreciacion en
    el mismo centro -- verificado: folio 01-0035004, Grd_ID 0004 tiene 15 Grc_ID solo en
    el centro 000027). Contar Grc_ID crudo como si fuera "documentos" inflaba n_grc y
    tiraba a reparto proporcional grupos que en realidad tenian el MISMO conteo de
    documentos que Poliza_Detalle (85 de 127 grupos de ese folio, ver docs/14_hito_v0_4.md)."""
    cols_prop = ["folio", "centro_costo", "cuenta_registro", "nombre_cuenta_registro", "cargo", "abono", "grd_id"]
    if poliza_cc.empty or grc.empty:
        return poliza_cc.iloc[0:0], pd.DataFrame(columns=cols_prop), poliza_cc

    poliza_cc = poliza_cc.copy()
    grc = grc.groupby(["folio", "centro_costo", "grd_id"], as_index=False)["grc_importe"].sum()

    n_pd = poliza_cc.groupby(["folio", "centro_costo"]).size().rename("n_pd")
    n_grc = grc.groupby(["folio", "centro_costo"]).size().rename("n_grc")
    conteo_ambos = pd.concat([n_pd, n_grc], axis=1).dropna()
    grupos_comunes = conteo_ambos.index
    grupos_iguales = conteo_ambos[conteo_ambos["n_pd"] == conteo_ambos["n_grc"]].index
    grupos_proporcional = grupos_comunes.difference(grupos_iguales)

    idx_pd = poliza_cc.set_index(["folio", "centro_costo"]).index
    idx_grc = grc.set_index(["folio", "centro_costo"]).index

    # --- 1. exacta: emparejamiento POR VALOR, no por orden de creacion ---
    # verificado con datos reales (folio 01-0035004, centro 000103): el documento MAS
    # GRANDE del grupo no cae en la "misma posicion" del lado de poliza -- Grd_ID 0003
    # ($59,495.92) es la 3a linea por Grd_ID pero la 5a cuenta por Pd_ID (Maquinaria y
    # Equipo) -- el orden de creacion NO coincide entre las dos tablas para este folio,
    # pero el IMPORTE si. Ordenar ambos lados por importe y emparejar por esa posicion
    # resuelve esto sin ambiguedad cuando los valores son distintos, y no importa cuando
    # son identicos (documentos fungibles, cualquier asignacion da el mismo agregado).
    pd_igual = poliza_cc[idx_pd.isin(grupos_iguales)].copy()
    pd_igual["valor"] = (pd_igual["cargo"] - pd_igual["abono"]).abs()
    pd_igual = pd_igual.sort_values(["folio", "centro_costo", "valor", "pd_id"])
    pd_igual["rn"] = pd_igual.groupby(["folio", "centro_costo"]).cumcount() + 1

    grc_igual = grc[idx_grc.isin(grupos_iguales)].sort_values(
        ["folio", "centro_costo", "grc_importe", "grd_id"]
    ).copy()
    grc_igual["rn"] = grc_igual.groupby(["folio", "centro_costo"]).cumcount() + 1

    exacta = pd_igual.drop(columns=["valor"]).merge(
        grc_igual[["folio", "centro_costo", "rn", "grd_id"]],
        on=["folio", "centro_costo", "rn"], how="left",
    ).drop(columns=["rn"])

    # --- 2. proporcional (por Grc_Importe dentro del grupo) ---
    pd_prop = poliza_cc[idx_pd.isin(grupos_proporcional)]
    grc_prop = grc[idx_grc.isin(grupos_proporcional)].copy()
    if pd_prop.empty or grc_prop.empty:
        proporcional = pd.DataFrame(columns=cols_prop)
    else:
        total_grupo = grc_prop.groupby(["folio", "centro_costo"])["grc_importe"].transform("sum")
        n_en_grupo = grc_prop.groupby(["folio", "centro_costo"])["grd_id"].transform("count")
        grc_prop["peso"] = (grc_prop["grc_importe"] / total_grupo).where(total_grupo != 0, 1.0 / n_en_grupo)

        pd_prop_agg = pd_prop.groupby(
            ["folio", "centro_costo", "cuenta_registro", "nombre_cuenta_registro"], as_index=False
        )[["cargo", "abono"]].sum()

        proporcional = pd_prop_agg.merge(
            grc_prop[["folio", "centro_costo", "grd_id", "peso"]], on=["folio", "centro_costo"], how="inner"
        )
        proporcional["cargo"] = proporcional["cargo"] * proporcional["peso"]
        proporcional["abono"] = proporcional["abono"] * proporcional["peso"]
        proporcional = proporcional.drop(columns=["peso"])

    # --- 3. sin datos del lado de Gasto_Registro_Control: al respaldo ---
    sin_grupo = poliza_cc[~idx_pd.isin(grupos_comunes)]

    return exacta, proporcional, sin_grupo


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

    emparejadas, proporcionales, sin_grupo = _atribuir_por_centro_costo(poliza_cc, grc)
    poliza_fallback = pd.concat([poliza_sc, sin_grupo], ignore_index=True)

    # --- detalle 1: cargo/abono/cuenta atribuidos al Grd_ID real via centro de costo ---
    detalle_cols = ["folio", "grd_id", "cuenta_registro", "nombre_cuenta_registro", "cargo", "abono", "metodo_atribucion"]
    exacta = pd.DataFrame(columns=detalle_cols)
    if not emparejadas.empty:
        exacta = emparejadas.groupby(
            ["folio", "grd_id", "cuenta_registro", "nombre_cuenta_registro"], as_index=False, dropna=False
        )[["cargo", "abono"]].sum()
        exacta["metodo_atribucion"] = "centro_costo"

    # --- detalle 1b: reparto proporcional (conteo distinto, ambos lados con datos) ---
    proporcional = pd.DataFrame(columns=detalle_cols)
    if not proporcionales.empty:
        proporcional = proporcionales.groupby(
            ["folio", "grd_id", "cuenta_registro", "nombre_cuenta_registro"], as_index=False, dropna=False
        )[["cargo", "abono"]].sum()
        proporcional["metodo_atribucion"] = "centro_costo_proporcional"

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
    detalle = pd.concat([exacta, proporcional, fallback], ignore_index=True)

    normal_final = normal_base.merge(detalle, on=["folio", "grd_id"], how="left")
    sin_detalle = normal_final["metodo_atribucion"].isna()
    normal_final.loc[sin_detalle, ["cargo", "abono"]] = normal_final.loc[sin_detalle, ["cargo", "abono"]].fillna(0.0)
    normal_final.loc[sin_detalle, "metodo_atribucion"] = "sin_poliza"

    # --- salvaguarda: si algun documento de un folio no cuadra, TODO el folio se
    # re-enruta a folio_completo (aunque otros de sus documentos si hubieran cuadrado
    # via centro de costo). El reparto proporcional puede acumular ruido de redondeo a
    # nivel de UN documento cuando ese documento participa en MUCHOS grupos distintos de
    # (folio, centro_costo) -- visto en folios de depreciacion con 70+ centros de costo
    # (folio 01-0035004: el folio completo cuadra exacto a $0.08, pero 3 de sus 8
    # documentos quedaban con diferencias de $1,400-$5,000 -- ver docs/14_hito_v0_4.md).
    # Se prefiere perder precision por documento en esos casos raros y caer al metodo de
    # respaldo ya validado a nivel folio, en vez de mostrar un numero por documento
    # ligeramente incorrecto.
    es_atribuido = normal_final["metodo_atribucion"].isin(["centro_costo", "centro_costo_proporcional"])
    chequeo = normal_final[es_atribuido].groupby(["folio", "grd_id"], as_index=False).agg(
        importe=("importe", "first"), cargo=("cargo", "sum"), abono=("abono", "sum"),
    )
    chequeo["diff"] = (chequeo["cargo"] - chequeo["abono"] - chequeo["importe"]).abs()
    max_diff_por_folio = chequeo.groupby("folio")["diff"].max()
    folios_reenrutar = max_diff_por_folio[max_diff_por_folio > TOLERANCIA].index.tolist()

    if folios_reenrutar:
        base_reenrutar = normal_base[normal_base["folio"].isin(folios_reenrutar)].copy()
        poliza_reenrutar = poliza[poliza["folio"].isin(folios_reenrutar)]
        agg_reenrutar = poliza_reenrutar.groupby(
            ["folio", "cuenta_registro", "nombre_cuenta_registro"], as_index=False
        )[["cargo", "abono"]].sum()
        ultimo_grd_reenrutar = base_reenrutar.groupby("folio")["grd_id"].transform("max")
        mapa_ultimo_reenrutar = base_reenrutar.loc[
            base_reenrutar["grd_id"] == ultimo_grd_reenrutar, ["folio", "grd_id"]
        ].drop_duplicates(subset=["folio"])
        detalle_reenrutar = agg_reenrutar.merge(mapa_ultimo_reenrutar, on="folio", how="left")

        base_reenrutada = base_reenrutar.merge(detalle_reenrutar, on=["folio", "grd_id"], how="left")
        base_reenrutada[["cargo", "abono"]] = base_reenrutada[["cargo", "abono"]].fillna(0.0)
        base_reenrutada["metodo_atribucion"] = "folio_completo"

        normal_final = pd.concat([
            normal_final[~normal_final["folio"].isin(folios_reenrutar)],
            base_reenrutada,
        ], ignore_index=True)

    # --- ajuste final: reversiones contables reales (Importe negativo) ---
    # el usuario propuso la regla mas simple posible: si el Importe de un folio es
    # negativo, usar su Abono (no su Cargo). Verificado con datos de 2025+2026 (84
    # folios con Importe<=-$1): con esta regla sola, 83 de 84 cuadran exacto -- el unico
    # que no es 05-0164271, que no tiene NINGUNA linea de poliza capturada (Cargo=Abono=0,
    # no hay nada que usar). No hizo falta la condicion extra "Cargo~Abono" de un primer
    # intento (que solo cubria 71 de los 84) -- el lado "Cargo" de estos folios siempre
    # cae en una cuenta de Provision/Pasivo por pagar (Aguinaldo, Prima
    # antiguedad/vacacional, Provision de costo estandar...), NO es un gasto real, es la
    # contrapartida de la reversion; el Abono si es la cuenta de Gastos real que se esta
    # reduciendo, y por si solo ya es igual al Importe (con signo) -- garantia de partida
    # doble. Probar solo por NOMBRE de cuenta ("Provision"/"por pagar") no sirve: esas
    # mismas cuentas se usan legitimamente como Cargo en folios de Importe POSITIVO
    # (costeo estandar) -- ahi no hay que tocar nada. La condicion Importe<=-$1 (a nivel
    # folio) aisla el patron sin falsos positivos porque nunca toca folios de Importe
    # positivo.
    importe_folio_normal = normal_final.drop_duplicates(subset=["folio", "grd_id"]).groupby("folio")["importe"].sum()
    es_reversion = importe_folio_normal <= -1.0
    folios_reversion = importe_folio_normal[es_reversion].index

    es_fila_reversion = normal_final["folio"].isin(folios_reversion)
    normal_final["ajuste_reversion"] = es_fila_reversion
    normal_final.loc[es_fila_reversion & (normal_final["cargo"] > 0), "cargo"] = 0.0

    filas.append(normal_final)

    resultado = pd.concat(filas, ignore_index=True)
    if "ajuste_reversion" not in resultado.columns:
        resultado["ajuste_reversion"] = False
    resultado["ajuste_reversion"] = resultado["ajuste_reversion"].fillna(False)
    return resultado.sort_values(["folio", "grd_id"])


def _explicar_gap(fila) -> str:
    """Clasifica cada fila de la comprobacion en un motivo legible -- para que el reporte
    diga POR QUE no cuadra en vez de solo mostrar el numero. Reglas en orden:
      1. Cuadra (dentro de TOLERANCIA) -- nada que explicar.
      2. Ruido de redondeo -- diferencia chica (<= UMBRAL_REDONDEO), atribuible a
         redondeo de centavos acumulado (ej. conversion de moneda, reparto entre varias
         cuentas), no a un problema real.
      3. Reclasificacion/ajuste manual con signo invertido -- Importe negativo (un
         "saldo"/reversion) pero Cargo y Abono de la poliza casi se cancelan entre si
         (neto ~ 0, como una reclasificacion real) -- la regla Cargo-Abono==Importe no
         tiene forma de cuadrar con esa convencion de signos (ver docs/12_hito_v0_2.md,
         folios 01-0034998/01-0034999/05-0181359 -- decision del usuario: dejarlos
         marcados, no forzar la regla).
      4. Sin explicacion automatica -- cualquier otro caso; señal de que hay que
         revisarlo a mano en vez de asumir que es "mas de lo mismo"."""
    diferencia = fila["diferencia"]
    if abs(diferencia) <= TOLERANCIA:
        return "Cuadra"
    if abs(diferencia) <= UMBRAL_REDONDEO:
        return "Ruido de redondeo"
    if fila["importe"] < 0 and abs(fila["neto"]) <= UMBRAL_REDONDEO:
        return "Reclasificación/ajuste manual con Importe negativo (Cargo≈Abono, neto≈0)"
    return "Sin explicación automática -- revisar a mano"


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
    agg["motivo"] = agg.apply(_explicar_gap, axis=1)

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
        print("\nPor motivo:")
        print(no_match["motivo"].value_counts().to_string())
        print()
        print(no_match.head(20).to_string(index=False))

    out_path = f"output/layout_gastos_v0_4_2_{fecha_ini}_a_{fecha_fin_excl}.csv"
    df.to_csv(out_path, index=False)
    print(f"\nGuardado: {out_path}")
