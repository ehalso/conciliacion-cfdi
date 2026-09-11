"""
Bloque UUID/XML (columnas 41-43, 47-52) + Concepto/Uso CFDI (44-46) del
layout de 60 columnas -- adaptado de layout_gastos_60col/legado/
layout-gastos-pasos/docs/queries/gastos/{uuid_factura,xml_detalle,
concepto_y_uso_cfdi}.sql (validados contra .200, agosto 2026).

Grano: 1 fila por FOLIO -- mismo patron que 19 (impuestos) y 22
(proveedor/pago), se une por FOLIO al resto del reporte.

Match XML: Comprobante_Digital.Cd_Documento LIKE Gr_Folio+'%',
Cd_Tabla='GASTO_REGISTRO', Es_Cve_Estado='AC' -- comodin amplio, NO
filtra por LEN(Cd_Documento), asi que NO hereda el bug de formato 14/18
que si afectaba a poliza_configuracion_lib.xml_gasto_registro() (ver
PROGRESS.md, 2026-09-05) -- aqui no hace falta el fix, el diseno ya es
mas permisivo. Dedup por COUNT(DISTINCT Cd_Timbre_UUID), no por conteo de
filas -- un folio puede repetir el mismo UUID en mas de una fila sin ser
"Varios" real (documentado en el legado, check_uuid_por_folio.py).

OJO -- XML_MONTO (Cd_Monto) es dato de EXHIBICION aqui, no se usa en
ninguna validacion de suma: viene en la moneda ORIGINAL del CFDI, sin
convertir (mismo gotcha ya resuelto en otro lado, ver PROGRESS.md
"Cd_Monto viene en moneda ORIGINAL del CFDI") -- si en el futuro se
quisiera comparar XML_MONTO contra SUBTOTAL_NETO/TOTAL, hay que
multiplicar por el tipo de cambio del documento primero, igual que se
hizo en 15_reconciliacion_xml_via_poliza_configuracion.py.

Uso:
    python3 23_bloque_xml_concepto.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv("/home/esteban/ehalso/conciliacion-cfdi/.env")  # worktree no trae .env (no versionado)

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from sqlalchemy import text

from connection_205_trivasadb3 import engine
from helpers_output import console, mostrar_tabla, resumen

EMPRESA = "0001"

XML_CONCEPTO_SQL = """
WITH folios AS (
    SELECT gr.Gr_Folio AS FOLIO, gr.Gr_Comentario
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
      AND gr.Es_Cve_Estado <> 'CA'
      AND s.Em_Cve_Empresa = :emp
      AND 1=1 -- ampliado 2026-09-11: incluye NOMINA y CONSUMO_INTERNO
),
xml AS (
    SELECT
        f.FOLIO, cd.Cd_Timbre_UUID, cd.Cd_Timbre_Fecha, cd.Cd_RFC_Emisor,
        cd.Cd_Monto, cd.Cd_Serie, cd.Cd_Serie_Folio, cd.Cd_Uso_CFDI,
        COALESCE(cd.Cd_Metdo_Pago_CFDI, cd.Cd_Metodo_Pago) AS METODO_PAGO,
        cd.Cd_Forma_Pago
    FROM folios f
    JOIN Comprobante_Digital cd
        ON cd.Cd_Tabla = 'GASTO_REGISTRO'
       AND cd.Cd_Documento LIKE f.FOLIO + '%'
       AND cd.Es_Cve_Estado = 'AC'
),
xml_agg AS (
    SELECT
        FOLIO,
        COUNT(DISTINCT Cd_Timbre_UUID) AS N_UUID,
        MIN(Cd_Timbre_UUID)  AS UUID_UNICO,
        MIN(Cd_Timbre_Fecha) AS FECHA_FACTURA_UNICA,
        MIN(Cd_RFC_Emisor)   AS RFC_EMISOR_UNICO,
        MIN(Cd_Monto)        AS MONTO_UNICO,
        MIN(Cd_Serie)        AS SERIE_UNICA,
        MIN(Cd_Serie_Folio)  AS SERIE_FOLIO_UNICO,
        MIN(METODO_PAGO)     AS METODO_PAGO_UNICO,
        MIN(Cd_Forma_Pago)   AS FORMA_PAGO_UNICA
    FROM xml
    GROUP BY FOLIO
),
uso_cfdi_agg AS (
    SELECT FOLIO, COUNT(DISTINCT Cd_Uso_CFDI) AS N_USO_CFDI, MIN(Cd_Uso_CFDI) AS USO_CFDI_UNICO
    FROM xml
    WHERE Cd_Uso_CFDI IS NOT NULL AND LTRIM(RTRIM(Cd_Uso_CFDI)) <> ''
    GROUP BY FOLIO
),
uso_cfdi_con_desc AS (
    SELECT ua.FOLIO, ua.N_USO_CFDI, ua.USO_CFDI_UNICO, uc.Uc_Descripcion
    FROM uso_cfdi_agg ua
    LEFT JOIN Uso_CFDI uc ON uc.Uc_Cve_Uso_CFDI = ua.USO_CFDI_UNICO
)
SELECT
    f.FOLIO,
    f.Gr_Comentario AS CONCEPTO_GASTO,
    CASE WHEN ud.N_USO_CFDI >= 2 THEN 'VARIOS' ELSE ud.USO_CFDI_UNICO END     AS CLAVE_USO_BIEN_SERVICIO,
    CASE WHEN ud.N_USO_CFDI >= 2 THEN 'VARIOS' ELSE ud.Uc_Descripcion END     AS DESCRIPCION_USO_BIEN_SERVICIO,
    CASE WHEN xa.N_UUID >= 2 THEN 'VARIOS' ELSE xa.UUID_UNICO END            AS UUID,
    CASE WHEN xa.N_UUID >= 2 THEN 'VARIOS' ELSE LEFT(xa.UUID_UNICO, 4) END   AS UUID_4,
    CASE WHEN xa.N_UUID >= 2 THEN 'VARIOS' ELSE CONVERT(varchar(19), xa.FECHA_FACTURA_UNICA, 120) END AS FECHA_FACTURA,
    CASE WHEN xa.N_UUID >= 2 THEN 'VARIOS' ELSE xa.RFC_EMISOR_UNICO END      AS XML_RFC_EMISOR,
    CASE WHEN xa.N_UUID >= 2 THEN NULL ELSE xa.MONTO_UNICO END               AS XML_MONTO,
    CASE WHEN xa.N_UUID >= 2 THEN 'VARIOS' ELSE xa.SERIE_UNICA END           AS XML_SERIE,
    CASE WHEN xa.N_UUID >= 2 THEN 'VARIOS' ELSE xa.SERIE_FOLIO_UNICO END     AS XML_FOLIO,
    CASE WHEN xa.N_UUID >= 2 THEN 'VARIOS' ELSE xa.METODO_PAGO_UNICO END     AS XML_METODO_PAGO,
    CASE WHEN xa.N_UUID >= 2 THEN 'VARIOS' ELSE xa.FORMA_PAGO_UNICA END      AS XML_FORMA_PAGO
