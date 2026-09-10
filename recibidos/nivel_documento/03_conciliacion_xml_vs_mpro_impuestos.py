"""
03 -- Conciliacion de IMPORTES + IMPUESTOS: CFDI recibido <-> registro MPro.

Extension directa del reporte 02: mismo universo, mismo grano (grupo de
conciliacion = componente conexa CFDI <-> documento, por origen), mismas
columnas de importe -- y encima el desglose fiscal de los dos lados.

Lado XML: se leen del nodo `cfdi:Impuestos` **hijo directo** de
`cfdi:Comprobante`. Ese mismo nodo existe dentro de cada `cfdi:Concepto`;
sumar los dos niveles duplica el IVA (error ya visto en el ELT de
raw_sat.cfdi_recibidos). Aqui se evita por construccion.

Lado MPro: tabla de impuestos propia de cada modulo
(`Gasto_Registro_Impuesto`, `Compra_Total_Impuesto`,
`Cuenta_X_Pagar_Impuesto`, `Compra_Indirecto_Impuesto`,
`Nota_Credito_Proveedor_Impuesto`, `Factura_Total_Impuesto`), traducida al
codigo del SAT con `Impuesto.Im_Codigo_SAT` (001 ISR / 002 IVA / 003 IEPS)
y separada en traslado vs retencion por el signo de `Impuesto.Im_Tasa`.
MPro guarda las retenciones en negativo y el CFDI en positivo: se comparan
en valor absoluto.

Impuestos locales (ISH y similares, complemento `implocal:ImpuestosLocales`):
MPro NO los lleva por separado -- los suma dentro de su clave de IVA. Por eso
el lado XML del par de IVA es `XML_IVA_TRASLADADO + XML_IMP_LOCAL_TRAS`.
Verificado al centavo: gasto 05-0175447, IVA federal del CFDI 208.86 + ISH
58.75 = 267.61, exactamente lo que MPro registro bajo "IVA ACREDITABLE 16%".
Sin esta suma el reporte marcaba 2 falsos positivos de "IVA mal capturado".
De los 434.59 de impuesto local de enero, MPro capturo 112.49 (2 gastos) y
dejo fuera 322.10 (7 gastos) -- eso ultimo si es un faltante real.

Dos modulos NO tienen tabla de impuestos en MPro y por eso salen como
`NO_COMPARABLE_MODULO`: CHEQUE y ANTICIPO_CXP. No es un hueco de captura --
un REP no genera IVA acreditable propio (el acreditamiento vive en la
factura que el REP paga), y un anticipo tampoco.

Salida: <script>_<fi>_<ff>.csv -- las columnas del 02 mas
XML_/MPRO_/DIF_ por IVA trasladado, IEPS trasladado, IVA retenido, ISR
retenido, el neto de impuestos y ESTATUS_IMPUESTOS.

Uso:
    python3 03_conciliacion_xml_vs_mpro_impuestos.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
"""
import argparse

import numpy as np
import pandas as pd

import conciliacion_xml_lib as L
from helpers_output import console, mostrar_tabla, resumen

# Modulos sin tabla de impuestos en MPro -- ver docstring.
SIN_TABLA_IMPUESTOS = {"CHEQUE", "ANTICIPO_CXP"}

PARES = [
    # MPro no lleva los impuestos locales por separado: los suma dentro de su
    # clave de IVA. Verificado al centavo -- gasto 05-0175447, IVA federal del
    # CFDI $208.86 + ISH $58.75 = $267.61, exactamente lo que MPro registro
    # bajo "IVA ACREDITABLE 16%". Por eso el lado XML del par es la suma.
    ("IVA_TRASLADADO", "XML_IVA_Y_LOCAL", "MPRO_IVA_TRASLADADO"),
    ("IEPS_TRASLADADO", "XML_IEPS_TRASLADADO", "MPRO_IEPS_TRASLADADO"),
    ("RET_IVA", "XML_RET_IVA", "MPRO_RET_IVA"),
    ("RET_ISR", "XML_RET_ISR", "MPRO_RET_ISR"),
]


