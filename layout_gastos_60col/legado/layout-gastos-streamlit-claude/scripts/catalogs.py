"""Catalogos SAT usados para enriquecer columnas crudas del layout (v2).

Fuente: catalogo oficial c_FormaPago del SAT (Anexo 20 CFDI). Solo se listan los codigos vistos
en los datos de Trivasa hasta ahora; si aparece un codigo nuevo, queda el crudo (no truena).
"""

FORMA_PAGO_SAT = {
    "01": "Efectivo",
    "02": "Cheque nominativo",
    "03": "Transferencia electronica de fondos",
    "04": "Tarjeta de credito",
    "05": "Monedero electronico",
    "06": "Dinero electronico",
    "08": "Vales de despensa",
    "12": "Dacion en pago",
    "13": "Pago por subrogacion",
    "14": "Pago por consignacion",
    "15": "Condonacion",
    "17": "Compensacion",
    "23": "Novacion",
    "24": "Confusion",
    "25": "Remision de deuda",
    "26": "Prescripcion o caducidad",
    "27": "A satisfaccion del acreedor",
    "28": "Tarjeta de debito",
    "29": "Tarjeta de servicios",
    "30": "Aplicacion de anticipos",
    "31": "Intermediario pagos",
    "99": "Por definir",
}


def describe_forma_pago(codigo):
    if codigo is None:
        return None
    codigo = str(codigo).strip()
    return FORMA_PAGO_SAT.get(codigo, codigo)


def enrich_forma_pago(df, column="XML FORMA PAGO", new_column="XML FORMA PAGO (desc)"):
    if column in df.columns:
        df = df.copy()
        df[new_column] = df[column].map(describe_forma_pago)
    return df
