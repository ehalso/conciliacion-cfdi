"""Vías de cuadre adicionales para CFDI que no cierran contra el cargo del
gasto, pero que SÍ están reconocidos completos en mpro por otro camino.

Todas salieron del drill-down folio por folio de la sesión 2026-09-09/10 y son
deliberadamente **estrechas**: se apoyan en una condición estructural
verificable, no en "existe un pago del mismo monto".
Un criterio laxo (por ejemplo, aceptar cualquier CFDI que aparezca en
`Pago_Cxp_Comprobante` con su total) cuadraría el 94% del universo de un
plumazo y taparía errores reales — entre ellos los CFDI capturados dos veces,
que también tienen su pago correcto.

1. `cuadre_arrendamiento_financiero`
   El CFDI de una mensualidad de leasing se contabiliza partido: solo el
   INTERÉS pasa por Gasto_Registro (cuenta de resultados), y el CAPITAL
   amortiza el pasivo por arrendamiento. La póliza de pago junta las dos
   piezas y abona al banco el TOTAL del CFDI. Ejemplo confirmado (CFDI
   070FE9DB…, START BANREGIO, total $69,185.79):

       póliza 0000478988, config 0246 "AF - START BANREGIO"
         Cargo 2130.001.004.003.019   52,785.58  ref M17916      <- capital
         Cargo 2130.001.004.003.019   16,400.21  ref FNN704472   <- interés (= Grd_Referencia)
         Cargo 1170.001.001 (IVA)      9,140.88
         Abono 1110.003.001.010.001   69,185.79                  <- total del CFDI
         Abono 1170.002.001            9,140.88

   La liga con el CFDI es la cadena
   `Comprobante_Digital` → `Gasto_Registro_Documento.Grd_Referencia`
   (el folio de la factura del arrendador) → `Poliza_Detalle.Pd_Referencia`.

2. `cuadre_repartido_por_referencia`
   Una sola factura se captura como VARIOS folios de Gasto_Registro, uno por
   sucursal, y `Comprobante_Digital` solo etiqueta uno. Los folios hermanos
   comparten `Grd_Referencia` y fecha. Sumando el gasto de todos, cuadra el
   CFDI completo. Caso confirmado: ISN (Impuesto Sobre Nómina) de la
   Secretaría de Administración y Finanzas, $397,161.00 repartido en 13
   sucursales bajo la referencia `0000000066`.
"""
from __future__ import annotations

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET

BATCH_SIZE = 120
# Cuentas de pasivo donde vive el capital del arrendamiento financiero
# (documentos por pagar a corto y largo plazo).
CUENTAS_PASIVO_LEASING = ("2130", "2230")
CUENTAS_BANCO = "1110"


def cuadre_arrendamiento_financiero(referencias: list[str]) -> pd.DataFrame:
    """Para cada referencia de proveedor, devuelve el abono a bancos de las
    pólizas activas que (a) traen una línea con esa referencia y (b) cargan
    esa línea a una cuenta de pasivo por arrendamiento. Una fila por
    (referencia, póliza)."""
    referencias = sorted({str(r).strip() for r in referencias if str(r).strip()})
    if not referencias:
        return pd.DataFrame(columns=["referencia", "Pl_Folio", "abono_banco"])

    like_pasivo = " OR ".join(
        f"pd.Cc_Cve_Cuenta_Contable LIKE '{c}%'" for c in CUENTAS_PASIVO_LEASING)

    filas: list[dict] = []
    for i in range(0, len(referencias), BATCH_SIZE):
        in_list = ", ".join(sql_quote(r) for r in referencias[i:i + BATCH_SIZE])
        sql = (
            "SELECT pd.Pd_Referencia AS referencia, pd.Pl_Folio "
            "FROM Poliza_Detalle pd JOIN Poliza p ON p.Pl_Folio = pd.Pl_Folio "
            f"WHERE pd.Pd_Referencia IN ({in_list}) AND p.Es_Cve_Estado <> 'CA' "
            f"AND pd.Pd_Tipo = 1 AND ({like_pasivo}) "
            "GROUP BY pd.Pd_Referencia, pd.Pl_Folio"
        )
        filas.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))

    if not filas:
        return pd.DataFrame(columns=["referencia", "Pl_Folio", "abono_banco"])
    ref_pol = pd.DataFrame(filas).drop_duplicates()

    folios = sorted(ref_pol["Pl_Folio"].unique())
    bancos: list[dict] = []
    for i in range(0, len(folios), BATCH_SIZE):
        in_list = ", ".join(sql_quote(f) for f in folios[i:i + BATCH_SIZE])
        sql = (
            "SELECT Pl_Folio, SUM(Pd_Importe) AS abono_banco FROM Poliza_Detalle "
            f"WHERE Pl_Folio IN ({in_list}) AND Pd_Tipo = 2 "
            f"AND Cc_Cve_Cuenta_Contable LIKE '{CUENTAS_BANCO}%' GROUP BY Pl_Folio"
        )
        bancos.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))

    if not bancos:
        return pd.DataFrame(columns=["referencia", "Pl_Folio", "abono_banco"])
    b = pd.DataFrame(bancos)
    b["abono_banco"] = pd.to_numeric(b["abono_banco"], errors="coerce").fillna(0.0)
    return ref_pol.merge(b, on="Pl_Folio", how="inner")


