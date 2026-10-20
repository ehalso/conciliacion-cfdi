"""Ejecuta streamlit con credenciales de .205 en el entorno (leidas de trivasa-bi-core, nunca impresas)."""
import os, sys
sys.path.insert(0, os.path.expanduser("~/ehalso/trivasa-bi-core"))
from shared import db_credentials
_u, _p = db_credentials.sa()
os.environ["MSSQL_205_USER"], os.environ["MSSQL_205_PASSWORD"] = _u, _p
os.environ["TRIVASADB_USER"], os.environ["TRIVASADB_PASSWORD"] = _u, _p
sys.path  # noqa
os.environ['PYTHONPATH']=os.path.dirname(os.path.abspath(__file__))+os.pathsep+os.environ.get('PYTHONPATH','')
os.execv(sys.argv[1], sys.argv[1:])
