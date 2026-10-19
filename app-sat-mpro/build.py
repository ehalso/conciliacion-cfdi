"""Genera index.html (pendientes + resumen) y extra.json (conciliados y nómina) desde data.json."""
import json, os
d = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(f'{d}/data.json'))
est = D['cols'].index('est')
pend = [r for r in D['rows'] if r[est] not in ('OK', 'NOM')]
extra = [r for r in D['rows'] if r[est] in ('OK', 'NOM')]
# resumen para que los KPIs/meses sean correctos aunque falten conciliados: se incluyen como filas "ligeras"
from collections import Counter
agg = [list(k) + [n] for k, n in Counter((r[1], r[2], r[4], r[est]) for r in extra).items()]
D2 = dict(D, rows=pend, agg=agg, completo=False)
html = open(f'{d}/plantilla.html').read().replace('__DATA__', json.dumps(D2, ensure_ascii=False, separators=(',', ':')))
open(f'{d}/index.html', 'w').write(html)
json.dump(extra, open(f'{d}/extra.json', 'w'), ensure_ascii=False, separators=(',', ':'))
print(len(pend), len(extra), os.path.getsize(f'{d}/index.html') // 1024, 'KB')