def construir(fi, ff):
    g, x, reg = L.conciliar_importes(fi, ff, console)

    # --- impuestos del lado XML (un UUID cuenta una sola vez por grupo)
    xu = x.drop_duplicates(["GRUPO", "UUID"])
    imp_x = xu.groupby(["ORIGEN", "GRUPO"]).agg(
        XML_IVA_TRASLADADO=("XML_IVA_TRASLADADO", "sum"),
        XML_IEPS_TRASLADADO=("XML_IEPS_TRASLADADO", "sum"),
        XML_RET_IVA=("XML_RET_IVA", "sum"),
        XML_RET_ISR=("XML_RET_ISR", "sum"),
        XML_BASE_EXENTA=("XML_BASE_EXENTA", "sum"),
        XML_PAGOS_IVA=("XML_PAGOS_IVA", "sum"),
        XML_IMP_LOCAL_TRAS=("XML_IMP_LOCAL_TRAS", "sum"),
        XML_IMP_LOCAL_RET=("XML_IMP_LOCAL_RET", "sum"),
    ).reset_index()
    imp_x["XML_IVA_Y_LOCAL"] = (imp_x.XML_IVA_TRASLADADO + imp_x.XML_IMP_LOCAL_TRAS).round(2)

    # --- impuestos del lado MPro
    folios = {o: sorted(gg.FOLIO.unique()) for o, gg in reg.groupby("ORIGEN")}
    piv, det = L.impuestos_mpro(folios_por_origen=folios)
    r = reg[["ORIGEN", "FOLIO", "DOC_ID", "GRUPO"]].drop_duplicates()
    piv = r.merge(piv, on=["ORIGEN", "FOLIO", "DOC_ID"], how="left").fillna(
        {c: 0.0 for c in piv.columns if c.startswith("MPRO_")})
    imp_r = piv.groupby(["ORIGEN", "GRUPO"]).agg(
        MPRO_IVA_TRASLADADO=("MPRO_IVA_TRASLADADO", "sum"),
        MPRO_IEPS_TRASLADADO=("MPRO_IEPS_TRASLADADO", "sum"),
        MPRO_RET_IVA=("MPRO_RET_IVA", "sum"),
        MPRO_RET_ISR=("MPRO_RET_ISR", "sum"),
        MPRO_IMP_NO_CFDI=("MPRO_IMP_NO_CFDI", "sum"),
        MPRO_IMP_OTRO=("MPRO_IMP_OTRO", "sum"),
    ).reset_index()

    g = g.drop(columns=[c for c in ("XML_IMP_LOCAL_TRAS",) if c in g.columns])
    g = g.merge(imp_x, on=["ORIGEN", "GRUPO"], how="left").merge(imp_r, on=["ORIGEN", "GRUPO"], how="left")
    num = [c for c in g.columns if c.startswith(("XML_", "MPRO_")) and g[c].dtype.kind in "fiu"]
    g[num] = g[num].fillna(0.0)

    for nombre, cx, cm in PARES:
        g[f"DIF_{nombre}"] = (g[cx] - g[cm]).round(2)
    g["XML_IMPUESTOS_NETO"] = (g.XML_IVA_Y_LOCAL + g.XML_IEPS_TRASLADADO
                               - g.XML_RET_IVA - g.XML_RET_ISR).round(2)
    g["MPRO_IMPUESTOS_NETO"] = (g.MPRO_IVA_TRASLADADO + g.MPRO_IEPS_TRASLADADO
                                - g.MPRO_RET_IVA - g.MPRO_RET_ISR).round(2)
    g["DIF_IMPUESTOS_NETO"] = (g.XML_IMPUESTOS_NETO - g.MPRO_IMPUESTOS_NETO).round(2)
    g["DIF_IMPUESTOS_ABS"] = sum(g[f"DIF_{n}"].abs() for n, _, _ in PARES).round(2)

    def estatus(r_):
        if r_.ORIGEN in SIN_TABLA_IMPUESTOS:
            return "NO_COMPARABLE_MODULO"
        if r_.N_DOC == 0:
            return r_.ESTATUS if r_.ESTATUS == "MODULO_NO_CUBIERTO" else "SIN_REGISTRO"
        # Si el CFDI se reparte entre dos modulos, su impuesto se reparte
        # igual: el IVA de cada modulo es proporcional a su parte del importe.
        # Verificado: CFDI 90227AAD, IVA 22,233.21 = 22,078.66 (COMPRA) +
        # 154.55 (COMPRA_INDIRECTO). Compararlos por separado marca un
        # descuadre que no existe.
        if r_.ESTATUS == "REPARTIDO_ENTRE_MODULOS":
            return "REPARTIDO_ENTRE_MODULOS"
        # Mismo hueco que a nivel importe (ver conciliar_importes): sin
        # match en raw_sat, los campos fiscales del XML son 0 -- no es un
        # descuadre de impuestos real, es que no hay con qué comparar.
        if r_.ESTATUS in ("SIN_RAW_SAT_CANCELADO", "SIN_RAW_SAT_PENDIENTE"):
            return r_.ESTATUS
        hay = (abs(r_.XML_IMPUESTOS_NETO) > L.TOL_CENTAVOS
               or abs(r_.MPRO_IMPUESTOS_NETO) > L.TOL_CENTAVOS)
        if not hay:
            return "SIN_IMPUESTOS"
        d = r_.DIF_IMPUESTOS_ABS
        if d <= L.TOL_CENTAVOS:
            return "CONCILIA"
        if d <= L.TOL_MENOR:
            return "DIF_CENTAVOS"
        return "DIF_MATERIAL"

    g["ESTATUS_IMPUESTOS"] = g.apply(estatus, axis=1)

    def motivo(r_):
        if r_.ESTATUS_IMPUESTOS not in ("DIF_MATERIAL", "DIF_CENTAVOS"):
            return ""
        m = []
        for nombre, _, _ in PARES:
            if abs(r_[f"DIF_{nombre}"]) > L.TOL_CENTAVOS:
                m.append(nombre + ("_MPRO_MENOS" if r_[f"DIF_{nombre}"] > 0 else "_MPRO_MAS"))
        if r_.MPRO_IMP_NO_CFDI:
            m.append("MPRO_TRAE_IMPUESTO_NO_CFDI")
        if r_.XML_IMP_LOCAL_TRAS > 0:
            m.append("CFDI_CON_IMPUESTO_LOCAL")
        if r_.XML_BASE_EXENTA > 0:
            m.append("CFDI_CON_BASE_EXENTA")
        return "|".join(m)

    g["MOTIVO_IMPUESTOS"] = g.apply(motivo, axis=1)

    base = [c for c in g.columns if c not in
            {"XML_IVA_TRASLADADO", "XML_IVA_Y_LOCAL", "XML_IMP_LOCAL_TRAS", "XML_IMP_LOCAL_RET",
             "XML_IEPS_TRASLADADO", "XML_RET_IVA", "XML_RET_ISR",
             "XML_BASE_EXENTA", "XML_PAGOS_IVA", "MPRO_IVA_TRASLADADO", "MPRO_IEPS_TRASLADADO",
             "MPRO_RET_IVA", "MPRO_RET_ISR", "MPRO_IMP_NO_CFDI", "MPRO_IMP_OTRO",
             "DIF_IVA_TRASLADADO", "DIF_IEPS_TRASLADADO", "DIF_RET_IVA", "DIF_RET_ISR",
             "XML_IMPUESTOS_NETO", "MPRO_IMPUESTOS_NETO", "DIF_IMPUESTOS_NETO",
             "DIF_IMPUESTOS_ABS", "ESTATUS_IMPUESTOS", "MOTIVO_IMPUESTOS", "FOLIOS", "UUIDS"}]
    fiscal = ["ESTATUS_IMPUESTOS", "MOTIVO_IMPUESTOS",
              "XML_IVA_TRASLADADO", "XML_IMP_LOCAL_TRAS", "XML_IVA_Y_LOCAL",
              "MPRO_IVA_TRASLADADO", "DIF_IVA_TRASLADADO",
              "XML_IEPS_TRASLADADO", "MPRO_IEPS_TRASLADADO", "DIF_IEPS_TRASLADADO",
              "XML_RET_IVA", "MPRO_RET_IVA", "DIF_RET_IVA",
              "XML_RET_ISR", "MPRO_RET_ISR", "DIF_RET_ISR",
              "XML_IMPUESTOS_NETO", "MPRO_IMPUESTOS_NETO", "DIF_IMPUESTOS_NETO",
              "DIF_IMPUESTOS_ABS", "XML_BASE_EXENTA", "XML_PAGOS_IVA", "XML_IMP_LOCAL_RET",
              "MPRO_IMP_NO_CFDI", "MPRO_IMP_OTRO"]
    return g[base + fiscal + ["FOLIOS", "UUIDS"]], det


