"""Conciliación de CFDI EMITIDOS (Trivasa como emisor): factura, nota de
crédito y retenciones (constancia + gasto).

Adaptado de la investigación de Claude Code (2026-09-10) al bridge_client y
esquema de datos ya validados en este repo. Metodología (ver
docs/emitidos_retenciones.md, resumen de la sesión original):

- Relación 1:1 estricta folio<->CFDI (sin componente conexa) para FACTURA,
  NOTA_CREDITO, CONSTANCIA_RETENCION.
- Para retenciones colgadas de GASTO_REGISTRO, el comparable es
  Grd_Precio_Descontado_Importe (bruto), no el neto.
- Un CFDI de retención de dividendos aparece en DOS filas de
  Comprobante_Digital (CONSTANCIA_RETENCION y GASTO_REGISTRO) con el mismo
  UUID — deduplicar por UUID antes de sumar importe, quedándose con
  CONSTANCIA_RETENCION como fila principal.
- COMPROBANTE_PAGO (REP) no tiene documento propio comparable aquí — se dejó
  fuera de este primer reporte (ver README para el plan de REP/cobranza).

Uso:
    python3 reconciliacion_emitidos.py --periodo 2026-01
    python3 reconciliacion_emitidos.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

import pandas as pd

sys.path.insert(0, "src")

from extract_emitidos import (
    extract_comprobante_digital_emitido,
    extract_xml_por_uuids,
    extract_factura,
    extract_nota_credito,
    extract_constancia_retencion,
    extract_gasto_registro_retenciones,
)
from cfdi_parser import parse_cfdi
from retenciones_parser import es_retenciones, parse_retencion

TOL_CENTAVOS = Decimal("0.05")
TOL_MENOR = Decimal("1.00")


def periodo_a_rango(periodo: str) -> tuple[str, str]:
    year, month = (int(x) for x in periodo.split("-"))
    fecha_ini = f"{year:04d}-{month:02d}-01"
    if month == 12:
        fecha_fin = f"{year + 1:04d}-01-01"
    else:
        fecha_fin = f"{year:04d}-{month + 1:02d}-01"
    return fecha_ini, fecha_fin


def clasificar(dif: Decimal, cancelado_cfdi: bool, cancelado_mpro: bool, tiene_mpro: bool) -> str:
    if not tiene_mpro:
        return "SIN_REGISTRO"
    if cancelado_cfdi and cancelado_mpro:
        return "AMBOS_CANCELADOS"
    if abs(dif) <= TOL_CENTAVOS:
        return "CONCILIA"
    if abs(dif) <= TOL_MENOR:
        return "DIF_CENTAVOS"
    return "DIF_MATERIAL"


def conciliar(fecha_ini: str, fecha_fin: str) -> pd.DataFrame:
    print(f"[1/5] Universo emitido en Comprobante_Digital [{fecha_ini}, {fecha_fin})...")
    cd = extract_comprobante_digital_emitido(fecha_ini, fecha_fin)
    print(f"      {len(cd)} filas, {cd['origen'].value_counts().to_dict() if not cd.empty else {}}")

    if cd.empty:
        return pd.DataFrame()

    # Excluir REP de este primer reporte (se concilia distinto, ver README)
    cd_sin_rep = cd[cd["origen"] != "COMPROBANTE_PAGO"].copy()

    print(f"[2/5] Parseando XML de {len(cd_sin_rep)} comprobantes (factura/NC/retención)...")
    xml_df = extract_xml_por_uuids(cd_sin_rep["uuid"].tolist())
    xml_by_uuid = dict(zip(xml_df["uuid"], xml_df["xml"])) if not xml_df.empty else {}

    parsed_rows = []
    for _, row in cd_sin_rep.iterrows():
        uuid = row["uuid"]
        xml = xml_by_uuid.get(uuid)
        if not xml:
            parsed_rows.append({"uuid": uuid, "es_retencion": None, "monto_xml": None})
            continue
        try:
            if es_retenciones(xml):
                r = parse_retencion(xml)
                parsed_rows.append({
                    "uuid": uuid, "es_retencion": True,
                    "monto_xml": r.monto_operacion, "monto_retenido_xml": r.monto_total_retenido,
                    "cve_retenc": r.cve_retenc,
                })
            else:
                c = parse_cfdi(xml)
                parsed_rows.append({"uuid": uuid, "es_retencion": False, "monto_xml": c.total})
        except Exception as exc:
            parsed_rows.append({"uuid": uuid, "es_retencion": None, "monto_xml": None, "error": str(exc)})

    # OJO: NO usar merge(on="uuid") aquí -- un mismo UUID puede tener más de
    # una fila en cd_sin_rep (retención de dividendos: una en
    # CONSTANCIA_RETENCION y otra en GASTO_REGISTRO), y un merge por UUID con
    # duplicados en ambos lados produce el producto cartesiano (2x2=4 filas
    # en vez de 2). parsed_rows se construyó iterando cd_sin_rep en el mismo
    # orden por posición, así que se concatena por índice, no por llave.
    parsed_df = pd.DataFrame(parsed_rows).drop(columns="uuid")
    parsed_df.index = cd_sin_rep.index
    df = pd.concat([cd_sin_rep, parsed_df], axis=1)

    print("[3/5] Deduplicando retenciones de dividendos (misma UUID en dos módulos)...")
    # Para retenciones, CONSTANCIA_RETENCION es la fila principal (donde vive Cd_Monto real).
    # GASTO_REGISTRO con mismo UUID es la fila hermana -> se concilia aparte, no suma doble.
    df["fila_principal"] = True
    uuids_retencion = df.loc[df["origen"] == "CONSTANCIA_RETENCION", "uuid"]
    es_hermana = (df["origen"] == "GASTO_REGISTRO") & (df["uuid"].isin(uuids_retencion))
    df.loc[es_hermana, "fila_principal"] = False

    print("[4/5] Trayendo documentos de mpro por origen...")
    folios_factura = df.loc[df["origen"] == "FACTURA", "documento"].tolist()
    folios_nc = df.loc[df["origen"] == "NOTA_CREDITO", "documento"].tolist()
    folios_constancia = df.loc[df["origen"] == "CONSTANCIA_RETENCION", "documento"].tolist()
    docs_gasto = df.loc[df["origen"] == "GASTO_REGISTRO", "documento"].tolist()

    factura_df = extract_factura(folios_factura)
    nc_df = extract_nota_credito(folios_nc)
    constancia_df = extract_constancia_retencion(folios_constancia)
    gasto_df = extract_gasto_registro_retenciones(docs_gasto)

    print("[5/5] Cruzando y clasificando...")
    resultados = []
    for _, row in df.iterrows():
        origen = row["origen"]
        documento = row["documento"]
        uuid = row["uuid"]
        monto_xml = row.get("monto_xml")
        cancelado_cfdi = row["estado"] == "CA"
        tiene_mpro = False
        mpro_comparable = None
        cancelado_mpro = False

        if origen == "FACTURA" and not factura_df.empty:
            m = factura_df[factura_df["folio"] == documento]
            if not m.empty:
                tiene_mpro = True
                mpro_comparable = m.iloc[0]["importe"]
                cancelado_mpro = m.iloc[0]["estado"] == "CA"
        elif origen == "NOTA_CREDITO" and not nc_df.empty:
            m = nc_df[nc_df["folio"] == documento]
            if not m.empty:
                tiene_mpro = True
                mpro_comparable = m.iloc[0]["importe"]
                cancelado_mpro = m.iloc[0]["estado"] == "CA"
        elif origen == "CONSTANCIA_RETENCION" and not constancia_df.empty:
            m = constancia_df[constancia_df["folio"] == documento]
            if not m.empty:
                tiene_mpro = True
                mpro_comparable = m.iloc[0]["importe"]
                cancelado_mpro = m.iloc[0]["estado"] == "CA"
        elif origen == "GASTO_REGISTRO" and not gasto_df.empty:
            m = gasto_df[gasto_df["documento"] == documento[:14]]
            if not m.empty:
                tiene_mpro = True
                mpro_comparable = m.iloc[0]["importe_bruto"]  # el bruto, no el neto

        if mpro_comparable is not None and monto_xml is not None:
            try:
                dif = Decimal(str(mpro_comparable)) - Decimal(str(monto_xml))
            except Exception:
                dif = None
        else:
            dif = None

        if not row["fila_principal"]:
            estatus = "CONCILIA_FILA_HERMANA" if (dif is not None and abs(dif) <= TOL_MENOR) else "DIF_FILA_HERMANA"
        elif dif is None:
            estatus = "SIN_XML" if monto_xml is None else "SIN_REGISTRO"
        else:
            estatus = clasificar(dif, cancelado_cfdi, cancelado_mpro, tiene_mpro)

        resultados.append({
            "uuid": uuid, "origen": origen, "documento": documento,
            "monto_xml": monto_xml, "mpro_comparable": mpro_comparable,
            "diferencia": dif, "estatus": estatus,
            "cancelado_cfdi": cancelado_cfdi, "cancelado_mpro": cancelado_mpro,
            "fila_principal": row["fila_principal"],
        })

    return pd.DataFrame(resultados)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--periodo", help="YYYY-MM")
    ap.add_argument("--fecha-ini")
    ap.add_argument("--fecha-fin")
    ap.add_argument("--salida", default=None)
    args = ap.parse_args()

    if args.periodo:
        fecha_ini, fecha_fin = periodo_a_rango(args.periodo)
    elif args.fecha_ini and args.fecha_fin:
        fecha_ini, fecha_fin = args.fecha_ini, args.fecha_fin
    else:
        raise SystemExit("Pasa --periodo YYYY-MM o --fecha-ini/--fecha-fin")

    df = conciliar(fecha_ini, fecha_fin)
    if df.empty:
        print("Sin resultados.")
        return

    print()
    print("=" * 70)
    print(f"RESULTADO [{fecha_ini}, {fecha_fin})")
    print("=" * 70)

    principales = df[df["fila_principal"]]
    conciliables = principales[~principales["estatus"].isin(["AMBOS_CANCELADOS"])]
    ok = principales["estatus"].isin(["CONCILIA", "DIF_CENTAVOS", "AMBOS_CANCELADOS"])
    ok_no_cancel = principales[principales["estatus"] != "AMBOS_CANCELADOS"]["estatus"].isin(["CONCILIA", "DIF_CENTAVOS"])

    print(f"\nCFDI (fila principal): {len(principales)}")
    print(f"Por estatus:\n{principales['estatus'].value_counts().to_string()}")
    print(f"\nPor origen x estatus:")
    print(principales.groupby(["origen", "estatus"]).size().to_string())

    n_no_cancel = len(principales[principales["estatus"] != "AMBOS_CANCELADOS"])
    n_ok_no_cancel = ok_no_cancel.sum()
    if n_no_cancel:
        print(f"\n% que concilia (excluyendo AMBOS_CANCELADOS): {n_ok_no_cancel}/{n_no_cancel} = {100*n_ok_no_cancel/n_no_cancel:.2f}%")

    salida = args.salida or f"output/reconciliacion_emitidos_{(args.periodo or fecha_ini)}.csv"
    df.to_csv(salida, index=False)
    print(f"\nGuardado: {salida}")


if __name__ == "__main__":
    main()
