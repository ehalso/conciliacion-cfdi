"""
Layout de gastos - v0.5.1: version SQL PURA -- extiende v0.5 agregando atribucion de
Cargo/Abono POR DOCUMENTO (Grd_ID) usando Gasto_Registro_Control, en vez de concentrar
todo en el ultimo documento del folio. Pedido explicito del usuario: "si hacemos la
v5.1 para usar el detalle de grc_id? estamos perdiendo granularidad y no creo que
complique mucho el sql". Ver sql/layout_gastos_v0_5_1.sql para el detalle completo.

Mecanismo (identico al validado en Python v0.4.2, pero SIN la salvaguarda de
re-enrutado -- se verifico que no hace falta una vez que se empareja por VALOR en vez
de por orden de creacion, ver docs/14):
  1. Exacto: mismo conteo de documentos en Gasto_Registro_Control vs Poliza_Detalle
     dentro de (folio, centro_costo) -- se emparejan ordenando ambos lados por VALOR.
  2. Proporcional: conteo distinto pero datos en ambos lados -- se reparte por
     Grc_Importe.
  3. Respaldo (igual que v0.5): sin centro de costo, o centro que no aparece en
     Gasto_Registro_Control -- se agrega por folio y se pega al ultimo documento.

Casos especiales 1-6 identicos a v0.5 (ver ese archivo / docs/17).

Uso: python3 scripts/layout_gastos_v0_5_1.py 2026-01-01 2026-01-31
"""
import sys
import os

import pandas as pd

from db import q

TOLERANCIA = 0.5
UMBRAL_REDONDEO = 5.0
ORIGENES_SIN_JOIN = {"CONSUMO_INTERNO", "GASTO_REGISTRO_NOMINA"}
EMPRESA = "0001"

_SQL_PATH = os.path.join(os.path.dirname(__file__), "..", "sql", "layout_gastos_v0_5_1.sql")


def _cargar_sql() -> str:
    with open(_SQL_PATH, encoding="utf-8") as f:
        texto = f.read()
    lineas = [
        ln for ln in texto.splitlines()
        if not ln.strip().startswith("DECLARE @Empresa")
        and not ln.strip().startswith("DECLARE @FechaInicio")
        and not ln.strip().startswith("DECLARE @FechaFin")
    ]
    return "\n".join(lineas)


_SQL_TEMPLATE = _cargar_sql()

_RENOMBRAR_COLUMNAS = {
    "folio": "folio", "grd_id": "grd_id", "fecha": "fecha_registro",
    "fechadocumento": "fecha_documento", "referencia": "referencia",
    "claveproveedor": "proveedor_clave", "razonsocial": "proveedor_nombre",
    "comentario": "comentario", "moneda": "moneda", "tipocambio": "tipo_cambio",
    "importe": "importe", "impuestos": "impuestos", "total": "total", "origen": "origen",
    "tienecomprobante": "tiene_comprobante", "uuid": "uuid",
    "cuentacontable": "cuenta_registro", "descripcioncuenta": "nombre_cuenta_registro",
    "cargo": "cargo", "abono": "abono",
}


def extract(fecha_ini: str, fecha_fin: str, empresa: str = EMPRESA) -> pd.DataFrame:
    """fecha_ini y fecha_fin son INCLUSIVE (igual que v0.5)."""
    sql = f"""
DECLARE @Empresa NVARCHAR(10) = '{empresa}';
DECLARE @FechaInicio DATE = '{fecha_ini}';
DECLARE @FechaFin DATE = '{fecha_fin}';
{_SQL_TEMPLATE}
"""
    df = q(sql)
    df.columns = [c.lower() for c in df.columns]
    return df.rename(columns=_RENOMBRAR_COLUMNAS)


