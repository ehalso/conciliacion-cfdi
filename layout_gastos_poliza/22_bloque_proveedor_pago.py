"""
Bloque proveedor/cobro/pago/comprobante (columnas 1-18 del layout de 60
columnas del Word) -- adaptado de layout_gastos_60col/legado/
layout-gastos-pasos/docs/queries/gastos/etapa6_columnas_1_18.sql
(validado 91.8%-100% en agosto 2026, contra .200).

Grano: 1 fila por FOLIO -- igual que el bloque impuestos (19), se junta
por FOLIO al resto del reporte (repetido en cada linea de CECO/CUENTA).

Adaptacion a este repo: el SQL original reconstruye
`FOLIO = Sc_Cve_Sucursal + '-' + RIGHT('0000000'+Gr_Folio, 7)` porque en
su .200 `Gr_Folio` era puramente numerico. En este `.205`, `Gr_Folio` YA
es el folio completo con prefijo de sucursal (confirmado repetidamente
en esta sesion, ej. "05-0181359") -- se usa tal cual, sin reconstruir.
El resto de la query (todos los JOIN por `Grd_ID`/`Cxp_Tabla`/etc.) no
cambia: usan el valor nativo de Gr_Folio como llave, sea cual sea su
formato, y eso no varia entre `.200` y `.205`.

Gaps ya documentados por el legado, no re-investigados aqui (confirmado
que no hay fuente identificada tras exploracion razonable):
  - FACTURA_REF: 0% poblado en Pago_Cxp_Comprobante.Pcc_Numero_Factura,
    <1% y sin confirmacion de negocio en Comprobante_Digital.
    Cd_Tipo_Relacion_UUID. Placeholder NULL, igual que el legado.

Uso:
    python3 22_bloque_proveedor_pago.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # ruta relativa -- no asumir usuario/maquina

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from sqlalchemy import text

from connection_205_trivasadb3 import engine
from helpers_output import console, mostrar_tabla, resumen

EMPRESA = "0001"

PROVEEDOR_PAGO_SQL = """
WITH folios AS (
    SELECT
        gr.Gr_Folio AS FOLIO,
        gr.Gr_Folio, gr.Sc_Cve_Sucursal, gr.Gr_Fecha, gr.Gr_Genera_Cxp,
        gr.Gr_Tabla AS ORIGEN
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = :emp
      AND 1=1 -- ampliado 2026-09-11: incluye NOMINA y CONSUMO_INTERNO
),
doc_rank AS (
    SELECT
        f.FOLIO, grd.Grd_ID, grd.Mn_Cve_Moneda, grd.Pv_Cve_Proveedor,
        ROW_NUMBER() OVER (PARTITION BY f.FOLIO ORDER BY grd.Grd_Precio_Neto_Importe DESC, grd.Grd_ID) AS rn
    FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = f.Gr_Folio
),
n_proveedores AS (
    SELECT f.FOLIO, COUNT(DISTINCT grd.Pv_Cve_Proveedor) AS n_proveedores
    FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = f.Gr_Folio
    GROUP BY f.FOLIO
),
proveedor_repr AS (
    SELECT d.FOLIO, d.Pv_Cve_Proveedor, d.Mn_Cve_Moneda,
           CASE WHEN np.n_proveedores > 1 THEN 'SI' ELSE 'NO' END AS PROVEEDOR_MULTIPLE
    FROM doc_rank d
    JOIN n_proveedores np ON np.FOLIO = d.FOLIO
    WHERE d.rn = 1
),
cxp_docs_general AS (
    SELECT DISTINCT f.FOLIO, cxp.Cxp_Folio
    FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = f.Gr_Folio
    JOIN Cuenta_X_Pagar cxp
        ON cxp.Cxp_Tabla = 'Gasto_Registro:' + f.Gr_Folio
       AND cxp.Cxp_Documento = grd.Grd_ID
),
cxp_docs_referencia AS (
    SELECT DISTINCT f.FOLIO, cxp.Cxp_Folio
    FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = f.Gr_Folio
    JOIN Cuenta_X_Pagar cxp
        ON cxp.Cxp_Tabla = 'Cuenta_X_Pagar'
       AND cxp.Cxp_Referencia = grd.Grd_Referencia
       AND cxp.Pv_Cve_Proveedor = grd.Pv_Cve_Proveedor
    WHERE grd.Grd_Referencia IS NOT NULL AND LTRIM(RTRIM(grd.Grd_Referencia)) <> ''
),
cxp_docs AS (
    SELECT * FROM cxp_docs_general
    UNION
    SELECT * FROM cxp_docs_referencia
),
pagos AS (
    SELECT cd.FOLIO, cd.Cxp_Folio, pc.Pc_ID, pc.Fp_Cve_Forma_Pago,
           pc.Pc_Banco, pc.Pc_Cuenta_Bancaria, pc.Pc_Documento, pc.Pc_Tabla,
           ROW_NUMBER() OVER (
               PARTITION BY cd.FOLIO
               ORDER BY CASE WHEN pc.Fp_Cve_Forma_Pago IN ('0001','0002','0003') THEN 0 ELSE 1 END,
                        ABS(pc.Pc_Importe) DESC, pc.Pc_ID
           ) AS rn
    FROM cxp_docs cd
    JOIN Pago_CXP pc ON pc.Cxp_Folio = cd.Cxp_Folio
),
pago_repr AS (
    SELECT p.FOLIO, p.Fp_Cve_Forma_Pago, p.Pc_Banco, p.Pc_Cuenta_Bancaria,
           p.Pc_Documento, p.Pc_Tabla
    FROM pagos p WHERE p.rn = 1
),
cheque_repr AS (
    SELECT pr.FOLIO, ch.Ch_Fecha, ch.Ch_Folio
    FROM pago_repr pr
    LEFT JOIN Cheque ch ON ch.Ch_Folio = pr.Pc_Documento AND pr.Pc_Tabla = 'Cheque'
),
monto_cobrado AS (
    SELECT cd.FOLIO, SUM(pc.Pc_Importe) AS MONTO_COBRADO
    FROM cxp_docs cd
    JOIN Pago_CXP pc ON pc.Cxp_Folio = cd.Cxp_Folio
    GROUP BY cd.FOLIO
),
comprobante_pago AS (
    SELECT cd.FOLIO,
           COUNT(DISTINCT pcc.Pcc_Timbre_UUID) AS N_UUID_PAGO,
           MIN(pcc.Pcc_Timbre_UUID) AS UUID_PAGO_UNICO
    FROM cxp_docs cd
    JOIN Pago_Cxp_Comprobante pcc ON pcc.Cxp_Folio = cd.Cxp_Folio
    GROUP BY cd.FOLIO
),
xml AS (
    SELECT f.FOLIO, cd.Cd_Timbre_UUID, cd.Cd_Tipo_CFDI, cd.Cd_Serie_Folio
    FROM folios f
    JOIN Comprobante_Digital cd
        ON cd.Cd_Tabla = 'GASTO_REGISTRO'
       AND cd.Cd_Documento LIKE f.Gr_Folio + '%'
       AND cd.Es_Cve_Estado = 'AC'
),
xml_agg AS (
    SELECT FOLIO,
           COUNT(DISTINCT Cd_Timbre_UUID) AS N_UUID_XML,
           MIN(Cd_Tipo_CFDI) AS TIPO_CFDI_UNICO,
           MIN(Cd_Serie_Folio) AS SERIE_FOLIO_UNICO
    FROM xml
    GROUP BY FOLIO
)
SELECT
    f.FOLIO,
    f.ORIGEN,
    f.Gr_Fecha                                                          AS FECHA,
    p.Mn_Cve_Moneda                                                     AS MONEDA,
    p.Pv_Cve_Proveedor                                                  AS CLAVE_PROVEEDOR,
    prov.Pv_R_F_C                                                       AS RFC_PROVEEDOR,
    prov.Pv_Descripcion                                                 AS NOMBRE_PROVEEDOR,
    p.PROVEEDOR_MULTIPLE,
    CASE WHEN pr.Fp_Cve_Forma_Pago = '0001' THEN 'SI'
         WHEN pr.Fp_Cve_Forma_Pago IS NULL THEN NULL ELSE 'NO' END       AS COBRADO_EFECTIVO,
    CASE WHEN pr.Fp_Cve_Forma_Pago IN ('0002','0003') THEN 'SI'
         WHEN pr.Fp_Cve_Forma_Pago IS NULL THEN NULL ELSE 'NO' END       AS COBRADO_CHEQUE_TRANSFERENCIA,
    CASE WHEN pr.Fp_Cve_Forma_Pago = '0002' THEN 'SI'
         WHEN pr.Fp_Cve_Forma_Pago IS NULL THEN NULL ELSE 'NO' END       AS CHEQUE,
    CASE WHEN cp.N_UUID_PAGO >= 2 THEN 'VARIOS' ELSE cp.UUID_PAGO_UNICO END AS CFDI_COMPROBANTE_PAGO,
    CAST(NULL AS nvarchar(50))                                          AS FACTURA_REF,
    pr.Pc_Banco                                                         AS BANCO,
    pr.Pc_Cuenta_Bancaria                                               AS CUENTA_BANCARIA,
    ch.Ch_Fecha                                                         AS FECHA_CHEQUE,
    ch.Ch_Folio                                                         AS NO_CHEQUE_TRANSF,
    mc.MONTO_COBRADO,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS'
         WHEN xa.TIPO_CFDI_UNICO = 'I' THEN 'Ingreso'
         WHEN xa.TIPO_CFDI_UNICO = 'E' THEN 'Egreso'
         WHEN xa.TIPO_CFDI_UNICO = 'D' THEN 'Diario'
         ELSE NULL END                                                  AS TIPO_COMPROBANTE,
    CASE WHEN xa.N_UUID_XML >= 2 THEN 'VARIOS' ELSE xa.SERIE_FOLIO_UNICO END AS NUMERO_FACTURA
