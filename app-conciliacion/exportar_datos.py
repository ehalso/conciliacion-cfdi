"""Convierte el DataFrame del reporte (build_reporte.py) en el JSON que consume plantilla.html.

Modo estático (como antes): python3 exportar_datos.py rep_2026-01-01_2026-02-01.pkl -> index.html con los datos incrustados.
Modo vivo: serve_vivo.py importa a_datos() y entrega el JSON por /api/reporte.
Las columnas con linea=false solo se llenan en la primera fila de cada folio.
"""
import json, sys, os
import pandas as pd

aqui = os.path.dirname(os.path.abspath(__file__))
COLS = json.load(open(os.path.join(aqui, 'columnas.json'), encoding='utf-8'))
FECHAS = ('FECHA', 'FECHA_POLIZA', 'FECHA_CHEQUE', 'FECHA_COMPLEMENTO_PAGO')
POLIZA = ('POLIZA', 'NUMERO_POLIZA', 'TIPO_POLIZA', 'FECHA_POLIZA', 'CONCEPTO_POLIZA')
REPITEN = ('registro_gasto', 'control_combustible', 'orden_compra', 'viaje')

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

def a_datos(d):
    d = d.reset_index(drop=True).copy()
    for c in COLS:
        if c['k'] not in d.columns:
            d[c['k']] = None
    primera = (~d.FOLIO.duplicated()).to_numpy()
    rep = d.ORIGEN.isin(REPITEN).to_numpy()
    for k in FECHAS:
        d[k] = pd.to_datetime(d[k], errors='coerce').dt.strftime('%d-%m-%Y')
    ks = [c['k'] for c in COLS]
    ia = [ks.index(k) for k in ('CARGO', 'ABONO')]
    filas = []
    for i, r in enumerate(d[ks].itertuples(index=False)):
        fila = [val(v) if (primera[i] or c['linea'] or (rep[i] and c['k'] not in POLIZA)) else None for c, v in zip(COLS, r)]
        for j in ia:
            fila[j] = fila[j] or None
        filas.append(fila)
    return {'cols': [{k: c[k] for k in ('k', 'l', 'g', 't')} for c in COLS], 'rows': filas}

if __name__ == '__main__':
    datos = a_datos(pd.read_pickle(sys.argv[1]))
    tpl = open(os.path.join(aqui, 'plantilla.html'), encoding='utf-8').read()
    out = os.environ.get('SALIDA', os.path.join(aqui, 'index.html'))
    open(out, 'w', encoding='utf-8').write(tpl.replace('/*DATA*/null', json.dumps(datos, ensure_ascii=False, separators=(',', ':'))))
    print(len(datos['rows']), 'filas ->', out)
