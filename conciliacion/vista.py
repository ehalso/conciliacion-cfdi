"""Convierte el DataFrame del reporte en el JSON {cols, rows, vista, agrupar} que consume la interfaz.

Vistas:
  layout  subtotales, impuestos, TOTAL, XML_MONTO y cobro solo en la primera fila del documento; las demás filas
          llevan únicamente Tipo/folio y los campos de póliza. Con agrupar=True las líneas de póliza se suman por
          cuenta contable. En registro_gasto, control_combustible, orden_compra y viaje los datos de texto
          (proveedor, UUID, XML, pago) se repiten en todas las filas del folio.
  ceco    análisis por CECO: subtotales e impuestos prorrateados en cada línea de póliza.
Las columnas sin ningún dato no se envían (salvo SIEMPRE).
"""
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

FECHAS = ("FECHA", "FECHA_POLIZA", "FECHA_CHEQUE", "FECHA_COMPLEMENTO_PAGO")
POLIZA = ("POLIZA", "NUMERO_POLIZA", "TIPO_POLIZA", "FECHA_POLIZA", "CONCEPTO_POLIZA")
REPITEN = ("registro_gasto", "control_combustible", "orden_compra", "viaje")
SIEMPRE = ("Tipo", "FOLIO", "FECHA", "SUBTOTAL_NETO", "TOTAL", "CARGO", "ABONO")
ORDEN_TIPO = {"Gasto": 0, "Compra": 1, "Indirecto": 2, "NC proveedor": 3, "CxP libre": 4, "CxP orden compra": 5}
CIFRAS_DOC = ("SUBTOTAL_0", "SUBTOTAL_16", "SUBTOTAL_EXENTA", "SUBTOTAL_NETO", "TOTAL")
SIN_CEROS = ("SUBTOTAL_0", "SUBTOTAL_16", "SUBTOTAL_EXENTA")
VISTAS = ("layout", "ceco")


@lru_cache(maxsize=1)
def catalogo() -> tuple[dict, ...]:
    ruta = Path(__file__).parent / "static" / "columnas.json"
    return tuple(json.loads(ruta.read_text(encoding="utf-8")))


def val(v):
    """Valor JSON-seguro: NaN/vacío → None, números a 2 decimales, texto recortado."""
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return str(v)
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, str):
        v = v.strip()
    elif isinstance(v, float):
        v = round(v, 2) + 0.0
    return None if v == "" else v


def columnas(d: pd.DataFrame) -> list[dict]:
    """Catálogo más las claves IMP_xxxx que traiga el DataFrame y no estén en columnas.json."""
    base = list(catalogo())
    conocidas = {c["k"] for c in base}
    extra = [{"k": k, "l": k[4:] + " Impuesto", "g": "Impuestos", "t": "n", "linea": True}
             for k in sorted(d.columns) if k.startswith("IMP_") and k not in conocidas]
    if not extra:
        return base
    i = max(j for j, c in enumerate(base) if c["g"] == "Impuestos") + 1
    return base[:i] + extra + base[i:]


def agrupar_cuenta(d: pd.DataFrame) -> pd.DataFrame:
    """Suma las líneas de póliza de cada documento por cuenta contable (CECO: el único, o VARIOS)."""
    d = d.copy()
    llave = ["Tipo", "FOLIO", "CUENTA_REGISTRO"]
    d["_net"] = d.CARGO.fillna(0) - d.ABONO.fillna(0)
    g = d.groupby(llave, sort=False, dropna=False)
    d["_net"] = g._net.transform("sum")
    d["CECO"] = np.where(g.CECO.transform("nunique") > 1, "VARIOS", g.CECO.transform("first"))
    d = d.drop_duplicates(llave).copy()
    d["CARGO"] = d._net.clip(lower=0).round(2)
    d["ABONO"] = (-d._net).clip(lower=0).round(2)
    return d.drop(columns="_net").reset_index(drop=True)


def a_datos(d: pd.DataFrame, vista: str = "layout", agrupar: bool = True) -> dict:
    layout = vista == "layout"
    d = d.reset_index(drop=True).copy()
    if "Tipo" not in d:
        d["Tipo"] = "Gasto"
    d["_t"] = d.Tipo.map(ORDEN_TIPO).fillna(9)
    d["_g"] = d.groupby(["Tipo", "FOLIO"], sort=False).ngroup()
    d = d.sort_values(["_t", "_g"], kind="stable").drop(columns=["_t", "_g"]).reset_index(drop=True)
    if layout and agrupar:
        d = agrupar_cuenta(d)

    cols = columnas(d)
    for c in cols:
        if c["k"] not in d:
            d[c["k"]] = None
    llave = d.Tipo.astype(str) + "|" + d.FOLIO.astype(str)
    primera = (llave != llave.shift()).to_numpy()
    repite = d.ORIGEN.isin(REPITEN).to_numpy()
    for k in FECHAS:
        d[k] = pd.to_datetime(d[k], errors="coerce").dt.strftime("%d-%m-%Y")

    ks = [c["k"] for c in cols]
    linea_poliza = {"Tipo", "ORIGEN", "FOLIO"} | {c["k"] for c in cols if c["g"] == "Póliza"}
    fuente = {k: "DOC_" + k if layout and "DOC_" + k in d and (k in CIFRAS_DOC or k.startswith("IMP_")) else k for k in ks}
    importes = [ks.index("CARGO"), ks.index("ABONO")]
    sin_ceros = {i for i, c in enumerate(cols)
                 if c["t"] == "n" and (c["g"] == "Impuestos" or c["k"] in SIN_CEROS)}

    filas = []
    for i, r in enumerate(d[[fuente[k] for k in ks]].itertuples(index=False)):
        fila = []
        for j, (c, v) in enumerate(zip(cols, r)):
            if layout:
                visible = primera[i] or c["k"] in linea_poliza or (repite[i] and c["t"] == "t" and c["k"] not in POLIZA)
            else:
                visible = primera[i] or c["linea"] or (repite[i] and c["k"] not in POLIZA)
            v = val(v) if visible else None
            fila.append(None if (j in sin_ceros and v == 0) else v)
        for j in importes:
            fila[j] = fila[j] or None
        filas.append(fila)

    if filas:
        usar = [j for j, c in enumerate(cols) if c["k"] in SIEMPRE or any(f[j] is not None for f in filas)]
        if len(usar) < len(cols):
            cols = [cols[j] for j in usar]
            filas = [[f[j] for j in usar] for f in filas]
    return {"cols": [{k: c[k] for k in ("k", "l", "g", "t")} for c in cols], "rows": filas,
            "vista": vista, "agrupar": bool(layout and agrupar)}
