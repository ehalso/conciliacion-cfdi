"""Configuración por variables de entorno (en el servicio: ~/.config/conciliacion_apps.env, valores de Infisical)."""
import os
from dataclasses import dataclass

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


def mpro_desde_entorno() -> Mpro:
    """Host/base por MPRO_HOST/MPRO_DB (por omisión .207/TRIVASADB, producción).

    Usuario y clave: MPRO_USER/MPRO_PASSWORD, o MSSQL_<207|205>_USER/PASSWORD.
    """
    host = os.environ.get("MPRO_HOST", "192.168.117.207")
    base = os.environ.get("MPRO_DB", "TRIVASADB")
    sufijo = "207" if host.endswith(".207") else "205"
    usuario = os.environ.get("MPRO_USER") or os.environ.get(f"MSSQL_{sufijo}_USER")
    clave = os.environ.get("MPRO_PASSWORD") or os.environ.get(f"MSSQL_{sufijo}_PASSWORD")
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
    Usuario y clave: SAT_PG_USER/SAT_PG_PASSWORD, o POSTGRES_DW_RO_USERNAME/PASSWORD.
    """
    host = os.environ.get("SAT_PG_HOST", "localhost")
    puerto = int(os.environ.get("SAT_PG_PORT", 5433))
    base = os.environ.get("SAT_PG_DB", "trivasa_dw")
    usuario = os.environ.get("SAT_PG_USER") or os.environ.get("POSTGRES_DW_RO_USERNAME")
    clave = os.environ.get("SAT_PG_PASSWORD") or os.environ.get("POSTGRES_DW_RO_PASSWORD")
    return Sat(host, puerto, base, usuario, clave) if usuario and clave else None
