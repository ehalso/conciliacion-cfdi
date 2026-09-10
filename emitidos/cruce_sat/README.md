# Emitidos — cruce independiente contra el SAT

Compara `raw_sat.cfdi_emitidos` (fuente **independiente** del ERP) contra
`Comprobante_Digital` (cualquier módulo) — detecta un CFDI que se timbró y
el ERP nunca registró, y el caso simétrico.

Script: [`cruce_sat_emitidos.py`](cruce_sat_emitidos.py), lógica de negocio
compartida con recibidos en [`src/cruce_sat.py`](../../src/cruce_sat.py).

```bash
python3 emitidos/cruce_sat/cruce_sat_emitidos.py --periodo 2026-01
```

## CAVEAT DE COBERTURA — importante

`raw_sat.cfdi_emitidos` solo tiene backfill hasta **enero 2026** (ver
`docs/emitidos_retenciones.md`). Para cualquier periodo posterior, el
cruce va a mostrar casi el 100% como `SOLO_MPRO` — **eso es el backfill
pendiente, no un hallazgo real de CFDI no registrados**. El script se deja
correr sobre cualquier periodo a propósito (para que sea inmediato en
cuanto el backfill avance) pero imprime una advertencia automática cuando
detecta ese patrón (>50% `SOLO_MPRO`).

## Resultado (validado en vivo, 2026-09-10)

| Periodo | En ambos | Solo SAT | Solo MPRO | Nota |
|---|---:|---:|---:|---|
| 2026-01 | 6,489 | 11 ($0 en todos) | 230 | Único periodo con backfill real — interpretable |
| 2026-03 | 0 | 0 | 6,473 (100%) | Backfill pendiente — no es un hallazgo, confirma el caveat de arriba |

Enero: `SOLO_MPRO` (230, 3.4%) puede incluir huecos reales del backfill
inicial incluso dentro de enero — no investigado a fondo todavía.
`SOLO_SAT` (11, monto $0 en todos) no parece un hueco real. Solo enero es
interpretable hasta que avance el backfill.
