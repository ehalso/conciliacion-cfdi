"""Normaliza el reporte unificado: cargo/abono, prorrateo de cifras por línea de póliza, totales y etiquetas."""
import numpy as np
import pandas as pd

FORMA_SAT = {
    "01": "Efectivo", "02": "Cheque nominativo", "03": "Transferencia electrónica de fondos", "04": "Tarjeta de crédito",
    "05": "Monedero electrónico", "06": "Dinero electrónico", "08": "Vales de despensa", "12": "Dación en pago",
    "13": "Pago por subrogación", "14": "Pago por consignación", "15": "Condonación", "17": "Compensación",
    "23": "Novación", "24": "Confusión", "25": "Remisión de deuda", "26": "Prescripción o caducidad",
    "27": "A satisfacción del acreedor", "28": "Tarjeta de débito", "29": "Tarjeta de servicios",
    "30": "Aplicación de anticipos", "31": "Intermediario pagos", "99": "Por definir",
}
METODO_SAT = {"PUE": "PUE - Pago en una sola exhibición", "PPD": "PPD - Pago en parcialidades o diferido"}
ORIGEN = {
    "GASTO_DIRECTO": "registro_gasto", "COMPROBACION_GASTO": "comprobacion_gasto", "ORDEN_COMPRA": "orden_compra",
    "CONTROL_COMBUSTIBLE": "control_combustible", "VIAJE": "viaje", "GASTO_RECLASIFICACION": "gasto_reclasificacion",
    "CONSUMO_INTERNO": "consumo_interno", "GASTO_REGISTRO_NOMINA": "gasto_registro_nomina",
}
FORMA_PAGO_CHEQUE = "0002"

_OPCIONALES = ("R_N", "R_MONTO", "R_SERIE", "R_FOLIO_XML", "FP_CVE", "TIPO_COMPROBANTE", "XML_MONTO", "XML_SERIE",
               "XML_FOLIO", "NUMERO_FACTURA", "FECHA_CHEQUE", "ORIGEN")
_TEXTO = ("TIPO_COMPROBANTE", "XML_SERIE", "XML_FOLIO", "NUMERO_FACTURA", "R_SERIE", "R_FOLIO_XML", "FP_CVE", "ORIGEN")


def _vacio(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v))


def _forma_sat(v):
    if _vacio(v) or str(v).strip() == "":
        return None
    v = str(v).strip()
    return v if v == "VARIOS" else f"{v} - {FORMA_SAT.get(v, '')}".rstrip(" -")


def _metodo_sat(v):
    return METODO_SAT.get(str(v).strip(), v) if v is not None and str(v).strip() != "" else None


def _origen(o):
    return None if _vacio(o) else ORIGEN.get(o, str(o).lower())


def post(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    if "Tipo" not in d:
        d["Tipo"] = "Gasto"
    for c in _OPCIONALES:
        if c not in d:
            d[c] = np.nan
    for c in _TEXTO:
        d[c] = d[c].astype(object)

    imp_cols = [c for c in d.columns if c.startswith("IMP_")]
    valores = ["SUBTOTAL_0", "SUBTOTAL_16", "SUBTOTAL_EXENTA", "SUBTOTAL_NETO"] + imp_cols
    for c in ["CARGO", "ABONO", "R_N", "R_MONTO", "XML_MONTO"] + valores:
        d[c] = pd.to_numeric(d[c], errors="coerce").astype(float)

    # CARGO y ABONO: neto positivo en cargo, neto negativo en abono (valor absoluto)
    neto = d.CARGO.fillna(0) - d.ABONO.fillna(0)
    d["CARGO"] = neto.clip(lower=0).round(2)
    d["ABONO"] = (-neto).clip(lower=0).round(2)

    # Gasto trae cifras por (FOLIO, CECO) y una línea de póliza por CECO: se prorratean por peso de la línea.
    # Los demás tipos traen cifras por documento.
    d["_net"] = d.CARGO - d.ABONO
    d["_abs"] = d._net.abs()
    d["_gk"] = np.where(d.Tipo == "Gasto", d.CECO.fillna("").astype(str), "")
    g = d.groupby(["Tipo", "FOLIO", "_gk"], sort=False)
    n = g.FOLIO.transform("size")
    suma_abs = g._abs.transform("sum")
    w = np.where(n == 1, 1.0, np.where(suma_abs > 0, d._abs / suma_abs.replace(0, np.nan), np.nan))
    primera = (g.cumcount() == 0).astype(float)
    w = np.where(np.isnan(w), primera, w)
    for c in valores:
        d[c] = d[c] * w

    # sin documento (reclasificación, nómina, consumo interno): subtotal neto = cargo - abono de la póliza
    sin = d.SUBTOTAL_NETO.isna() | (d.ORIGEN.isin(["CONSUMO_INTERNO"]) & (d.SUBTOTAL_NETO.fillna(0) == 0))
    d.loc[sin, "SUBTOTAL_NETO"] = d.loc[sin, "_net"]

    # valor del documento completo (suma de sus líneas prorrateadas)
    por_doc = d.groupby(["Tipo", "FOLIO"], sort=False)
    for c in valores:
        d["DOC_" + c] = por_doc[c].transform("sum").round(2)
    d["DOC_TOTAL"] = (d.DOC_SUBTOTAL_NETO.fillna(0) + d[["DOC_" + c for c in imp_cols]].fillna(0).sum(axis=1)).round(2)
    for c in valores:
        d[c] = d[c].round(2)
    d["DESCUENTO"] = np.nan
    d["DESCUENTO_GLOBAL"] = np.nan
    d["TOTAL"] = (d.SUBTOTAL_NETO.fillna(0) + d[imp_cols].fillna(0).sum(axis=1)).round(2)

    fp = d.FP_CVE
    d["CHEQUE"] = np.where(fp.isna(), None, np.where(fp == FORMA_PAGO_CHEQUE, "SI", "NO"))

    # retenciones: un CFDI de retenciones sustituye al XML del documento; varios → VARIOS
    r = d.R_N.fillna(0) >= 1
    d.loc[r & (d.R_N == 1), "TIPO_COMPROBANTE"] = "R - Retenciones e información de pagos"
    d.loc[r & (d.R_N >= 2), "TIPO_COMPROBANTE"] = "VARIOS"
    uno = r & (d.R_N == 1)
    d.loc[uno, "XML_MONTO"] = d.R_MONTO[uno]
    d.loc[uno, "XML_SERIE"] = d.R_SERIE[uno]
    d.loc[uno, "XML_FOLIO"] = d.R_FOLIO_XML[uno]
    d.loc[uno, "NUMERO_FACTURA"] = d.R_FOLIO_XML[uno]

    d["XML_FORMA_PAGO"] = d.XML_FORMA_PAGO.map(_forma_sat)
    d["XML_METODO_PAGO"] = d.XML_METODO_PAGO.map(_metodo_sat)
    d["ORIGEN"] = d.ORIGEN.map(_origen)
    d["FECHA_CHEQUE"] = pd.to_datetime(d.FECHA_CHEQUE, errors="coerce").dt.strftime("%Y-%m-%d")
    d.loc[d.FECHA_CHEQUE == "1900-01-01", "FECHA_CHEQUE"] = None
    return d.drop(columns=["_net", "_abs", "_gk"])
