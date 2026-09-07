"""Cliente para el bridge de consultas SQL en ctunlinux
(https://reportesweb.frento.com.mx/query).

El bridge es de solo lectura: recibe {"target", "sql"} y regresa
{"columns", "rows", "row_count", "truncated"}. No usamos el parámetro
`params` del bridge (su soporte de bind vars no está verificado para
mssql) — en su lugar construimos SQL con literales, escapando strings
nosotros mismos (los únicos valores dinámicos que insertamos son UUIDs,
fechas ISO y periodos, todos de bajo riesgo, pero igual se escapan).
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://reportesweb.frento.com.mx"
TOKEN_FILE = Path(os.environ.get("QUERY_API_TOKEN_FILE", "/home/claude/.query_api_token"))


def _token() -> str:
    tok = os.environ.get("QUERY_API_TOKEN")
    if tok:
        return tok.strip()
    return TOKEN_FILE.read_text().strip()


def sql_quote(value: str) -> str:
    """Escapa un literal string para SQL (Postgres y T-SQL usan la misma
    convención: comilla simple se duplica)."""
    return "'" + str(value).replace("'", "''") + "'"


def run_query(target: str, sql: str, max_retries: int = 3, timeout: int = 60) -> dict[str, Any]:
    """Ejecuta una consulta vía el bridge. Reintenta en 502/503 (vistos como
    transitorios en consultas de tabla completa sin WHERE selectivo)."""
    token = _token()
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                f"{BASE_URL}/query",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"target": target, "sql": sql},
                timeout=timeout,
            )
            if resp.status_code in (502, 503, 504):
                last_err = RuntimeError(f"HTTP {resp.status_code} (intento {attempt}/{max_retries})")
                time.sleep(2 * attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_err = exc
            time.sleep(2 * attempt)
    raise RuntimeError(f"Falló /query tras {max_retries} intentos: {last_err}\nSQL: {sql[:300]}")


def rows_as_dicts(result: dict[str, Any]) -> list[dict[str, Any]]:
    cols = result["columns"]
    return [dict(zip(cols, row)) for row in result["rows"]]
