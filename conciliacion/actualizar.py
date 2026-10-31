"""Refresco bajo demanda de los datos: ingest dlt (.207 → raw.*). Lo lanza el botón "Actualizar datos" del servidor.

Mismos run_daily que los crons de 06:00 y 06:20 de trivasa-bi-core, en serie. Un solo refresco a la vez (flock) y no corre
en la ventana de los crons, para no pisar sus pipelines dlt. Estado en STATE_DIR/estado.json; el log va a stdout.
"""
import datetime as dt
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

CORE = Path(os.environ.get("BI_CORE", Path.home() / "ehalso" / "trivasa-bi-core"))
DLT = CORE / "dlt"
STATE_DIR = Path(os.environ.get("STATE_DIR", Path.home() / "conciliacion_state"))
TZ = ZoneInfo("America/Mexico_City")
PASO_TIMEOUT = 1800
VENTANA_CRON = (dt.time(5, 55), dt.time(7, 5))  # hora del host: dlt_comprobante_digital 06:00, dlt_gastos_cxp 06:20, dbt 06:58
INTERVALO_MIN = 600  # segundos desde la última corrida correcta

PY = sys.executable
PASOS = [
    ("Gastos, CxP y pólizas", [PY, "-c", "from load_gastos_cxp import run_daily; run_daily()"]),
    ("Comprobantes digitales", [PY, "-c", "from load_comprobante_digital import run_daily; run_daily()"]),
]


def ahora() -> str:
    return dt.datetime.now(TZ).isoformat(timespec="seconds")


def leer_estado() -> dict:
    try:
        return json.loads((STATE_DIR / "estado.json").read_text())
    except Exception:
        return {}


def guardar(d: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_DIR / "estado.tmp"
    tmp.write_text(json.dumps(d, ensure_ascii=False))
    os.replace(tmp, STATE_DIR / "estado.json")


def en_ventana_cron() -> bool:
    return VENTANA_CRON[0] <= dt.datetime.now().time() <= VENTANA_CRON[1]


def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(STATE_DIR / "actualizar.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("ya hay un refresco en curso")
        return 3
    est = leer_estado()
    ok = est.get("ultima_ok")
    if en_ventana_cron():
        guardar({**est, "estado": "rechazado", "fin": ahora(),
                 "motivo": "Hay cargas programadas en curso (05:55–07:05, hora del servidor). Intenta de nuevo después."})
        return 4
    if ok and (dt.datetime.now(TZ) - dt.datetime.fromisoformat(ok)).total_seconds() < INTERVALO_MIN:
        guardar({**est, "estado": "rechazado", "fin": ahora(),
                 "motivo": f"Los datos se actualizaron hace menos de {INTERVALO_MIN // 60} minutos."})
        return 5

    pasos = [{"nombre": n, "estado": "pendiente", "segundos": None} for n, _ in PASOS]
    est = {**est, "estado": "corriendo", "inicio": ahora(), "fin": None, "error": None, "motivo": None, "pasos": pasos}
    guardar(est)
    t0 = time.time()
    for i, (nombre, cmd) in enumerate(PASOS):
        pasos[i]["estado"] = "corriendo"
        guardar(est)
        print(f"[{ahora()}] {nombre}", flush=True)
        t = time.time()
        try:
            rc = subprocess.run(cmd, cwd=DLT, timeout=PASO_TIMEOUT).returncode
        except subprocess.TimeoutExpired:
            rc = -1
        pasos[i]["segundos"] = round(time.time() - t)
        if rc != 0:
            pasos[i]["estado"] = "error"
            guardar({**est, "estado": "error", "fin": ahora(), "error": f"Falló el paso «{nombre}» (código {rc})."})
            return 1
        pasos[i]["estado"] = "ok"
        guardar(est)
    fin = ahora()
    guardar({**est, "estado": "ok", "fin": fin, "ultima_ok": fin, "segundos": round(time.time() - t0)})
    print(f"[{fin}] listo en {round(time.time() - t0)} s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
