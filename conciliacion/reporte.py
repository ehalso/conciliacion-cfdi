"""Arma el reporte unificado (todos los tipos de documento) para un periodo [fi, ff)."""
import pandas as pd
from sqlalchemy.engine import Engine

from .dialecto import sql
from .complemento import agregar_complemento
from .db import parametros, tablas_temporales
from .documentos import TIPOS, consultar_proveedores, construir_tipo
from .gasto import construir_gasto
from .posproceso import post
from .sat import agregar_sat, agregar_solo_sat


ETAPAS = ("Preparando tablas", "Gastos", "Pólizas y documentos", "Posproceso y complemento", "Cruce con el SAT", "CFDI solo en el SAT")


def construir(engine: Engine, fi: str, ff: str, engine_sat: Engine | None = None, avance=None) -> pd.DataFrame:
    """DataFrame final (ya posprocesado): una fila por línea de póliza, columna `Tipo`.

    Con `engine_sat` agrega el cruce por UUID contra el SAT (columnas SAT_* y CONC_*).
    `avance(etapas, i)` se llama al empezar cada etapa (i = índice en `etapas`).
    """
    etapas = ETAPAS if engine_sat is not None else ETAPAS[:4]

    def paso(i: int) -> None:
        if avance:
            avance(etapas, i)

    p = parametros(fi, ff)
    paso(0)
    with engine.connect() as con:
        # Postgres: las tablas grandes se leen una sola vez (TEMP de precarga); en mssql no hay precarga
        with tablas_temporales(con, getattr(sql, "PRECARGA_SETUP", ""), p, *getattr(sql, "PRECARGA_TEMPORALES", ())):
            with tablas_temporales(con, sql.GASTO_DOCS_SETUP, p, *sql.TEMPORALES):
                paso(1)
                gasto = construir_gasto(con, p)
            gasto["Tipo"] = "Gasto"
            paso(2)
            proveedores = consultar_proveedores(con)
            partes = [gasto] + [construir_tipo(con, t, p, proveedores) for t in TIPOS]
    paso(3)
    d = post(pd.concat(partes, ignore_index=True, sort=False))
    d = agregar_complemento(d, engine)
    if engine_sat is None:
        return d
    paso(4)
    d = agregar_sat(d, engine_sat)
    paso(5)
    return agregar_solo_sat(d, engine_sat, engine, fi, ff) if "SAT_UUID" in d else d
