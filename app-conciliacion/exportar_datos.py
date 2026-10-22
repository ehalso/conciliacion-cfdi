"""Convierte el DataFrame del reporte (build_reporte.py) en el JSON que consume plantilla.html.

Modo estático: python3 exportar_datos.py rep_2026-01-01_2026-02-01.pkl -> index.html con los datos incrustados (vista Layout).
Modo vivo: serve_vivo.py importa a_datos() y entrega el JSON por /api/reporte.

Dos vistas:
  layout  (por defecto) subtotales, impuestos, TOTAL, XML_MONTO y MONTO_COBRADO solo en la primera fila del documento;
          las demás filas llevan únicamente Tipo/folio y los campos de la póliza. Con agrupar=True las líneas de
          póliza se suman por cuenta contable. En registro_gasto, control_combustible, orden_compra y viaje los
          datos de texto (proveedor, UUID, XML, pago) se repiten en todas las filas del folio (observación de Ismael).
  ceco    análisis por CECO: subtotales e impuestos prorrateados en cada línea de póliza (TOTAL por línea).
Las columnas sin ningún dato en el resultado no se envían.
"""
import json, sys, os
import numpy as np, pandas as pd

aqui = os.path.dirname(os.path.abspath(__file__))
COLS = json.load(open(os.path.join(aqui, 'columnas.json'), encoding='utf-8'))
FECHAS = ('FECHA', 'FECHA_POLIZA', 'FECHA_CHEQUE', 'FECHA_COMPLEMENTO_PAGO')
POLIZA = ('POLIZA', 'NUMERO_POLIZA', 'TIPO_POLIZA', 'FECHA_POLIZA', 'CONCEPTO_POLIZA')
REPITEN = ('registro_gasto', 'control_combustible', 'orden_compra', 'viaje')
SIEMPRE = ('Tipo', 'FOLIO', 'FECHA', 'SUBTOTAL_NETO', 'TOTAL', 'CARGO', 'ABONO')
ORDEN_TIPO = {'Gasto': 0, 'Compra': 1, 'Indirecto': 2, 'NC proveedor': 3, 'CxP libre': 4, 'CxP orden compra': 5}
CIFRAS_DOC =('SUBTOTAL_0', 'SUBTOTAL_16', 'SUBTOTAL_EXENTA', 'SUBTOTAL_NETO', 'TOTAL')
LAYOUT_LINEA = {'Tipo', 'ORIGEN', 'FOLIO'} | {c['k'] for c in COLS if c['g'] == 'Póliza'}

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

def columnas(d):
    """COLS más las claves IMP_xxxx que traiga el DataFrame y aún no estén en columnas.json."""
    ks = {c['k'] for c in COLS}
    extra = [{'k': k, 'l': k[4:] + ' Impuesto', 'g': 'Impuestos', 't': 'n', 'linea': True}
             for k in sorted(d.columns) if k.startswith('IMP_') and k not in ks]
    if not extra:
        return list(COLS)
    i = max(j for j, c in enumerate(COLS) if c['g'] == 'Impuestos') + 1
    return COLS[:i] + extra + COLS[i:]

def agrupar_cuenta(d):
    """Suma las líneas de póliza de cada documento por cuenta contable (CECO: el único, o VARIOS)."""
    d = d.copy()
    k = ['Tipo', 'FOLIO', 'CUENTA_REGISTRO']
    d['_net'] = d.CARGO.fillna(0) - d.ABONO.fillna(0)
    g = d.groupby(k, sort=False, dropna=False)
    d['_net'] = g._net.transform('sum')
    nu, uno = g.CECO.transform('nunique'), g.CECO.transform('first')
    d['CECO'] = np.where(nu > 1, 'VARIOS', uno)
    d = d.drop_duplicates(k).copy()
    d['CARGO'] = d._net.clip(lower=0).round(2)
    d['ABONO'] = (-d._net).clip(lower=0).round(2)
    return d.drop(columns='_net').reset_index(drop=True)

def a_datos(d, vista='layout', agrupar=True):
    layout = vista == 'layout'
    d = d.reset_index(drop=True).copy()
    if 'Tipo' not in d.columns:
        d['Tipo'] = 'Gasto'
    d['_t'] = d.Tipo.map(ORDEN_TIPO).fillna(9)
    d['_g'] = d.groupby(['Tipo', 'FOLIO'], sort=False).ngroup()
    d = d.sort_values(['_t', '_g'], kind='stable').drop(columns=['_t', '_g']).reset_index(drop=True)
    if layout and agrupar:
        d = agrupar_cuenta(d)
    cols = columnas(d)
    for c in cols:
        if c['k'] not in d.columns:
            d[c['k']] = None
    llave = d.Tipo.astype(str) + '|' + d.FOLIO.astype(str)
    primera = (llave != llave.shift()).to_numpy()
    rep = d.ORIGEN.isin(REPITEN).to_numpy()
    for k in FECHAS:
        d[k] = pd.to_datetime(d[k], errors='coerce').dt.strftime('%d-%m-%Y')
    ks = [c['k'] for c in cols]
    fuente = {k: ('DOC_' + k if layout and ('DOC_' + k) in d.columns and (k in CIFRAS_DOC or k.startswith('IMP_')) else k) for k in ks}
    ia = [ks.index(k) for k in ('CARGO', 'ABONO')]
    cero = {i for i, c in enumerate(cols) if c['t'] == 'n' and (c['g'] == 'Impuestos' or c['k'] in ('SUBTOTAL_0', 'SUBTOTAL_16', 'SUBTOTAL_EXENTA'))}
    filas = []
    for i, r in enumerate(d[[fuente[k] for k in ks]].itertuples(index=False)):
        fila = []
        for j, (c, v) in enumerate(zip(cols, r)):
            if layout:
                visible = primera[i] or c['k'] in LAYOUT_LINEA or (rep[i] and c['t'] == 't' and c['k'] not in POLIZA)
            else:
                visible = primera[i] or c['linea'] or (rep[i] and c['k'] not in POLIZA)
            v = val(v) if visible else None
            fila.append(None if (j in cero and v == 0) else v)
        for j in ia:
            fila[j] = fila[j] or None
        filas.append(fila)
    if filas:
        usar = [j for j, c in enumerate(cols) if c['k'] in SIEMPRE or any(f[j] is not None for f in filas)]
        if len(usar) < len(cols):
            cols = [cols[j] for j in usar]
            filas = [[f[j] for j in usar] for f in filas]
    return {'cols': [{k: c[k] for k in ('k', 'l', 'g', 't')} for c in cols], 'rows': filas, 'vista': vista, 'agrupar': bool(layout and agrupar)}

if __name__ == '__main__':
    datos = a_datos(pd.read_pickle(sys.argv[1]))
    tpl = open(os.path.join(aqui, 'plantilla.html'), encoding='utf-8').read()
    out = os.environ.get('SALIDA', os.path.join(aqui, 'index.html'))
    open(out, 'w', encoding='utf-8').write(tpl.replace('/*DATA*/null', json.dumps(datos, ensure_ascii=False, separators=(',', ':'))))
    print(len(datos['rows']), 'filas ->', out)
