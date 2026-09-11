"""Catálogo de cuentas contables de mpro y su clasificación por familia.

Fuente: `Cuenta_Contable` en TRIVASADB3 (`mssql_205`, ver src/config.py).
Columnas reales (confirmadas en vivo 2026-09-11, INFORMATION_SCHEMA):

    Cc_Cve_Cuenta_Contable  nvarchar(30)  clave jerárquica punteada
    Cc_Descripcion          nvarchar(70)
    Cc_Acumula              nvarchar(30)  cuenta padre a la que acumula
    Cc_Tipo                 char(2)       '01' detalle / '03' agrupador de estado financiero
    Cc_Registro             char(2)
    Cc_Titulo               char(2)       '01' activo '02' pasivo '03' capital '04' resultados '05' orden
    Cc_Naturaleza           char(2)       'DE' deudora / 'AC' acreedora
    Cc_Resultado            char(2)       'SI' cuenta de resultados / 'NO' de balance
    Cc_Grupo_Cuenta_Contable nvarchar(6)
    Es_Cve_Estado           nvarchar(4)   'AC' activa

La clave es JERÁRQUICA y con longitud variable: `1170`, `1170.002`,
`1170.002.001`, y en inventarios hasta `1140.015.002.092`. El primer
segmento (4 dígitos) es la cuenta mayor y es lo único estable para
agrupar — de ahí `raiz()`.

Las cuentas de ORDEN son las de raíz de 5 dígitos (`10100`..`10600`,
grupo `E.*`: Valores Ajenos / Contingentes / De Control). Todo el pipeline
de conciliación las excluye con `NOT LIKE '10[1-6]00%'` — ver el comentario
largo en `src/extract_poliza_por_origen.py` sobre por qué el filtro por
texto de `Poliza_Configuracion.Pc_Descripcion` no basta.
"""
from __future__ import annotations

import pandas as pd

from bridge_client import run_query, rows_as_dicts
from config import MPRO_TARGET

# --- Raíces (cuenta mayor) confirmadas en vivo 2026-09-11 -------------------
# Descripción tal cual la trae el catálogo, para no re-consultar en cada uso.
RAICES: dict[str, str] = {
    "1110": "EFECTIVO Y EQUIVALENTES DE EFECTIVO",
    "1120": "CUENTAS POR COBRAR A CLIENTES",
    "1130": "CUENTAS POR COBRAR OTROS DEUDORES",
    "1140": "INVENTARIOS",
    "1150": "PAGOS ANTICIPADOS",
    "1160": "ANTICIPO A IMPUESTOS",
    "1170": "IVA ACREDITABLE",
    "1180": "CONTRIBUCIONES A FAVOR",
    "1210": "PROPIEDADES, PLANTA Y EQUIPO",
    "1220": "REVALUACION DE PROPIEDADES, PLANTA Y EQUIPO",
    "1230": "DEPRECIACION ACUMULADA",
    "1240": "DEPRECIACION ACUMULADA REVALUACION PROPIEDADES, PLANTA Y EQUIPO",
    "1250": "ACTIVOS INTANGIBLES",
    "1260": "REVALUACION DE ACTIVOS INTANGIBLES",
    "1270": "AMORTIZACION ACUMULADA",
    "1280": "AMORTIZACION ACUMULADA REVALUACION DE ACTIVOS INTANGIBLES",
    "1290": "ACTIVOS TOTALMENTE DEPRECIADOS",
    "1300": "PAGOS ANTICIPADOS",
    "2110": "PROVEEDORES",
    "2120": "ACREEDORES",
    "2130": "DOCUMENTOS POR PAGAR A CORTO PLAZO",
    "2140": "ANTICIPO DE CLIENTES",
    "2150": "CONTRIBUCIONES POR PAGAR",
    "2160": "IVA TRASLADADO",
    "2170": "DIVIDENDOS POR PAGAR",
    "2180": "COBROS ANTICIPADOS",
    "2230": "DOCUMENTOS POR PAGAR A LARGO PLAZO",
    "3110": "CAPITAL SOCIAL",
    "3120": "APORTACIONES PARA FUTUROS AUMENTOS DE CAPITAL",
    "3210": "RESERVA LEGAL",
    "3220": "SUPERAVIT POR REVALUACION",
    "3230": "RESULTADO POR DEPURACION DE CUENTAS",
    "3240": "DIVIDENDOS PAGADOS ANTICIPADAMENTE",
    "3250": "UTILIDADES RETENIDAS DE EJERCICIOS ANTERIORES",
    "3260": "PERDIDAS ACUMULADAS DE EJERCICIOS ANTERIORES",
    "3270": "RESULTADO DEL EJERCICIO",
    "4100": "VENTAS",
    "4200": "DEVOLUCIONES Y REBAJAS SOBRE VENTAS",
    "5100": "COSTO DE VENTA",
    "6100": "GASTOS DE VENTA",
    "6200": "GASTOS DE DISTRIBUCION",
    "6300": "GASTOS DE LOGISTICA",
    "6400": "GASTOS DE MANTENIMIENTO",
    "6500": "GASTOS DE ADMINISTRACION",
    "7100": "OTROS INGRESOS",
    "7200": "OTROS GASTOS",
    "8100": "PRODUCTOS FINANCIEROS",
    "8200": "GASTOS FINANCIEROS",
    "9100": "IMPUESTO DEL EJERCICIO",
}

