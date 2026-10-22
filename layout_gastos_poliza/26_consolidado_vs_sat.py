"""V3 -- agrega al consolidado de v2 (25_consolidado_final) el bloque
"Base de datos SAT" (UUID ... Importe, de `raw_sat_api`) y el bloque de
conciliación (Existe UUID en Mpro / en SAT / Coincide existencia / Coincide
importes), cruzando por UUID. "No localizados" queda vacío (pendiente).

El UUID y el monto de Mpro (UUID, XML_MONTO) ya vienen del consolidado v2,
que los toma de Comprobante_Digital con sus reglas de deduplicación.

Uso (credenciales por Infisical: MSSQL_205_*, POSTGRES_DW_RO_*):
    python3 26_consolidado_vs_sat.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
    python3 26_consolidado_vs_sat.py --csv ../layout_gastos_60col/CONSOLIDADO_X.csv
"""
import argparse
import os
import sys
from pathlib import Path

if "PG_USER" not in os.environ and "POSTGRES_DW_RO_USERNAME" in os.environ:
    os.environ["PG_USER"] = os.environ["POSTGRES_DW_RO_USERNAME"]
    os.environ["PG_PASSWORD"] = os.environ["POSTGRES_DW_RO_PASSWORD"]

import pandas as pd

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parent / "src"))
from extract_sat_api import extract_sat_api  # noqa: E402

TOL_IMPORTE = 0.05
SI, NO = "Sí", "No"
COLS_SAT = ["UUID", "Serie UUID", "Folio UUID", "Estatus", "Tipo de CFDI", "Fecha UUID",
            "Concepto UUID", "RFC del proveedor", "Nombre del proveedor", "Importe",
            "No localizados"]
COLS_CONC = ["Existe UUID en Mpro", "Existe UUID en SAT", "Coincide existencia", "Coincide importes"]


def agregar_sat(consolidado: pd.DataFrame) -> pd.DataFrame:
    df = consolidado.copy()
    df["_uuid"] = df["UUID"].astype("string").str.strip().str.upper()
    uuids = df["_uuid"].dropna().unique().tolist()
    sat = extract_sat_api("recibidos", uuids=uuids).drop_duplicates("UUID")
    sat = sat.rename(columns={c: f"SAT {c}" if c == "UUID" else c for c in COLS_SAT})
    out = df.merge(sat, left_on="_uuid", right_on="SAT UUID", how="left")

    en_mpro = out["_uuid"].notna() & (out["_uuid"] != "")
    en_sat = out["SAT UUID"].notna()
    out["Existe UUID en Mpro"] = en_mpro.map({True: SI, False: NO})
    out["Existe UUID en SAT"] = en_sat.map({True: SI, False: NO})
    out["Coincide existencia"] = (en_mpro == en_sat).map({True: SI, False: NO})
    # el monto de Mpro se repite en cada línea de póliza del folio; se compara por línea
    dif = (pd.to_numeric(out["XML_MONTO"], errors="coerce") - out["Importe"]).abs()
    out["Coincide importes"] = (dif <= TOL_IMPORTE).map({True: SI, False: NO})
    out.loc[~(en_mpro & en_sat), "Coincide importes"] = ""
    return out.drop(columns="_uuid")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", default="2026-01-01")
    ap.add_argument("--fecha-fin", default="2026-02-01")
    ap.add_argument("--csv", help="consolidado v2 ya generado (evita consultar Mpro)")
    args = ap.parse_args()

    if args.csv:
        base = pd.read_csv(args.csv)
        etiqueta = Path(args.csv).stem
    else:
        from importlib import import_module
        base = import_module("25_consolidado_final").construir(args.fecha_ini, args.fecha_fin)
        etiqueta = f"{args.fecha_ini}_{args.fecha_fin}"

    res = agregar_sat(base)
    out = AQUI.parent / "layout_gastos_60col" / f"CONSOLIDADO_SAT_{etiqueta}.xlsx"
    out.parent.mkdir(exist_ok=True)
    res.to_excel(out, sheet_name="Recibidos", index=False)
    print(out)
    print(res[COLS_CONC].apply(pd.Series.value_counts).fillna(0).astype(int))


if __name__ == "__main__":
    main()
