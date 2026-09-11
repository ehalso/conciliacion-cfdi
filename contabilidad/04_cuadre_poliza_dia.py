#!/usr/bin/env python3
"""Cuadre POR DÍA de la póliza contra los CFDI relacionados — recibidos y emitidos.

Motivación (confirmada en vivo 2026-09-11): varias pólizas de mpro consolidan
TODO el día en un solo asiento por configuración — no hay manera de aislar
"la línea de este documento" para el IVA/proveedores en COMPRA, ni para
prácticamente ninguna línea en la póliza de INGRESO de VENTA
(`docs/hallazgos.md` punto 28: solo 19 de 2,191 facturas de enero 2026 son
aislables por `Pd_Referencia`). Donde no se puede cuadrar por documento, sí
se puede cuadrar por DÍA: la póliza es, por construcción, el agregado del
día — así que compararla contra la suma de los CFDI relacionados de ese
mismo día es una comparación legítima aunque el detalle no lo sea.

## Lado RECIBIDOS

Grano: **día**. Para cada día del periodo:
  - PÓLIZA: cargo a cuentas base (inventario `1140*` + gasto `6*`), cargo a
    IVA por acreditar (`1170*`), abono a retenciones (`2150.002*`/`2150.005*`),
    abono a proveedores (`2110*`) — de TODAS las pólizas que tocan al menos
    un documento con CFDI conocido ese día.
  - CFDI: base fiscal, IVA, retenciones y total de los CFDI cuyo documento
    quedó posteado en una póliza de ese día (deduplicados por UUID dentro
    del día — un CFDI repartido en dos pólizas del MISMO día no se
    duplica; si aparece en pólizas de días distintos, sí se cuenta en cada
    uno, caso raro, documentado como límite conocido).

El lado póliza incluye TODAS las líneas de las pólizas tocadas, no solo las
de los documentos con CFDI — así que un exceso de cargo contra el CFDI es
señal real de "algo se contabilizó ese día sin CFDI conocido" (otro
documento del mismo origen/día sin factura electrónica ligada), no ruido.

## Lado EMITIDOS (VENTA)

La póliza de ingreso de VENTA (config con descripción "VENTAS…", que carga
Clientes y abona Ventas + IVA Trasladado) se postea consolidada por
sucursal/día y su Cargo/Abono casi nunca lleva `Pd_Referencia` al documento
— por diseño, no por hueco (`docs/hallazgos.md` punto 28). Aquí el cuadre
por día es la ÚNICA vía razonable, y no hace falta ligar documento a
documento: se suman TODAS las líneas de la póliza de VENTA del día
(excluyendo la póliza gemela de COSTO DE VENTA, que es otro asiento) contra
TODOS los CFDI emitidos tipo Ingreso de ese mismo día de `fecha_emision`.

`raw_sat.cfdi_emitidos` solo cubre 2025-09..2026-02 (más completo en
2026-01) — se valida la cobertura antes de correr y se avisa si el periodo
pedido cae fuera.

Uso:
    python3 contabilidad/04_cuadre_poliza_dia.py --periodo 2026-02 --lado recibidos
    python3 contabilidad/04_cuadre_poliza_dia.py --periodo 2026-01 --lado emitidos
    python3 contabilidad/04_cuadre_poliza_dia.py --periodo 2026-02 --lado ambos --csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "contabilidad"))

import pandas as pd  # noqa: E402

from bridge_client import run_query, rows_as_dicts, sql_quote  # noqa: E402
from config import MPRO_TARGET  # noqa: E402
import cuentas_lib as cl  # noqa: E402
import poliza_lineas_lib as pll  # noqa: E402
import universo_lib as ul  # noqa: E402
from helpers_output import mostrar_tabla_err, resumen_err, console_err  # noqa: E402

TOL_PCT_VERDE = 0.1
TOL_PCT_AMARILLO = 1.0


def semaforo(pct: float) -> str:
    if pd.isna(pct):
        return "sin CFDI"
    if pct <= TOL_PCT_VERDE:
        return "verde"
    if pct <= TOL_PCT_AMARILLO:
        return "amarillo"
    return "rojo"


# =============================================================================
# RECIBIDOS
# =============================================================================

def cuadre_recibidos(periodos: list[str]) -> pd.DataFrame:
    console_err.print("[bold]Recibidos — armando universo…[/bold]")
    sat, origenes = ul.universo(periodos=periodos)
    console_err.print(f"  {len(sat)} CFDI I/E, {origenes['uuid'].nunique()} con etiqueta")

    ini = pd.Timestamp(min(periodos) + "-01")
    fin = pd.Timestamp(max(periodos) + "-01") + pd.offsets.MonthBegin(1)
    # Ventana de gracia para captura tardía real (documento del último día del
    # mes contabilizado unos días después) sin abrir la puerta a folios
    # viejos reciclados.
    ventana_ini, ventana_fin = ini - pd.Timedelta(days=10), fin + pd.Timedelta(days=10)

    pol_maps = []
    for origen in ul.origenes_con_cargo(origenes):
        docs = origenes.loc[origenes["origen"] == origen, "documento_real"].dropna().unique().tolist()
        if not docs:
            continue
        pm = pll.polizas_de_documentos(origen, docs)
        if not pm.empty:
            pol_maps.append(pm)
    pol_map = pd.concat(pol_maps, ignore_index=True) if pol_maps else pd.DataFrame()
    if pol_map.empty:
        console_err.print("[red]Sin pólizas encontradas.[/red]")
        return pd.DataFrame()

    # Reciclaje de folio (docs/hallazgos.md, calidad de dato): un folio corto
    # de 10 caracteres puede colisionar con una póliza de un año totalmente
    # distinto para el mismo origen. Sin validar la fecha, un CFDI chico de
    # este mes "hereda" el cargo de una póliza vieja no relacionada — se vio
    # en vivo (2026-09-11): 12+ CFDI de <$100 emparejados con cargos de
    # $10K-$40K de otros años. Se descarta cualquier par fuera de la ventana
    # del periodo ± 10 días y se reporta cuántos se cayeron.
    antes = pol_map["poliza"].nunique()
    pol_map = pol_map[pol_map["fecha_poliza"].between(ventana_ini, ventana_fin)]
    despues = pol_map["poliza"].nunique()
    if antes != despues:
        console_err.print(f"[yellow]{antes - despues} pólizas descartadas por caer fuera "
                          f"de {ventana_ini.date()}..{ventana_fin.date()} — probable "
                          "colisión de folio reciclado, no captura tardía real.[/yellow]")
    if pol_map.empty:
        console_err.print("[red]Sin pólizas dentro de la ventana del periodo.[/red]")
        return pd.DataFrame()

    # uuid -> (día, configuración) de la póliza. Grano (día, config) y no
    # solo día: mezclar en un mismo renglón GASTO_REGISTRO, COMPRA y
    # CUENTA_X_PAGAR del mismo día (escalas y mecanismos de captura
    # distintos) resultó, en la práctica, en diferencias de cientos de por
    # ciento sin ningún significado — cada configuración es un mecanismo de
    # póliza propio y aislarla da una señal limpia. Puede haber más de un
    # (día, config) por uuid si el CFDI se repartió entre documentos de
    # configs/fechas distintas (caso raro) — el CFDI se cuenta completo en
    # cada uno, documentado como límite conocido.
    liga = origenes.merge(pol_map, left_on=["origen", "documento_real"],
                          right_on=["origen", "documento"], how="inner")
    liga["dia"] = liga["fecha_poliza"].dt.date
    uuid_por_grupo = liga[["uuid", "dia", "configuracion", "config_descripcion"]].drop_duplicates()

    folios = pol_map["poliza"].dropna().unique().tolist()
    console_err.print(f"  {len(folios)} pólizas distintas -> trayendo TODAS sus líneas…")
    lineas = pll.lineas_de_polizas(folios)
    lineas["dia"] = lineas["fecha_poliza"].dt.date
    lineas = cl.enriquecer(lineas)

    # Base = a dónde va el cargo que SÍ corresponde al CFDI: inventario
    # (1140), gasto (6*) y activo fijo (1210 — confirmado en vivo 2026-09-11:
    # sin 1210, CUENTA_X_PAGAR de compra de activo fijo aparecía como "cargo
    # $0 / CFDI $8.7M", 100% de diferencia, cuando en realidad el cargo SÍ
    # estaba, solo que en la cuenta equivocada para este filtro).
    es_base = lineas["cuenta"].str.startswith(("1140", "6", "1210"))
    es_iva = lineas["cuenta"].str.startswith("1170")
    es_ret = lineas["cuenta"].str.startswith(("2150.002", "2150.005"))
    es_prov = lineas["cuenta"].str.startswith("2110")
    GRUPO = ["dia", "configuracion", "config_descripcion"]

    def neto(mask: pd.Series, tipo_positivo: str) -> pd.Series:
        sub = lineas[mask]
        pos = sub[sub["tipo"] == tipo_positivo].groupby(GRUPO)["importe"].sum()
        neg_tipo = "Abono" if tipo_positivo == "Cargo" else "Cargo"
        neg = sub[sub["tipo"] == neg_tipo].groupby(GRUPO)["importe"].sum()
        return pos.sub(neg, fill_value=0.0)

    pol_dia = pd.DataFrame({
        "cargo_base": neto(es_base, "Cargo"),
        "cargo_iva": neto(es_iva, "Cargo"),
        "abono_retenciones": neto(es_ret, "Abono"),
        "abono_proveedores": neto(es_prov, "Abono"),
    }).fillna(0.0)

    # CFDI-side por (día, config), dedup por uuid dentro del grupo.
    sat_dia = sat.merge(uuid_por_grupo, on="uuid", how="inner")
    base_fiscal = (sat_dia["subtotal"] - sat_dia["descuento"] + sat_dia["ieps_trasladado"]
                   + sat_dia["impuestos_locales_trasladados"] - sat_dia["impuestos_locales_retenidos"])
    sat_dia = sat_dia.assign(base_fiscal=base_fiscal,
                              ret_total=sat_dia["ret_iva"] + sat_dia["ret_isr"])
    cfdi_dia = sat_dia.groupby(GRUPO).agg(
        cfdi_base=("base_fiscal", "sum"), cfdi_iva=("iva", "sum"),
        cfdi_ret=("ret_total", "sum"), cfdi_total=("total", "sum"),
        n_cfdi=("uuid", "nunique")).fillna(0.0)

    out = pol_dia.join(cfdi_dia, how="outer").fillna(0.0).sort_index()
    out["dif_base"] = (out["cargo_base"] - out["cfdi_base"]).round(2)
    out["pct_base"] = (out["dif_base"].abs() / out["cfdi_base"].replace(0, float("nan")).abs() * 100)
    out["dif_iva"] = (out["cargo_iva"] - out["cfdi_iva"]).round(2)
    out["pct_iva"] = (out["dif_iva"].abs() / out["cfdi_iva"].replace(0, float("nan")).abs() * 100)
    out["semaforo_base"] = out["pct_base"].map(semaforo)
    out["semaforo_iva"] = out["pct_iva"].map(semaforo)
    out = out.reset_index()
    for c in out.select_dtypes("float"):
        out[c] = out[c].round(2)
    return out


def drill_down_dia_recibidos(dia: str, periodos: list[str]) -> None:
    """Toma un día concreto y muestra pólizas + líneas + CFDI relacionados."""
    console_err.print(f"\n[bold]Drill-down recibidos — {dia}[/bold]")
    sat, origenes = ul.universo(periodos=periodos)
    pol_maps = []
    for origen in ul.origenes_con_cargo(origenes):
        docs = origenes.loc[origenes["origen"] == origen, "documento_real"].dropna().unique().tolist()
        if docs:
            pm = pll.polizas_de_documentos(origen, docs)
            if not pm.empty:
                pol_maps.append(pm)
    pol_map = pd.concat(pol_maps, ignore_index=True)
    pol_map["dia"] = pol_map["fecha_poliza"].dt.date
    pol_dia = pol_map[pol_map["dia"].astype(str) == dia]
    if pol_dia.empty:
        console_err.print("[red]Sin pólizas ese día.[/red]")
        return
    mostrar_tabla_err(pol_dia[["origen", "documento", "poliza", "configuracion",
                                "config_descripcion"]].drop_duplicates(),
                      f"Pólizas tocadas el {dia}", max_filas=30)

    lineas = pll.lineas_de_polizas(pol_dia["poliza"].unique().tolist())
    lineas = cl.enriquecer(lineas)
    mostrar_tabla_err(lineas[["poliza", "cuenta", "cuenta_descripcion", "familia",
                              "tipo", "importe", "referencia"]].sort_values(
                          ["poliza", "pd_id"] if "pd_id" in lineas else ["poliza"]),
                      "Todas las líneas de esas pólizas", max_filas=40)

    uuids_dia = origenes.merge(pol_dia[["origen", "documento"]].rename(
        columns={"documento": "documento_real"}), on=["origen", "documento_real"])["uuid"].unique()
    cfdi_dia = sat[sat["uuid"].isin(uuids_dia)]
    mostrar_tabla_err(cfdi_dia[["uuid", "rfc_emisor", "nombre_emisor", "subtotal", "iva", "total"]],
                      f"CFDI relacionados a esas pólizas ({len(cfdi_dia)})", max_filas=30)


# =============================================================================
# EMITIDOS (VENTA)
# =============================================================================

def _cobertura_emitidos() -> tuple[str, str]:
    sql = "SELECT MIN(periodo) AS mn, MAX(periodo) AS mx FROM raw_sat.cfdi_emitidos"
    r = rows_as_dicts(run_query("postgres_dw", sql))[0]
    return r["mn"], r["mx"]


def poliza_venta_por_dia(fecha_ini: str, fecha_fin: str) -> pd.DataFrame:
    """Todas las líneas de la póliza de INGRESO de VENTA (excluye la póliza
    gemela de COSTO DE VENTA), agrupadas por día.

    NO se une `Poliza_Control`: una póliza de VENTA consolida decenas de
    documentos (`Pc_Documento`), así que unir `Poliza_Detalle` por `Pl_Folio`
    a través de `Poliza_Control` sin más multiplica cada línea una vez por
    cada documento de la póliza (fan-out) — confirmado en vivo 2026-09-11,
    daba cargos a Clientes 500x el total real de los CFDI. `Poliza_Configuracion`
    ya identifica el origen (`Pc_Tabla='Venta'`) sin pasar por `Poliza_Control`.
    """
    sql = (
        "SELECT p.Pl_Fecha AS fecha_poliza, pd.Cc_Cve_Cuenta_Contable AS cuenta, "
        "pd.Pd_Tipo AS pd_tipo, pd.Pd_Importe AS importe "
        "FROM Poliza p "
        "JOIN Poliza_Configuracion pcf ON pcf.Pc_Cve_Poliza_Configuracion = p.Pl_Configuracion "
        "JOIN Poliza_Detalle pd ON pd.Pl_Folio = p.Pl_Folio "
        "WHERE UPPER(pcf.Pc_Tabla) = 'VENTA' AND p.Es_Cve_Estado <> 'CA' "
        "AND UPPER(pcf.Pc_Descripcion) NOT LIKE '%COSTO DE VENTA%' "
        "AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '10[1-6]00%' "
        f"AND p.Pl_Fecha >= '{fecha_ini}' AND p.Pl_Fecha < '{fecha_fin}'"
    )
    df = pd.DataFrame(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    if df.empty:
        return df
    df["importe"] = pd.to_numeric(df["importe"], errors="coerce").fillna(0.0)
    df["tipo"] = df["pd_tipo"].map({1: "Cargo", 2: "Abono"})
    df["dia"] = pd.to_datetime(df["fecha_poliza"]).dt.date
    df["familia"] = df["cuenta"].map(cl.familia)
    return df


def cuadre_emitidos(periodos: list[str]) -> pd.DataFrame:
    mn, mx = _cobertura_emitidos()
    console_err.print(f"[bold]Emitidos — cobertura raw_sat.cfdi_emitidos: {mn} a {mx}[/bold]")
    fuera = [p for p in periodos if not (mn <= p <= mx)]
    if fuera:
        console_err.print(f"[yellow]Periodos fuera de cobertura, se omiten: {fuera}[/yellow]")
    periodos = [p for p in periodos if mn <= p <= mx]
    if not periodos:
        console_err.print("[red]Ningún periodo pedido cae dentro de la cobertura.[/red]")
        return pd.DataFrame()

    sat, origenes = ul.universo(periodos=periodos, tabla="cfdi_emitidos")
    sat = sat[sat["tipo_comprobante"] == "I"].copy()
    console_err.print(f"  {len(sat)} CFDI emitidos tipo Ingreso")

    ini = pd.Timestamp(min(periodos) + "-01")
    fin = pd.Timestamp(max(periodos) + "-01") + pd.offsets.MonthBegin(1)
    pol = poliza_venta_por_dia(ini.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d"))
    console_err.print(f"  {len(pol)} líneas en pólizas VENTA (ingreso) del rango")

    if pol.empty:
        return pd.DataFrame()

    def neto(df, mask, tipo_pos):
        sub = df[mask]
        pos = sub[sub["tipo"] == tipo_pos].groupby("dia")["importe"].sum()
        neg_tipo = "Abono" if tipo_pos == "Cargo" else "Cargo"
        neg = sub[sub["tipo"] == neg_tipo].groupby("dia")["importe"].sum()
        return pos.sub(neg, fill_value=0.0)

    es_cli = pol["cuenta"].str.startswith("1120")
    es_ventas = pol["cuenta"].str.startswith("4100")
    es_ivat = pol["cuenta"].str.startswith("2160")

    pol_dia = pd.DataFrame({
        "cargo_clientes": neto(pol, es_cli, "Cargo"),
        "abono_ventas": neto(pol, es_ventas, "Abono"),
        "abono_iva_trasladado": neto(pol, es_ivat, "Abono"),
    }).fillna(0.0)

    sat["dia"] = pd.to_datetime(sat["fecha"]).dt.date
    cfdi_dia = sat.groupby("dia").agg(
        cfdi_total=("total", "sum"), cfdi_subtotal=("subtotal", "sum"),
        cfdi_iva=("iva", "sum"), n_cfdi=("uuid", "nunique"))

    out = pol_dia.join(cfdi_dia, how="outer").fillna(0.0).sort_index()
    out["dif_total"] = (out["cargo_clientes"] - out["cfdi_total"]).round(2)
    out["pct_total"] = (out["dif_total"].abs() / out["cfdi_total"].replace(0, float("nan")).abs() * 100)
    out["dif_subtotal"] = (out["abono_ventas"] - out["cfdi_subtotal"]).round(2)
    out["dif_iva"] = (out["abono_iva_trasladado"] - out["cfdi_iva"]).round(2)
    out["semaforo_total"] = out["pct_total"].map(semaforo)
    out = out.reset_index().rename(columns={"index": "dia"})
    for c in out.select_dtypes("float"):
        out[c] = out[c].round(2)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--periodo", required=True)
    ap.add_argument("--lado", choices=["recibidos", "emitidos", "ambos"], default="ambos")
    ap.add_argument("--drill-down-dia", help="fecha YYYY-MM-DD para ver el detalle (solo recibidos)")
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()
    periodos = [args.periodo]

    if args.drill_down_dia:
        drill_down_dia_recibidos(args.drill_down_dia, periodos)
        return

    if args.lado in ("recibidos", "ambos"):
        rec = cuadre_recibidos(periodos)
        if not rec.empty:
            resumen_err(dias=len(rec),
                        verdes=int((rec["semaforo_base"] == "verde").sum()),
                        amarillos=int((rec["semaforo_base"] == "amarillo").sum()),
                        rojos=int((rec["semaforo_base"] == "rojo").sum()))
            cols_base = ["dia", "configuracion", "config_descripcion", "n_cfdi",
                         "cargo_base", "cfdi_base", "dif_base", "pct_base", "semaforo_base"]
            mostrar_tabla_err(rec[cols_base].sort_values("dif_base", key=abs, ascending=False),
                              "RECIBIDOS — cuadre por (día, config), base (inventario+gasto), "
                              "peores primero", max_filas=35)
            cols_iva = ["dia", "configuracion", "cargo_iva", "cfdi_iva", "dif_iva",
                        "pct_iva", "semaforo_iva"]
            mostrar_tabla_err(rec[cols_iva].sort_values("dif_iva", key=abs, ascending=False),
                              "RECIBIDOS — cuadre por (día, config), IVA por acreditar, "
                              "peores primero", max_filas=35)
            resumen_diario = (rec.groupby("dia")
                              .agg(cargo_base=("cargo_base", "sum"), cfdi_base=("cfdi_base", "sum"),
                                   n_cfdi=("n_cfdi", "sum")).reset_index())
            resumen_diario["dif_base"] = (resumen_diario["cargo_base"] - resumen_diario["cfdi_base"]).round(2)
            resumen_diario["pct_base"] = (resumen_diario["dif_base"].abs()
                                          / resumen_diario["cfdi_base"].replace(0, float("nan")).abs() * 100).round(2)
            mostrar_tabla_err(resumen_diario, "RECIBIDOS — roll-up por día (todas las configs sumadas)",
                              max_filas=35)
            tot_cargo, tot_cfdi = rec["cargo_base"].sum(), rec["cfdi_base"].sum()
            resumen_err(total_periodo_cargo_base=f"${tot_cargo:,.2f}",
                        total_periodo_cfdi_base=f"${tot_cfdi:,.2f}",
                        pct_dif=f"{abs(tot_cargo - tot_cfdi) / (tot_cfdi or 1) * 100:.2f}%")
            peor = rec.loc[rec["dif_base"].abs().idxmax()]
            console_err.print(f"[yellow]Peor (día,config) en base: {peor['dia']} / "
                              f"{peor['configuracion']} ({peor['config_descripcion']}) — "
                              f"diferencia ${peor['dif_base']:,.2f} ({peor['pct_base']:.2f}%). "
                              f"Usar --drill-down-dia {peor['dia']} para investigar.[/yellow]")
            if args.csv:
                print("--- CSV_PARA_CLAUDE: cuadre_dia_recibidos ---")
                print(rec.to_csv(index=False))

    if args.lado in ("emitidos", "ambos"):
        emi = cuadre_emitidos(periodos)
        if not emi.empty:
            resumen_err(dias=len(emi), verdes=int((emi["semaforo_total"] == "verde").sum()),
                        amarillos=int((emi["semaforo_total"] == "amarillo").sum()),
                        rojos=int((emi["semaforo_total"] == "rojo").sum()))
            mostrar_tabla_err(emi[["dia", "n_cfdi", "cargo_clientes", "cfdi_total", "dif_total",
                                    "pct_total", "semaforo_total"]],
                              "EMITIDOS — cuadre diario, Clientes vs Total CFDI", max_filas=35)
            mostrar_tabla_err(emi[["dia", "abono_ventas", "cfdi_subtotal", "dif_subtotal",
                                    "abono_iva_trasladado", "cfdi_iva", "dif_iva"]],
                              "EMITIDOS — Ventas/IVA trasladado vs CFDI", max_filas=35)
            # El día individual es ruidoso por desfase de 1-2 días entre
            # Pl_Fecha (cuándo se contabiliza) y fecha_emision (cuándo se
            # timbra) -- confirmado en vivo: día por día hay diferencias de
            # hasta 400%, pero el MES completo cierra fino. Es la señal real:
            # no hay hueco de importe, hay corrimiento de fecha.
            tot_cli, tot_cfdi = emi["cargo_clientes"].sum(), emi["cfdi_total"].sum()
            tot_vt, tot_sub = emi["abono_ventas"].sum(), emi["cfdi_subtotal"].sum()
            tot_iva_p, tot_iva_c = emi["abono_iva_trasladado"].sum(), emi["cfdi_iva"].sum()
            resumen_err(
                _nota="el ruido diario es desfase de fecha (Pl_Fecha vs fecha_emision), "
                      "no un hueco de importe -- ver el total del mes:",
                total_mes_cargo_clientes=f"${tot_cli:,.2f}", total_mes_cfdi_total=f"${tot_cfdi:,.2f}",
                pct_dif=f"{abs(tot_cli - tot_cfdi) / tot_cfdi * 100:.2f}%")
            resumen_err(total_mes_abono_ventas=f"${tot_vt:,.2f}", total_mes_cfdi_subtotal=f"${tot_sub:,.2f}",
                        pct_dif_ventas=f"{abs(tot_vt - tot_sub) / tot_sub * 100:.2f}%",
                        total_mes_iva_trasladado=f"${tot_iva_p:,.2f}", total_mes_cfdi_iva=f"${tot_iva_c:,.2f}",
                        pct_dif_iva=f"{abs(tot_iva_p - tot_iva_c) / tot_iva_c * 100:.2f}%")
            if args.csv:
                print("--- CSV_PARA_CLAUDE: cuadre_dia_emitidos ---")
                print(emi.to_csv(index=False))


if __name__ == "__main__":
    main()
