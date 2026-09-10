# Recibidos — cruce independiente contra el SAT

Compara `raw_sat.cfdi_recibidos` (fuente **independiente** — el XML que el
PAC deja en el share del SAT, cargado a Postgres sin pasar por el ERP)
contra `Comprobante_Digital` (cualquier módulo, sin filtrar por origen) —
detecta un CFDI recibido que el ERP nunca registró en ningún lado, y el
caso simétrico: algo etiquetado en el ERP con un UUID que no aparece en la
fuente independiente del SAT.

Es un chequeo de **existencia**, no de importe — la contraparte más simple
de `recibidos/nivel_poliza/baseline_universal.py` (que sí exige que el
cargo agregado cuadre contra el Subtotal). Un CFDI de valor $0 (complemento
de traslado, pago) es candidato igual que uno con valor real.

Script: [`cruce_sat_recibidos.py`](cruce_sat_recibidos.py), lógica de
negocio compartida con emitidos en [`src/cruce_sat.py`](../../src/cruce_sat.py).

```bash
python3 recibidos/cruce_sat/cruce_sat_recibidos.py --periodo 2026-02
```

## Gotcha resuelto: no excluir el RFC contrario del lado MPRO

El primer intento filtraba `Comprobante_Digital` por
`Cd_RFC_Receptor = Trivasa AND Cd_RFC_Emisor <> Trivasa` (la definición de
"recibido" de `recibidos/nivel_documento/docs/metodologia.md`) — dio un
censo de solo 2,179 UUID contra los 5,523 ya validados vía
`extract_origenes_por_uuids` (que no filtra por RFC, solo busca por UUID
conocido). Causa: `raw_sat.cfdi_recibidos` **sí incluye** complementos
autoemitidos (`Cd_Tabla='TRASLADO'`, `Cd_RFC_Emisor=Cd_RFC_Receptor=Trivasa`,
~3,350 filas de febrero-2026) — excluirlos rompía el cruce contra el SAT.
El filtro correcto es solo `Cd_RFC_Receptor = Trivasa`, sin condición sobre
el emisor. Ver el comentario en `extract_mpro_universo()`.

## Resultado (validado en vivo, 2026-09-10)

| Periodo | En ambos | Solo SAT | Solo MPRO |
|---|---:|---:|---:|
| 2026-02 | 5,519 | 44 (32 con subtotal > $1) | 10 |

`SOLO_SAT` es el hallazgo interesante: CFDI que el PAC timbró y que el ERP
nunca etiquetó en ningún módulo — de los 44, 32 tienen valor monetario real
y son candidatos a hueco de registro (pendiente de investigar caso por
caso, no hecho todavía). `SOLO_MPRO` (10) puede ser UUID capturado con
error en `Comprobante_Digital`, o un pequeño efecto de borde de fecha entre
`Cd_Timbre_Fecha` (mpro) y `periodo` (SAT) — no investigado a fondo.
