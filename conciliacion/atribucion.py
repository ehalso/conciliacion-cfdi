"""Folios de Gasto con varios documentos: asigna cada línea de póliza a su documento (Grd_ID).

La póliza trae una línea por (cuenta, CECO) sin indicar de qué documento proviene. `Gasto_Registro_Control`
reparte cada documento por CECO, así que una línea se atribuye al documento cuyo renglón coincide por
(FOLIO, CECO, |importe|). Si hay más de un candidato con distinto proveedor/UUID, o la línea mezcla documentos,
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

    rep = {k: g for k, g in reparto.assign(ABS=reparto.Grc_Importe.abs()).groupby(["FOLIO", "CECO"])}
    neto = (base.CARGO.fillna(0) - base.ABONO.fillna(0)).abs()
    asignado = []
    for i, r in base[aplica].iterrows():
        firma = {d: firmas.get((r.FOLIO, d)) for d in docs[docs.FOLIO == r.FOLIO].DOC_ID}
        g = rep.get((r.FOLIO, r.CECO))
        if g is None:
            asignado.append((i, VARIOS))
            continue
        coincide = g[(g.ABS - neto[i]).abs() <= TOL_IMPORTE].Grd_ID
        asignado.append((i, _unico(coincide, firma) if len(coincide) else
                         (_unico(g.Grd_ID, firma) if g.Grd_ID.nunique() == 1 else VARIOS)))
    for i, d in asignado:
        base.at[i, "DOC_ID"] = d

    # documentos sin ninguna línea: una fila en cero para que su bloque exista
    con_linea = set(zip(base.FOLIO[aplica], base.DOC_ID[aplica]))
    nuevas = []
    for f, d in zip(docs.FOLIO, docs.DOC_ID):
        if f in multi and (f, d) not in con_linea and (base.FOLIO[aplica] == f).any():
            molde = base[aplica & (base.FOLIO == f)].iloc[0].copy()
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