# --- Familias funcionales ---------------------------------------------------
# Agrupación de trabajo (no del catálogo): responde "¿qué papel juega esta
# línea en la contabilización de un CFDI?". Se asigna por prefijo, del más
# específico al más general (ver `familia()`).
FAMILIAS: list[tuple[str, str]] = [
    # (prefijo, familia)  -- orden importa: el primero que haga match gana.
    ("1170.001", "IVA_ACREDITABLE"),
    ("1170.002", "IVA_POR_ACREDITAR"),
    ("1170", "IVA_ACREDITABLE"),
    ("2160.001", "IVA_TRASLADADO"),
    ("2160.002", "IVA_POR_TRASLADAR"),
    ("2160", "IVA_TRASLADADO"),
    ("2150.002", "RETENCION_EFECTUADA"),
    ("2150.005", "RETENCION_POR_ENTERAR"),
    ("2150.003", "SEGURIDAD_SOCIAL"),
    ("2150.001", "IMPUESTO_FEDERAL"),
    ("2150.004", "IMPUESTO_ESTATAL"),
    ("2150", "CONTRIBUCION_POR_PAGAR"),
    ("1180", "CONTRIBUCION_A_FAVOR"),
    ("1160", "ANTICIPO_IMPUESTOS"),
    ("2110", "PROVEEDORES"),
    ("2120", "ACREEDORES"),
    ("2130", "DOC_POR_PAGAR_CP"),
    ("2230", "DOC_POR_PAGAR_LP"),
    ("1110", "BANCOS_Y_EFECTIVO"),
    ("1120", "CLIENTES"),
    ("1130", "DEUDORES_DIVERSOS"),
    ("1140", "INVENTARIO"),
    ("1150", "ANTICIPOS_Y_PAGOS_ANTICIPADOS"),
    ("1300", "ANTICIPOS_Y_PAGOS_ANTICIPADOS"),
    ("2140", "ANTICIPO_CLIENTES"),
    ("2180", "COBROS_ANTICIPADOS"),
    ("4100", "VENTAS"),
    ("4200", "DEVOLUCIONES_SOBRE_VENTAS"),
    ("5100", "COSTO_DE_VENTA"),
    ("6100", "GASTO"), ("6200", "GASTO"), ("6300", "GASTO"),
    ("6400", "GASTO"), ("6500", "GASTO"),
    ("7100", "OTROS_INGRESOS"),
    ("7200", "OTROS_GASTOS"),
    ("8100", "PRODUCTOS_FINANCIEROS"),
    ("8200", "GASTOS_FINANCIEROS"),
    ("9100", "IMPUESTO_DEL_EJERCICIO"),
    ("3", "CAPITAL"),
    ("12", "ACTIVO_FIJO"),
]

