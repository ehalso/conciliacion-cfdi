"""Conexion a .205/TRIVASADB3 -- copia restaurada periodicamente, NO produccion.
Para cifras oficiales es .207/TRIVASADB (ver trivasa-context,
docs/arquitectura/servidores-y-bases.md). Este proyecto usa .205 a proposito:
es exploracion y conciliacion de estructura, no cierre contable.

Adaptado (2026-09-10) al consolidar `adjuntar-xml` dentro de este repo, bajo
`recibidos/nivel_documento/`: en vez de depender de `trivasa-bi-core`
(externo, no vive en este checkout), lee las MISMAS credenciales que ya usa
`src/bridge_client.py` para `mssql_205` (`MSSQL_205_USER`/`MSSQL_205_PASSWORD`,
`.env` en la raíz del repo) -- un solo `.env`, no dos mecanismos de
credenciales en el mismo repo. Sin password embebido -- regla dura desde el
incidente 2026-08-29, ver
trivasa-context/docs/arquitectura/credenciales-y-conexiones.md.

Verificable con:  git grep -n "mssql+pymssql://.*:.*@"   (no debe dar nada)
"""
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

HOST, PORT, DATABASE = "192.168.117.205", 1433, "TRIVASADB3"


def _credenciales():
    user = os.environ.get("MSSQL_205_USER")
    password = os.environ.get("MSSQL_205_PASSWORD")
    if not user or not password:
        raise RuntimeError(
            "Sin credenciales: define MSSQL_205_USER / MSSQL_205_PASSWORD "
            "(mismo .env que usa src/bridge_client.py, en la raíz del repo).")
    return user, password


_user, _password = _credenciales()
engine = create_engine(URL.create(
    "mssql+pymssql", username=_user, password=_password,
    host=HOST, port=PORT, database=DATABASE,
))


def q(sql):
    return pd.read_sql(sql, engine)


def show(sql):
    df = q(sql)
    print(df.to_markdown(index=False))
    print(f"\n{len(df)} rows")
    return df