def cuadre_repartido_por_referencia(referencias: list[str]) -> pd.DataFrame:
    """Para cada `Grd_Referencia`, suma el gasto (`Gasto_Registro_Control`) de
    TODOS los folios de Gasto_Registro no cancelados que comparten esa
    referencia, agrupando además por fecha del folio (una misma referencia se
    reutiliza entre periodos). Devuelve referencia / fecha / n_folios / suma.
    """
    referencias = sorted({str(r).strip() for r in referencias if str(r).strip()})
    if not referencias:
        return pd.DataFrame(columns=["referencia", "Gr_Fecha", "n_folios", "suma_grupo"])

    filas: list[dict] = []
    for i in range(0, len(referencias), BATCH_SIZE):
        in_list = ", ".join(sql_quote(r) for r in referencias[i:i + BATCH_SIZE])
        sql = (
            "SELECT grd.Grd_Referencia AS referencia, gr.Gr_Fecha, "
            "COUNT(DISTINCT gr.Gr_Folio) AS n_folios, SUM(ABS(grc.Grc_Importe)) AS suma_grupo "
            "FROM Gasto_Registro_Documento grd "
            "JOIN Gasto_Registro gr ON gr.Gr_Folio = grd.Gr_Folio "
            "JOIN Gasto_Registro_Control grc ON grc.Gr_Folio = grd.Gr_Folio "
            "     AND grc.Grd_ID = grd.Grd_ID "
            f"WHERE grd.Grd_Referencia IN ({in_list}) AND gr.Es_Cve_Estado <> 'CA' "
            "GROUP BY grd.Grd_Referencia, gr.Gr_Fecha"
        )
        filas.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))

    if not filas:
        return pd.DataFrame(columns=["referencia", "Gr_Fecha", "n_folios", "suma_grupo"])
    df = pd.DataFrame(filas)
    df["suma_grupo"] = pd.to_numeric(df["suma_grupo"], errors="coerce").fillna(0.0)
    df["n_folios"] = pd.to_numeric(df["n_folios"], errors="coerce").fillna(0).astype(int)
    return df