def reportar(g, det):
    fuera = ["NO_COMPARABLE_MODULO", "SIN_REGISTRO", "MODULO_NO_CUBIERTO",
             "REPARTIDO_ENTRE_MODULOS", "SIN_RAW_SAT_CANCELADO", "SIN_RAW_SAT_PENDIENTE"]
    comparables = g[~g.ESTATUS_IMPUESTOS.isin(fuera)]
    ok = comparables.ESTATUS_IMPUESTOS.isin(["CONCILIA", "SIN_IMPUESTOS"])
    okc = comparables.ESTATUS_IMPUESTOS.isin(["CONCILIA", "SIN_IMPUESTOS", "DIF_CENTAVOS"])
    iva = g.XML_IVA_Y_LOCAL.sum()
    difiva = g.DIF_IVA_TRASLADADO.abs().sum()
    resumen(
        grupos=len(g),
        comparables=len(comparables),
        impuestos_CONCILIA=f"{ok.sum()} ({100*ok.mean() if len(comparables) else 0:.1f}%)",
        con_centavos=f"{okc.sum()} ({100*okc.mean() if len(comparables) else 0:.1f}%)",
        IVA_XML=f"{iva:,.2f}",
        IVA_en_descuadre=f"{difiva:,.2f} ({100*difiva/iva if iva else 0:.2f}%)",
    )
    t = g.groupby(["ORIGEN", "ESTATUS_IMPUESTOS"]).agg(
        GRUPOS=("GRUPO", "size"),
        XML_IVA=("XML_IVA_Y_LOCAL", "sum"), MPRO_IVA=("MPRO_IVA_TRASLADADO", "sum"),
        XML_RET=("XML_RET_IVA", "sum"), MPRO_RET=("MPRO_RET_IVA", "sum"),
        DIF_ABS=("DIF_IMPUESTOS_ABS", "sum")).reset_index()
    for c in ("XML_IVA", "MPRO_IVA", "XML_RET", "MPRO_RET", "DIF_ABS"):
        t[c] = t[c].map(lambda v: f"{v:,.2f}")
    mostrar_tabla(t, "Semaforo de impuestos por origen", max_filas=40)

    tot = pd.DataFrame([
        {"CONCEPTO": n, "XML": g[cx].sum(), "MPRO": g[cm].sum(), "DIF": g[cx].sum() - g[cm].sum()}
        for n, cx, cm in PARES] + [
        {"CONCEPTO": "NETO", "XML": g.XML_IMPUESTOS_NETO.sum(), "MPRO": g.MPRO_IMPUESTOS_NETO.sum(),
         "DIF": g.DIF_IMPUESTOS_NETO.sum()}])
    for c in ("XML", "MPRO", "DIF"):
        tot[c] = tot[c].map(lambda v: f"{v:,.2f}")
    mostrar_tabla(tot, "Total de impuestos del periodo -- XML vs MPro", max_filas=10)

    peor = g[g.ESTATUS_IMPUESTOS == "DIF_MATERIAL"].copy()
    if len(peor):
        peor = peor.reindex(peor.DIF_IMPUESTOS_ABS.sort_values(ascending=False).index)
        mostrar_tabla(peor[["ORIGEN", "GRUPO", "MOTIVO_IMPUESTOS", "XML_IVA_Y_LOCAL",
                            "MPRO_IVA_TRASLADADO", "XML_RET_IVA", "MPRO_RET_IVA",
                            "DIF_IMPUESTOS_ABS"]].head(20),
                      "Mayores descuadres de impuestos", max_filas=20)

    if len(det):
        nc = det[~det.ES_CFDI]
        if len(nc):
            mostrar_tabla(nc.groupby(["CVE", "DESCRIPCION"]).agg(
                N=("IMPORTE", "size"), IMPORTE=("IMPORTE", "sum")).reset_index().head(12),
                "Impuestos de MPro excluidos de la comparacion (no son impuestos de CFDI)",
                max_filas=12)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    args = ap.parse_args()
    g, det = construir(args.fecha_ini, args.fecha_fin)
    reportar(g, det)
    out = f"03_conciliacion_xml_vs_mpro_impuestos_{args.fecha_ini}_{args.fecha_fin}.csv"
    g.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]  ({len(g)} filas, {len(g.columns)} columnas)")


if __name__ == "__main__":
    main()
