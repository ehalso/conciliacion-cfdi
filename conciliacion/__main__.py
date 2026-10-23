"""python -m conciliacion  →  levanta el reporte web (APP_USER, APP_PASS, APP_PORT, TTL_SEG; BD por MPRO_*)."""
from .config import mpro_desde_entorno, servidor_desde_entorno
from .db import crear_engine
from .servidor import crear_servidor


def main() -> None:
    cfg, mpro = servidor_desde_entorno(), mpro_desde_entorno()
    srv = crear_servidor(cfg, mpro, crear_engine(mpro))
    print(srv.server_address[1], flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
