"""
Conciliacion 1:1 contra XML (CFDI) a nivel documento -- grano
(FOLIO, GRD_ID), el que sugiere la exploracion del 2026-09-04 (ver
PROGRESS.md, entrada "Rank-pairing vs. reconstruccion real via Poliza_
Configuracion") en vez de (FOLIO, CUENTA_CONTABLE).

Por que este grano y no cuenta contable: el XML liga a Comprobante_
Digital.Cd_Documento, que decodificado es Gr_Folio + Grd_ID -- el
DOCUMENTO, no la cuenta. Comparado empiricamente (ver PROGRESS.md):
- 86.28% de los folios tienen el mismo numero de documentos que de
  cuentas, y de esos 99.86% son ademas biyeccion real -- ahi da igual.
- El 13.72% restante diverge (cuenta mas gruesa o mas fina que
  documento), y ese grupo divergente tiene MAS XML ligado (81.77%) que el
  grupo que si coincide (61.92%) -- agrupar por cuenta fallaria
  precisamente donde mas importa que funcione.

CONTRA QUE SE COMPARA EL XML -- correccion importante encontrada armando
este script: el primer intento comparo CARGO (reconstruido via Poliza_
Configuracion -- el importe NETO de gasto, sin IVA, que es el que cuadra
contra Poliza_Detalle) contra Cd_Monto (el total BRUTO del CFDI, con IVA)
-- 2.75% de cuadre, prácticamente todo desviado por el impuesto que vive
en otro renglon de la poliza. La comparacion correcta es Grd_Precio_Neto_
Importe (campo nativo de Gasto_Registro_Documento, YA incluye impuesto,
la misma logica que IMPORTE_FOLIO_SQL de layout_gastos_lib.py pero a
nivel documento) contra Cd_Monto: 97.21% (1,288/1,325 XML_UUID).

Segunda correccion: un mismo XML a veces se repite en VARIOS Grd_ID (1.83%
de los UUID, ej. una factura de luz partida en 16 lineas identicas de
$237 cada una, capturada como 16 documentos que apuntan al MISMO
Comprobante_Digital) -- Cd_Monto en esos casos es el total del CFDI
completo, no de un solo documento. Hay que sumar Grd_Precio_Neto_Importe
de TODOS los documentos que comparten un XML_UUID antes de comparar, no
comparar documento por documento.

CARGO (columna informativa, ya validado en 14): reconstruido via Poliza_
Configuracion, importe neto atribuido a Poliza_Detalle. ABONO: mismo
patron que layout_gastos_lib.POLIZA_SQL (Pd_Referencia=Gr_Folio,
Pd_Tipo=2) -- para esta config da 0 (el Abono queda consolidado a nivel
proveedor dentro de una poliza que a su vez consolida varios folios, su
Pd_Referencia es la referencia de la factura del proveedor, no Gr_Folio)
-- se deja la columna igual, es honesto reflejar que no es atribuible por
folio para esta config, no un bug de esta reconciliacion.

Cobertura: solo config 0450 (la dominante de GASTO_DIRECTO/CONTROL_
COMBUSTIBLE/VIAJE/ORDEN_COMPRA), igual que el 14.

Uso:
    python3 15_reconciliacion_xml_via_poliza_configuracion.py --fecha-ini 2026-01-01 --fecha-fin 2026-04-01 [--config 0450]
"""
import argparse
import sys

from connection_205_trivasadb3 import engine  # default de exploracion

import pandas as pd
from sqlalchemy import text
from helpers_output import console, mostrar_tabla, resumen
from poliza_configuracion_lib import reconstruir_config, abono_via_referencia, xml_gasto_registro


