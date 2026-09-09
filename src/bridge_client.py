"""Cliente de conexión DIRECTA a las bases de Trivasa (Postgres `raw_sat` /
`trivasa_dw`, y los dos SQL Server de mpro), sin pasar por una bridge HTTP.

Historia: hasta 2026-09, este repo corría en un entorno Cowork sin ruta de
red hacia la LAN de Trivasa, así que todas las extracciones pasaban por una
API bridge (`https://reportesweb.frento.com.mx/query`) mantenida aparte en
ctunlinux. Con acceso de red directo ya disponible (VPN sobre
192.168.117.0/24), este módulo conserva el mismo contrato —
`run_query(target, sql) -> {"columns", "rows", "row_count", "truncated"}` —
para que los ~10 extractores que hacen `from bridge_client import run_query,
rows_as_dicts, sql_quote` no necesiten cambiar una sola línea: solo cambió
el transporte, de HTTP a una conexión SQL directa.

Solo lectura, mismo espíritu que la bridge que reemplaza (ver
docs/arquitectura.md): cada SQL se valida como un único SELECT/WITH antes
de ejecutarse (`_guard_readonly`, espejo en texto de `sql_guard.py` del
lado servidor, ya sin servidor intermedio que lo aplique), y Postgres abre
la conexión en modo read-only real (`postgresql_readonly=True`). Para los
SQL Server (pymssql no soporta un modo read-only por sesión) la red de
seguridad es no llamar `commit()` nunca — SQLAlchemy hace rollback al
cerrar una conexión sin commit.

Credenciales: host/puerto/nombre de base NO son secreto (topología de red,
documentada en docs/arquitectura.md) y quedan hardcodeados abajo. Usuario y
password sí lo son — SIEMPRE por variable de entorno, nunca en este
archivo. Se leen de un `.env` local (gitignored, cargado automáticamente
si existe) o de variables ya exportadas en el shell:

  PG_HOST / PG_PORT / PG_DATABASE / PG_USER / PG_PASSWORD    (postgres_dw)
  MSSQL_205_USER / MSSQL_205_PASSWORD                        (mssql_205)
  MSSQL_207_USER / MSSQL_207_PASSWORD                        (mssql_207)

Ver `.env.example` para la plantilla.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# Host/puerto/base: topología de red, no secreto (ver docs/arquitectura.md
# y trivasa-context/docs/arquitectura/servidores-y-bases.md).
TARGETS: dict[str, dict[str, Any]] = {
    "postgres_dw": dict(
        drivername="postgresql+psycopg2",
        host=os.environ.get("PG_HOST", "192.168.117.14"),
        port=int(os.environ.get("PG_PORT", "5433")),
        database=os.environ.get("PG_DATABASE", "trivasa_dw"),
        user_env="PG_USER", password_env="PG_PASSWORD",
    ),
    "mssql_205": dict(
        drivername="mssql+pymssql", host="192.168.117.205", port=1433, database="TRIVASADB3",
        user_env="MSSQL_205_USER", password_env="MSSQL_205_PASSWORD",
    ),
    "mssql_207": dict(
        drivername="mssql+pymssql", host="192.168.117.207", port=1433, database="TRIVASADB",
        user_env="MSSQL_207_USER", password_env="MSSQL_207_PASSWORD",
    ),
}

_ENGINES: dict[str, Engine] = {}

_WRITE_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|EXEC|EXECUTE|MERGE|GRANT|REVOKE|CREATE|INTO)\b",
    re.IGNORECASE,
)


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return sql


def _guard_readonly(sql: str) -> None:
    """Un único SELECT/WITH, sin palabras clave de escritura. No es un
    parser SQL real (tampoco lo era el sql_guard.py del bridge original) —
    es una red de seguridad de texto, ahora del lado cliente."""
    stripped = _strip_comments(sql).strip()
    if stripped.endswith(";"):
        stripped = stripped[:-1].strip()
    if ";" in stripped:
        raise ValueError("Solo se permite un statement por consulta (sin ';' en medio).")
    if not re.match(r"^(SELECT|WITH)\b", stripped, re.IGNORECASE):
        raise ValueError("Solo se permiten sentencias SELECT / WITH ... SELECT.")
    match = _WRITE_KEYWORDS.search(stripped)
    if match:
        raise ValueError(f"Palabra clave de escritura no permitida: {match.group(0)!r}")


def _engine(target: str) -> Engine:
    if target not in TARGETS:
        raise ValueError(f"target debe ser uno de {sorted(TARGETS)}, se recibió {target!r}")
    if target not in _ENGINES:
        cfg = TARGETS[target]
        user = os.environ.get(cfg["user_env"])
        password = os.environ.get(cfg["password_env"])
        if not user or not password:
            raise RuntimeError(
                f"Faltan credenciales para {target!r}: define {cfg['user_env']} y "
                f"{cfg['password_env']} (variable de entorno, o en un .env local — ver "
                f".env.example). Nunca hardcodeadas en código."
            )
        url = URL.create(cfg["drivername"], username=user, password=password,
                          host=cfg["host"], port=cfg["port"], database=cfg["database"])
        connect_args = {"timeout": 60, "login_timeout": 15} if "mssql" in cfg["drivername"] \
            else {"connect_timeout": 15}
        _ENGINES[target] = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    return _ENGINES[target]


def sql_quote(value: str) -> str:
    """Escapa un literal string para SQL (Postgres y T-SQL usan la misma
    convención: comilla simple se duplica)."""
    return "'" + str(value).replace("'", "''") + "'"


def run_query(target: str, sql: str, max_retries: int = 3, timeout: int = 60) -> dict[str, Any]:
    """Ejecuta un SELECT/WITH de solo lectura directo contra `target`
    (postgres_dw / mssql_205 / mssql_207). Devuelve el mismo shape que
    devolvía la bridge HTTP: {"columns", "rows", "row_count", "truncated"}
    (`truncated` siempre False aquí — ya no hay tope de 20,000 filas del
    lado servidor; si algún query necesita paginar, lo sigue haciendo con
    su propio LIMIT/OFFSET como ya hacían los extractores).

    Reintenta con backoff ante errores de conexión transitorios (la VPN a
    la LAN puede tener hiccups) — no reintenta errores de la propia
    consulta (SQL inválido, permisos, etc.), esos se propagan de inmediato.
    """
    _guard_readonly(sql)
    engine = _engine(target)
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            options = {"postgresql_readonly": True} if target == "postgres_dw" else {}
            with engine.connect().execution_options(**options) as conn:
                result = conn.execute(text(sql))
                cols = list(result.keys())
                rows = [list(row) for row in result.fetchall()]
            return {"columns": cols, "rows": rows, "row_count": len(rows), "truncated": False}
        except (TimeoutError, ConnectionError) as exc:
            last_err = exc
            time.sleep(2 * attempt)
        except Exception as exc:
            # sqlalchemy envuelve los errores de driver (psycopg2/pymssql) en
            # OperationalError para problemas de conexión/timeout — esos sí
            # vale la pena reintentar; cualquier otra cosa (SQL inválido,
            # tabla no existe, permiso denegado) se propaga de inmediato.
            from sqlalchemy.exc import OperationalError
            if isinstance(exc, OperationalError) and attempt < max_retries:
                last_err = exc
                time.sleep(2 * attempt)
                continue
            raise
    raise RuntimeError(f"Falló la consulta a {target!r} tras {max_retries} intentos: {last_err}\nSQL: {sql[:300]}")


def rows_as_dicts(result: dict[str, Any]) -> list[dict[str, Any]]:
    cols = result["columns"]
    return [dict(zip(cols, row)) for row in result["rows"]]
