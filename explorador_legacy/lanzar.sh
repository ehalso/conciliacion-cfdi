#!/bin/bash
# Levanta el explorador (:32841) y las apps legacy (:32842, :32843). Uso: ./lanzar.sh [detener]
CF=/home/ealcocer/ehalso/conciliacion-cfdi
RM=/home/ealcocer/ehalso/reportes-mpro
ST=$RM/streamlit_venv/bin/streamlit
LOG=/tmp/legacy_explorer
mkdir -p $LOG
if [ "$1" = "detener" ]; then
  for p in 32840 32841 32842 32843 32844 32845 32846 32847 32848 32849 32850 32851 32852; do pid=$(ss -ltnp | grep ":$p " | grep -o 'pid=[0-9]*' | cut -d= -f2); [ -n "$pid" ] && kill $pid; done; exit 0
fi
arranca() { # puerto dir archivo
  ss -ltn | grep -q ":$1 " && { echo ":$1 ya corre"; return; }
  (cd $2 && nohup python3 $CF/explorador_legacy/run_con_creds.py $ST run $3 --server.port $1 --server.address 0.0.0.0 --server.headless true > $LOG/$1.log 2>&1 &)
}
arranca 32841 $CF/explorador_legacy app.py
arranca 32842 /home/ealcocer/ehalso/trivasa-apps-archivadas/conciliacion-hub-cont app.py
arranca 32840 $RM reportes_streamlit/streamlit_app.py
FIFO=/home/ealcocer/ehalso/trivasa-context/docs/proyectos/consumo-interno-fifo/scripts
PO=/home/ealcocer/por_ordenar/exploracion
HUB=/home/ealcocer/ehalso/trivasa-apps-archivadas/hub-reportes-trivasa
arranca 32850 $HUB/layout-gastos-ctunlinux hub_app.py
PY=$RM/streamlit_venv/bin/python
EX=$CF/explorador_legacy
