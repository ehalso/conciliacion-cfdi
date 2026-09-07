# Resultados — febrero 2026, CFDI recibidos

Corrida de referencia: `python3 reconciliacion_por_origen.py --periodo 2026-02`
(contra `mssql_207` en la corrida original que generó estas cifras; se
revalidó después contra `mssql_205` con resultados prácticamente
idénticos — ver `arquitectura.md`).

## Nivel 1 — existencia e importe por CFDI

5,563 CFDI recibidos en el periodo. ~99% conciliados como `OK` a nivel
CFDI (existe en mpro, importe coincide con tolerancia $1) usando
`main.py`.

## Censo de orígenes (Comprobante_Digital.Cd_Tabla)

De los CFDI matcheados, a qué módulo de mpro se traza cada uno y cuánto $
representa (columna `monto_total`, suma de los CFDI de ese origen):

| origen | n_cfdi | monto_total | nota |
|---|---:|---:|---|
| COMPRA | 713 | $32,559,261 | |
| CUENTA_X_PAGAR | 62 | $12,553,833 | |
| GASTO_REGISTRO | 745–759 | $9,376,320 | rango según deduplicación |
| FACTURA | 5 | $912,384 | volumen mínimo, no trabajado |
| CHEQUE | 652 | $540,461 | ver nota subtotal=0 en `hallazgos.md` |
| NOTA_CREDITO_PROVEEDOR | 14 | $480,896 | |
| COMPRA_INDIRECTO | 6 | $228,830 | |
| ANTICIPO_CXP | 1 | $77,385 | volumen mínimo, no trabajado |
| NOTA_CREDITO | 1 | $77,385 | volumen mínimo, no trabajado |
| COMPROBANTE_PAGO | 6 | $0 | |
| TRASLADO | 3,350 | $0 | 100% CFDI tipo T (Carta Porte autoemitida), sin efecto fiscal — excluido a propósito |

## Nivel 3 — conciliación por origen (los 6 orígenes con volumen relevante)

### Cuadre documento a documento

| Origen | Documentos | Cuadra | Con póliza sin cuadrar | Sin póliza |
|---|---:|---:|---:|---:|
| CHEQUE | 350 | 350 (100%) | 0 | 0 |
| COMPRA | 770 | 635 (82.5%) | 135 | 0 |
| CUENTA_X_PAGAR | 84 | 18 (21.4%) | 33 | 33 |
| GASTO_REGISTRO | 1,169 | 581 (49.7%) | 588 | 0 |
| NOTA_CREDITO_PROVEEDOR | 15 | 7 (46.7%) | 8 | 0 |
| COMPRA_INDIRECTO | 8 | 0 | 8 | 0 |

### Cuadre agregado por origen ($ contabilizado vs. $ CFDI de la misma base)

| Origen | Suma subtotal CFDI | Suma total CFDI | Suma cargo | Suma abono | Cargo / Subtotal | Cargo / Total |
|---|---:|---:|---:|---:|---:|---:|
| COMPRA | $29,627,265 | $34,252,100 | $28,702,368 | $0 | **96.9%** | 83.8% |
| CUENTA_X_PAGAR | $12,563,782 | $14,515,090 | $11,339,240 | $0 | **90.3%** | 78.1% |
| NOTA_CREDITO_PROVEEDOR | $775,876 | $883,242 | $412,675 | $540,701 | 53.2% | 46.7% (cargo) / 61.2% (abono) |
| GASTO_REGISTRO | $24,393,519 | $27,694,954 | $8,933,668 | $775,953 | 36.6% | 32.3% |
| COMPRA_INDIRECTO | $218,347 | $253,283 | $6,789 | $0 | 3.1% | 2.7% |
| CHEQUE | $521,749 | $540,461 | $0 | $43,814,160 | — | — (ver nota) |

**Nota Cheque**: el CFDI subtotal/total no es comparable (structuralmente
$0 para los REP que dominan este origen — ver `hallazgos.md` punto 6). El
$43.8M de abono es el monto real de los cheques emitidos, ya validado
1-a-1 contra `Cheque.Ch_Importe` por el método de match por monto — el
100% de cuadre documento-a-documento reportado arriba es la cifra
correcta para este origen, no la columna de "% vs CFDI".

### Lectura de estos números

- **Compra y Cuenta_x_Pagar cuadran bien en agregado** (97% y 90% contra
  subtotal) — la brecha restante es esencialmente el IVA, que se postea
  aparte.
- **Cheque está resuelto** (100%, por el método correcto: match de monto,
  no de CFDI).
- **Gasto_Registro y Compra_Indirecto tienen un problema real de
  cobertura**, no solo de redondeo — la suma contabilizada que se logra
  aislar es bien inferior a la suma de sus CFDI. Gasto_Registro necesita
  la lógica adicional de `layout-gastos` (nómina/CECO, reversiones,
  reclasificación — ver `hallazgos.md` punto 7 y `pendientes.md`).
  Compra_Indirecto necesita su propio método dedicado (volumen mínimo, 8
  documentos, barato de resolver).
- **Nota_Credito_Proveedor** tiene un patrón de documentos partidos (ver
  `hallazgos.md` punto 8) que probablemente explica buena parte de su
  53%/47% — no confirmado a fondo por bajo volumen (15 documentos).

## Otras corridas de referencia (nivel 1, `main.py`)

- Enero 2026: `output/conciliacion_2026-01.xlsx`
- Febrero 2026: `output/conciliacion_2026-02.xlsx`
- Agosto 2026: `output/conciliacion_2026-08.xlsx`
- Q1 2026 (ene-mar consolidado): `output/conciliacion_2026-Q1.xlsx`
- Piloto nivel póliza, enero 2026: `output/poliza_2026-01.xlsx`

(Estos `.xlsx` no se versionan en el repo — se regeneran corriendo los
scripts correspondientes; ver `README.md`.)
