"""Compara el reporte de Mpro (.207) contra el de Postgres (raw.*) para un periodo.

    python tools/comparar_backends.py 2026-01-01 2026-02-01 [--sin-sat] [--refrescar-mssql]

Corre `construir` una vez por backend en procesos separados (CONC_BACKEND se fija al importar) y compara los
DataFrames: filas, columnas y valores (tolerancia 0.005 en numéricos). Sale con código 1 si hay diferencias.
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent


def _generar(backend: str, fi: str, ff: str, destino: str, sat: bool) -> None:
    from conciliacion.config import mpro_desde_entorno, sat_desde_entorno
    from conciliacion.db import crear_engine, crear_engine_dw, crear_engine_sat
    from conciliacion.reporte import construir
    s = sat_desde_entorno()
    engine = crear_engine_dw(s) if backend == "postgres" else crear_engine(mpro_desde_entorno())
    d = construir(engine, fi, ff, crear_engine_sat(s) if sat and s else None)
    d.to_pickle(destino)


def _llaves(d: pd.DataFrame) -> list[str]:
    return [c for c in ("Tipo", "FOLIO", "POLIZA", "CUENTA_REGISTRO", "CECO") if c in d]


def comparar(a: pd.DataFrame, b: pd.DataFrame, tol: float = 0.005) -> list[str]:
    out = []
    if set(a.columns) != set(b.columns):
        out.append(f"columnas: solo mssql={sorted(set(a.columns) - set(b.columns))} solo pg={sorted(set(b.columns) - set(a.columns))}")
    cols = [c for c in a.columns if c in b.columns]
    out.append(f"filas: mssql={len(a)} pg={len(b)}")
    k = _llaves(a)

    def prep(d):
        d = d[cols].copy()
        d["_n"] = d.groupby(k, dropna=False).cumcount()
        return d.set_index(k + ["_n"]).sort_index()

    a, b = prep(a), prep(b)
    solo_a, solo_b = a.index.difference(b.index), b.index.difference(a.index)
    out.append(f"filas solo en mssql: {len(solo_a)}  solo en pg: {len(solo_b)}")
    for nombre, idx in (("mssql", solo_a), ("pg", solo_b)):
        for i in list(idx)[:5]:
            out.append(f"   solo {nombre}: {i}")
    com = a.index.intersection(b.index)
    a, b = a.loc[com], b.loc[com]
    for c in a.columns:
        x, y = a[c], b[c]
        num = pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")
        if num[0].notna().sum() == x.notna().sum() and num[1].notna().sum() == y.notna().sum() and x.notna().any():
            dif = ~(((num[0] - num[1]).abs() <= tol) | (num[0].isna() & num[1].isna()))
        else:
            sx, sy = x.astype("string").str.strip(), y.astype("string").str.strip()
            dif = ~((sx == sy) | (sx.isna() & sy.isna()))
        dif = dif.fillna(True).astype(bool).to_numpy()
        if dif.any():
            ej = [(i, x[i], y[i]) for i in list(x.index[dif])[:3]]
            out.append(f"   {c}: {int(dif.sum())} diferencias; ej. {ej}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("fi"); ap.add_argument("ff")
    ap.add_argument("--sin-sat", action="store_true")
    ap.add_argument("--refrescar-mssql", action="store_true", help="ignora el resultado de mssql guardado")
    ap.add_argument("--generar", choices=["mssql", "postgres"])
    ap.add_argument("--destino")
    a = ap.parse_args()
    if a.generar:
        sys.path.insert(0, str(RAIZ))
        _generar(a.generar, a.fi, a.ff, a.destino, not a.sin_sat)
        sys.exit(0)
    cache = Path.home() / ".cache" / "conciliacion_cmp"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        res = {"mssql": str(cache / f"mssql_{a.fi}_{a.ff}_{'nosat' if a.sin_sat else 'sat'}.pkl")}
        for b in ("mssql", "postgres"):
            if b == "mssql" and Path(res[b]).exists() and not a.refrescar_mssql:
                print("mssql: reutilizo", res[b], flush=True)
                continue
            if b == "postgres":
                res[b] = f"{t}/{b}.pkl"
            cmd = [sys.executable, __file__, a.fi, a.ff, "--generar", b, "--destino", res[b]] + (["--sin-sat"] if a.sin_sat else [])
            subprocess.run(cmd, check=True, env={**os.environ, "CONC_BACKEND": b})
        informe = comparar(pd.read_pickle(res["mssql"]), pd.read_pickle(res["postgres"]))
    print("\n".join(informe))
    sys.exit(1 if any("solo en mssql: 0  solo en pg: 0" not in l and l.startswith("filas solo") or "diferencias" in l for l in informe) else 0)
