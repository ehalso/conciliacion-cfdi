#!/usr/bin/env python3
"""Dump de contexto completo de los pendientes — base para la investigación
folio por folio (2026-09-09/10, sesión nocturna).

Corre el baseline universal una sola vez y guarda en `output/investigacion/`
todo lo necesario para trabajar los 149 pendientes sin volver a golpear el
bridge para lo básico:

  pendientes.csv        los CFDI que no cuadran, con subtotal/cargo/diferencia
  conciliados.csv       los que sí cuadran (para probar que un fix no rompe nada)
  resumen.csv           el universo completo
  cd_rows.csv           filas crudas de Comprobante_Digital de los pendientes
  origenes.csv          etiquetas (origen, documento) de los pendientes
  gr_header.csv         Gasto_Registro (cabecera) de los folios involucrados
  gr_documento.csv      Gasto_Registro_Documento de esos folios
  gr_control.csv        suma de Gasto_Registro_Control por (folio, Grd_ID)

Uso:  python3 investigacion/dump_contexto.py --periodo 2026-02
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "src"))

import pandas as pd  # noqa: E402

from baseline_universal import calcular  # noqa: E402
from bridge_client import run_query, rows_as_dicts, sql_quote  # noqa: E402
from config import MPRO_TARGET  # noqa: E402
from extract_origen import extract_origenes_por_uuids  # noqa: E402

SALIDA = RAIZ / "output" / "investigacion"
LOTE = 120


def en_lotes(valores, n=LOTE):
    valores = list(dict.fromkeys(valores))
    for i in range(0, len(valores), n):
        yield valores[i:i + n]


def consulta_en_lotes(plantilla: str, valores) -> pd.DataFrame:
    """plantilla debe traer {in_list}."""
    partes = []
    for lote in en_lotes(valores):
        in_list = ", ".join(sql_quote(v) for v in lote)
        filas = rows_as_dicts(run_query(MPRO_TARGET, plantilla.format(in_list=in_list)))
        if filas:
            partes.append(pd.DataFrame(filas))
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def main(periodo: str) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)

    conciliados, pendientes, resumen = calcular(periodo)
    conciliados.to_csv(SALIDA / "conciliados.csv", index=False)
    pendientes.to_csv(SALIDA / "pendientes.csv", index=False)
    resumen.to_csv(SALIDA / "resumen.csv", index=False)
    print(f"[dump] pendientes={len(pendientes)}  conciliados={len(conciliados)}")

    uuids = pendientes["uuid"].tolist()

    print("[dump] Comprobante_Digital crudo de los pendientes")
    cd = consulta_en_lotes(
        """SELECT Cd_Tabla, Cd_Documento, Cd_Timbre_UUID, Cd_Monto, Cd_Tipo_CFDI,
                  Cd_RFC_Emisor, Cd_RFC_Receptor, Cd_Serie, Cd_Serie_Folio,
                  Cd_Moneda, Cd_Tipo_Cambio, Cd_Timbre_Fecha
           FROM Comprobante_Digital WHERE Cd_Timbre_UUID IN ({in_list})""",
        uuids)
    if not cd.empty:
        cd["Cd_Timbre_UUID"] = cd["Cd_Timbre_UUID"].str.upper()
    cd.to_csv(SALIDA / "cd_rows.csv", index=False)
    print(f"     {len(cd)} filas de Comprobante_Digital")

    print("[dump] orígenes (extract_origen)")
    og = extract_origenes_por_uuids(uuids)
    og.to_csv(SALIDA / "origenes.csv", index=False)
    print(f"     {len(og)} etiquetas documento")

    folios_gr = sorted({d[:10] for d, o in zip(og["documento"].fillna(""), og["origen"].fillna(""))
                        if o.upper() == "GASTO_REGISTRO" and len(d) >= 10})
    print(f"[dump] Gasto_Registro: {len(folios_gr)} folios involucrados")

    if folios_gr:
        gr = consulta_en_lotes(
            """SELECT Gr_Folio, Gr_Fecha, Sc_Cve_Sucursal, Gr_Comentario, Gr_Referencia,
                      Gr_Tabla, Gr_Documento, Es_Cve_Estado, Oper_Alta, Fecha_Alta,
                      Gr_Genera_Cxp, Gr_Proveedor
               FROM Gasto_Registro WHERE Gr_Folio IN ({in_list})""",
            folios_gr)
        gr.to_csv(SALIDA / "gr_header.csv", index=False)

        grd = consulta_en_lotes(
            """SELECT Gr_Folio, Grd_ID, Grd_Referencia, Grd_Precio_Neto_Importe,
                      Grd_Precio_Descontado_Importe, Grd_Tipo_Cambio, Mn_Cve_Moneda
               FROM Gasto_Registro_Documento WHERE Gr_Folio IN ({in_list})""",
            folios_gr)
        grd.to_csv(SALIDA / "gr_documento.csv", index=False)

        grc = consulta_en_lotes(
            """SELECT Gr_Folio, Grd_ID, COUNT(*) AS n_lineas,
                      SUM(ABS(Grc_Importe)) AS suma_abs, SUM(Grc_Importe) AS suma_neta
               FROM Gasto_Registro_Control WHERE Gr_Folio IN ({in_list})
               GROUP BY Gr_Folio, Grd_ID""",
            folios_gr)
        grc.to_csv(SALIDA / "gr_control.csv", index=False)
        print(f"     header={len(gr)} documento={len(grd)} control={len(grc)}")

    print(f"[dump] listo -> {SALIDA}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--periodo", default="2026-02")
    main(ap.parse_args().periodo)
