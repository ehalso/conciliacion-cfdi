#!/usr/bin/env python3
"""Triage numérico de los 149 pendientes — prueba en bloque una batería de
relaciones candidatas entre el CFDI (SAT) y lo capturado en mpro, para
separar "esto es un patrón conocido" de "esto hay que mirarlo a mano".

No consulta el bridge: trabaja sobre los CSV que dejó dump_contexto.py.

Relaciones que prueba, por CFDI (S=subtotal, I=iva, T=total,
R=retenciones=S+I-T, C=cargo agregado encontrado):

  C≈T           el cargo trae IVA (base equivocada)
  C≈S+I         cargo = subtotal + IVA sin restar retención
  C≈S-R         cargo neto de retención
  C≈2S / C≈2T   doble conteo
  C≈S/2         mitad
  C≈0           no se encontró cargo
  |C|≈S         signo invertido (nota de crédito / reversión)
  C≈S*0.9       retención ISR 10% (patrón de honorarios ya documentado)

Además, para GASTO_REGISTRO compara el subtotal contra lo que traen los
campos propios del documento (Grd_Precio_Neto / Grd_Precio_Descontado, con
y sin tipo de cambio), que es donde vive el importe "correcto" cuando
Gasto_Registro_Control está mal capturado.

Uso: python3 investigacion/triage.py
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "output" / "investigacion"
sys.path.insert(0, str(RAIZ))

import pandas as pd  # noqa: E402

TOL = 1.00


def num(s):
    return pd.to_numeric(s, errors="coerce").fillna(0.0)


def cerca(a, b, tol=TOL):
    return (a - b).abs() <= tol


def cargar():
    p = pd.read_csv(DATOS / "pendientes.csv")
    resumen = pd.read_csv(DATOS / "resumen.csv")
    cols = ["uuid", "subtotal", "iva", "total", "cargo_agregado", "ajuste_local",
            "subtotal_ajustado", "total_mxn", "tipo_cambio", "cheque_abono", "origenes"]
    cols = [c for c in cols if c in resumen.columns]
    r = resumen[cols].copy()
    p = p.drop(columns=[c for c in ("subtotal", "iva", "total", "cargo_agregado", "origenes")
                        if c in p.columns]).merge(r, on="uuid", how="left")
    for c in ("subtotal", "iva", "total", "cargo_agregado", "ajuste_local",
              "subtotal_ajustado", "total_mxn", "tipo_cambio", "cheque_abono"):
        if c in p.columns:
            p[c] = num(p[c])
    return p


def relaciones(p: pd.DataFrame) -> pd.DataFrame:
    tc = p["tipo_cambio"].replace(0, 1.0)
    S = p["subtotal_ajustado"]           # ya en MXN, con ajuste implocal
    I = p["iva"] * tc
    T = p["total_mxn"]
    C = p["cargo_agregado"]
    R = S + I - T  # retenciones implícitas
    p = p.copy()
    p["retenciones"] = R.round(2)
    p["ratio_cargo_subtotal"] = (C / S.replace(0, pd.NA)).round(4)
    p["diferencia"] = (C - S).round(2)

    pruebas = {
        "C=T": cerca(C, T),
        "C=S+I": cerca(C, S + I),
        "C=S-R": cerca(C, S - R),
        "C=T-R": cerca(C, T - R),
        "C=2S": cerca(C, 2 * S),
        "C=2T": cerca(C, 2 * T),
        "C=S/2": cerca(C, S / 2),
        "C=0": cerca(C, 0),
        "|C|=S": cerca(C.abs(), S.abs()),
        "|C|=T": cerca(C.abs(), T.abs()),
        "C=S*0.9": cerca(C, S * 0.9),
        "C=S*1.16": cerca(C, S * 1.16),
    }
    for nombre, hit in pruebas.items():
        p[f"hit_{nombre}"] = hit
    return p


def campos_gasto_registro(p: pd.DataFrame) -> pd.DataFrame:
    """Para los pendientes de GASTO_REGISTRO, trae lo que dicen los campos
    propios del documento (Grd_*), que es independiente de lo capturado en
    Gasto_Registro_Control."""
    og = pd.read_csv(DATOS / "origenes.csv")
    grd = pd.read_csv(DATOS / "gr_documento.csv", dtype={"Grd_ID": str})
    grc = pd.read_csv(DATOS / "gr_control.csv", dtype={"Grd_ID": str})

    og = og[og["origen"].str.upper() == "GASTO_REGISTRO"].copy()
    og["Gr_Folio"] = og["documento"].str.slice(0, 10)
    og["Grd_ID"] = og["documento"].str.slice(10, 14)

    for df in (grd, grc):
        df["Grd_ID"] = df["Grd_ID"].astype(str).str.zfill(4)
    og["Grd_ID"] = og["Grd_ID"].astype(str).str.zfill(4)

    grd["neto"] = num(grd["Grd_Precio_Neto_Importe"])
    grd["descontado"] = num(grd["Grd_Precio_Descontado_Importe"])
    grd["tc"] = num(grd["Grd_Tipo_Cambio"]).replace(0, 1.0)
    grc["control"] = num(grc["suma_abs"])

    j = og.merge(grd[["Gr_Folio", "Grd_ID", "neto", "descontado", "tc", "Mn_Cve_Moneda"]],
                 on=["Gr_Folio", "Grd_ID"], how="left")
    j = j.merge(grc[["Gr_Folio", "Grd_ID", "control", "n_lineas"]],
                on=["Gr_Folio", "Grd_ID"], how="left")

    agg = j.groupby("uuid").agg(
        gr_neto=("neto", "sum"),
        gr_descontado=("descontado", "sum"),
        gr_control=("control", "sum"),
        gr_neto_mxn=("neto", "sum"),
        gr_docs=("documento", "count"),
        gr_lineas=("n_lineas", "sum"),
        monedas=("Mn_Cve_Moneda", lambda s: ",".join(sorted(set(str(x) for x in s if pd.notna(x))))),
    ).reset_index()
    # neto convertido a MXN (por si el CFDI viene en otra moneda)
    j["neto_mxn"] = j["neto"] * j["tc"]
    agg = agg.drop(columns=["gr_neto_mxn"]).merge(
        j.groupby("uuid")["neto_mxn"].sum().rename("gr_neto_mxn").reset_index(),
        on="uuid", how="left")

    p = p.merge(agg, on="uuid", how="left")
    S = p["subtotal_ajustado"]
    p["hit_GRD_neto=S"] = cerca(num(p["gr_neto"]), S)
    p["hit_GRD_desc=S"] = cerca(num(p["gr_descontado"]), S)
    p["hit_GRD_netoMXN=S"] = cerca(num(p["gr_neto_mxn"]), S)
    p["hit_GRD_neto=T"] = cerca(num(p["gr_neto"]), p["total_mxn"])
    return p


def main():
    p = cargar()
    p = relaciones(p)
    p = campos_gasto_registro(p)

    cols_hit = [c for c in p.columns if c.startswith("hit_")]
    p["hits"] = p[cols_hit].apply(
        lambda fila: ",".join(c[4:] for c in cols_hit if bool(fila[c])), axis=1)
    p["explicado"] = p["hits"] != ""

    p.to_csv(DATOS / "triage.csv", index=False)

    print(f"=== TRIAGE: {len(p)} pendientes ===\n")
    print("Por origen:")
    print(p["origenes"].value_counts().to_string())
    print(f"\nCon alguna relación numérica que pega: {int(p['explicado'].sum())} / {len(p)}\n")
    print("Relaciones que pegan (cuántos pendientes cada una):")
    for c in cols_hit:
        n = int(p[c].sum())
        if n:
            print(f"  {c[4:]:<18} {n}")

    print("\n=== Pendientes con relación identificada ===")
    ident = p[p["explicado"]][["uuid", "origenes", "nombre_emisor", "subtotal_ajustado",
                               "cargo_agregado", "diferencia", "hits"]]
    print(ident.to_string(index=False, max_colwidth=28))

    print(f"\n=== Sin relación simple: {int((~p['explicado']).sum())} ===")
    resto = p[~p["explicado"]].sort_values("diferencia", key=lambda s: s.abs(), ascending=False)
    print(resto[["uuid", "origenes", "nombre_emisor", "subtotal_ajustado", "cargo_agregado",
                 "diferencia", "ratio_cargo_subtotal"]].head(45).to_string(index=False, max_colwidth=28))


if __name__ == "__main__":
    main()
