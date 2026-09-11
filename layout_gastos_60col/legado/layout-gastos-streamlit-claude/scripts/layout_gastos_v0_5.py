"""
Layout de gastos - v0.5: version SQL PURA (una sola consulta, sin post-proceso en
pandas) -- ver sql/layout_gastos_v0_5.sql para el archivo listo para entregar a un
programador. Pedido explicito del usuario: "con todo lo aprendido, como hariamos este
reporte pero con una consulta SQL...sin nada muy sofisticado, solo hardcodeando algunos
casos especiales", tomando como base el ContabilidadRepository.cs / QueryAuditoria2.0.sql
que compartio (otro programador que intento este reporte antes).

Diferencia clave con v0.4.2 (deliberada, para mantenerlo simple): la atribucion de
Cargo/Abono es a nivel de FOLIO COMPLETO (como v0.2), pegada al ULTIMO Grd_ID del folio
-- NO usa Gasto_Registro_Control ni reparto por centro de costo. Para folios de un solo
documento (la mayoria) el resultado es identico a v0.4.2; para folios multi-documento,
el Cargo/Abono queda concentrado en el ultimo documento en vez de repartido entre todos.

Casos especiales "hardcodeados" (aprendidos en v0.1-v0.4.2, ver docs/09-16):
  1. CONSUMO_INTERNO / GASTO_REGISTRO_NOMINA: sin poliza (Cargo/Abono/Cuenta = NULL).
  2. GASTO_RECLASIFICACION: cargo/abono por signo de Importe, cuenta = Tipo_Gasto.
  3. Abono solo cuenta si la cuenta es raiz 'F', o sin grupo y empieza con '6', o su
     descripcion es "Gastos a cuenta de costo estandar" (docs/16).
  4. Reversiones (Importe de folio <= -$1): se usa solo Abono, Cargo en 0 (docs/15).
  5. Comprobante_Digital via OUTER APPLY TOP 1 (no LEFT JOIN...LIKE, evita duplicar fila).
  6. NO usa Poliza_Detalle_Comprobante -- liga UUID de complemento de PAGO, no del CFDI
     de registro; no sirve para esta atribucion (verificado con folio 01-0034739).

Uso: python3 scripts/layout_gastos_v0_5.py 2026-01-01 2026-01-31
"""
import sys
import os

import pandas as pd

from db import q

TOLERANCIA = 0.5
UMBRAL_REDONDEO = 5.0
ORIGENES_SIN_JOIN = {"CONSUMO_INTERNO", "GASTO_REGISTRO_NOMINA"}
EMPRESA = "0001"

_SQL_PATH = os.path.join(os.path.dirname(__file__), "..", "sql", "layout_gastos_v0_5.sql")


def _cargar_sql() -> str:
    """Lee sql/layout_gastos_v0_5.sql y le quita las 3 lineas DECLARE (son solo para
    correrlo suelto en SSMS) -- los parametros se sustituyen aqui via .format()."""
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
    """fecha_ini y fecha_fin son INCLUSIVE (a diferencia de v0.1-v0.4.2, que usaban
    fecha_fin EXCLUSIVE) -- asi esta escrito el .sql, para parecerse al query de
    referencia (BETWEEN @FechaInicio AND @FechaFin)."""
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
    """Misma logica de docs/14 -- clasifica el motivo de cada discrepancia."""
    diferencia = fila["diferencia"]
    if abs(diferencia) <= TOLERANCIA:
        return "Cuadra"
    if abs(diferencia) <= UMBRAL_REDONDEO:
        return "Ruido de redondeo"
    if fila["importe"] < 0 and abs(fila["neto"]) <= UMBRAL_REDONDEO:
        return "Reclasificación/ajuste manual con Importe negativo (Cargo≈Abono, neto≈0)"
    return "Sin explicación automática -- revisar a mano"


def validar(df: pd.DataFrame):
    """Igual que v0.4.2: si un folio tiene su Cargo/Abono a nivel folio completo (todo
    folio con 2+ documentos, ya que v0.5 SIEMPRE ataca a nivel folio), se valida a nivel
    folio; los de un solo documento se validan por fila (son equivalentes de cualquier
    forma)."""
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

    out_path = f"output/layout_gastos_v0_5_{fecha_ini}_a_{fecha_fin}.csv"
    df.to_csv(out_path, index=False)
    print(f"\nGuardado: {out_path}")
