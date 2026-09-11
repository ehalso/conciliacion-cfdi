#!/usr/bin/env python3
"""Auditoría de impuestos en TRES vías: XML del SAT → documento mpro → cuenta contable.

El repo ya concilia las dos primeras vías a nivel documento
(`recibidos/nivel_documento/03_conciliacion_xml_vs_mpro_impuestos.py`: el XML
contra las tablas `*_Impuesto` de cada módulo). Lo que faltaba es la tercera:
**lo que el documento capturó, ¿llegó a la póliza, y a qué cuenta?** Es la
vía que importa para la declaración, porque el IVA que se acredita ante el
SAT es el que está en la balanza, no el que está en el documento operativo.

    vía 1  raw_sat.cfdi_recibidos        iva / ret_iva / ret_isr / ieps
    vía 2  Gasto_Registro_Impuesto, Compra_Total_Impuesto, ...   (por documento)
    vía 3  Poliza_Detalle                cuentas 1170.* / 2150.* / 2160.*

El mapeo impuesto→cuenta NO se infiere: está en `Impuesto.Im_Cuenta_Contable`,
que es la misma columna que el motor de pólizas usa para decidir a dónde
mandar cada impuesto (`Poliza_Configuracion_Detalle`, renglones 0100/0110:
cargo si `Im_Tasa >= 0`, abono si es negativa). Ver `cuentas_lib`.

## Por qué la vía 3 NO es atribuible por CFDI — y qué se hace al respecto

Confirmado en vivo (2026-09-11): dentro de una misma póliza, el cargo a
inventario/gasto lleva `Pd_Referencia` = folio del documento, pero **la línea
de IVA no**. Según el origen trae la FECHA del día (COMPRA), la referencia
externa del proveedor (CUENTA_X_PAGAR), o viene vacía (GASTO_REGISTRO,
COMPRA_INDIRECTO). Solo NOTA_CREDITO_PROVEEDOR referencia el folio.

Por eso la vía 3 solo cierra en AGREGADO, y el reporte ofrece dos alcances,
cada uno con un sesgo distinto y conocido:

  --alcance universo  (default)
      Solo las pólizas que amparan documentos de los CFDI del periodo.
      Sesgo: la póliza ampara TAMBIÉN otros documentos (de otros CFDI o de
      otros meses), así que el contable trae de MÁS. Se reporta ese exceso.

  --alcance contable
      Todas las líneas de cuentas de impuesto con `Pl_Fecha` en el mes,
      vengan de donde vengan. Es el número que ve Contabilidad en la balanza.
      Sesgo: desfase temporal — un CFDI de enero contabilizado en febrero
      cuenta aquí y no en la vía 1 del mes.

Ninguno de los dos es "el bueno": la diferencia entre ambos ES el hallazgo.

Uso:
    python3 contabilidad/02_auditoria_impuestos.py --periodo 2026-02
    python3 contabilidad/02_auditoria_impuestos.py --periodo 2026-02 --alcance contable --csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "contabilidad"))
sys.path.insert(0, str(RAIZ / "recibidos" / "nivel_documento"))

import pandas as pd  # noqa: E402

import cuentas_lib as cl  # noqa: E402
import poliza_lineas_lib as pll  # noqa: E402
import universo_lib as ul  # noqa: E402
from helpers_output import mostrar_tabla_err, resumen_err, console_err  # noqa: E402

# Reutiliza el extractor ya validado del lado documento (vía 2) en vez de
# reescribir las 6 consultas por módulo. Ver su docstring para el detalle de
# cada tabla y los gotchas (retenciones en negativo, impuestos locales que
# mpro suma dentro de su clave de IVA, módulos sin tabla de impuestos).
from conciliacion_xml_lib import impuestos_mpro  # noqa: E402

TOL = 1.00

# Conceptos auditados: (etiqueta, campo raw_sat, columna de impuestos_mpro,
# prefijos de cuenta contable, naturaleza contable esperada).
CONCEPTOS = [
    ("IVA acreditable", "iva", "MPRO_IVA_TRASLADADO",
     ["1170.001", "1170.002"], "Cargo"),
    ("IVA retenido a proveedor", "ret_iva", "MPRO_RET_IVA",
     ["2150.005.003", "2150.005.004", "2150.005.005", "2150.005.006",
      "2150.002.007", "2150.002.008", "2150.002.009", "2150.002.010"], "Abono"),
    ("ISR retenido a proveedor", "ret_isr", "MPRO_RET_ISR",
     ["2150.005.001", "2150.005.002", "2150.005.007", "2150.002.001",
      "2150.002.002", "2150.002.003", "2150.002.004", "2150.002.005",
      "2150.002.006", "2150.002.011"], "Abono"),
    # IEPS: mpro NO tiene ninguna clave de `Impuesto` con Im_Codigo_SAT='003'
    # — no sabe registrarlo a nivel comprobante, así que lo manda a la BASE
    # del gasto. No hay cuenta contable de IEPS y el cruce contable no aplica.
    ("IEPS trasladado", "ieps_trasladado", "MPRO_IEPS_TRASLADADO", [], "(va a la base)"),
]


def lado_xml(sat: pd.DataFrame) -> pd.Series:
    """Vía 1 — lo que dicen los CFDI del periodo."""
    out = {}
    for etiqueta, campo, _, _, _ in CONCEPTOS:
        out[etiqueta] = pd.to_numeric(sat.get(campo), errors="coerce").fillna(0.0).sum()
    out["Impuestos locales trasladados"] = pd.to_numeric(
        sat.get("impuestos_locales_trasladados"), errors="coerce").fillna(0.0).sum()
    return pd.Series(out, name="XML_SAT").round(2)


def lado_documento(origenes: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """Vía 2 — lo que capturó el documento operativo de mpro."""
    folios_por_origen: dict[str, list[str]] = {}
    for origen, sub in origenes.groupby("origen_up"):
        folios_por_origen[origen] = sub["documento_real"].dropna().unique().tolist()
    piv, det = impuestos_mpro(folios_por_origen=folios_por_origen)
    out = {}
    for etiqueta, _, col_mpro, _, _ in CONCEPTOS:
        out[etiqueta] = float(piv[col_mpro].sum()) if col_mpro in piv.columns else 0.0
    out["Impuestos locales trasladados"] = float("nan")  # mpro los suma dentro del IVA
    return pd.Series(out, name="DOCUMENTO_mpro").round(2), piv


def lado_contable(lineas: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """Vía 3 — lo que quedó posteado en la póliza, por cuenta contable."""
    out, detalle = {}, []
    for etiqueta, _, _, prefijos, naturaleza in CONCEPTOS:
        if not prefijos:
            out[etiqueta] = float("nan")
            continue
        m = lineas["cuenta"].str.startswith(tuple(prefijos))
        sub = lineas[m]
        # El signo contable: un cargo a IVA acreditable suma, un abono
        # (devolución / nota de crédito) resta. Mismo criterio del lado
        # inverso para las retenciones, que son de naturaleza acreedora.
        if naturaleza == "Cargo":
            neto = sub.loc[sub["tipo"] == "Cargo", "importe"].sum() - \
                   sub.loc[sub["tipo"] == "Abono", "importe"].sum()
        else:
            neto = sub.loc[sub["tipo"] == "Abono", "importe"].sum() - \
                   sub.loc[sub["tipo"] == "Cargo", "importe"].sum()
        out[etiqueta] = neto
        if not sub.empty:
            d = (sub.groupby(["cuenta", "cuenta_descripcion", "tipo"])
                 .agg(lineas=("importe", "size"), polizas=("poliza", "nunique"),
                      monto=("importe", "sum")).reset_index())
            d.insert(0, "concepto", etiqueta)
            detalle.append(d)
    out["Impuestos locales trasladados"] = float("nan")
    det = pd.concat(detalle, ignore_index=True) if detalle else pd.DataFrame()
    return pd.Series(out, name="CONTABLE_poliza").round(2), det


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--periodo", help="periodo YYYY-MM")
    ap.add_argument("--periodos", nargs="+")
    ap.add_argument("--alcance", choices=["universo", "contable"], default="universo",
                    help="universo: solo pólizas de los CFDI del periodo. "
                         "contable: todo lo posteado en el mes (la balanza).")
    ap.add_argument("--csv", action="store_true")
    args = ap.parse_args()

    periodos = args.periodos or ([args.periodo] if args.periodo else None)
    if not periodos:
        ap.error("hay que pasar --periodo o --periodos")

    console_err.print(f"[bold]Auditoría de impuestos — {', '.join(periodos)} "
                      f"(alcance: {args.alcance})[/bold]")

    sat, origenes = ul.universo(periodos=periodos)
    console_err.print(f"  vía 1 · {len(sat)} CFDI tipo I/E, "
                      f"{origenes['uuid'].nunique()} con etiqueta en mpro")

    xml = lado_xml(sat)
    # La vía 2 y la vía 3 solo pueden ver los CFDI que SÍ llegaron a mpro.
    # Comparar contra el XML de todos sería comparar universos distintos, así
    # que se acota la vía 1 a los mismos CFDI y el faltante se reporta aparte.
    sat_en_mpro = sat[sat["uuid"].isin(set(origenes["uuid"]))]
    xml_en_mpro = lado_xml(sat_en_mpro).rename("XML_SAT_en_mpro")

    doc, piv = lado_documento(origenes)
    console_err.print(f"  vía 2 · {len(piv)} documentos con tabla de impuestos")

    cuentas_impuesto = sorted({p for _, _, _, pres, _ in CONCEPTOS for p in pres})
    if args.alcance == "contable":
        ini = pd.Timestamp(min(periodos) + "-01")
        fin = (pd.Timestamp(max(periodos) + "-01") + pd.offsets.MonthBegin(1))
        console_err.print(f"  vía 3 · auxiliar contable {ini.date()} → {fin.date()}…")
        lineas = pll.auxiliar_cuenta(ini.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d"),
                                      cuentas_like=cuentas_impuesto)
    else:
        polizas = []
        for origen in ul.origenes_con_cargo(origenes):
            docs = origenes.loc[origenes["origen"] == origen, "documento_real"].dropna().unique().tolist()
            if docs:
                p = pll.polizas_de_documentos(origen, docs)
                if not p.empty:
                    polizas.append(p)
        pol_map = pd.concat(polizas, ignore_index=True) if polizas else pd.DataFrame()
        folios = pol_map["poliza"].dropna().unique().tolist() if not pol_map.empty else []
        console_err.print(f"  vía 3 · {len(folios)} pólizas del universo…")
        lineas = pll.lineas_de_polizas(folios)
        lineas = lineas[lineas["cuenta"].str.startswith(tuple(cuentas_impuesto))]
    con, det_cta = lado_contable(lineas)
    console_err.print(f"  vía 3 · {len(lineas)} líneas en cuentas de impuesto")

    # --- Cuadro de las tres vías ---
    cuadro = pd.concat([xml, xml_en_mpro, doc, con], axis=1)
    cuadro["dif_XMLmpro_vs_DOC"] = (cuadro["XML_SAT_en_mpro"] - cuadro["DOCUMENTO_mpro"]).round(2)
    cuadro["dif_DOC_vs_CONTABLE"] = (cuadro["DOCUMENTO_mpro"] - cuadro["CONTABLE_poliza"]).round(2)
    cuadro["dif_XMLmpro_vs_CONTABLE"] = (cuadro["XML_SAT_en_mpro"] - cuadro["CONTABLE_poliza"]).round(2)
    cuadro = cuadro.reset_index().rename(columns={"index": "concepto"})

    resumen_err(periodos=",".join(periodos), alcance=args.alcance,
                cfdi_total=len(sat), cfdi_en_mpro=len(sat_en_mpro),
                cfdi_sin_etiqueta=len(sat) - len(sat_en_mpro))

    mostrar_tabla_err(cuadro, "Las tres vías del impuesto (XML → documento → cuenta contable)",
                      max_filas=20)

    if not det_cta.empty:
        det_cta["monto"] = det_cta["monto"].round(2)
        mostrar_tabla_err(det_cta.sort_values("monto", ascending=False),
                          "Vía 3 — desglose por cuenta contable de impuesto", max_filas=30)

    # --- Semáforo por concepto ---
    filas = []
    for _, r in cuadro.iterrows():
        for par, etiqueta in (("dif_XMLmpro_vs_DOC", "XML vs documento"),
                              ("dif_DOC_vs_CONTABLE", "documento vs contable"),
                              ("dif_XMLmpro_vs_CONTABLE", "XML vs contable")):
            dif = r[par]
            if pd.isna(dif):
                estado = "no aplica"
            elif abs(dif) <= TOL:
                estado = "cuadra"
            else:
                base = abs(r["XML_SAT_en_mpro"]) or 1.0
                pct = abs(dif) / base * 100
                estado = f"descuadre {pct:.2f}%"
            filas.append({"concepto": r["concepto"], "comparación": etiqueta,
                          "diferencia": dif, "estado": estado})
    mostrar_tabla_err(pd.DataFrame(filas), "Semáforo", max_filas=20)

    if args.csv:
        print("--- CSV_PARA_CLAUDE: tres_vias ---")
        print(cuadro.to_csv(index=False))
        print("--- CSV_PARA_CLAUDE: detalle_cuentas_impuesto ---")
        print(det_cta.to_csv(index=False))


if __name__ == "__main__":
    main()
