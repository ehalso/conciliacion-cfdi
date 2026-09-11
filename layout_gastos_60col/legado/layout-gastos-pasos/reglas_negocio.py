"""
Reglas de negocio del layout de gastos -- toda la logica de "elegir un
valor representativo cuando hay mas de uno" vive aqui, no en SQL.

Convencion: cada funcion recibe un DataFrame CRUDO (a nivel documento/pago/
XML/poliza, tal como sale de raw_*.sql) y devuelve un DataFrame a nivel
FOLIO (1 fila por folio), con las columnas de decision ya resueltas
('VARIOS' cuando aplica). Cada funcion valida su propia unicidad al final.
"""
import pandas as pd


def resolver_proveedor(documentos: pd.DataFrame) -> pd.DataFrame:
    """Proveedor/moneda representativos del folio.

    Se toma el documento de mayor importe neto. Moneda es siempre uniforme
    dentro de un folio (confirmado 1425/1425, enero 2026); proveedor casi
    siempre lo es (1406/1425) -- se marca PROVEEDOR_MULTIPLE='SI' cuando no.
    """
    d = documentos.sort_values(["FOLIO", "Grd_Precio_Neto_Importe", "Grd_ID"],
                                ascending=[True, False, True])
    repr_ = d.groupby("FOLIO", as_index=False).first()[["FOLIO", "Pv_Cve_Proveedor", "Mn_Cve_Moneda"]]

    n_prov = documentos.groupby("FOLIO")["Pv_Cve_Proveedor"].nunique().rename("n_proveedores")
    repr_ = repr_.merge(n_prov, on="FOLIO", how="left")
    repr_["PROVEEDOR_MULTIPLE"] = (repr_["n_proveedores"] > 1).map({True: "SI", False: "NO"})
    repr_ = repr_.drop(columns="n_proveedores")

    assert repr_["FOLIO"].is_unique
    return repr_


def resolver_referencia(documentos: pd.DataFrame) -> pd.DataFrame:
    """FACTURA_REF (columna 11) = Grd_Referencia. 'VARIOS' si el folio
    tiene documentos con referencia distinta entre si."""
    d = documentos[documentos["Grd_Referencia"].notna() & (documentos["Grd_Referencia"].str.strip() != "")]
    agg = d.groupby("FOLIO")["Grd_Referencia"].agg(["nunique", "first"]).reset_index()
    agg["FACTURA_REF"] = agg.apply(lambda r: "VARIOS" if r["nunique"] >= 2 else r["first"], axis=1)

    out = agg[["FOLIO", "FACTURA_REF"]]
    assert out["FOLIO"].is_unique
    return out


def resolver_pago(pagos: pd.DataFrame) -> pd.DataFrame:
    """Pago representativo (Banco/Cuenta/Forma de pago) + Monto Cobrado
    (suma de TODOS los pagos, no solo el representativo).

    Prioridad de representante: forma de pago con instrumento bancario
    real (0001/0002/0003) primero, luego mayor importe absoluto.
    """
    INSTRUMENTO_REAL = {"0001", "0002", "0003"}
    p = pagos.copy()
    p["prioridad"] = (~p["Fp_Cve_Forma_Pago"].isin(INSTRUMENTO_REAL)).astype(int)
    p["importe_abs"] = p["Pc_Importe"].abs()
    p = p.sort_values(["FOLIO", "prioridad", "importe_abs", "Pc_ID"], ascending=[True, True, False, True])
    repr_ = p.groupby("FOLIO", as_index=False).first()[
        ["FOLIO", "Fp_Cve_Forma_Pago", "Pc_Banco", "Pc_Cuenta_Bancaria", "Pc_Documento", "Pc_Tabla"]
    ]

    monto = pagos.groupby("FOLIO", as_index=False)["Pc_Importe"].sum().rename(columns={"Pc_Importe": "MONTO_COBRADO"})
    out = repr_.merge(monto, on="FOLIO", how="outer")

    assert out["FOLIO"].is_unique
    return out


def resolver_cheque(pago_repr: pd.DataFrame, cheques: pd.DataFrame) -> pd.DataFrame:
    """Fecha/Numero de cheque, solo para pagos representativos vía Cheque."""
    candidatos = pago_repr[pago_repr["Pc_Tabla"] == "Cheque"][["FOLIO", "Pc_Documento"]]
    out = candidatos.merge(cheques, left_on="Pc_Documento", right_on="Ch_Folio", how="left")
    out = out[["FOLIO", "Ch_Fecha", "Ch_Folio"]]

    assert out["FOLIO"].is_unique
    return out