def _explicar_gap(fila) -> str:
    diferencia = fila["diferencia"]
    if abs(diferencia) <= TOLERANCIA:
        return "Cuadra"
    if abs(diferencia) <= UMBRAL_REDONDEO:
        return "Ruido de redondeo"
    if fila["importe"] < 0 and abs(fila["neto"]) <= UMBRAL_REDONDEO:
        return "Reclasificación/ajuste manual con Importe negativo (Cargo≈Abono, neto≈0)"
    return "Sin explicación automática -- revisar a mano"


def validar(df: pd.DataFrame):
    """Igual que v0.5: se valida a nivel folio completo para folios multi-documento
    (conservador -- no se distingue en el SQL cuales folios quedaron resueltos por
    documento via Gasto_Registro_Control vs cuales cayeron al respaldo, asi que se
    verifica de la forma que cubre ambos casos correctamente)."""
    df = df.copy()
    df["cargo"] = df["cargo"].fillna(0)
    df["abono"] = df["abono"].fillna(0)

    n_docs_por_folio = df.groupby("folio")["grd_id"].transform("nunique")
    es_multi = n_docs_por_folio > 1

    multi = df[es_multi]
    importe_folio = (
        multi.drop_duplicates(subset=["origen", "folio", "grd_id"])
        .groupby(["origen", "folio"], as_index=False)["importe"].sum()
    )
    cargo_abono_folio = multi.groupby(["origen", "folio"], as_index=False)[["cargo", "abono"]].sum()
    nivel_folio = importe_folio.merge(cargo_abono_folio, on=["origen", "folio"])
    nivel_folio["grd_id"] = "(folio completo)"

    nivel_fila = df[~es_multi].groupby(["origen", "folio", "grd_id"], as_index=False, dropna=False).agg(
        importe=("importe", "first"), cargo=("cargo", "sum"), abono=("abono", "sum"),
    )

    agg = pd.concat([nivel_fila, nivel_folio], ignore_index=True)
    agg["neto"] = agg["cargo"] - agg["abono"]
    agg["diferencia"] = agg["neto"] - agg["importe"]
    agg["motivo"] = agg.apply(_explicar_gap, axis=1)

    resumen = []
    for origen, g in agg.groupby("origen", dropna=False):
        if origen in ORIGENES_SIN_JOIN:
            resumen.append({"origen": origen or "(vacío)", "n": len(g), "aplica": False,
                             "match": None, "pct_match": None})
            continue
        match = (g["diferencia"].abs() <= TOLERANCIA).sum()
        resumen.append({
            "origen": origen or "(vacío)", "n": len(g), "aplica": True,
            "match": match, "pct_match": round(match / len(g) * 100, 2),
        })
    return agg, pd.DataFrame(resumen)


if __name__ == "__main__":
    fecha_ini = sys.argv[1] if len(sys.argv) > 1 else "2026-01-01"
    fecha_fin = sys.argv[2] if len(sys.argv) > 2 else "2026-01-31"

    df = extract(fecha_ini, fecha_fin)
    print(f"{len(df)} filas totales\n")

    agg, resumen = validar(df)
    print("=== Validacion por origen (Cargo - Abono == Importe) ===")
    print(resumen.to_string(index=False))

    print("\n=== Top discrepancias (origenes que SI aplican comprobacion) ===")
    aplica = agg[agg["origen"].apply(lambda o: o not in ORIGENES_SIN_JOIN)]
    no_match = aplica[aplica["diferencia"].abs() > TOLERANCIA].sort_values("diferencia", key=abs, ascending=False)
    print(f"{len(no_match)} de {len(aplica)} filas con diferencia > {TOLERANCIA}")
    if len(no_match):
        print("\nPor motivo:")
        print(no_match["motivo"].value_counts().to_string())
        print()
        print(no_match.head(20).to_string(index=False))

    out_path = f"output/layout_gastos_v0_5_1_{fecha_ini}_a_{fecha_fin}.csv"
    df.to_csv(out_path, index=False)
    print(f"\nGuardado: {out_path}")