FROM folios f
LEFT JOIN proveedor_repr p   ON p.FOLIO = f.FOLIO
LEFT JOIN Proveedor prov     ON prov.Pv_Cve_Proveedor = p.Pv_Cve_Proveedor
LEFT JOIN pago_repr pr       ON pr.FOLIO = f.FOLIO
LEFT JOIN cheque_repr ch     ON ch.FOLIO = f.FOLIO
LEFT JOIN monto_cobrado mc   ON mc.FOLIO = f.FOLIO
LEFT JOIN comprobante_pago cp ON cp.FOLIO = f.FOLIO
LEFT JOIN xml_agg xa         ON xa.FOLIO = f.FOLIO
ORDER BY f.FOLIO
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", default="2026-01-01")
    ap.add_argument("--fecha-fin", default="2026-02-01")
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print(f"[bold]Bloque proveedor/pago (1-18) -- {fi} a {ff}[/bold]\n")

    df = pd.read_sql(text(PROVEEDOR_PAGO_SQL), engine, params={"fi": fi, "ff": ff, "emp": EMPRESA})
    df["FOLIO"] = df.FOLIO.str.strip()
    console.print(f"Folios: {len(df)}\n")

    cols_interes = ["MONEDA", "CLAVE_PROVEEDOR", "RFC_PROVEEDOR", "COBRADO_EFECTIVO",
                     "COBRADO_CHEQUE_TRANSFERENCIA", "CFDI_COMPROBANTE_PAGO", "BANCO",
                     "MONTO_COBRADO", "TIPO_COMPROBANTE", "NUMERO_FACTURA", "FACTURA_REF"]
    cobertura = pd.DataFrame({
        "columna": cols_interes,
        "poblado": [df[c].notna().sum() for c in cols_interes],
        "pct": [round(df[c].notna().mean() * 100, 2) for c in cols_interes],
    })
    mostrar_tabla(cobertura, f"Cobertura por columna ({len(df)} folios)", max_filas=20)

    varios = (df.CFDI_COMPROBANTE_PAGO == "VARIOS").sum()
    resumen(
        proveedor_multiple=f"{(df.PROVEEDOR_MULTIPLE=='SI').sum()} folios con 2+ proveedores",
        cfdi_pago_varios=f"{varios} folios con 2+ UUID de comprobante de pago",
        numero_factura_varios=(df.NUMERO_FACTURA == "VARIOS").sum(),
    )

    out = Path(__file__).resolve().parent.parent / "layout_gastos_60col" / f"proveedor_pago_{fi}_{ff}.csv"
    out.parent.mkdir(exist_ok=True)
    df.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]")


if __name__ == "__main__":
    main()