FROM folios f
LEFT JOIN xml_agg xa ON xa.FOLIO = f.FOLIO
LEFT JOIN uso_cfdi_con_desc ud ON ud.FOLIO = f.FOLIO
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", default="2026-01-01")
    ap.add_argument("--fecha-fin", default="2026-02-01")
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print(f"[bold]Bloque UUID/XML + Concepto/Uso CFDI (41-52, 44-46) -- {fi} a {ff}[/bold]\n")

    df = pd.read_sql(text(XML_CONCEPTO_SQL), engine, params={"fi": fi, "ff": ff, "emp": EMPRESA})
    df["FOLIO"] = df.FOLIO.str.strip()
    console.print(f"Folios: {len(df)}\n")

    cols_interes = ["CONCEPTO_GASTO", "CLAVE_USO_BIEN_SERVICIO", "DESCRIPCION_USO_BIEN_SERVICIO",
                     "UUID", "FECHA_FACTURA", "XML_RFC_EMISOR", "XML_MONTO", "XML_SERIE",
                     "XML_FOLIO", "XML_METODO_PAGO", "XML_FORMA_PAGO"]
    cobertura = pd.DataFrame({
        "columna": cols_interes,
        "poblado": [df[c].notna().sum() for c in cols_interes],
        "pct": [round(df[c].notna().mean() * 100, 2) for c in cols_interes],
    })
    mostrar_tabla(cobertura, f"Cobertura por columna ({len(df)} folios)", max_filas=20)

    resumen(
        uuid_varios=(df.UUID == "VARIOS").sum(),
        uso_cfdi_varios=(df.CLAVE_USO_BIEN_SERVICIO == "VARIOS").sum(),
    )

    out = Path(__file__).resolve().parent.parent / "layout_gastos_60col" / f"xml_concepto_{fi}_{ff}.csv"
    out.parent.mkdir(exist_ok=True)
    df.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]")


if __name__ == "__main__":
    main()