# --- Mapeo impuesto -> cuenta contable: NO se infiere, está en la base ------
# `Impuesto.Im_Cuenta_Contable` es la columna que el motor de pólizas usa para
# decidir a qué cuenta mandar cada impuesto (ver los renglones 0100/0110 de
# `Poliza_Configuracion_Detalle`, que eligen cargo o abono según el signo de
# `Im_Tasa`). `catalogo_impuestos()` la lee en vivo; el diccionario de abajo
# es el censo confirmado 2026-09-11, para poder clasificar sin consultar.
#
# OJO con el par acreditable/por-acreditar: mpro NO usa 1170.001 al
# contabilizar la factura, usa **1170.002 ("Iva por acreditar")** en las 5
# claves de IVA acreditable — el IVA solo se vuelve acreditable al PAGARSE
# (criterio de flujo de efectivo, art. 5 LIVA). Por eso el cruce contra el
# IVA del CFDI del periodo va contra 1170.002, y el traspaso
# 1170.002 -> 1170.001 hay que buscarlo en las pólizas de pago.
# Mismo patrón en retenciones, pero NO es uniforme: honorarios/arrendamiento/
# fletes/personal/RESICO van a 2150.005 ("por retener"), mientras que
# trabajadores/asimilables/dividendos/intereses van directo a 2150.002
# ("retenido"). No asumir la rama por el tipo de impuesto — usar la columna.
IMPUESTO_A_CUENTA: dict[str, str] = {
    "0001": "1170.002.001",  # IVA ACREDITABLE 16%
    "0002": "1170.002.001",  # IVA ACREDITABLE 16% VARIABLE
    "0003": "1170.002.001",  # IVA ACREDITABLE 0%
    "0004": "1170.002.001",  # IVA ACREDITABLE EXENTO
    "0005": "1170.002.002",  # IVA ACREDITABLE IMPORTACIÓN
    "0006": "2160.002.001",  # IVA TRASLADADO 16%
    "0007": "2160.002.001",  # IVA TRASLADADO 0%
    "0008": "2160.002.001",  # IVA TRASLADADO EXENTO
    "0009": "2150.002.001",  # ISR RETENIDO A TRABAJADORES
    "0010": "2150.002.002",  # ISR RETENIDO ASIMILABLES
    "0011": "2150.005.001",  # ISR RETENIDO SOBRE HONORARIOS 10%
    "0012": "2150.005.002",  # ISR RETENIDO SOBRE ARRENDAMIENTOS 10%
    "0013": "2150.002.005",  # ISR RETENIDO SOBRE DIVIDENDOS 10%
    "0014": "2150.002.006",  # ISR RETENIDO SOBRE INTERESES 20%
    "0015": "2150.005.003",  # IVA RETENIDO SOBRE FLETES 4% (PROVEEDOR)
    "0016": "1160.003.001",  # IVA RETENIDO SOBRE FLETES 4% (CLIENTE)
    "0017": "1160.003.002",  # IVA RETENIDO SOBRE DESPERDICIOS 16% (CLIENTE)
    "0018": "2150.005.004",  # IVA RETENIDO SOBRE HONORARIOS 10.67%
    "0019": "2150.003.001",  # IMSS TRABAJADOR
    "0020": "1160.004.001",  # SUBSIDIO AL EMPLEO
    "0021": "1180.005.001",  # ISR A FAVOR (DECLARACION ANUAL)
    "0022": "2150.003.001",  # IMSS PATRON
    "0023": "2150.005.005",  # IVA RETENIDO S/ARRENDAMIENTO 10.67%
    "0024": "2150.005.006",  # IVA RETENIDO S/SERVICIO DE PERSONAL 6% (PROVEEDOR)
    "0025": "1170.002.003",  # IVA ACREDITABLE AL 8% REGION FRONTERIZA
    "0026": "2150.005.007",  # ISR RETENIDO RESICO 1.25%
    "0027": "1170.002.003",  # IVA ACREDITABLE AL 8% VARIABLE REGION FRONTERIZA
    "0028": "1170.002.001",  # IVA ACREDITABLE DIESEL (tasa 15.6636)
}

# Claves de `Impuesto` que traen `Im_Codigo_SAT` pero NO son impuestos de un
# CFDI: son provisiones de nómina. Excluirlas al comparar contra el SAT — ya
# documentado en `recibidos/nivel_documento/docs/metodologia.md`.
IMPUESTOS_NO_CFDI = {"0019", "0020", "0021", "0022"}

# Agrupación de las claves de `Impuesto` por concepto del CFDI, para cruzar
# contra `raw_sat.cfdi_recibidos`. `Im_Tasa` negativa = retención.
IMPUESTO_CONCEPTO: dict[str, set[str]] = {
    # Lo que el proveedor me traslada y yo acredito -> campo SAT `iva`
    "IVA_ACREDITABLE": {"0001", "0002", "0003", "0004", "0005", "0025", "0027", "0028"},
    # Lo que yo traslado al cliente (emitidos) -> campo SAT `iva`
    "IVA_TRASLADADO": {"0006", "0007", "0008"},
    # Lo que yo le retengo al proveedor -> campo SAT `ret_iva`
    "RET_IVA": {"0015", "0018", "0023", "0024"},
    # Lo que yo le retengo al proveedor -> campo SAT `ret_isr`
    "RET_ISR": {"0009", "0010", "0011", "0012", "0013", "0014", "0026"},
    # Lo que el cliente me retiene a mí (emitidos, va a cuenta por cobrar)
    "RET_QUE_ME_HACEN": {"0016", "0017"},
    "NOMINA_NO_CFDI": IMPUESTOS_NO_CFDI,
}

# Campo de `raw_sat.cfdi_recibidos` contra el que se compara cada concepto.
CONCEPTO_A_CAMPO_SAT = {
    "IVA_ACREDITABLE": "iva",
    "IVA_TRASLADADO": "iva",
    "RET_IVA": "ret_iva",
    "RET_ISR": "ret_isr",
}

CUENTAS_ORDEN_LIKE = "10[1-6]00%"


