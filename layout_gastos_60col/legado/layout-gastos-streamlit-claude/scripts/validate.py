"""Comprobacion cuantitativa: suma de Cargo (poliza) vs Subtotal Neto (cabecera) por operacion.
Ver docs/03_hito_v1.md."""
import argparse
import pandas as pd
from layout_gastos_v1 import extract_header, extract_poliza


def reconcile(start_date: str, end_date_exclusive: str) -> pd.DataFrame:
    h = extract_header(start_date, end_date_exclusive)
    p = extract_poliza(start_date, end_date_exclusive)
    hs = h.groupby("Operacion (ID)")["Subtotal Neto"].sum().rename("subtotal_neto")
    ps = p.groupby("Operacion (ID)")[["Cargo", "Abono"]].sum()
    cmp = pd.concat([hs, ps], axis=1).fillna(0)
    cmp["neto_poliza"] = cmp["Cargo"] - cmp["Abono"]
    cmp["diferencia"] = cmp["neto_poliza"] - cmp["subtotal_neto"]
    return cmp.reset_index()


def summarize(cmp: pd.DataFrame) -> dict:
    total_subtotal = cmp["subtotal_neto"].sum()
    total_neto = cmp["neto_poliza"].sum()
    gap_pct = (total_neto - total_subtotal) / total_subtotal * 100 if total_subtotal else float("nan")
    return {
        "folios": len(cmp),
        "total_subtotal_neto": total_subtotal,
        "total_cargo": cmp["Cargo"].sum(),
        "total_abono": cmp["Abono"].sum(),
        "total_neto_poliza": total_neto,
        "brecha_pct": gap_pct,
        "folios_sin_cargo": int((cmp["neto_poliza"] == 0).sum()),
        "folios_con_diferencia_mayor_1": int((cmp["diferencia"].abs() > 1).sum()),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("start")
    parser.add_argument("end_exclusive")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    cmp = reconcile(args.start, args.end_exclusive)
    summary = summarize(cmp)
    for k, v in summary.items():
        print(f"{k}: {v}")
    if args.out:
        cmp.sort_values("diferencia", key=abs, ascending=False).to_csv(args.out, index=False)
        print(f"guardado: {args.out}")
