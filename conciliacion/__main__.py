"""python -m conciliacion  →  levanta el reporte web (APP_USER, APP_PASS, APP_PORT, TTL_SEG; BD por MPRO_* (CONC_BACKEND=mssql, por omisión) o por SAT_PG_* con CONC_BACKEND=postgres; SAT por SAT_PG_*)."""
from types import SimpleNamespace

from .config import mpro_desde_entorno, sat_desde_entorno, servidor_desde_entorno
from .db import crear_engine, crear_engine_dw, crear_engine_sat
from .dialecto import BACKEND
from .servidor import crear_servidor


def main() -> None:
    cfg, sat = servidor_desde_entorno(), sat_desde_entorno()
    if BACKEND == "postgres":
        if not sat:
            raise RuntimeError("CONC_BACKEND=postgres requiere SAT_PG_USER/SAT_PG_PASSWORD (o POSTGRES_DW_RO_*).")
        fuente, engine = SimpleNamespace(etiqueta=f"Postgres {sat.base} (raw)"), crear_engine_dw(sat)
    else:
        fuente = mpro_desde_entorno()
        engine = crear_engine(fuente)
    srv = crear_servidor(cfg, fuente, engine, crear_engine_sat(sat) if sat else None)
    print(srv.server_address[1], flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