def resumen_folios_gasto(folios: list[str]) -> pd.DataFrame:
    """Por folio de Gasto_Registro: importe total del folio (suma de
    `Grc_Importe` de TODOS sus renglones, estén etiquetados o no) y cuántos
    CFDI distintos lo tienen etiquetado en `Comprobante_Digital`.

    Sirve para el caso "el CFDI cubre el folio completo pero solo uno de sus
    renglones quedó etiquetado" (confirmado en el complemento de pago del IMSS,
    folio `01-0035148`: 6 renglones que suman $14,455.34 = subtotal del CFDI,
    con la etiqueta puesta solo en el renglón de $7,210.60)."""
    folios = sorted({f for f in folios if f})
    if not folios:
        return pd.DataFrame(columns=["folio", "suma_folio", "n_cfdi"])

    sumas: list[dict] = []
    cfdis: list[dict] = []
    for i in range(0, len(folios), BATCH_SIZE):
        in_list = ", ".join(sql_quote(f) for f in folios[i:i + BATCH_SIZE])
        sumas.extend(rows_as_dicts(run_query(MPRO_TARGET, (
            "SELECT Gr_Folio AS folio, SUM(ABS(Grc_Importe)) AS suma_folio "
            f"FROM Gasto_Registro_Control WHERE Gr_Folio IN ({in_list}) GROUP BY Gr_Folio"))))
        cfdis.extend(rows_as_dicts(run_query(MPRO_TARGET, (
            "SELECT LEFT(Cd_Documento, 10) AS folio, COUNT(DISTINCT Cd_Timbre_UUID) AS n_cfdi "
            "FROM Comprobante_Digital WHERE Cd_Tabla = 'GASTO_REGISTRO' "
            f"AND LEFT(Cd_Documento, 10) IN ({in_list}) GROUP BY LEFT(Cd_Documento, 10)"))))

    a = pd.DataFrame(sumas) if sumas else pd.DataFrame(columns=["folio", "suma_folio"])
    b = pd.DataFrame(cfdis) if cfdis else pd.DataFrame(columns=["folio", "n_cfdi"])
    if a.empty:
        return pd.DataFrame(columns=["folio", "suma_folio", "n_cfdi"])
    a["suma_folio"] = pd.to_numeric(a["suma_folio"], errors="coerce").fillna(0.0)
    out = a.merge(b, on="folio", how="left")
    out["n_cfdi"] = pd.to_numeric(out["n_cfdi"], errors="coerce").fillna(0).astype(int)
    return out


