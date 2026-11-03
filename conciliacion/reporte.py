"""Arma el reporte unificado (todos los tipos de documento) para un periodo [fi, ff)."""
import pandas as pd
from sqlalchemy.engine import Engine

from .dialecto import sql
from .complemento import agregar_complemento
from .db import parametros, tablas_temporales
from .documentos import TIPOS, TIPOS_CLIENTE, consultar_clientes, consultar_proveedores, construir_tipo
from .gasto import construir_gasto
from .posproceso import post
from .sat import EMITIDO, agregar_sat, agregar_solo_sat


def construir(engine: Engine, fi: str, ff: str, engine_sat: Engine | None = None) -> pd.DataFrame:
    """DataFrame final (ya posprocesado): una fila por línea de póliza, columna `Tipo`.

    Con `engine_sat` agrega el cruce por UUID contra el SAT (columnas SAT_* y CONC_*).
    """
    p = parametros(fi, ff)
    with engine.connect() as con:
        # Postgres: las tablas grandes se leen una sola vez (TEMP de precarga); en mssql no hay precarga
        with tablas_temporales(con, getattr(sql, "PRECARGA_SETUP", ""), p, *getattr(sql, "PRECARGA_TEMPORALES", ())):
            with tablas_temporales(con, sql.GASTO_DOCS_SETUP, p, *sql.TEMPORALES):
                gasto = construir_gasto(con, p)
            gasto["Tipo"] = "Gasto"
            proveedores = consultar_proveedores(con)
            partes = [gasto] + [construir_tipo(con, t, p, proveedores) for t in TIPOS]
    d = post(pd.concat(partes, ignore_index=True, sort=False))
    d = agregar_complemento(d, engine)
    if engine_sat is None:
        return d
    d = agregar_sat(d, engine_sat)
    return agregar_solo_sat(d, engine_sat, engine, fi, ff) if "SAT_UUID" in d else d


def construir_emitidos(engine: Engine, fi: str, ff: str, engine_sat: Engine | None = None) -> pd.DataFrame:
    """Ventas y notas de crédito de cliente (CFDI emitidos) para [fi, ff); solo Mpro (SQL Server).

    CLAVE/RFC/NOMBRE_PROVEEDOR llevan los datos del cliente. Con `engine_sat` cruza por UUID contra los EMITIDO del SAT.
    """
    if engine.dialect.name != "mssql":
        raise RuntimeError("Ventas solo está disponible con CONC_BACKEND=mssql: el warehouse no replica Factura/Nota_Credito/Cliente.")
    p = parametros(fi, ff)
    with engine.connect() as con:
        clientes = consultar_clientes(con)
        partes = [construir_tipo(con, t, p, clientes) for t in TIPOS_CLIENTE]
    d = post(pd.concat(partes, ignore_index=True, sort=False))
    if engine_sat is None:
        return d
    d = agregar_sat(d, engine_sat, EMITIDO)
    return agregar_solo_sat(d, engine_sat, engine, fi, ff, EMITIDO) if "SAT_UUID" in d else d
