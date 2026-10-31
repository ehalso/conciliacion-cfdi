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


def crear_engine_dw(sat: Sat) -> Engine:
    """Postgres del warehouse como fuente de datos (esquema raw). Rol de solo lectura sobre las tablas, pero sin forzar
    sesión read-only: las tablas TEMP de la sesión (mismo patrón que las #temporales de Mpro) las necesitan."""
    url = URL.create("postgresql+psycopg2", username=sat.usuario, password=sat.clave,
                     host=sat.host, port=sat.puerto, database=sat.base)
    return create_engine(url, pool_pre_ping=True,
                         connect_args={"options": "-c search_path=raw,public", "connect_timeout": 10})


def parametros(fi: str, ff: str) -> dict:
    """Periodo [fi, ff): `ff` es exclusivo."""
    return {"fi": fi, "ff": ff, "emp": EMPRESA}


def normalizar_pg(d: pd.DataFrame) -> pd.DataFrame:
    """Columnas en mayúsculas y fechas timestamptz a hora local sin zona, como las entrega SQL Server."""
    d.columns = [c.upper() if c == c.lower() else c for c in d.columns]
    for c in d.columns:
        if isinstance(d[c].dtype, pd.DatetimeTZDtype):
            d[c] = d[c].dt.tz_convert("America/Mexico_City").dt.tz_localize(None)
    return d


def consultar(con: Connection, sql: str, p: dict | None = None) -> pd.DataFrame:
    d = pd.read_sql(text(sql), con, params=p)
    if con.dialect.name == "postgresql":
        d = normalizar_pg(d)
    if "FOLIO" in d:
        d["FOLIO"] = d.FOLIO.str.strip()
    return d


@contextmanager
def tablas_temporales(con: Connection, crear: str, p: dict, *nombres: str):
    """Crea tablas #temporales en la sesión y las elimina al salir.

    Con estadísticas reales el optimizador baja la consulta de pagos de ~68 s a ~1 s en .207.
    """
    con.execute(text(crear), p)
    pg = con.dialect.name == "postgresql"
    try:
        if pg:
            for n in nombres:
                if con.scalar(text("SELECT to_regclass(:n)"), {"n": f"pg_temp.{n}"}):
                    con.execute(text(f"ANALYZE {n}"))
        yield
    finally:
        if pg:
            con.rollback()  # una consulta fallida deja la transacción abortada; las TEMP se van con ella
        else:
            for n in nombres:
                con.execute(text(f"IF OBJECT_ID('tempdb..{n}') IS NOT NULL DROP TABLE {n}"))
