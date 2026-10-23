"""Configuración por variables de entorno. Nunca se escriben credenciales en disco."""
import os
import sys
from dataclasses import dataclass
from pathlib import Path

EMPRESA = "0001"


@dataclass(frozen=True)
class Mpro:
    host: str
    base: str
    usuario: str
    clave: str
    puerto: int = 1433

    @property
    def etiqueta(self) -> str:
        return f".{self.host.rsplit('.', 1)[-1]} {self.base}"


def _credenciales_bi_core(cuenta: str = "ealcocer"):
    """Respaldo: credenciales de ~/ehalso/trivasa-bi-core (o BI_CORE_DIR), solo en memoria."""
    raiz = Path(os.environ.get("BI_CORE_DIR", "~/ehalso/trivasa-bi-core")).expanduser()
    if not raiz.is_dir():
        return None
    sys.path.insert(0, str(raiz))
    try:
        from shared import db_credentials
        return getattr(db_credentials, cuenta)()
    except Exception:
        return None
    finally:
        sys.path.remove(str(raiz))


def mpro_desde_entorno() -> Mpro:
    """Host/base por MPRO_HOST/MPRO_DB (por omisión .207/TRIVASADB, producción).

    Usuario y clave: MPRO_USER/MPRO_PASSWORD, o MSSQL_<207|205>_USER/PASSWORD, o trivasa-bi-core.
    """
    host = os.environ.get("MPRO_HOST", "192.168.117.207")
    base = os.environ.get("MPRO_DB", "TRIVASADB")
    sufijo = "207" if host.endswith(".207") else "205"
    usuario = os.environ.get("MPRO_USER") or os.environ.get(f"MSSQL_{sufijo}_USER")
    clave = os.environ.get("MPRO_PASSWORD") or os.environ.get(f"MSSQL_{sufijo}_PASSWORD")
    if not (usuario and clave) and sufijo == "207":
        usuario, clave = _credenciales_bi_core() or (None, None)
    if not (usuario and clave):
        raise RuntimeError(f"Sin credenciales de BD: define MPRO_USER y MPRO_PASSWORD (o MSSQL_{sufijo}_USER/PASSWORD).")
    return Mpro(host, base, usuario, clave)


@dataclass(frozen=True)
class Servidor:
    usuario: str
    clave: str
    puerto: int
    ttl_seg: int
    max_cache: int = 6


def servidor_desde_entorno() -> Servidor:
    usuario, clave = os.environ.get("APP_USER"), os.environ.get("APP_PASS")
    if not (usuario and clave):
        raise RuntimeError("Define APP_USER y APP_PASS (autenticación básica).")
    return Servidor(usuario, clave, int(os.environ.get("APP_PORT", 0)), int(os.environ.get("TTL_SEG", 600)))


@dataclass(frozen=True)
class Sat:
    host: str
    puerto: int
    base: str
    usuario: str
    clave: str


def sat_desde_entorno() -> Sat | None:
    """Postgres del warehouse (`raw_sat_api`), solo lectura. None si no hay credenciales (el reporte sale sin SAT).

    Host/puerto/base: SAT_PG_HOST (localhost), SAT_PG_PORT (5433), SAT_PG_DB (trivasa_dw).
    Usuario y clave: SAT_PG_USER/SAT_PG_PASSWORD, o POSTGRES_DW_RO_USERNAME/PASSWORD, o trivasa-bi-core (en memoria).
    """
    host = os.environ.get("SAT_PG_HOST", "localhost")
    puerto = int(os.environ.get("SAT_PG_PORT", 5433))
    base = os.environ.get("SAT_PG_DB", "trivasa_dw")
    usuario = os.environ.get("SAT_PG_USER") or os.environ.get("POSTGRES_DW_RO_USERNAME")
    clave = os.environ.get("SAT_PG_PASSWORD") or os.environ.get("POSTGRES_DW_RO_PASSWORD")
    if not (usuario and clave):
        creds = _credenciales_bi_core("postgres_dw")
        if creds:
            usuario, clave, base = creds[0], creds[1], creds[2] if len(creds) > 2 else base
    return Sat(host, puerto, base, usuario, clave) if usuario and clave else None
