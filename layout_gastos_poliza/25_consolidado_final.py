"""
Consolidado final del layout de 60 columnas -- une los 4 bloques ya
construidos y validados por separado, sobre el grano de detalle
(FOLIO x POLIZA x CUENTA x CECO, tal como sale de Poliza_Detalle real):

  - 24_bloque_poliza_directo.py       -- Poliza/Cuenta/Centro/Cargo/Abono
                                          (join directo Pd_Referencia=Gr_Folio,
                                          reemplaza a reconstruir_config())
  - 21_impuestos_por_ceco.py          -- Subtotales/retenciones/IVA acreditable,
                                          atribuidos por Grc_Factor (grano FOLIO x CECO)
  - 22_bloque_proveedor_pago.py       -- Proveedor/cobro/pago (grano FOLIO,
                                          se repite en cada linea del folio)
  - 23_bloque_xml_concepto.py         -- UUID/XML/Concepto/Uso CFDI (grano
                                          FOLIO, se repite en cada linea)

DESCUENTO / DESCUENTO_GLOBAL: placeholder NULL -- igual que el legado,
sin fuente identificada en el sistema tras exploracion razonable (ver
layout_gastos_60col/legado/.../v5_impuestos_layout.sql, que ya los traia
hardcodeados en 0). FACTURA_REF: mismo tratamiento, ver 22.

Uso:
    python3 25_consolidado_final.py --fecha-ini 2026-01-01 --fecha-fin 2026-04-01
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # ruta relativa -- no asumir usuario/maquina

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from importlib import import_module

from helpers_output import console, resumen

m21 = import_module("21_impuestos_por_ceco")
m22 = import_module("22_bloque_proveedor_pago")
m23 = import_module("23_bloque_xml_concepto")
m24 = import_module("24_bloque_poliza_directo")

from connection_205_trivasadb3 import engine
from sqlalchemy import text


def construir(fi, ff):
    console.print("[bold]1/4 -- bloque poliza (join directo)[/bold]")
    poliza = m24.cargar(fi, ff)

    console.print("[bold]2/4 -- bloque impuestos por CECO (Grc_Factor)[/bold]")
    impuestos, _ = m21.construir(fi, ff)
    impuestos["DESCUENTO"] = None
    impuestos["DESCUENTO_GLOBAL"] = None

    console.print("[bold]3/4 -- bloque proveedor/pago[/bold]")
    prov_pago = pd.read_sql(text(m22.PROVEEDOR_PAGO_SQL), engine, params={"fi": fi, "ff": ff, "emp": m22.EMPRESA})
    prov_pago["FOLIO"] = prov_pago.FOLIO.str.strip()
    prov_pago = prov_pago.drop(columns=["ORIGEN"])  # ya viene de poliza

    console.print("[bold]4/4 -- bloque UUID/XML/concepto[/bold]")
    xml_concepto = pd.read_sql(text(m23.XML_CONCEPTO_SQL), engine, params={"fi": fi, "ff": ff, "emp": m22.EMPRESA})
    xml_concepto["FOLIO"] = xml_concepto.FOLIO.str.strip()

    consolidado = (
        poliza
        .merge(impuestos, on=["FOLIO", "CECO"], how="left")
        .merge(prov_pago, on="FOLIO", how="left")
        .merge(xml_concepto, on="FOLIO", how="left")
    )
    return consolidado


ORDEN_COLUMNAS = [
    # identidad / pago
    "FOLIO", "ORIGEN", "FECHA", "MONEDA",
    "CLAVE_PROVEEDOR", "RFC_PROVEEDOR", "NOMBRE_PROVEEDOR", "PROVEEDOR_MULTIPLE",
    "COBRADO_EFECTIVO", "COBRADO_CHEQUE_TRANSFERENCIA", "CHEQUE",
    "BANCO", "CUENTA_BANCARIA", "FECHA_CHEQUE", "NO_CHEQUE_TRANSF", "MONTO_COBRADO",
    # factura / CFDI
    "NUMERO_FACTURA", "UUID", "UUID_4", "FECHA_FACTURA", "TIPO_COMPROBANTE",
    "CFDI_COMPROBANTE_PAGO", "FACTURA_REF",
    # importes e impuestos
    "SUBTOTAL_0", "SUBTOTAL_16", "SUBTOTAL_EXENTA", "DESCUENTO", "DESCUENTO_GLOBAL",
    "SUBTOTAL_NETO", "IVA_ACREDITABLE", "RETENCIONES_IVA", "RETENCIONES_ISR",
    # xml
    "XML_RFC_EMISOR", "XML_MONTO", "XML_SERIE", "XML_FOLIO", "XML_METODO_PAGO", "XML_FORMA_PAGO",
    # concepto / uso cfdi
    "CONCEPTO_GASTO", "CLAVE_USO_BIEN_SERVICIO", "DESCRIPCION_USO_BIEN_SERVICIO",
    # poliza (detalle, grano final)
    "POLIZA", "FECHA_POLIZA", "TIPO_POLIZA", "NUMERO_POLIZA", "CONCEPTO_POLIZA",
    "CECO", "CECO_DESCRIPCION", "CUENTA_REGISTRO", "NOMBRE_CUENTA_REGISTRO", "CARGO", "ABONO",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", default="2026-01-01")
    ap.add_argument("--fecha-fin", default="2026-04-01")
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print(f"[bold]Consolidado final -- {fi} a {ff}[/bold]\n")
    df = construir(fi, ff)

    faltantes = [c for c in ORDEN_COLUMNAS if c not in df.columns]
    if faltantes:
        console.print(f"[red]Columnas esperadas que no aparecieron: {faltantes}[/red]")
    cols_final = [c for c in ORDEN_COLUMNAS if c in df.columns]
    df = df[cols_final]

    resumen(
        filas=len(df),
        folios=df.FOLIO.nunique(),
        columnas=len(df.columns),
        CARGO_menos_ABONO=f"{(df.CARGO.sum() - df.ABONO.sum()):,.2f}",
    )

    out = Path(__file__).resolve().parent.parent / "layout_gastos_60col" / f"CONSOLIDADO_{fi}_{ff}.csv"
    out.parent.mkdir(exist_ok=True)
    df.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]")
    return df


if __name__ == "__main__":
    main()
