"""Reconciliación a nivel póliza, YA distinguida por origen de documento
(Comprobante_Digital.Cd_Tabla / Poliza_Control.Pc_Tabla) — no agregado como
en extract_poliza.py (el piloto de la sesión anterior).

Para cada (origen, documento) real — sacado de Comprobante_Digital, no
inventado — trae el Cargo/Abono posteado en Poliza_Detalle vía
Poliza_Control, en pólizas activas, EXCLUYENDO el lado "cuentas de orden"
cuando el origen tiene el patrón de doble póliza documentado en
poliza-explor/configuracion-polizas.md (Compra, Compra_Indirecto:
Pl_Configuracion → Poliza_Configuracion.Pc_Descripcion NOT LIKE '%CUENTAS
DE ORDEN%').

Nota de mapeo: `Poliza_Control.Pc_Tabla` usa 'Cheque' (title-case) para ese
origen específico y MAYÚSCULAS para el resto — confirmado en vivo
(DISTINCT Pc_Tabla, 2026-09-07). Se compara con UPPER() por seguridad.
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET

BATCH_SIZE = 150


def _fetch_batch(origen: str, documentos: list[str], excluir_descripcion: list[str] | None = None) -> list[dict]:
    in_list = ", ".join(sql_quote(d) for d in documentos)
    excluir_sql = "".join(
        f" AND (pcf.Pc_Descripcion IS NULL OR UPPER(pcf.Pc_Descripcion) NOT LIKE '%{txt.upper()}%')"
        for txt in (excluir_descripcion or []))
    # Clave del fix (confirmado en vivo 2026-09-07): un Pl_Folio consolida
    # VARIOS documentos del mismo origen (ej. varios Gr_Folio bajo una sola
    # póliza del día) — sumar por Poliza_Control sin más trae el cargo/abono
    # de TODOS esos documentos, no solo el que nos interesa. Filtrar
    # además por Poliza_Detalle.Pd_Referencia = documento aísla las líneas
    # correctas dentro de la póliza consolidada — mismo método ya validado
    # en layout-gastos para GASTO_REGISTRO, generalizado aquí a los demás
    # orígenes con Pd_Referencia confiable (todos salvo Cheque, ver
    # extract_poliza_cheque()).
    sql = (
        "SELECT pd.Pd_Referencia AS documento, pd.Pd_Tipo, SUM(pd.Pd_Importe) AS importe, "
        "COUNT(DISTINCT pc.Pl_Folio) AS n_polizas "
        "FROM Poliza_Control pc "
        "JOIN Poliza p ON p.Pl_Folio = pc.Pl_Folio "
        "JOIN Poliza_Detalle pd ON pd.Pl_Folio = pc.Pl_Folio AND pd.Pd_Referencia = pc.Pc_Documento "
        "LEFT JOIN Poliza_Configuracion pcf ON pcf.Pc_Cve_Poliza_Configuracion = p.Pl_Configuracion "
        f"WHERE UPPER(pc.Pc_Tabla) = UPPER({sql_quote(origen)}) "
        "AND p.Es_Cve_Estado <> 'CA' "
        "AND (pcf.Pc_Descripcion IS NULL OR UPPER(pcf.Pc_Descripcion) NOT LIKE '%CUENTAS DE ORDEN%') "
        # Filtro estructural de cuentas de orden (2026-09-09): el de arriba, por
        # texto de Pc_Descripcion, se le escapan las variantes reales que usa el
        # catálogo — "(CTS ORDEN)", "( CUENTA DE ORDEN)", "(CUENT ORDEN)",
        # "(CUENTA ORDEN)" — y por eso Cuenta_x_Pagar (config 0360) y
        # Nota_Credito_Proveedor (0235/0352) contaban el cargo DOS VECES.
        # En el catálogo de cuentas, las de orden son exactamente las de raíz de
        # 5 dígitos (10100..10600, grupo `E.*`: Valores Ajenos / Contingentes /
        # De Control); las cuentas reales tienen raíz de 4 dígitos (1110, 1140,
        # 2110, 6100...). Eso no depende de cómo esté redactada la configuración.
        "AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '10[1-6]00%' "
        + excluir_sql +
        f" AND pc.Pc_Documento IN ({in_list}) "
        "GROUP BY pd.Pd_Referencia, pd.Pd_Tipo"
    )
    result = run_query(MPRO_TARGET, sql)
    return rows_as_dicts(result)


def extract_poliza_por_origen(origen: str, documentos: list[str],
                               excluir_descripcion: list[str] | None = None) -> pd.DataFrame:
    """Devuelve una fila por `documento` con suma de cargo/abono (pólizas
    activas, sin cuentas de orden) para ese origen específico.

    `excluir_descripcion`: substrings adicionales de `Poliza_Configuracion.Pc_Descripcion`
    a excluir, además de "CUENTAS DE ORDEN" (siempre excluido). Caso de uso: VENTA
    genera, por documento, DOS pólizas separadas — una de ingreso (config "VENTAS
    ...", Cargo=Clientes/Abono=Ventas+IVA) y otra de costo de venta (config "COSTO
    DE VENTA ...", Cargo=Costo/Abono=Inventario) — confirmado en vivo 2026-09-10.
    Sin excluir la segunda, cargo_agregado suma inventario+clientes y ya no
    compara contra el total fiscal del CFDI."""
    documentos = sorted(set(documentos))
    raw: list[dict] = []
    for i in range(0, len(documentos), BATCH_SIZE):
        raw.extend(_fetch_batch(origen, documentos[i : i + BATCH_SIZE], excluir_descripcion))

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for r in raw:
        by_doc[r["documento"]].append(r)

    out = []
    for doc, rows in by_doc.items():
        cargo = sum(float(r["importe"]) for r in rows if r["Pd_Tipo"] == 1)
        abono = sum(float(r["importe"]) for r in rows if r["Pd_Tipo"] == 2)
        n_polizas = max((r["n_polizas"] for r in rows), default=0)
        out.append({"documento": doc, "cargo": cargo, "abono": abono, "n_polizas": int(n_polizas)})
    return pd.DataFrame(out, columns=["documento", "cargo", "abono", "n_polizas"])


def extract_poliza_factura(fc_folios: list[str]) -> pd.DataFrame:
    """Método específico para FACTURA (emitidos) — CORRIGE un hallazgo falso
    de la sesión 2026-09-10: `Comprobante_Digital.Cd_Documento` (= `Factura_
    Encabezado.Fc_Folio`) **NO** es directamente `Poliza_Control.Pc_Documento`
    bajo `Pc_Tabla='VENTA'`, aunque una consulta ingenua por `Pc_Documento =
    <Fc_Folio>` sí devuelve filas — es un **falso positivo por reciclaje de
    folio**: la serie `XX-NNNNNNN` de `Venta_Encabezado.Vn_Folio` es
    independiente de la de `Factura_Encabezado.Fc_Folio` y ambas reciclan el
    mismo rango de números en años distintos (confirmado en vivo: folios que
    matchean por texto traen `Poliza.Pl_Fecha` de 2018-2025, sin relación con
    la fecha real de la factura). Cualquier resultado de una consulta directa
    por `Fc_Folio` en `Poliza_Control` sin filtrar por fecha es basura.

    La cadena real, verificada con fecha (2026-09-10): `Factura_Encabezado.
    Fc_Folio` -> `Venta_Encabezado.Fc_Folio` (puede haber más de un `Vn_Folio`
    por factura — el caso "factura consolida muchas ventas" — hasta 382 en
    enero 2026) -> `Vn_Folio` = `Poliza_Control.Pc_Documento` (`Pc_Tabla=
    'VENTA'`), exigiendo `Poliza.Pl_Fecha` a máximo 3 días de `Venta_
    Encabezado.Vn_Fecha` (mismo reciclaje de folio aplica también a `Vn_Folio`
    — sin este filtro se repite el mismo falso positivo un nivel más abajo).

    Cobertura confirmada MUY baja (~1% de las FACTURA de enero 2026): incluso
    con la cadena correcta, el `Cargo` a Clientes casi nunca trae `Pd_Referencia
    = Vn_Folio` — solo la póliza de "COSTO DE VENTA" (costo/inventario, sin
    relación con el importe fiscal del CFDI) aísla el documento de forma
    confiable. La póliza de ingreso ("VENTAS ... EN ADELANTE": Cargo Clientes
    1120.xxx = Abono Ventas 4100.xxx + IVA Trasladado 2160.xxx) aparenta
    postearse consolidada por sucursal/día, sin referencia por documento en la
    inmensa mayoría de los casos — pendiente sin resolver, ver docs/pendientes.md.
    """
    fc_folios = sorted(set(fc_folios))
    raw: list[dict] = []
    for i in range(0, len(fc_folios), BATCH_SIZE):
        batch = fc_folios[i : i + BATCH_SIZE]
        in_list = ", ".join(sql_quote(f) for f in batch)
        sql = (
            "SELECT ve.Fc_Folio AS documento, pd.Pd_Tipo, SUM(pd.Pd_Importe) AS importe, "
            "COUNT(DISTINCT pc.Pl_Folio) AS n_polizas "
            "FROM Venta_Encabezado ve "
            "JOIN Poliza_Control pc ON pc.Pc_Documento = ve.Vn_Folio AND UPPER(pc.Pc_Tabla) = 'VENTA' "
            "JOIN Poliza p ON p.Pl_Folio = pc.Pl_Folio AND p.Es_Cve_Estado <> 'CA' "
            "  AND ABS(DATEDIFF(day, p.Pl_Fecha, ve.Vn_Fecha)) <= 3 "
            "JOIN Poliza_Detalle pd ON pd.Pl_Folio = pc.Pl_Folio AND pd.Pd_Referencia = pc.Pc_Documento "
            "LEFT JOIN Poliza_Configuracion pcf ON pcf.Pc_Cve_Poliza_Configuracion = p.Pl_Configuracion "
            "  AND UPPER(pcf.Pc_Descripcion) LIKE '%COSTO DE VENTA%' "
            f"WHERE ve.Fc_Folio IN ({in_list}) AND pcf.Pc_Cve_Poliza_Configuracion IS NULL "
            "GROUP BY ve.Fc_Folio, pd.Pd_Tipo"
        )
        raw.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for r in raw:
        by_doc[r["documento"]].append(r)

    out = []
    for doc, rows in by_doc.items():
        cargo = sum(float(r["importe"]) for r in rows if r["Pd_Tipo"] == 1)
        abono = sum(float(r["importe"]) for r in rows if r["Pd_Tipo"] == 2)
        n_polizas = max((r["n_polizas"] for r in rows), default=0)
        out.append({"documento": doc, "cargo": cargo, "abono": abono, "n_polizas": int(n_polizas)})
    return pd.DataFrame(out, columns=["documento", "cargo", "abono", "n_polizas"])


def extract_poliza_nota_credito(nc_folios: list[str]) -> pd.DataFrame:
    """Método específico para NOTA_CREDITO (emitidos) — el `Pd_Referencia =
    Nc_Folio` genérico (`extract_poliza_por_origen`) es CONFIABLE para ligar
    el documento (a diferencia de FACTURA/VENTA, sin reciclaje de folio:
    verificado con fecha, `Poliza.Pl_Fecha` = `Nota_Credito.Nc_Fecha` exacto
    en 8/8 de una muestra), pero sumar TODO el Cargo da un número sin sentido
    para dos de las cuatro configuraciones reales (censo enero 2026,
    `Poliza_Configuracion.Pc_Descripcion`):

    - `DIRECTA` (ajuste de precio, sin devolución física): Cargo
      `2140.xxx` (=subtotal) + Cargo `2160.xxx` (=iva) = Abono `2140.xxx`
      (sub-cuenta distinta) = TOTAL del CFDI. Verificado exacto en 5/5 casos
      reales de enero 2026 (ej. folio 11-0000846: subtotal 2368.09 = Cargo
      2140.001.001; iva 378.90 = Cargo 2160.002.001; total 2746.99 = Abono
      2140.001.002). Sumar TODO el Cargo (como hace el método genérico) da
      el número correcto aquí.
    - `BONIFICACION` / `DEVOL C/REF` / `DEVOL S/REF` (con devolución física
      de mercancía): Cargo `4200.xxx` (Devoluciones sobre Ventas) = SUBTOTAL
      del CFDI — el número correcto — PERO en las dos variantes "DEVOL" la
      MISMA póliza/`Pd_Referencia` trae ADEMÁS un segundo Cargo a `2140.xxx`
      que empareja exacto con un Abono a `5100.xxx` (costo de venta) — es la
      reversión de costo/inventario por la mercancía devuelta, un monto sin
      relación con el importe fiscal del CFDI (verificado: para 102 folios
      DEVOL C/REF de enero 2026, `SUM(Cargo 2140) = SUM(Abono 5100)` exacto,
      $1,296,132.74). Sumar TODO el Cargo (método genérico) suma subtotal +
      este ruido de costo — por eso el primer intento (`extract_poliza_por_
      origen` genérico) daba solo 33.5%, con diferencias que no eran ruido
      sino este segundo cargo colándose completo.

    Por eso aquí se separa el Cargo por cuenta: `cargo_4200` (Devoluciones,
    aísla BONIFICACION/DEVOL) y `cargo_resto` (todo lo demás, aísla DIRECTA
    sin el ruido de costo porque DIRECTA nunca usa la cuenta 4200). El
    llamador decide contra qué comparar cada uno (`cargo_4200` vs Subtotal,
    `cargo_resto` vs Total) — ver `via_nota_credito()` en
    `baseline_universal_emitido.py`.
    """
    nc_folios = sorted(set(nc_folios))
    raw: list[dict] = []
    for i in range(0, len(nc_folios), BATCH_SIZE):
        batch = nc_folios[i : i + BATCH_SIZE]
        in_list = ", ".join(sql_quote(f) for f in batch)
        sql = (
            "SELECT pd.Pd_Referencia AS documento, pd.Pd_Tipo, "
            "CASE WHEN pd.Cc_Cve_Cuenta_Contable LIKE '4200%' THEN 1 ELSE 0 END AS es_devolucion, "
            "SUM(pd.Pd_Importe) AS importe "
            "FROM Poliza_Control pc "
            "JOIN Poliza p ON p.Pl_Folio = pc.Pl_Folio "
            "JOIN Poliza_Detalle pd ON pd.Pl_Folio = pc.Pl_Folio AND pd.Pd_Referencia = pc.Pc_Documento "
            "WHERE UPPER(pc.Pc_Tabla) = 'NOTA_CREDITO' AND p.Es_Cve_Estado <> 'CA' "
            "AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '10[1-6]00%' "
            f"AND pc.Pc_Documento IN ({in_list}) "
            "GROUP BY pd.Pd_Referencia, pd.Pd_Tipo, "
            "CASE WHEN pd.Cc_Cve_Cuenta_Contable LIKE '4200%' THEN 1 ELSE 0 END"
        )
        raw.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for r in raw:
        by_doc[r["documento"]].append(r)

    out = []
    for doc, rows in by_doc.items():
        cargo_4200 = sum(float(r["importe"]) for r in rows if r["Pd_Tipo"] == 1 and r["es_devolucion"] == 1)
        cargo_resto = sum(float(r["importe"]) for r in rows if r["Pd_Tipo"] == 1 and r["es_devolucion"] == 0)
        abono = sum(float(r["importe"]) for r in rows if r["Pd_Tipo"] == 2)
        out.append({"documento": doc, "cargo_4200": cargo_4200, "cargo_resto": cargo_resto, "abono": abono})
    return pd.DataFrame(out, columns=["documento", "cargo_4200", "cargo_resto", "abono"])


def extract_poliza_cheque(folios: list[str]) -> pd.DataFrame:
    """Método específico para Cheque, ya validado en poliza-explor:
    `Pd_Referencia` NO es confiable para este origen (72% de los casos trae
    `Ch_Referencia`, la referencia externa, en vez de `Ch_Folio`). Se aísla
    el Abono por MONTO en vez de por referencia: `ABS(Pd_Importe -
    Ch_Importe) <= 1`, dentro de las pólizas activas ligadas por
    `Poliza_Control`.
    """
    folios = sorted(set(folios))
    out = []
    for i in range(0, len(folios), BATCH_SIZE):
        batch = folios[i : i + BATCH_SIZE]
        in_list = ", ".join(sql_quote(f) for f in batch)
        sql = (
            "SELECT ch.Ch_Folio AS documento, ch.Ch_Importe AS importe_cheque, "
            "pd.Pd_Importe AS importe_poliza, pc.Pl_Folio "
            "FROM Cheque ch "
            "JOIN Poliza_Control pc ON pc.Pc_Documento = ch.Ch_Folio AND UPPER(pc.Pc_Tabla) = 'CHEQUE' "
            "JOIN Poliza p ON p.Pl_Folio = pc.Pl_Folio AND p.Es_Cve_Estado <> 'CA' "
            "JOIN Poliza_Detalle pd ON pd.Pl_Folio = pc.Pl_Folio AND pd.Pd_Tipo = 2 "
            f"WHERE ch.Ch_Folio IN ({in_list}) "
            "AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '10[1-6]00%' "
            "AND ABS(pd.Pd_Importe - ch.Ch_Importe) <= 1"
        )
        result = run_query(MPRO_TARGET, sql)
        out.extend(rows_as_dicts(result))

    df = pd.DataFrame(out, columns=["documento", "importe_cheque", "importe_poliza", "Pl_Folio"])
    if df.empty:
        return pd.DataFrame(columns=["documento", "cargo", "abono", "n_polizas"])
    df["importe_poliza"] = pd.to_numeric(df["importe_poliza"], errors="coerce")
    agg = df.groupby("documento").agg(
        abono=("importe_poliza", "sum"),
        n_polizas=("Pl_Folio", "nunique"),
    ).reset_index()
    agg["cargo"] = 0.0
    return agg[["documento", "cargo", "abono", "n_polizas"]]
