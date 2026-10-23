"""Conexión a SQL Server (Mpro) y utilidades de consulta."""
from contextlib import contextmanager

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection, Engine

from .config import EMPRESA, Mpro, Sat


def crear_engine(mpro: Mpro) -> Engine:
    url = URL.create("mssql+pymssql", username=mpro.usuario, password=mpro.clave,
                     host=mpro.host, port=mpro.puerto, database=mpro.base)
    return create_engine(url, pool_pre_ping=True)


def crear_engine_sat(sat: Sat) -> Engine:
    """Postgres del SAT: la sesión se abre en solo lectura aunque la cuenta tenga permisos de escritura."""
    url = URL.create("postgresql+psycopg2", username=sat.usuario, password=sat.clave,
                     host=sat.host, port=sat.puerto, database=sat.base)
    return create_engine(url, pool_pre_ping=True,
                         connect_args={"options": "-c default_transaction_read_only=on", "connect_timeout": 10})


def parametros(fi: str, ff: str) -> dict:
    """Periodo [fi, ff): `ff` es exclusivo."""
    return {"fi": fi, "ff": ff, "emp": EMPRESA}


def consultar(con: Connection, sql: str, p: dict | None = None) -> pd.DataFrame:
    d = pd.read_sql(text(sql), con, params=p)
    if "FOLIO" in d:
        d["FOLIO"] = d.FOLIO.str.strip()
    return d


@contextmanager
def tablas_temporales(con: Connection, crear: str, p: dict, *nombres: str):
    """Crea tablas #temporales en la sesión y las elimina al salir.

    Con estadísticas reales el optimizador baja la consulta de pagos de ~68 s a ~1 s en .207.
    """
    con.execute(text(crear), p)
    try:
        yield
    finally:
        for n in nombres:
            con.execute(text(f"IF OBJECT_ID('tempdb..{n}') IS NOT NULL DROP TABLE {n}"))