def cuadre_cheque_agrupado(folios_cheque: list[str]) -> pd.DataFrame:
    """Un cheque puede liquidar VARIAS facturas a la vez. Devuelve, por folio de
    cheque, su importe y la suma de los montos de todos los CFDI que mpro le
    tiene etiquetados. Cuando ambos coinciden, cada uno de esos CFDI está
    pagado y el grupo cuadra (confirmado: cheque `01-0081509` de ECOLSUR,
    $64,721.04 = $26,361.00 + $38,360.04 de sus dos facturas)."""
    folios_cheque = sorted({f for f in folios_cheque if f})
    if not folios_cheque:
        return pd.DataFrame(columns=["documento", "importe_cheque", "suma_cfdi", "n_cfdi"])

    filas: list[dict] = []
    for i in range(0, len(folios_cheque), BATCH_SIZE):
        in_list = ", ".join(sql_quote(f) for f in folios_cheque[i:i + BATCH_SIZE])
        ch = rows_as_dicts(run_query(MPRO_TARGET, (
            "SELECT Ch_Folio AS documento, Ch_Importe AS importe_cheque "
            f"FROM Cheque WHERE Ch_Folio IN ({in_list})")))
        cd = rows_as_dicts(run_query(MPRO_TARGET, (
            "SELECT Cd_Documento AS documento, COUNT(DISTINCT Cd_Timbre_UUID) AS n_cfdi, "
            "SUM(Cd_Monto) AS suma_cfdi FROM ("
            "  SELECT DISTINCT LEFT(cd.Cd_Documento, 10) AS Cd_Documento, cd.Cd_Timbre_UUID, cd.Cd_Monto "
            "  FROM Comprobante_Digital cd JOIN Cheque ch ON ch.Ch_Folio = LEFT(cd.Cd_Documento, 10) "
            "  WHERE cd.Cd_Tabla = 'CHEQUE' "
            f"  AND LEFT(cd.Cd_Documento, 10) IN ({in_list}) "
            # Se excluye la fila cuyo monto es el importe COMPLETO del cheque:
            # ese comprobante es el recibo de pago (REP) que ampara todo el
            # cheque, no una de las facturas que el cheque liquida. Dejarla
            # dentro duplica el total y ningún grupo cuadraría nunca.
            "  AND ABS(cd.Cd_Monto - ch.Ch_Importe) > 0.01) t GROUP BY Cd_Documento")))
        a = pd.DataFrame(ch)
        b = pd.DataFrame(cd)
        if not a.empty and not b.empty:
            filas.extend(a.merge(b, on="documento", how="inner").to_dict("records"))

    if not filas:
        return pd.DataFrame(columns=["documento", "importe_cheque", "suma_cfdi", "n_cfdi"])
    df = pd.DataFrame(filas)
    for c in ("importe_cheque", "suma_cfdi"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


# Cada tabla de origen guarda el importe capturado del documento en su propia
# columna `Xx_Precio_Neto_Importe` (confirmado vía INFORMATION_SCHEMA). Sirve
# como respaldo cuando el cargo no se puede aislar en la póliza: si el importe
# capturado coincide con el CFDI, el documento SÍ recoge el comprobante.
IMPORTE_DOCUMENTO = {
    "COMPRA": ("Compra_Encabezado", "Co_Folio", "Co_Precio_Neto_Importe"),
    "COMPRA_INDIRECTO": ("Compra_Indirecto", "Ci_Folio", "Ci_Precio_Neto_Importe"),
    "CUENTA_X_PAGAR": ("Cuenta_X_Pagar", "Cxp_Folio", "Cxp_Precio_Neto_Importe"),
    "NOTA_CREDITO_PROVEEDOR": ("Nota_Credito_Proveedor", "Nc_Folio", "Nc_Precio_Neto_Importe"),
    "FACTURA": ("Factura_Encabezado", "Fc_Folio", "Fc_Precio_Neto_Importe"),
}


def extract_importe_documento(origen: str, documentos: list[str]) -> pd.DataFrame:
    """Importe capturado del documento de origen, por folio (suma de sus
    renglones). Devuelve documento / importe_documento."""
    fuente = IMPORTE_DOCUMENTO.get(origen.upper())
    if fuente is None:
        return pd.DataFrame(columns=["documento", "importe_documento"])
    tabla, col_folio, col_importe = fuente

    documentos = sorted({d for d in documentos if d})
    filas: list[dict] = []
    for i in range(0, len(documentos), BATCH_SIZE):
        in_list = ", ".join(sql_quote(d) for d in documentos[i:i + BATCH_SIZE])
        sql = (
            f"SELECT {col_folio} AS documento, SUM({col_importe}) AS importe_documento "
            f"FROM {tabla} WHERE {col_folio} IN ({in_list}) GROUP BY {col_folio}"
        )
        filas.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))

    df = pd.DataFrame(filas, columns=["documento", "importe_documento"])
    if df.empty:
        return df
    df["importe_documento"] = pd.to_numeric(df["importe_documento"], errors="coerce").fillna(0.0)
    return df


def extract_referencia_cxp(folios: list[str]) -> pd.DataFrame:
    """`Cuenta_X_Pagar.Cxp_Referencia` por folio: la referencia del proveedor
    (folio de su factura). Es el equivalente de `Grd_Referencia` para el módulo
    de cuentas por pagar, y hace falta porque parte del arrendamiento
    financiero se captura por ahí en vez de por Gasto_Registro (START BANREGIO,
    abril-mayo 2026): el CXP solo recoge el interés y el capital vive en la
    póliza de pago, igual que en el caso ya documentado."""
    folios = sorted({f for f in folios if f})
    if not folios:
        return pd.DataFrame(columns=["documento", "referencia"])
    filas: list[dict] = []
    for i in range(0, len(folios), BATCH_SIZE):
        in_list = ", ".join(sql_quote(f) for f in folios[i:i + BATCH_SIZE])
        filas.extend(rows_as_dicts(run_query(MPRO_TARGET, (
            "SELECT DISTINCT Cxp_Folio AS documento, Cxp_Referencia AS referencia "
            f"FROM Cuenta_X_Pagar WHERE Cxp_Folio IN ({in_list}) "
            "AND Cxp_Referencia IS NOT NULL AND LTRIM(RTRIM(Cxp_Referencia)) <> ''"))))
    return pd.DataFrame(filas, columns=["documento", "referencia"])
