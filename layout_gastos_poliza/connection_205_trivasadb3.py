"""Conexion a .205/TRIVASADB3 -- DEFAULT de este directorio para explorar y
perfilar esquema. Copia restaurada periodicamente, no produccion -- para
cifras oficiales usar .207/TRIVASADB.

Adaptado (2026-09-10) al consolidar layout-gastos dentro de este repo, bajo
`layout_gastos_poliza/`: lee las mismas credenciales que ya usa
`src/bridge_client.py` para mssql_205 (MSSQL_205_USER/MSSQL_205_PASSWORD,
.env en la raiz del repo) en vez de depender de trivasa-bi-core (externo,
no vive en este checkout)."""

import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

_user = os.environ.get("MSSQL_205_USER")
_password = os.environ.get("MSSQL_205_PASSWORD")
if not _user or not _password:
    raise RuntimeError(
        "Sin credenciales: define MSSQL_205_USER / MSSQL_205_PASSWORD "
        "(mismo .env que usa src/bridge_client.py, en la raíz del repo).")

engine = create_engine(URL.create(
    "mssql+pymssql", username=_user, password=_password,
    host="192.168.117.205", port=1433, database="TRIVASADB3",
))

def q(sql):
    return pd.read_sql(sql, engine)

def show(sql):
    df = q(sql)
    print(df.to_markdown(index=False))
    print(f'\n{len(df)} rows')
    return df
