"""Ejecuta streamlit con credenciales de .205 en el entorno (leidas de trivasa-bi-core, nunca impresas)."""
import os, sys
sys.path.insert(0, os.path.expanduser("~/ehalso/trivasa-bi-core"))
from shared import db_credentials
_u, _p = db_credentials.sa()
os.environ["MSSQL_205_USER"], os.environ["MSSQL_205_PASSWORD"] = _u, _p
os.environ["TRIVASADB_USER"], os.environ["TRIVASADB_PASSWORD"] = _u, _p
_u7, _p7 = db_credentials.ealcocer()
os.environ["MSSQL_207_USER"], os.environ["MSSQL_207_PASSWORD"] = _u7, _p7
import json, subprocess
_env = dict(os.environ)
for _l in open(os.path.expanduser("~/.config/infisical/.env")):
    if _l.startswith("export "):
        for _kv in _l[7:].split():
            _k, _, _v = _kv.partition("="); _env[_k] = _v
_out = subprocess.run(["infisical", "secrets", "--env", "dev", "--projectId", "b6567423-9986-448e-b2b8-dffe44fe1657", "-o", "json"],
                      env=_env, capture_output=True, text=True, timeout=60, check=True).stdout
_s = {x["secretKey"]: x["secretValue"] for x in json.loads(_out)}
os.environ["PG_USER"], os.environ["PG_PASSWORD"] = _s["POSTGRES_DW_RO_USERNAME"], _s["POSTGRES_DW_RO_PASSWORD"]
os.environ["PG_HOST"], os.environ["PG_PORT"], os.environ["PG_DATABASE"] = _s["POSTGRES_DW_HOST"], _s["POSTGRES_DW_PORT"], _s["POSTGRES_DW_DBNAME"]
_d=os.path.dirname(os.path.abspath(__file__)); os.environ['PYTHONPATH']=_d+os.pathsep+os.path.join(_d,'_deps')+os.pathsep+os.environ.get('PYTHONPATH','')
os.execv(sys.argv[1], sys.argv[1:])
