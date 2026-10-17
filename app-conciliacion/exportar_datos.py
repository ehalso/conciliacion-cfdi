"""Convierte el pickle del reporte (build_reporte.py) en data.json y genera index.html.

Uso: python3 exportar_datos.py rep_2026-01-01_2026-02-01.pkl
Las columnas con linea=false solo se llenan en la primera fila de cada folio.
"""
import json, sys, os
import pandas as pd

aqui = os.path.dirname(os.path.abspath(__file__))
cols = json.load(open(os.path.join(aqui, 'columnas.json'), encoding='utf-8'))
d = pd.read_pickle(sys.argv[1]).reset_index(drop=True)
primera = (~d.FOLIO.duplicated()).to_numpy()
FECHAS = ('FECHA', 'FECHA_POLIZA', 'FECHA_CHEQUE', 'FECHA_COMPLEMENTO_PAGO')
POLIZA = ('POLIZA', 'NUMERO_POLIZA', 'TIPO_POLIZA', 'FECHA_POLIZA', 'CONCEPTO_POLIZA')
REPITEN = ('registro_gasto', 'control_combustible', 'orden_compra', 'viaje')
rep = d.ORIGEN.isin(REPITEN).to_numpy()
for k in FECHAS:
    d[k] = pd.to_datetime(d[k], errors='coerce').dt.strftime('%d-%m-%Y')

def val(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return str(v)
    if hasattr(v, 'item'):
        v = v.item()
    if isinstance(v, str):
        v = v.strip()
    elif isinstance(v, float):
        v = round(v, 2)
    return None if v == '' else v

ia = [[c['k'] for c in cols].index(k) for k in ('CARGO', 'ABONO')]
filas = []
for i, r in enumerate(d[[c['k'] for c in cols]].itertuples(index=False)):
    fila = [val(v) if (primera[i] or c['linea'] or (rep[i] and c['k'] not in POLIZA)) else None for c, v in zip(cols, r)]
    for j in ia:
        fila[j] = fila[j] or None
    filas.append(fila)
datos = {'cols': [{k: c[k] for k in ('k', 'l', 'g', 't')} for c in cols], 'rows': filas}
tpl = open(os.path.join(aqui, 'plantilla.html'), encoding='utf-8').read()
open(os.path.join(aqui, 'index.html'), 'w', encoding='utf-8').write(
    tpl.replace('__DATA__', json.dumps(datos, ensure_ascii=False, separators=(',', ':'))))
print(len(filas), 'filas ->', os.path.join(aqui, 'index.html'))
