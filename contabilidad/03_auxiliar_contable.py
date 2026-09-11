#!/usr/bin/env python3
"""Auxiliar contable de una cuenta, cruzado contra los CFDI del periodo.

La pregunta de negocio: tomo una cuenta contable, veo TODAS las líneas de
póliza que la afectaron en el periodo (cargo y abono), y busco dónde están
los huecos entre lo que dice la cuenta y lo que dicen los CFDI del periodo.

Ejemplo típico: la cuenta 1170.002 (IVA por acreditar) debería, en teoría,
moverse por el IVA de los CFDI de compra/gasto del mes. En la práctica NUNCA
cuadra exacto contra el mes, por razones reales que este reporte descompone
en vez de esconder:

  1. La cuenta se mueve por PÓLIZA (día), no por CFDI — trae de más lo que
     un CFDI de otro mes contabilizado este mes aportó, y de menos lo que un
     CFDI de este mes contabilizado el mes siguiente no aportó todavía.
  2. Hay CFDI del periodo sin ninguna etiqueta en `Comprobante_Digital` —
     nunca llegaron a una póliza.
  3. Hay líneas de la cuenta en pólizas de orígenes sin CFDI (ajustes,
     reclasificaciones, traspasos 1170.002 -> 1170.001 al pagar).

Es la MISMA cuenta que audita `02_auditoria_impuestos.py` para el bloque de
impuestos, pero aquí el foco es cualquier cuenta (inventario, proveedores,
lo que sea) y el drill-down de los huecos, no el semáforo de 3 vías.

Uso:
    python3 contabilidad/03_auxiliar_contable.py --periodo 2026-02 --top-cuentas 25
    python3 contabilidad/03_auxiliar_contable.py --periodo 2026-02 --cuenta 1170.002
    python3 contabilidad/03_auxiliar_contable.py --periodo 2026-02 --cuenta 2150.005 --csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "contabilidad"))

import pandas as pd  # noqa: E402

import cuentas_lib as cl  # noqa: E402
import poliza_lineas_lib as pll  # noqa: E402
import universo_lib as ul  # noqa: E402
from helpers_output import mostrar_tabla_err, resumen_err, console_err  # noqa: E402

TOL = 1.00

# Concepto SAT contra el que se cruza cada cuenta -- mismo mapeo que usa
# 02_auditoria_impuestos.py, pero indexado por prefijo de cuenta para poder
# ir de "cuenta que me pasaron" a "campo del CFDI que le corresponde".
CUENTA_A_CAMPO_SAT: list[tuple[str, str, str]] = [
    ("1170", "iva", "IVA acreditable (raw_sat.iva)"),
    ("2160", "iva", "IVA trasladado -- ojo, mismo campo SAT que acreditable "
                    "(recibidos no debería tocar 2160, es cuenta de EMITIDOS)"),
    ("2150.005", "ret_iva+ret_isr", "Retenciones por enterar (ret_iva + ret_isr)"),
    ("2150.002.006", "ret_isr", "ISR retenido intereses 20%"),
    ("1140", "base", "Inventario -- base fiscal (subtotal ajustado)"),
    ("6", "base", "Gasto -- base fiscal (subtotal ajustado)"),
]


def _periodo_rango(periodos: list[str]) -> tuple[pd.Timestamp, pd.Timestamp]:
    ini = pd.Timestamp(min(periodos) + "-01")
    fin = pd.Timestamp(max(periodos) + "-01") + pd.offsets.MonthBegin(1)
    return ini, fin


def listar_top_cuentas(ini: pd.Timestamp, fin: pd.Timestamp, top: int) -> pd.DataFrame:
    """Barrido rápido del auxiliar completo del periodo, para que el usuario
    elija qué cuenta auditar. Trae TODO Poliza_Detalle del rango -- caro para
    rangos largos, pensado para 1-2 meses."""
    console_err.print(f"[dim]Barriendo auxiliar completo {ini.date()} -> {fin.date()}"
                      f" para listar top cuentas…[/dim]")
    df = pll.auxiliar_cuenta(ini.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d"))
    df = cl.enriquecer(df)
    rank = (df.groupby(["cuenta", "cuenta_descripcion", "familia"])
            .agg(lineas=("importe", "size"), polizas=("poliza", "nunique"),
                 cargo=("importe", lambda s: s[df.loc[s.index, "tipo"] == "Cargo"].sum()),
                 abono=("importe", lambda s: s[df.loc[s.index, "tipo"] == "Abono"].sum()))
            .reset_index())
    rank["movimiento"] = (rank["cargo"] + rank["abono"]).round(2)
    rank["cargo"] = rank["cargo"].round(2)
    rank["abono"] = rank["abono"].round(2)
    return rank.sort_values("movimiento", ascending=False).head(top)


def campo_sat_de_cuenta(cuenta: str) -> tuple[str, str] | tuple[None, None]:
    for prefijo, campo, etiqueta in CUENTA_A_CAMPO_SAT:
        if cuenta.startswith(prefijo):
            return campo, etiqueta
    return None, None


def cruzar_contra_cfdi(campo: str, sat: pd.DataFrame) -> float:
    if campo == "ret_iva+ret_isr":
        return (pd.to_numeric(sat.get("ret_iva"), errors="coerce").fillna(0.0).sum()
                + pd.to_numeric(sat.get("ret_isr"), errors="coerce").fillna(0.0).sum())
    if campo == "base":
        desc = pd.to_numeric(sat.get("descuento"), errors="coerce").fillna(0.0)
        ieps = pd.to_numeric(sat.get("ieps_trasladado"), errors="coerce").fillna(0.0)
        loc_t = pd.to_numeric(sat.get("impuestos_locales_trasladados"), errors="coerce").fillna(0.0)
        loc_r = pd.to_numeric(sat.get("impuestos_locales_retenidos"), errors="coerce").fillna(0.0)
        sub = pd.to_numeric(sat["subtotal"], errors="coerce").fillna(0.0)
        return (sub - desc + ieps + loc_t - loc_r).sum()
    return pd.to_numeric(sat.get(campo), errors="coerce").fillna(0.0).sum()


def auditar_cuenta(cuenta: str, periodos: list[str]) -> None:
    ini, fin = _periodo_rango(periodos)
    console_err.print(f"\n[bold]Auxiliar de {cuenta}* — {ini.date()} a {fin.date()}[/bold]")

    lineas = pll.auxiliar_cuenta(ini.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d"),
                                  cuentas_like=[cuenta])
    if lineas.empty:
        console_err.print("[red]Sin movimiento en esa cuenta para el periodo.[/red]")
        return
    lineas = cl.enriquecer(lineas)

    cargo = lineas.loc[lineas["tipo"] == "Cargo", "importe"].sum()
    abono = lineas.loc[lineas["tipo"] == "Abono", "importe"].sum()
    resumen_err(lineas=len(lineas), polizas=lineas["poliza"].nunique(),
                cargo=f"${cargo:,.2f}", abono=f"${abono:,.2f}",
                neto=f"${cargo - abono:,.2f}")

    por_subcuenta = (lineas.groupby(["cuenta", "cuenta_descripcion", "tipo"])
                     .agg(lineas=("importe", "size"), monto=("importe", "sum"))
                     .reset_index().sort_values("monto", ascending=False))
    por_subcuenta["monto"] = por_subcuenta["monto"].round(2)
    mostrar_tabla_err(por_subcuenta, "Desglose por sub-cuenta", max_filas=20)

    por_config = (lineas.groupby(["configuracion", "config_descripcion", "tipo"])
                  .agg(lineas=("importe", "size"), monto=("importe", "sum"))
                  .reset_index().sort_values("monto", ascending=False))
    por_config["monto"] = por_config["monto"].round(2)
    mostrar_tabla_err(por_config, "Desglose por configuración de póliza", max_filas=15)

    por_dia = (lineas.assign(dia=lineas["fecha_poliza"].dt.date)
               .groupby(["dia", "tipo"])["importe"].sum().reset_index()
               .pivot(index="dia", columns="tipo", values="importe").fillna(0.0).reset_index())
    for c in ("Cargo", "Abono"):
        if c not in por_dia.columns:
            por_dia[c] = 0.0
    por_dia["neto"] = (por_dia["Cargo"] - por_dia["Abono"]).round(2)
    mostrar_tabla_err(por_dia.round(2), "Movimiento diario", max_filas=35)

    # --- Cruce contra CFDI ---
    campo, etiqueta = campo_sat_de_cuenta(cuenta)
    if campo is None:
        console_err.print("[yellow]Sin mapeo cuenta->campo SAT conocido para este "
                          "prefijo; solo se muestra el auxiliar, sin cruce.[/yellow]")
        return

    console_err.print(f"\n[bold]Cruce contra CFDI del periodo[/bold] — vía: {etiqueta}")
    sat, origenes = ul.universo(periodos=periodos)
    total_sat = cruzar_contra_cfdi(campo, sat)
    naturaleza = "Cargo" if cuenta.startswith(("1140", "1170", "6")) else "Abono"
    neto_cuenta = cargo - abono if naturaleza == "Cargo" else abono - cargo

    resumen_err(cfdi_total=len(sat), cfdi_valor_campo=f"${total_sat:,.2f}",
                cuenta_neta=f"${neto_cuenta:,.2f}",
                diferencia=f"${neto_cuenta - total_sat:,.2f}",
                pct=f"{abs(neto_cuenta - total_sat) / (abs(total_sat) or 1) * 100:.2f}%")

    # --- Descomposición del hueco ---
    en_mpro = sat["uuid"].isin(set(origenes["uuid"]))
    sat_sin_etiqueta = sat[~en_mpro]
    aporte_sin_etiqueta = cruzar_contra_cfdi(campo, sat_sin_etiqueta)

    tipos_no_ie = sat["tipo_comprobante"].isin(ul.TIPOS_CON_VALOR)
    ajuste_conciliacion = pd.DataFrame([
        {"paso": "Total en la cuenta (neto, alcance mes contable)", "monto": round(neto_cuenta, 2)},
        {"paso": f"(-) CFDI del periodo, vía {etiqueta}", "monto": round(-total_sat, 2)},
        {"paso": "  de los cuales: CFDI SIN etiqueta en Comprobante_Digital "
                 f"({(~en_mpro).sum()} CFDI)",
         "monto": round(-aporte_sin_etiqueta, 2)},
        {"paso": "Diferencia residual (desfase temporal + ajustes/traspasos "
                 "sin CFDI propio)", "monto": round(neto_cuenta - total_sat + 0, 2)},
    ])
    mostrar_tabla_err(ajuste_conciliacion, "De la cuenta al CFDI — descomposición del hueco",
                      max_filas=10)

    if (~en_mpro).sum():
        console_err.print(f"[yellow]{(~en_mpro).sum()} CFDI del periodo no tienen "
                          "ninguna etiqueta en mpro -- no pudieron mover esta cuenta "
                          "todavía.[/yellow]")
        muestra = sat_sin_etiqueta[["uuid", "fecha", "rfc_emisor", "nombre_emisor",
                                     "subtotal", "iva"]].head(10)
        mostrar_tabla_err(muestra, "Muestra de CFDI sin etiqueta (hasta 10)", max_filas=10)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--periodo")
    ap.add_argument("--periodos", nargs="+")
    ap.add_argument("--cuenta", action="append", help="prefijo de cuenta a auditar (repetible)")
    ap.add_argument("--top-cuentas", type=int, help="listar las N cuentas con más movimiento")
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()

    periodos = args.periodos or ([args.periodo] if args.periodo else None)
    if not periodos:
        ap.error("hay que pasar --periodo o --periodos")
    ini, fin = _periodo_rango(periodos)

    if args.top_cuentas and not args.cuenta:
        rank = listar_top_cuentas(ini, fin, args.top_cuentas)
        mostrar_tabla_err(rank, f"Top {args.top_cuentas} cuentas con más movimiento — "
                          f"{ini.date()} a {fin.date()}", max_filas=args.top_cuentas)
        if args.csv:
            print("--- CSV_PARA_CLAUDE: top_cuentas ---")
            print(rank.to_csv(index=False))
        return

    if not args.cuenta:
        ap.error("hay que pasar --cuenta <prefijo> (repetible) o --top-cuentas N")

    for cuenta in args.cuenta:
        auditar_cuenta(cuenta, periodos)


if __name__ == "__main__":
    main()
