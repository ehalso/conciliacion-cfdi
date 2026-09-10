#!/usr/bin/env python3
"""Reporte de cruce independiente: CFDI de retención timbrados ante el SAT
(`raw_sat.cfdi_retencion`) vs lo que mpro tiene registrado
(`Comprobante_Digital`) — puerto directo, a `bridge_client` (conexión SQL
directa, sin bridge HTTP) de la metodología ya validada en
`~/proyectos/conciliacion-master/conciliacion-emitidos/04_cruce_sat_vs_mpro.py`
(ver `docs/emitidos_retenciones.md` de este repo para el resumen y el
hallazgo).

Por qué existe aparte de `baseline_universal_emitido.py` / `main.py --tipo
emitido`: esos dos comparan mpro CONSIGO MISMO (el `Cd_XML` que el ERP
guarda, contra el documento que lo originó, o contra la póliza) — por
construcción no pueden ver un comprobante que se timbró pero el ERP nunca
registró. Este reporte usa una fuente INDEPENDIENTE — los XML que el PAC
deja en el share del SAT, cargados a Postgres sin pasar por el ERP
(`raw_sat.cfdi_retencion`, proyecto `consulta-xmls`) — y por eso sí puede
encontrar ese caso.

`raw_sat.cfdi_retencion` ya llega con el XML de retenciones parseado desde
la ingesta (`monto_total_operacion`, `monto_total_retenido`, `cve_retenc`,
...) — no hace falta bajar ni parsear XML aquí, es pura consulta SQL de los
dos lados. `raw_sat.cfdi_emitidos` (para el CFDI normal I/E/P) también trae
ya parseadas `descuento`/`ieps_trasladado`/`impuestos_locales_*` desde la
mejora de ingesta del 2026-09-10 (ver `docs/hallazgos.md`) — no se usan
todavía en este reporte (solo mira retenciones) pero quedan disponibles
para cuando se porte el resto del cruce (CFDI normal, pendiente).

Del lado mpro, un mismo CFDI de retención se registra DOS VECES bajo
`Comprobante_Digital` (gotcha ya documentado en trivasa-context,
`docs/schema/calidad-de-datos.md`): una fila con `Cd_Tabla=GASTO_REGISTRO`
y `Cd_Tipo_CFDI='RETENCIONES'` (`Cd_Monto=0`, la retención de intereses) y,
para las de dividendos, una fila hermana `Cd_Tabla=CONSTANCIA_RETENCION`
con el monto real. Se deduplica por UUID quedándose con el monto que no es
cero.

Uso:
    python3 cruce_sat_retenciones.py --periodo 2026-01
    python3 cruce_sat_retenciones.py --periodos 2026-01,2026-02,2026-03,2026-04,2026-05,2026-06
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd  # noqa: E402

from bridge_client import run_query, rows_as_dicts, sql_quote  # noqa: E402
from config import MPRO_TARGET  # noqa: E402

TOL = 0.05
RFC_TRIVASA = "TRI970922TL2"


def extract_mpro_retenciones(periodo: str) -> pd.DataFrame:
    y, m = int(periodo[:4]), int(periodo[5:7])
    fi = f"{y:04d}-{m:02d}-01"
    y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
    ff = f"{y2:04d}-{m2:02d}-01"
    sql = (
        "SELECT UPPER(LTRIM(RTRIM(Cd_Timbre_UUID))) AS uuid, Cd_Tabla AS origen, "
        "Cd_Documento AS cd_documento, Cd_Tipo_CFDI AS tipo, Cd_Monto AS cd_monto, "
        "Cd_Serie_Folio AS serie_folio, Es_Cve_Estado AS cd_estado, "
        "Cd_Timbre_Fecha AS timbrado, LTRIM(RTRIM(Cd_RFC_Receptor)) AS rfc_receptor "
        "FROM Comprobante_Digital "
        f"WHERE Cd_Timbre_Fecha >= {sql_quote(fi)} AND Cd_Timbre_Fecha < {sql_quote(ff)} "
        f"AND LTRIM(RTRIM(Cd_RFC_Emisor)) = {sql_quote(RFC_TRIVASA)} "
        "AND Cd_Timbre_UUID IS NOT NULL AND LTRIM(RTRIM(Cd_Timbre_UUID)) <> ''"
    )
    df = pd.DataFrame(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    if df.empty:
        return df
    df["uuid"] = df["uuid"].str.upper()
    df["cd_monto"] = pd.to_numeric(df["cd_monto"], errors="coerce").fillna(0.0)
    return df


def extract_sat_retencion(periodo: str) -> pd.DataFrame:
    sql = (
        "SELECT UPPER(uuid) AS uuid, cve_retenc, monto_total_operacion, "
        "monto_total_retenido, rfc_receptor, fecha_emision "
        f"FROM raw_sat.cfdi_retencion WHERE periodo = {sql_quote(periodo)}"
    )
    df = pd.DataFrame(rows_as_dicts(run_query("postgres_dw", sql)))
    if df.empty:
        return df
    df["uuid"] = df["uuid"].str.upper()
    for c in ("monto_total_operacion", "monto_total_retenido"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def cruzar(periodo: str) -> tuple[pd.DataFrame, dict]:
    mpro_raw = extract_mpro_retenciones(periodo)
    sat = extract_sat_retencion(periodo)

    mret = mpro_raw[mpro_raw["tipo"].fillna("").str.strip() == "RETENCIONES"].copy()
    extra = mpro_raw[mpro_raw["origen"] == "CONSTANCIA_RETENCION"]
    mret = pd.concat([mret, extra], ignore_index=True)
    cols_mret = ["uuid", "origen", "cd_documento", "cd_monto", "serie_folio",
                 "cd_estado", "timbrado", "rfc_receptor"]
    if not mret.empty:
        mret = (mret.sort_values("cd_monto", ascending=False)
                 .drop_duplicates("uuid")[cols_mret]
                 .rename(columns={"rfc_receptor": "rfc_receptor_mpro"}))
    else:
        mret = pd.DataFrame(columns=[c if c != "rfc_receptor" else "rfc_receptor_mpro" for c in cols_mret])

    m = sat.merge(mret, on="uuid", how="outer", indicator=True) if not sat.empty else \
        mret.assign(_merge="right_only")
    if sat.empty and not mret.empty:
        m = mret.copy()
        m["_merge"] = "right_only"
    m["cubo"] = m["_merge"].map({"both": "EN_AMBOS", "left_only": "SOLO_SAT", "right_only": "SOLO_MPRO"})
    m["periodo"] = periodo

    resumen = {
        "periodo": periodo,
        "sat": len(sat),
        "mpro": len(mret),
        "solo_sat": int((m["cubo"] == "SOLO_SAT").sum()),
        "solo_mpro": int((m["cubo"] == "SOLO_MPRO").sum()),
        "en_ambos": int((m["cubo"] == "EN_AMBOS").sum()),
    }

    ambos = m[m["cubo"] == "EN_AMBOS"].copy()
    if not ambos.empty:
        ambos = ambos[ambos["cd_monto"].fillna(0).abs() > TOL]
        if not ambos.empty:
            ambos["dif"] = ambos["monto_total_operacion"] - ambos["cd_monto"]
            resumen["en_ambos_cuadran"] = int((ambos["dif"].abs() <= TOL).sum())

    faltan = m[m["cubo"] == "SOLO_SAT"]
    resumen["faltantes_monto_operacion"] = float(faltan["monto_total_operacion"].sum()) if len(faltan) else 0.0
    resumen["faltantes_isr"] = float(faltan["monto_total_retenido"].sum()) if len(faltan) else 0.0

    return m, resumen


def run(periodos: list[str]):
    resumenes = []
    faltantes_todos = []
    for periodo in periodos:
        print(f"[{periodo}] cruzando SAT vs mpro ...")
        m, resumen = cruzar(periodo)
        resumenes.append(resumen)
        faltan = m[m["cubo"] == "SOLO_SAT"].copy()
        if not faltan.empty:
            faltantes_todos.append(faltan)
        print(f"     SAT: {resumen['sat']}  mpro: {resumen['mpro']}  "
              f"solo_SAT (faltantes en mpro): {resumen['solo_sat']}  "
              f"solo_mpro: {resumen['solo_mpro']}")

    df_resumen = pd.DataFrame(resumenes)
    total_row = {
        "periodo": "TOTAL",
        "sat": df_resumen["sat"].sum(),
        "mpro": df_resumen["mpro"].sum(),
        "solo_sat": df_resumen["solo_sat"].sum(),
        "solo_mpro": df_resumen["solo_mpro"].sum(),
        "en_ambos": df_resumen["en_ambos"].sum(),
        "faltantes_monto_operacion": df_resumen["faltantes_monto_operacion"].sum(),
        "faltantes_isr": df_resumen["faltantes_isr"].sum(),
    }
    print()
    print(pd.concat([df_resumen, pd.DataFrame([total_row])], ignore_index=True)
          [["periodo", "sat", "mpro", "solo_sat", "solo_mpro", "faltantes_monto_operacion", "faltantes_isr"]]
          .to_string(index=False))

    if faltantes_todos:
        faltantes = pd.concat(faltantes_todos, ignore_index=True)
        cols = ["periodo", "uuid", "cve_retenc", "monto_total_operacion", "monto_total_retenido",
                "rfc_receptor", "fecha_emision"]
        faltantes = faltantes[cols].sort_values(["periodo", "monto_total_operacion"], ascending=[True, False])
        out = Path("output") / f"cruce_sat_retenciones_faltantes_{periodos[0]}_a_{periodos[-1]}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        faltantes.to_csv(out, index=False)
        print(f"\nFaltantes en mpro: {len(faltantes)} — ${faltantes['monto_total_operacion'].sum():,.2f} "
              f"(${faltantes['monto_total_retenido'].sum():,.2f} de retención)")
        print(f"Detalle: {out}")
    else:
        print("\nSin faltantes en el rango pedido.")

    return df_resumen, faltantes_todos


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--periodo", help="YYYY-MM")
    g.add_argument("--periodos", help="Varios periodos separados por coma")
    args = ap.parse_args()
    periodos = [args.periodo] if args.periodo else [p.strip() for p in args.periodos.split(",")]
    run(periodos)
