"""Cargo GRANULAR para el origen GASTO_REGISTRO — reemplaza el patrón
folio-truncado-a-10 + suma de Poliza_Detalle que usa `extract_poliza_por_origen`
para los demás orígenes.

Hallazgo en vivo 2026-09-09: `Comprobante_Digital.Cd_Documento` para este
origen NO es solo el folio de 10 caracteres — trae folio(10) + Grd_ID(4)
pegados sin separador (ej. '01-00351170001'). `Grd_ID` es el renglón de
`Gasto_Registro_Documento` (una comprobación de gastos puede traer VARIOS
renglones, cada uno con su propio CFDI).

Corrección 2026-09-09 (segunda vuelta): la hipótesis inicial era que
también traía pegado un `Grc_ID` (prorrateo por centro de costo) de otros 4
dígitos, dando 18 caracteres en vez de 14. Verificado en vivo que es FALSO:
`Comprobante_Digital` genera **una sola fila por (Gr_Folio, Grd_ID)**,
nunca una por cada `Grc_ID` — confirmado sobre las 1,211 etiquetas
GASTO_REGISTRO de feb-2026: agrupando por los primeros 14 caracteres
(folio+Grd_ID) nunca hay más de un `Cd_Documento` completo distinto. Los 4
dígitos que a veces aparecen después del 14° carácter (dando 18 en vez de
14) NO son un `Grc_ID` que aísle un renglón — son un sufijo que no
distingue nada adicional (se ignoran). La llave real es (Gr_Folio, Grd_ID);
el cargo correcto es la **suma de TODOS los `Grc_Importe`** en
`Gasto_Registro_Control` para esa llave (verificado exacto contra el cargo
real posteado en `Poliza_Detalle` vía `extract_poliza_por_origen`, incluso
en folios con 8 renglones de prorrateo: folio 01-0027091, 4 splits,
suma control $2,746.64 == cargo póliza $2,746.64).

`Gasto_Registro_Control.Grc_Importe` es el importe EXACTO que termina
posteado como cargo en `Poliza_Detalle` (cuando la póliza está bien
generada) — y a diferencia de `Poliza_Detalle`, esta tabla no depende de
qué póliza (activa o cancelada) haya materializado el motor, así que no
hace falta filtrar por `Es_Cve_Estado`.

Truncar a 10 y sumar TODA la póliza referenciando ese folio corto (como
hacía el método anterior, previo a este archivo) suma de más cuando el
folio agrupa más de un `Grd_ID` (confirmado: 41/120 pendientes de
GASTO_REGISTRO en feb-2026 caían en este patrón). Usando la llave
(folio, Grd_ID) cada CFDI aísla su propio importe sin tocar los de sus
folio-hermanos.

Documentos que no traen al menos el folio+Grd_ID (14 caracteres, formato
inesperado) caen en `sin_dato` — no se inventan valores.
"""
from __future__ import annotations

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET

BATCH_SIZE = 150


def _parse_documento(documento: str):
    if not documento or len(documento) < 14:
        return None
    return documento[:10], documento[10:14]


def extract_gasto_registro_granular(documentos_completos: list[str]) -> pd.DataFrame:
    """`documentos_completos`: valores de `Cd_Documento` TAL CUAL (sin
    truncar). Devuelve una fila por documento con:

    - `cargo`: suma de `Grc_Importe` sobre TODOS los `Grc_ID` (prorrateos de
      centro de costo) de su (Gr_Folio, Grd_ID), vía `Gasto_Registro_Control`.
      Es lo que realmente se postea como gasto.
    - `neto`: `Gasto_Registro_Documento.Grd_Precio_Neto_Importe`, el importe
      del documento tal como se capturó — el que corresponde al CFDI.
    - `referencia`: `Grd_Referencia`, la referencia del proveedor (número de
      factura del emisor). Sirve para seguir el documento hacia la póliza de
      pago cuando el gasto se registra parcial (arrendamiento financiero).

    `cargo` y `neto` NO siempre coinciden: mpro puede aplicar un descuento
    propio al distribuir el gasto (confirmado 2026-09-09 en las cuotas del
    IMSS, donde `neto` = subtotal exacto del CFDI y `descontado`/control es
    menor por la parte que no es gasto de la empresa)."""
    documentos_completos = sorted(set(d for d in documentos_completos if d))
    parsed = {d: _parse_documento(d) for d in documentos_completos}
    folios = sorted({p[0] for p in parsed.values() if p is not None})

    rows: list[dict] = []
    doc_rows: list[dict] = []
    for i in range(0, len(folios), BATCH_SIZE):
        batch = folios[i:i + BATCH_SIZE]
        in_list = ", ".join(sql_quote(f) for f in batch)
        sql = (
            "SELECT Gr_Folio, Grd_ID, Grc_ID, Grc_Importe "
            f"FROM Gasto_Registro_Control WHERE Gr_Folio IN ({in_list})"
        )
        rows.extend(rows_as_dicts(run_query(MPRO_TARGET, sql)))
        sql_doc = (
            "SELECT Gr_Folio, Grd_ID, Grd_Precio_Neto_Importe, "
            "Grd_Precio_Descontado_Importe, Grd_Referencia "
            f"FROM Gasto_Registro_Documento WHERE Gr_Folio IN ({in_list})"
        )
        doc_rows.extend(rows_as_dicts(run_query(MPRO_TARGET, sql_doc)))

    neto_map: dict[tuple[str, str], float] = {}
    desc_map: dict[tuple[str, str], float] = {}
    ref_map: dict[tuple[str, str], str] = {}
    for r in doc_rows:
        key = (r["Gr_Folio"], str(r["Grd_ID"]).zfill(4))
        try:
            neto_map[key] = neto_map.get(key, 0.0) + float(r["Grd_Precio_Neto_Importe"])
        except (TypeError, ValueError):
            pass
        try:
            desc_map[key] = desc_map.get(key, 0.0) + float(r["Grd_Precio_Descontado_Importe"])
        except (TypeError, ValueError):
            pass
        ref = (r.get("Grd_Referencia") or "").strip()
        if ref:
            ref_map[key] = ref

    grc_map: dict[tuple[str, str], float] = {}
    for r in rows:
        try:
            importe = float(r["Grc_Importe"])
        except (TypeError, ValueError):
            importe = 0.0
        key = (r["Gr_Folio"], str(r["Grd_ID"]).zfill(4))
        grc_map[key] = grc_map.get(key, 0.0) + importe

    out = []
    for d in documentos_completos:
        p = parsed[d]
        if p is None:
            out.append({"documento": d, "cargo": None, "neto": None,
                        "descontado": None, "folio": None, "referencia": ""})
            continue
        key = (p[0], str(p[1]).zfill(4))
        out.append({"documento": d, "cargo": grc_map.get(key, 0.0),
                    "neto": neto_map.get(key, 0.0), "descontado": desc_map.get(key, 0.0),
                    "folio": p[0], "referencia": ref_map.get(key, "")})
    return pd.DataFrame(out, columns=["documento", "cargo", "neto", "descontado",
                                      "folio", "referencia"])
