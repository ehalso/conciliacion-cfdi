"""Arma el reporte unificado (todos los tipos de documento) para un periodo [fi, ff)."""
import pandas as pd
from sqlalchemy.engine import Engine

from . import sql
from .complemento import agregar_complemento
from .db import parametros, tablas_temporales
from .documentos import TIPOS, consultar_proveedores, construir_tipo
from .gasto import construir_gasto
from .posproceso import post
from .uso_cfdi_sat import completar_uso_cfdi


def construir(engine: Engine, fi: str, ff: str, engine_sat: Engine | None = None) -> pd.DataFrame:
    """DataFrame final (ya posprocesado): una fila por línea de póliza, columna `Tipo`."""
    p = parametros(fi, ff)
    with engine.connect() as con:
        with tablas_temporales(con, sql.GASTO_DOCS_SETUP, p, *sql.TEMPORALES):
            gasto = construir_gasto(con, p)
        gasto["Tipo"] = "Gasto"
        proveedores = consultar_proveedores(con)
        partes = [gasto] + [construir_tipo(con, t, p, proveedores) for t in TIPOS]
    d = post(pd.concat(partes, ignore_index=True, sort=False))
    return completar_uso_cfdi(agregar_complemento(d, engine), engine_sat, engine)