def raiz(cuenta: str | None) -> str:
    """Cuenta mayor (primer segmento). `1170.002.001` -> `1170`."""
    if cuenta is None or (isinstance(cuenta, float) and pd.isna(cuenta)):
        return ""
    return str(cuenta).split(".")[0]


def familia(cuenta: str | None) -> str:
    """Familia funcional de la cuenta — el papel que juega la línea en la
    contabilización (IVA_POR_ACREDITAR, PROVEEDORES, GASTO, ...)."""
    if cuenta is None or (isinstance(cuenta, float) and pd.isna(cuenta)):
        return "SIN_CUENTA"
    c = str(cuenta)
    if c.startswith(("10100", "10200", "10300", "10400", "10500", "10600")):
        return "CUENTAS_DE_ORDEN"
    for prefijo, fam in FAMILIAS:
        if c.startswith(prefijo):
            return fam
    return "OTRA"


def es_cuenta_de_orden(cuenta: str | None) -> bool:
    return familia(cuenta) == "CUENTAS_DE_ORDEN"


def catalogo(solo_activas: bool = False) -> pd.DataFrame:
    """Catálogo completo de `Cuenta_Contable`, con `raiz` y `familia`
    calculadas. Una consulta, ~4,900 filas."""
    sql = (
        "SELECT Cc_Cve_Cuenta_Contable AS cuenta, Cc_Descripcion AS descripcion, "
        "Cc_Acumula AS acumula, Cc_Tipo AS tipo, Cc_Titulo AS titulo, "
        "Cc_Naturaleza AS naturaleza, Cc_Resultado AS resultado, "
        "Cc_Grupo_Cuenta_Contable AS grupo, Es_Cve_Estado AS estado "
        "FROM Cuenta_Contable"
    )
    if solo_activas:
        sql += " WHERE Es_Cve_Estado = 'AC'"
    df = pd.DataFrame(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    if df.empty:
        return df
    for c in ("cuenta", "descripcion", "acumula", "naturaleza", "estado"):
        df[c] = df[c].astype("string").fillna("").str.strip()
    df["raiz"] = df["cuenta"].map(raiz)
    df["raiz_descripcion"] = df["raiz"].map(RAICES).fillna("")
    df["familia"] = df["cuenta"].map(familia)
    df["nivel"] = df["cuenta"].str.count(r"\.") + 1
    return df


def catalogo_impuestos() -> pd.DataFrame:
    """Catálogo `Impuesto` con la cuenta contable a la que manda cada clave.

    `Im_Codigo_SAT`: '001' ISR, '002' IVA, '003' IEPS (ninguna clave usa
    '003' — mpro no sabe registrar IEPS a nivel comprobante, por eso el IEPS
    se va a la base del gasto).
    `Im_Tasa`: el SIGNO separa traslado (>0) de retención (<0).
    `concepto`: agrupación de trabajo, ver `IMPUESTO_CONCEPTO`.
    """
    sql = (
        "SELECT Im_Cve_Impuesto AS clave, Im_Descripcion AS descripcion, "
        "Im_Tipo_Impuesto AS tipo, Im_Tasa AS tasa, Im_Codigo_SAT AS codigo_sat, "
        "Im_Cuenta_Contable AS cuenta, Im_Cuenta_Contable_1 AS cuenta_1, "
        "Im_Cuenta_Contable_2 AS cuenta_2, Im_Impuesto_Local AS es_local, "
        "Im_Tipo_Factor AS tipo_factor, Es_Cve_Estado AS estado "
        "FROM Impuesto"
    )
    df = pd.DataFrame(rows_as_dicts(run_query(MPRO_TARGET, sql)))
    if df.empty:
        return df
    df["tasa"] = pd.to_numeric(df["tasa"], errors="coerce").fillna(0.0)
    for c in ("clave", "descripcion", "tipo", "codigo_sat", "cuenta", "estado"):
        df[c] = df[c].astype("string").fillna("").str.strip()
    df["es_retencion"] = df["tasa"] < 0
    inverso = {clave: concepto for concepto, claves in IMPUESTO_CONCEPTO.items()
               for clave in claves}
    df["concepto"] = df["clave"].map(inverso).fillna("OTRO")
    df["campo_sat"] = df["concepto"].map(CONCEPTO_A_CAMPO_SAT).fillna("")
    df["familia_cuenta"] = df["cuenta"].map(familia)
    return df.sort_values("clave").reset_index(drop=True)


def enriquecer(df: pd.DataFrame, col: str = "cuenta") -> pd.DataFrame:
    """Agrega `raiz`, `raiz_descripcion` y `familia` a un DataFrame que ya
    trae una columna de cuenta contable. No consulta la base."""
    out = df.copy()
    out["raiz"] = out[col].map(raiz)
    out["raiz_descripcion"] = out["raiz"].map(RAICES).fillna("")
    out["familia"] = out[col].map(familia)
    return out