def resolver_comprobante_pago(comprobantes: pd.DataFrame) -> pd.DataFrame:
    """CFDI Comprobante de pago (columna 10). 'VARIOS' si 2+ UUID distintos."""
    agg = comprobantes.groupby("FOLIO")["Pcc_Timbre_UUID"].agg(["nunique", "min"]).reset_index()
    agg["CFDI_COMPROBANTE_PAGO"] = agg.apply(lambda r: "VARIOS" if r["nunique"] >= 2 else r["min"], axis=1)

    out = agg[["FOLIO", "CFDI_COMPROBANTE_PAGO"]]
    assert out["FOLIO"].is_unique
    return out


def resolver_xml(xml: pd.DataFrame) -> pd.DataFrame:
    """Todas las columnas de Comprobante_Digital (UUID, fecha, tipo,
    serie/folio, RFC emisor, monto, metodo/forma de pago, uso CFDI).
    'VARIOS' (o NULL para el monto) si el folio tiene 2+ UUID distintos.
    """
    TIPO_CFDI = {"I": "Ingreso", "E": "Egreso", "D": "Diario"}

    n_uuid = xml.groupby("FOLIO")["Cd_Timbre_UUID"].nunique().rename("n_uuid")
    x = xml.sort_values(["FOLIO", "Cd_Timbre_UUID"]).groupby("FOLIO", as_index=False).first()
    x = x.merge(n_uuid, on="FOLIO")

    varios = x["n_uuid"] >= 2

    out = pd.DataFrame({"FOLIO": x["FOLIO"]})
    out["UUID"] = x["Cd_Timbre_UUID"].where(~varios, "VARIOS")
    out["UUID_4"] = x["Cd_Timbre_UUID"].str[:4].where(~varios, "VARIOS")
    out["FECHA_FACTURA"] = x["Cd_Timbre_Fecha"].where(~varios, "VARIOS")
    out["TIPO_COMPROBANTE"] = x["Cd_Tipo_CFDI"].map(TIPO_CFDI).where(~varios, "VARIOS")
    out["XML_SERIE"] = x["Cd_Serie"].where(~varios, "VARIOS")
    out["XML_FOLIO"] = x["Cd_Serie_Folio"].where(~varios, "VARIOS")
    out["NUMERO_FACTURA"] = x["Cd_Serie_Folio"].where(~varios, "VARIOS")  # mismo dato, dos nombres de layout
    out["XML_RFC_EMISOR"] = x["Cd_RFC_Emisor"].where(~varios, "VARIOS")
    out["XML_MONTO"] = x["Cd_Monto"].where(~varios, pd.NA)  # numerico: NULL, no 'VARIOS'
    out["XML_METODO_PAGO"] = x["METODO_PAGO"].where(~varios, "VARIOS")
    out["XML_FORMA_PAGO"] = x["Cd_Forma_Pago"].where(~varios, "VARIOS")
    out["CLAVE_USO_BIEN_SERVICIO"] = x["Cd_Uso_CFDI"].where(~varios, "VARIOS")

    assert out["FOLIO"].is_unique
    return out


def resolver_poliza(polizas: pd.DataFrame) -> pd.DataFrame:
    """Fecha/Tipo/Numero/Concepto de poliza. 'VARIOS' si 2+ polizas."""
    n_pol = polizas.groupby("FOLIO")["Pl_Folio"].nunique().rename("n_polizas")
    p = polizas.sort_values(["FOLIO", "Pl_Folio"]).groupby("FOLIO", as_index=False).first()
    p = p.merge(n_pol, on="FOLIO")

    varios = p["n_polizas"] >= 2

    out = pd.DataFrame({"FOLIO": p["FOLIO"]})
    out["FECHA_POLIZA"] = p["Pl_Fecha"].where(~varios, "VARIOS")
    out["TIPO_POLIZA"] = p["Pl_Tipo"].where(~varios, pd.NA)  # numerico: NULL, no 'VARIOS'
    out["NUMERO_POLIZA"] = p["Pl_Numero"].where(~varios, "VARIOS")
    out["CONCEPTO_POLIZA"] = p["Pl_Comentario"].where(~varios, "VARIOS")

    assert out["FOLIO"].is_unique
    return out


def resolver_cobrado_efectivo_cheque(pago_repr: pd.DataFrame) -> pd.DataFrame:
    """Columnas 7-9 (Cobrado Efectivo / Cheque-Transferencia / Cheque),
    derivadas del codigo de forma de pago del pago representativo.
    """
    out = pago_repr[["FOLIO", "Fp_Cve_Forma_Pago"]].copy()
    fp = out["Fp_Cve_Forma_Pago"]

    out["COBRADO_EFECTIVO"] = fp.map(lambda v: None if pd.isna(v) else ("SI" if v == "0001" else "NO"))
    out["COBRADO_CHEQUE_TRANSFERENCIA"] = fp.map(lambda v: None if pd.isna(v) else ("SI" if v in ("0002", "0003") else "NO"))
    out["CHEQUE"] = fp.map(lambda v: None if pd.isna(v) else ("SI" if v == "0002" else "NO"))

    return out.drop(columns="Fp_Cve_Forma_Pago")
