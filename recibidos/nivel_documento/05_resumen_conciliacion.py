"""
05 -- Resumen ejecutivo de los tres reportes de conciliacion.

Lee los CSV que dejan `02_`, `03_` y `04_` (no vuelve a calcularlos, salvo
el detalle de impuestos por documento, que se consulta en vivo para poder
medir que parte del IVA acreditable del mes esta respaldada por un CFDI).

Pregunta que responde: **los importes e impuestos registrados en MPro estan
soportados por los XML que se le reportan al SAT.** Y donde no, cuanto y por
que.

Salida: 05_resumen_conciliacion_<fi>_<ff>.csv -- una fila por indicador,
con su valor, su base y la seccion del artifact a la que corresponde.

Uso:
    python3 05_resumen_conciliacion.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
"""
import argparse

import pandas as pd

import conciliacion_xml_lib as L
from helpers_output import console, mostrar_tabla, resumen

EXPLICADO = {
    "SIN_XML_CANCELADO", "SIN_XML_IMPORTE_CERO", "SIN_XML_IMPORTE_NEGATIVO",
    "SIN_XML_ORIGEN_INTERNO", "SIN_XML_CFDI_EN_ORIGEN", "SIN_XML_TRASPASO_INTERNO",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    a = ap.parse_args()
    fi, ff = a.fecha_ini, a.fecha_fin

    # El 02 (solo importes) se retiró al consolidar este proyecto en
    # reconciliacion-cowork (2026-09-10): el 03 es el 02 más el desglose
    # fiscal, mismas columnas de importe -- se lee una sola vez.
    r2 = pd.read_csv(f"03_conciliacion_xml_vs_mpro_impuestos_{fi}_{ff}.csv")
    r1 = r2
    r3 = pd.read_csv(f"04_conciliacion_mpro_vs_xml_{fi}_{ff}.csv")

    f = []
    add = lambda s, k, v, b="": f.append({"SECCION": s, "INDICADOR": k, "VALOR": v, "BASE": b})

    # ---- Reporte 1: importes
    ok1 = r1.ESTATUS.eq("CONCILIA")
    okc1 = r1.ESTATUS.isin(L.ESTATUS_CUADRA)
    mal1 = r1[~r1.ESTATUS.isin(L.ESTATUS_EXPLICADO)]
    add("R1", "grupos_de_conciliacion", len(r1))
    add("R1", "cfdi_recibidos_distintos", int(r1.N_XML.sum()), "un CFDI cuenta una vez por grupo")
    add("R1", "pct_grupos_concilia_exacto", round(100 * ok1.mean(), 2), "|dif| <= 0.05")
    add("R1", "pct_grupos_concilia_con_centavos", round(100 * okc1.mean(), 2), "|dif| <= 1.00")
    add("R1", "importe_xml", round(r1.XML_IMPORTE.sum(), 2))
    add("R1", "importe_mpro", round(r1.MPRO_TOTAL.sum(), 2))
    add("R1", "importe_en_descuadre_abs", round(mal1.DIF.abs().sum(), 2), "grupos DIF_MATERIAL / REGISTRO_EN_CERO")
    add("R1", "pct_importe_en_descuadre", round(100 * mal1.DIF.abs().sum() / r1.XML_IMPORTE.sum(), 2))
    add("R1", "grupos_descuadrados", len(mal1))
    add("R1", "importe_en_complemento", round(r1.XML_COMPLEMENTO_IMPORTE.sum(), 2),
        "CFDI cuyo importe real vive en un complemento (vales de despensa)")
    add("R1", "grupos_importe_en_complemento", int(r1.ESTATUS.eq("IMPORTE_EN_COMPLEMENTO").sum()))
    add("R1", "grupos_sin_registro", int(r1.ESTATUS.eq("SIN_REGISTRO").sum()))

    # ---- Reporte 2: impuestos
    comp = r2[~r2.ESTATUS_IMPUESTOS.isin(["NO_COMPARABLE_MODULO", "SIN_REGISTRO",
                                          "MODULO_NO_CUBIERTO", "REPARTIDO_ENTRE_MODULOS"])]
    ok2 = comp.ESTATUS_IMPUESTOS.isin(["CONCILIA", "SIN_IMPUESTOS"])
    okc2 = comp.ESTATUS_IMPUESTOS.isin(["CONCILIA", "SIN_IMPUESTOS", "DIF_CENTAVOS"])
    add("R2", "grupos_comparables_en_impuestos", len(comp), "excluye CHEQUE y ANTICIPO_CXP (MPro no lleva impuestos ahi)")
    add("R2", "pct_impuestos_concilia_exacto", round(100 * ok2.mean(), 2))
    add("R2", "pct_impuestos_concilia_con_centavos", round(100 * okc2.mean(), 2))
    add("R2", "xml_impuesto_local_trasladado", round(r2.XML_IMP_LOCAL_TRAS.sum(), 2),
        "MPro los suma dentro de su clave de IVA; van incluidos en el par de abajo")
    for c in ("IVA_TRASLADADO", "RET_IVA", "RET_ISR", "IEPS_TRASLADADO"):
        col = "XML_IVA_Y_LOCAL" if c == "IVA_TRASLADADO" else f"XML_{c}"
        add("R2", f"xml_{c.lower()}", round(r2[col].sum(), 2))
        add("R2", f"mpro_{c.lower()}", round(r2[f"MPRO_{c}"].sum(), 2))
        add("R2", f"dif_{c.lower()}", round(r2[col].sum() - r2[f"MPRO_{c}"].sum(), 2))
    add("R2", "iva_en_descuadre_abs", round(r2.DIF_IVA_TRASLADADO.abs().sum(), 2))
    add("R2", "pct_iva_en_descuadre", round(100 * r2.DIF_IVA_TRASLADADO.abs().sum() / r2.XML_IVA_Y_LOCAL.sum(), 2))
    add("R2", "iva_no_comparable_modulo", round(
        r2.loc[r2.ESTATUS_IMPUESTOS.eq("NO_COMPARABLE_MODULO"), "XML_IVA_Y_LOCAL"].sum(), 2),
        "IVA de los REP: informativo, se acredita en la factura, no en el pago")

    # ---- Reporte 3: cobertura inversa
    con = r3.N_XML > 0
    sin_expl = r3.CLASE.isin(EXPLICADO)
    pend = r3.CLASE.eq("SIN_XML_PENDIENTE")
    add("R3", "documentos_mpro", len(r3))
    add("R3", "importe_mpro_total", round(r3.TOTAL.sum(), 2))
    add("R3", "docs_con_xml", int(con.sum()))
    add("R3", "pct_docs_con_xml", round(100 * con.mean(), 2))
    add("R3", "pct_importe_con_xml", round(100 * r3.loc[con, "TOTAL"].sum() / r3.TOTAL.sum(), 2))
    add("R3", "docs_sin_xml_explicado", int(sin_expl.sum()))
    add("R3", "importe_sin_xml_explicado", round(r3.loc[sin_expl, "TOTAL"].sum(), 2))
    add("R3", "docs_sin_xml_pendiente", int(pend.sum()))
    add("R3", "importe_sin_xml_pendiente", round(r3.loc[pend, "TOTAL"].sum(), 2))
    add("R3", "pct_importe_sin_xml_pendiente", round(100 * r3.loc[pend, "TOTAL"].sum() / r3.TOTAL.sum(), 2))

    # ---- IVA acreditable del mes respaldado por CFDI (cruce vivo)
    piv, _ = L.impuestos_mpro(fi, ff, origenes=["GASTO_REGISTRO", "COMPRA", "COMPRA_INDIRECTO",
                                                "NOTA_CREDITO_PROVEEDOR"])
    piv["DOC_ID"] = piv.DOC_ID.astype("string").fillna("")
    k = r3.copy()
    k["DOC_ID"] = k.DOC_ID.fillna("").astype(str).replace({"nan": ""})
    k.loc[k.ORIGEN.eq("GASTO_REGISTRO"), "DOC_ID"] = (
        pd.to_numeric(k.loc[k.ORIGEN.eq("GASTO_REGISTRO"), "DOC_ID"], errors="coerce")
        .astype("Int64").astype("string").str.zfill(4).fillna(""))
    k = k.merge(piv, on=["ORIGEN", "FOLIO", "DOC_ID"], how="left")
    k["MPRO_IVA_TRASLADADO"] = k.MPRO_IVA_TRASLADADO.fillna(0.0)
    vig = k[k.ESTADO != "CA"]
    iva_tot = vig.MPRO_IVA_TRASLADADO.sum()
    iva_con = vig.loc[vig.N_XML > 0, "MPRO_IVA_TRASLADADO"].sum()
    add("IVA", "iva_acreditable_registrado_mes", round(iva_tot, 2),
        "gasto+compra+compra indirecta+NCP, documentos no cancelados fechados en el mes")
    add("IVA", "iva_con_cfdi_ligado", round(iva_con, 2))
    add("IVA", "pct_iva_con_cfdi_ligado", round(100 * iva_con / iva_tot if iva_tot else 0, 2))
    add("IVA", "iva_sin_cfdi_ligado", round(iva_tot - iva_con, 2))
    iva_pend = vig.loc[vig.CLASE.eq("SIN_XML_PENDIENTE"), "MPRO_IVA_TRASLADADO"].sum()
    add("IVA", "iva_sin_cfdi_en_documentos_pendientes", round(iva_pend, 2),
        "el subconjunto realmente sin explicacion")

    res = pd.DataFrame(f)
    for s in ("R1", "R2", "R3", "IVA"):
        mostrar_tabla(res[res.SECCION == s].drop(columns="SECCION"),
                      {"R1": "Reporte 1 -- importes XML vs MPro",
                       "R2": "Reporte 2 -- impuestos",
                       "R3": "Reporte 3 -- cobertura desde MPro",
                       "IVA": "IVA acreditable del mes: respaldo documental"}[s], max_filas=40)
    resumen(
        importe_conciliado=f"{100*(1 - mal1.DIF.abs().sum()/r1.XML_IMPORTE.sum()):.2f}%",
        impuestos_conciliados=f"{100*okc2.mean():.2f}% de grupos",
        IVA_con_CFDI=f"{100*iva_con/iva_tot if iva_tot else 0:.2f}%",
        pendiente_real=f"{r3.loc[pend,'TOTAL'].sum():,.2f} en {int(pend.sum())} documentos",
    )
    out = f"05_resumen_conciliacion_{fi}_{ff}.csv"
    res.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]")


if __name__ == "__main__":
    main()
