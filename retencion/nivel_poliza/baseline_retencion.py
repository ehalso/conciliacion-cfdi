#!/usr/bin/env python3
"""Nivel 3 de conciliación de retención (intereses a prestamistas/
inversionistas terceros, `cve_retenc=16`) — GRANULAR por CFDI, mismo método
que `recibidos/nivel_poliza/baseline_universal.py`:

    SAT (raw_sat.cfdi_retencion) -> ubicar el UUID en Comprobante_Digital
    -> de ahí sacar su(s) documento(s) -> sumar el cargo real de TODOS los
    documentos ligados a ese UUID -> comparar contra el importe del CFDI.

No se asume de antemano cuál `Cd_Tabla` trae el cargo — eso se lee de
`Comprobante_Digital` para cada UUID, igual que hace `baseline_universal.py`
con TODOS los orígenes de recibidos. Lo único especial (también igual que
`baseline_universal.py`) es que `GASTO_REGISTRO` usa su propio extractor
granular (`extract_gasto_registro_granular`, llave real `Gr_Folio+Grd_ID`,
`Gasto_Registro_Control.Grc_Importe`) en vez del genérico por
`Pd_Referencia`, porque un mismo folio corto puede traer varios renglones.
Cualquier otro origen que aparezca (`CONSTANCIA_RETENCION` incluido, si
algún UUID lo trajera) pasa por el extractor genérico
`extract_poliza_por_origen` — que para `CONSTANCIA_RETENCION` en la
práctica no aporta nada (no es una tabla contabilizable en
`Poliza_Configuracion_Tabla`, ver trivasa-context/docs/proyectos/
poliza-explor/configuracion-polizas.md), pero no se descarta a ciegas.

A diferencia del intento anterior de este archivo (un atajo que ubicaba la
póliza por `Poliza_Configuracion` + fecha y comparaba SOLO el total del
mes): esto es CFDI por CFDI, y por diseño **no se espera 100%** — un CFDI
sin ninguna fila en `Comprobante_Digital` (el mecanismo de re-timbrado ya
documentado) queda como pendiente aquí, aunque su dinero ya esté
contabilizado bajo otro folio/periodo. Ese es el punto: este nivel sirve
para DETECTAR esos casos, no para esconderlos promediando por mes.

Uso:
    python3 baseline_retencion.py --periodo 2026-02
    python3 baseline_retencion.py --periodos 2025-11,2026-01,2026-02
    python3 baseline_retencion.py --periodo 2026-02 --salida output/retencion_cfdi_2026-02.xlsx
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pandas as pd  # noqa: E402

from extract_origen import extract_origenes_por_uuids  # noqa: E402
from extract_gasto_registro import extract_gasto_registro_granular  # noqa: E402
from extract_poliza_por_origen import extract_poliza_por_origen  # noqa: E402
from report import write_report  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from extract_poliza_retencion import extract_sat_retencion_intereses  # noqa: E402

TOL = 1.00
ORIGEN_GRANULAR = {"GASTO_REGISTRO"}


def calcular(periodo: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    print(f"[1/3] SAT retención intereses (cve_retenc=16), periodo fiscal {periodo}")
    sat = extract_sat_retencion_intereses(periodo)
    print(f"      {len(sat)} CFDI")

    if sat.empty:
        vacio = pd.DataFrame(columns=["uuid", "fecha_emision", "rfc_receptor", "nombre_receptor",
                                       "monto_total_operacion", "cargo_agregado", "diferencia"])
        return vacio, vacio, vacio

    print("[2/3] Comprobante_Digital: TODOS los orígenes de cada UUID (cualquier Cd_Tabla, sin asumir cuál)")
    origenes = extract_origenes_por_uuids(sat["uuid"].tolist())
    origenes = origenes.dropna(subset=["documento"]).copy()
    if not origenes.empty:
        origenes["documento_real"] = origenes["documento"].str.slice(0, 10)
        origenes["origen_up"] = origenes["origen"].str.upper()
        # Mismo dedup que baseline_universal: por folio corto para orígenes
        # normales, por folio+Grd_ID (14 car.) para GASTO_REGISTRO (el mismo
        # documento puede venir capturado dos veces, en formato de 14 y de 18
        # caracteres, con el mismo monto — sumar ambas filas duplica el cargo).
        origenes["_dedup_doc"] = origenes["documento_real"].where(
            ~origenes["origen_up"].isin(ORIGEN_GRANULAR), origenes["documento"].str.slice(0, 14))
        origenes = origenes.drop_duplicates(subset=["uuid", "origen_up", "_dedup_doc"]).drop(columns=["_dedup_doc"])
        print(f"      {origenes['uuid'].nunique()}/{len(sat)} CFDI con al menos 1 etiqueta en mpro"
              f" — orígenes encontrados: {sorted(origenes['origen'].unique())}")
    else:
        print(f"      0/{len(sat)} CFDI con alguna etiqueta en mpro")

    print("[3/3] Cargo por origen: GASTO_REGISTRO vía Gasto_Registro_Control (granular); el resto, genérico vía Poliza_Detalle")
    cargo_partes = []
    folios_gasto_por_uuid = pd.Series(dtype=object, name="gasto_folios")
    if not origenes.empty:
        gasto = origenes[origenes["origen_up"].isin(ORIGEN_GRANULAR)]
        docs_gasto = gasto["documento"].dropna().unique().tolist()
        if docs_gasto:
            gasto_cargo = extract_gasto_registro_granular(docs_gasto)
            gasto_cargo["cargo"] = gasto_cargo["cargo"].fillna(0.0)
            gasto_map = gasto[["uuid", "documento"]].merge(gasto_cargo, on="documento", how="left")
            gasto_map["cargo"] = gasto_map["cargo"].fillna(0.0)
            cargo_partes.append(gasto_map[["uuid", "cargo"]])
            folios_gasto_por_uuid = gasto_map.groupby("uuid")["folio"].apply(
                lambda s: ", ".join(sorted({str(x) for x in s if pd.notna(x)}))).rename("gasto_folios")

        otros_origenes_presentes = sorted(o for o in origenes["origen"].unique()
                                           if o.upper() not in ORIGEN_GRANULAR)
        for origen in otros_origenes_presentes:
            docs = origenes.loc[origenes["origen"] == origen, "documento_real"].dropna().unique().tolist()
            if not docs:
                continue
            pol = extract_poliza_por_origen(origen, docs)
            if pol.empty:
                print(f"      origen '{origen}': {len(docs)} documento(s), 0 con cargo/abono en póliza (no aporta)")
                continue
            pol = pol.rename(columns={"documento": "documento_real"})
            mapa = origenes.loc[origenes["origen"] == origen, ["uuid", "documento_real"]]
            merged_ext = mapa.merge(pol[["documento_real", "cargo"]], on="documento_real", how="left")
            cargo_partes.append(merged_ext[["uuid", "cargo"]])
            print(f"      origen '{origen}': {len(docs)} documento(s) -> {len(pol)} con cargo/abono en póliza")

    if cargo_partes:
        cargo_df = pd.concat(cargo_partes, ignore_index=True)
        cargo_df["cargo"] = cargo_df["cargo"].fillna(0.0)
        cargo_por_uuid = cargo_df.groupby("uuid")["cargo"].sum().rename("cargo_agregado")
    else:
        cargo_por_uuid = pd.Series(dtype=float, name="cargo_agregado")

    resumen = sat.set_index("uuid").join(cargo_por_uuid, how="left").join(folios_gasto_por_uuid, how="left")
    resumen = resumen.reset_index()
    resumen["cargo_agregado"] = resumen["cargo_agregado"].fillna(0.0)
    resumen["en_mpro"] = resumen["uuid"].isin(set(origenes["uuid"])) if not origenes.empty else False
    resumen["diferencia"] = (resumen["cargo_agregado"] - resumen["monto_total_operacion"]).round(2)
    resumen["cuadra"] = resumen["diferencia"].abs() <= TOL

    def motivo(row):
        if row["cuadra"]:
            return "OK"
        if not row["en_mpro"]:
            return "no encontrado en Comprobante_Digital (ningún Cd_Tabla)"
        if row["cargo_agregado"] <= TOL:
            return "etiquetado pero sin cargo (stub Cd_Monto=0 / Gasto_Registro_Control vacío)"
        return "cargo != importe CFDI"

    resumen["motivo_pendiente"] = resumen.apply(motivo, axis=1)

    cols = ["uuid", "fecha_emision", "rfc_receptor", "nombre_receptor",
            "monto_total_operacion", "gasto_folios", "cargo_agregado", "diferencia"]
    conciliados = resumen[resumen["cuadra"]][cols].copy()
    pendientes = resumen[~resumen["cuadra"]][cols + ["motivo_pendiente"]].copy()

    return conciliados, pendientes, resumen


def run(periodos: list[str], salida: str | None = None):
    detalle_partes = []
    resumen_partes = []
    for periodo in periodos:
        conciliados, pendientes, resumen = calcular(periodo)
        resumen = resumen.assign(periodo=periodo) if not resumen.empty else resumen
        total = len(conciliados) + len(pendientes)
        pct = (len(conciliados) / total * 100) if total else 0.0
        print(f"  {periodo}: {len(conciliados)}/{total} CFDI conciliados ({pct:.1f}%)")
        conciliados = conciliados.assign(periodo=periodo)
        pendientes = pendientes.assign(periodo=periodo)
        detalle_partes.append(pd.concat([conciliados.assign(estatus="CONCILIADO"),
                                          pendientes.assign(estatus="PENDIENTE")], ignore_index=True))
        resumen_partes.append(resumen)

    detalle = pd.concat(detalle_partes, ignore_index=True) if detalle_partes else pd.DataFrame()
    resumen_todo = pd.concat(resumen_partes, ignore_index=True) if resumen_partes else pd.DataFrame()

    if not detalle.empty:
        n_ok = int((detalle["estatus"] == "CONCILIADO").sum())
        print(f"\nTotal: {n_ok}/{len(detalle)} CFDI conciliados ({n_ok/len(detalle)*100:.1f}%).")
        if n_ok < len(detalle):
            print(f"{len(detalle) - n_ok} pendientes — ver columna 'motivo_pendiente' en el detalle.")

    if salida and not detalle.empty:
        resumen_estatus = (detalle.groupby(["periodo", "estatus"])
                           .agg(conteo=("uuid", "count"), monto=("monto_total_operacion", "sum"))
                           .reset_index())
        Path(salida).parent.mkdir(parents=True, exist_ok=True)
        write_report(detalle.rename(columns={"estatus": "estatus"}), resumen_estatus, salida)
        print(f"\nReporte: {salida}")

    return detalle, resumen_todo


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--periodo", help="Periodo fiscal único, formato YYYY-MM")
    g.add_argument("--periodos", help="Varios periodos separados por coma, ej. 2025-11,2026-01,2026-02")
    ap.add_argument("--salida", default=None, help="Ruta .xlsx opcional para el reporte")
    args = ap.parse_args()

    periodos = args.periodos.split(",") if args.periodos else [args.periodo]
    run(periodos, args.salida)


if __name__ == "__main__":
    main()
