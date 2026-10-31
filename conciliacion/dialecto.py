"""Elige las consultas según CONC_BACKEND: 'postgres' (warehouse, raw.*) o 'mssql' (Mpro, por omisión)."""
import os

from . import sql as sql_mssql
from . import sql_pg

BACKEND = os.environ.get("CONC_BACKEND", "mssql").lower()
sql = sql_pg if BACKEND == "postgres" else sql_mssql
