# Cobranza / REP (pendiente)

Carpeta reservada, aún sin construir (2026-09-10). Portar la metodología ya
validada en el proyecto hermano
`~/proyectos/conciliacion-master/conciliacion-emitidos` (reportes 02/03):
¿la cobranza registrada en mpro (`Pago_CXC`) está amparada por un REP
(recibo electrónico de pago) timbrado?

Resultado ya medido ahí (enero 2026, `.205`): 96.18% de facturas con
cobranza conciliada; el hallazgo real es `COBRO_SIN_REP` — cobros
registrados cuya parcialidad nunca se le reportó al SAT ($53K-$134K/mes) y
REP timbrados por duplicado.

Dos detalles de método que ya cuestan 30 puntos porcentuales si se pasan
por alto (ver `docs/metodologia.md` del proyecto original antes de
reimplementar):

1. **`DISTINCT` sobre `Cxc_Folio`** antes de sumar — una factura ampara
   varias ventas y cada venta genera su propia cuenta por cobrar.
2. **Cierre del universo de REP hacia atrás Y hacia adelante** (24 meses
   atrás, hasta HOY, no hasta `--fecha-fin`) — un cobro de enero puede
   llevar su REP timbrado en febrero.

Ver `docs/emitidos_retenciones.md` y `docs/pendientes.md` de este repo para
el estado actual del frente de emitidos.