def importe_documento(folios: list) -> pd.DataFrame:
    """Importe nativo por documento (FOLIO, GRD_ID), SIN convertir a MXN --
    a nivel Grd_ID. Este es el que compara contra el XML (con impuesto),
    no CARGO (neto de poliza, sin impuesto).

    Corregido 2026-09-05: la version anterior multiplicaba por Grd_Tipo_
    Cambio (formula de IMPORTE_FOLIO_SQL de layout_gastos_lib.py, correcta
    ahi porque ese es un total en MXN para sumar folios de distinta moneda).
    Aqui NO aplica -- Comprobante_Digital.Cd_Monto viene en la MONEDA
    ORIGINAL del CFDI, no convertido. Confirmado con datos reales: 12/12
    documentos en USD de ORDEN_COMPRA que "no cuadraban" (diferencia de
    hasta 18x, exactamente el tipo de cambio) cuadran exacto ($0.00 de
    diferencia) comparando Grd_Precio_Neto_Importe sin convertir contra
    Cd_Monto. Seguro para MXN tambien: Grd_Tipo_Cambio siempre es 1.0 ahi
    (verificado, 7,026/7,026 documentos MXN de enero 2026), asi que quitar
    la conversion no cambia nada para el caso normal."""
    partes = []
    for i in range(0, len(folios), 900):
        chunk = folios[i:i + 900]
        in_list = ",".join(f"'{f}'" for f in chunk)
        partes.append(f"""
        SELECT Gr_Folio AS FOLIO, Grd_ID AS GRD_ID,
               Grd_Precio_Neto_Importe AS IMPORTE_DOC
        FROM Gasto_Registro_Documento
        WHERE Gr_Folio IN ({in_list})
        """)
    df = pd.read_sql(text(" UNION ALL ".join(partes)), engine)
    df["FOLIO"] = df.FOLIO.str.strip()
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    ap.add_argument("--empresa", default="0001")
    ap.add_argument("--config", default="0450")
    args = ap.parse_args()

    console.print(f"[bold]15 -- Conciliacion XML a nivel documento, config {args.config}[/bold]")

    recon = reconstruir_config(args.config, args.empresa, args.fecha_ini, args.fecha_fin)
    cargo = recon.groupby(["FOLIO", "GRD_ID", "CUENTA"], as_index=False).IMPORTE.sum().rename(columns={"IMPORTE": "CARGO"})
    folios = sorted(cargo.FOLIO.unique().tolist())

    abono = abono_via_referencia(args.config, args.empresa, args.fecha_ini, args.fecha_fin)
    abono_folio = abono.groupby("FOLIO", as_index=False).ABONO.sum()

    doc = importe_documento(folios)
    xml = xml_gasto_registro(folios)

    m = doc.merge(xml, on=["FOLIO", "GRD_ID"], how="left")
    m["TIENE_XML"] = m["XML_UUID"].notna()

    n_docs = len(m)
    n_con_xml = int(m.TIENE_XML.sum())
    resumen(documentos=n_docs, con_xml=n_con_xml, pct=f"{100*n_con_xml/n_docs:.2f}%")

    # Reconciliacion de monto -- por XML_UUID (no por documento), ver
    # docstring: un XML puede repartirse en varios Grd_ID.
    con_xml = m[m.TIENE_XML]
    por_uuid = con_xml.groupby("XML_UUID", as_index=False).agg(
        IMPORTE_DOC=("IMPORTE_DOC", "sum"), XML_MONTO=("XML_MONTO", "first"), n_documentos=("GRD_ID", "nunique")
    )
    por_uuid["DIFERENCIA"] = (por_uuid.IMPORTE_DOC - por_uuid.XML_MONTO).abs()
    por_uuid["CUADRA"] = por_uuid.DIFERENCIA < 1
    c, n = int(por_uuid.CUADRA.sum()), len(por_uuid)
    resumen(xml_uuid=n, cuadran_monto=c, pct=f"{100*c/n:.2f}%" if n else "n/a")
    if n > c:
        mostrar_tabla(
            por_uuid[~por_uuid.CUADRA].sort_values("DIFERENCIA", ascending=False).head(20),
            "XML_UUID donde el importe de documento(s) != Cd_Monto",
        )

    reporte = cargo.merge(m[["FOLIO", "GRD_ID", "IMPORTE_DOC", "XML_UUID", "XML_MONTO", "XML_RFC_EMISOR", "XML_FACTURA", "TIENE_XML"]],
                           on=["FOLIO", "GRD_ID"], how="left")
    reporte = reporte.merge(abono_folio, on="FOLIO", how="left")
    reporte["ABONO"] = reporte["ABONO"].fillna(0)

    out = f"15_reconciliacion_xml_config_{args.config}_{args.fecha_ini}_{args.fecha_fin}.csv"
    reporte.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]")


if __name__ == "__main__":
    main()
