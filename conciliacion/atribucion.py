"""Folios de Gasto con varios documentos: asigna cada línea de póliza a su documento (Grd_ID).

La póliza trae una línea por (cuenta, CECO) sin indicar de qué documento proviene. `Gasto_Registro_Control`
reparte cada documento por CECO en varios renglones, y la póliza los suma, así que una línea se atribuye al
documento cuya suma en ese CECO coincide por (FOLIO, CECO, documento, |importe|). Si hay más de un candidato con distinto proveedor/UUID, o la línea mezcla documentos,
queda como VARIOS.
"""
import numpy as np
import pandas as pd

VARIOS = "VARIOS"
TOL_IMPORTE = 0.02
SIN_DOCUMENTO = ("GASTO_RECLASIFICACION", "CONSUMO_INTERNO")


def _unico(docs, firma):
    """Documento único del conjunto, o el de menor Grd_ID si todos comparten proveedor y UUID; si no, VARIOS."""
    docs = sorted(set(docs))
    if len(docs) == 1 or (docs and len({firma.get(d) for d in docs}) == 1):
        return docs[0]
    return VARIOS


def atribuir_documento(base: pd.DataFrame, reparto: pd.DataFrame, docs: pd.DataFrame, firmas: dict) -> pd.DataFrame:
    """Agrega DOC_ID a `base` (VARIOS si no se puede atribuir) y una fila en cero por documento sin líneas.

    `docs`: FOLIO, DOC_ID de todos los documentos. `firmas`: {(FOLIO, DOC_ID): (proveedor, uuid)}.
    Solo los folios con 2 o más documentos y origen distinto de reclasificación/consumo interno reciben DOC_ID.
    """
    base = base.copy()
    base["DOC_ID"] = None
    n_docs = docs.groupby("FOLIO").DOC_ID.nunique()
    multi = set(n_docs[n_docs >= 2].index)
    aplica = base.FOLIO.isin(multi) & ~base.ORIGEN.isin(SIN_DOCUMENTO)
    if not aplica.any():
        return base

    suma = reparto.groupby(["FOLIO", "CECO", "Grd_ID"], as_index=False).Grc_Importe.sum().assign(ABS=lambda x: x.Grc_Importe.abs())
    rep = {k: g for k, g in suma.groupby(["FOLIO", "CECO"])}
    neto = (base.CARGO.fillna(0) - base.ABONO.fillna(0)).abs()
    docs_de = {f: list(g) for f, g in docs.groupby("FOLIO").DOC_ID}
    firma_de = {f: {d: firmas.get((f, d)) for d in ds} for f, ds in docs_de.items()}
    # por (FOLIO, CECO): Grd_ID y |importe| como arreglos, para no filtrar un DataFrame por línea
    rep = {k: (g.Grd_ID.to_numpy(), g.ABS.to_numpy()) for k, g in suma.groupby(["FOLIO", "CECO"])}
    idx = base.index[aplica]
    asignado = []
    for i, f, c, n in zip(idx, base.FOLIO[aplica], base.CECO[aplica], neto[aplica]):
        g = rep.get((f, c))
        if g is None:
            asignado.append(VARIOS)
            continue
        ids, abs_ = g
        firma = firma_de.get(f, {})
        coincide = ids[np.abs(abs_ - n) <= TOL_IMPORTE]
        asignado.append(_unico(coincide, firma) if len(coincide) else
                        (_unico(ids, firma) if len(set(ids)) == 1 else VARIOS))
    base.loc[idx, "DOC_ID"] = asignado

    # documentos sin ninguna línea: una fila en cero para que su bloque exista
    con_linea = set(zip(base.FOLIO[aplica], base.DOC_ID[aplica]))
    folios_aplica = set(base.FOLIO[aplica])
    primera = base[aplica].drop_duplicates("FOLIO").set_index("FOLIO")
    nuevas = []
    for f, d in zip(docs.FOLIO, docs.DOC_ID):
        if f in multi and (f, d) not in con_linea and f in folios_aplica:
            molde = primera.loc[f].copy()
            molde["FOLIO"] = f
            g = reparto[(reparto.FOLIO == f) & (reparto.Grd_ID == d)]
            molde["CUENTA_REGISTRO"] = molde["NOMBRE_CUENTA_REGISTRO"] = None
            molde["CECO"] = g.CECO.iloc[0] if len(g) else molde.CECO
            molde["CECO_DESCRIPCION"] = None
            molde["CARGO"] = molde["ABONO"] = 0.0
            molde["DOC_ID"] = d
            nuevas.append(molde)
    if nuevas:
        base = pd.concat([base, pd.DataFrame(nuevas)], ignore_index=True)
    return base
