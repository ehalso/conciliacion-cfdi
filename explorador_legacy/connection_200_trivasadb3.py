"""Shim para el codigo legacy: el servidor .200 ya no existe; redirige a .205/TRIVASADB3 con las credenciales de db_credentials."""
import os, sys
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
sys.path.insert(0, os.path.expanduser("~/ehalso/trivasa-bi-core"))
from shared import db_credentials
_u, _p = db_credentials.sa()
engine = create_engine(URL.create("mssql+pymssql", username=_u, password=_p, host="192.168.117.205", port=1433, database="TRIVASADB3"))

def q(sql):
    return pd.read_sql(sql, engine)
