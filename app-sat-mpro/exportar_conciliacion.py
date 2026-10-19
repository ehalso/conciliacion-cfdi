"""Cruza raw_sat_api.cfdi (Postgres) con Comprobante_Digital (MPRO) por UUID y genera data.json."""
import os, sys, json, datetime as dt
import pandas as pd, psycopg
from dotenv import dotenv_values
from sqlalchemy import text

DESDE = sys.argv[1] if len(sys.argv) > 1 else '2026-01-01'
HASTA = sys.argv[2] if len(sys.argv) > 2 else '2027-01-01'
OWN = 'TRI970922TL2'
TOL = 1.0
OUT = os.path.dirname(os.path.abspath(__file__))

def conn_erp():
    from connection_205_trivasadb3 import engine
    return engine

def dmy(s):
    return s.dt.strftime('%d-%m-%Y').fillna('')

erp = pd.read_sql(text("""
 select Cd_Tabla TABLA, Cd_Documento DOC, upper(Cd_Timbre_UUID) UUID, Cd_RFC_Emisor RE, Cd_RFC_Receptor RR,
        Cd_Monto MONTO, Cd_Moneda MON, Cd_Timbre_Fecha FT, Es_Cve_Estado EST, Cd_Tipo_CFDI TIPO
 from Comprobante_Digital
 where Cd_Timbre_Fecha>=:d and Cd_Timbre_Fecha<:h and Cd_Timbre_UUID is not null and Cd_Timbre_UUID<>''"""),
 conn_erp(), params={'d': DESDE, 'h': HASTA})
erp['DOC'] = erp.DOC.fillna('').astype(str).str.strip()
erp['REF'] = erp.TABLA.fillna('') + ' ' + erp.DOC
g = erp.groupby('UUID').agg(RE=('RE', 'first'), RR=('RR', 'first'), MONTO=('MONTO', 'max'), MON=('MON', 'first'),
    FT=('FT', 'first'), TIPO=('TIPO', 'first'), EST=('EST', lambda s: 'CA' if (s == 'CA').all() else ('AC' if (s == 'AC').any() else s.iloc[0])),
    DOCS=('REF', lambda s: ' | '.join(dict.fromkeys(s))), MODULOS=('TABLA', lambda s: ', '.join(sorted(set(s.fillna('')))))).reset_index()

from sqlalchemy import create_engine
cn = create_engine(dotenv_values(os.path.expanduser('~/ehalso/sat-descarga-cfdi/.env'))['PG_DSN'].replace('postgresql://','postgresql+psycopg://',1))
sat = pd.read_sql("""select upper(uuid) uuid, tipo, tipo_comprobante tc, fecha, serie, folio, rfc_emisor re, nombre_emisor ne,
   rfc_receptor rr, nombre_receptor nr, moneda, total, metodo_pago from raw_sat_api.cfdi
   where fecha>=%(d)s and fecha<%(h)s""", cn, params={'d': DESDE, 'h': HASTA})
sat['pri'] = ((sat.tipo == 'emitidos') == (sat.re == OWN)).astype(int)
sat = sat.sort_values('pri', ascending=False).drop_duplicates('uuid')
sat['total'] = sat.total.astype(float)
sat['fecha'] = pd.to_datetime(sat.fecha)

CORTE = erp.FT.max().normalize()
m = sat.merge(g, how='outer', left_on='uuid', right_on='UUID', indicator='lado')
rows = []
m['lado'] = m['lado'].astype(str)
for d in m.to_dict('records'):
    ins, ine = d['lado'] != 'right_only', d['lado'] != 'left_only'
    uuid = d['uuid'] if ins else d['UUID']
    re_ = d['re'] if ins else d['RE']; rr = d['rr'] if ins else d['RR']
    emitido = re_ == OWN
    tc = d['tc'] if ins else (d['TIPO'] or '')
    fecha = d['fecha'] if ins else d['FT']
    contra = (rr if emitido else re_) or ''
    nombre = (d['nr'] if emitido else d['ne']) if ins else ''
    sf = ''.join([str(d['serie'] or ''), str(d['folio'] or '')]) if ins else ''
    total = d['total'] if ins else None
    monto = float(d['MONTO']) if ine and d['MONTO'] == d['MONTO'] and d['MONTO'] is not None else None
    nota = ''
    if ins and ine:
        if d['EST'] == 'CA':
            est, nota = 'CAN', 'En MPRO está cancelado y en el SAT vigente'
        else:
            dif = []
            if monto is not None and total is not None and abs(monto - total) > TOL:
                dif.append(f'Importe: SAT {total:,.2f} vs MPRO {monto:,.2f}')
            if (d['RE'] and d['RE'] != d['re']) or (d['RR'] and d['RR'] != d['rr']):
                dif.append('RFC emisor/receptor distinto')
            est, nota = ('DIF', '; '.join(dif)) if dif else ('OK', '')
    elif ins:
        if tc == 'N':
            est, nota = 'NOM', 'Nómina: no se registra en MPRO'
        elif fecha > CORTE + pd.Timedelta(days=1):
            est, nota = 'PEN', f'Posterior al último timbre cargado en MPRO ({CORTE:%d-%m-%Y})'
        else:
            est, nota = 'FSM', ''
    else:
        est, nota = 'FSAT', ('Cancelado en MPRO' if d['EST'] == 'CA' else '')
    rows.append([uuid, 'E' if emitido else 'R', tc, fecha.strftime('%d-%m-%Y') if pd.notna(fecha) else '',
        fecha.strftime('%Y-%m') if pd.notna(fecha) else '', contra, nombre or '', sf,
        round(total, 2) if total is not None else None, round(monto, 2) if monto is not None else None,
        (d['moneda'] if ins else d['MON']) or '', est, d['DOCS'] if ine else '', d['MODULOS'] if ine else '', nota])

cols = ['uuid', 'dir', 'tc', 'fecha', 'mes', 'rfc', 'nombre', 'folio', 'sat', 'mpro', 'mon', 'est', 'docs', 'mod', 'nota']
json.dump({'cols': cols, 'rows': rows, 'corte': CORTE.strftime('%d-%m-%Y'), 'generado': dt.datetime.now().strftime('%d-%m-%Y %H:%M'), 'desde': DESDE, 'hasta': HASTA},
          open(os.path.join(OUT, 'data.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
df = pd.DataFrame(rows, columns=cols)
print(len(df)); print(df.groupby(['dir', 'est']).size().unstack(fill_value=0))
