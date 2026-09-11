"""
Layout de gastos - v0.1: replica del reporte nativo de MPRO "Facturas de gastos
(por documento)" (RPAG008_99.asp, Agrupar=99), a nivel Gasto_Registro_Documento
(Gr_Folio + Grd_ID) -- SIN el detalle de poliza/cuenta contable que usan v1/v1.1
(ver layout_gastos_v1.py). Es el punto de partida mas simple, validado directo
contra un export real de MPRO.

Validado contra el export real de MPRO para enero 2026
(gastos_por_documento_enero_26.xlsx, 7,043 filas, 4,494 folios):
  IMPORTE:   $39,469,269.50 (nuestro) vs $39,469,269.59 (MPRO) -- diff $0.09
  IMPUESTOS:  $1,084,277.23 (nuestro) vs  $1,084,277.29 (MPRO) -- diff $0.06
  TOTAL:     $40,553,546.72 (nuestro) vs $40,553,546.79 (MPRO) -- diff $0.07
(diferencias de centavos en 7,043 filas -- ruido de redondeo, no un error de logica)

Hallazgo clave en el camino: los importes de Gasto_Registro_Documento estan en la
MONEDA ORIGINAL del documento (Mn_Cve_Moneda), no en pesos. El reporte nativo
multiplica por Grd_Tipo_Cambio para mostrar el equivalente en MXN -- sin ese
factor, los documentos en USD (ej. 05-0175047, renta de montacargas, USD 3,201.60
-> MXN 57,496.57 al tipo de cambio 17.9587) salian ~18x mas chicos. Se corrigio
multiplicando IMPORTE/IMPUESTOS/TOTAL por Grd_Tipo_Cambio (=1.0 para MXN, no
afecta esos registros).

Otro hallazgo importante (pedido explicito del usuario, columna `origen`):
Gasto_Registro.Gr_Tabla identifica folios generados automaticamente por OTRO
subsistema -- 'CONSUMO_INTERNO' y 'GASTO_REGISTRO_NOMINA' SI aparecen dentro de
Gasto_Registro (2,970 y 2,268 documentos de enero 2026 respectivamente, $6.59M y
$10.63M) -- contradice el supuesto de layout_gastos_v1.py (que asumia que anclar
en Gasto_Registro los excluia automaticamente por estar en tablas separadas). Este
reporte v0.1 los incluye TODOS (asi es el reporte nativo); la columna `origen` deja
visible cual es cual para que un reporte derivado (como el de auditoria externa,
que si debe excluirlos) pueda filtrar.

Bug encontrado despues durante la validacion de v0.2 y corregido tambien aqui: el join a
Comprobante_Digital via LIKE folio+Grd_ID+'%' no es unico -- para ciertos documentos hay
2 UUID distintos cuyo Cd_Documento matchea el mismo prefijo (ej. folio 23-0006650:
'23-00066500001' Y '23-000665000010001'), duplicando la fila entera y sobre-contando su
importe (15 filas de mas en enero 2026, ~$158,838.85 de mas en IMPORTE). Fix: cambiar el
LEFT JOIN ... LIKE por OUTER APPLY (SELECT TOP 1 ... ORDER BY Cd_Documento), que
garantiza como maximo 1 fila de comprobante por documento. Tras el fix, los numeros
vuelven a coincidir exacto con el Excel de referencia (ver arriba). Detalle completo del
hallazgo en docs/12_hito_v0_2.md (bug encontrado ahi, corregido en los dos reportes).

Uso: python3 scripts/layout_gastos_v0_1.py 2026-01-01 2026-02-01
"""
import sys

from db import q

BASE_SQL = """
SELECT
    gr.Gr_Folio                          AS folio,
    gr.Gr_Fecha                          AS fecha_registro,
    grd.Grd_Fecha                        AS fecha_documento,
    grd.Grd_Referencia                   AS referencia,
    grd.Pv_Cve_Proveedor                 AS proveedor_clave,
    pv.Pv_Descripcion                    AS proveedor_nombre,
    grd.Grd_Comentario                   AS comentario,
    grd.Mn_Cve_Moneda                    AS moneda,
    grd.Grd_Tipo_Cambio                  AS tipo_cambio,
    grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio AS importe,
    grd.Grd_Impuesto_Importe * grd.Grd_Tipo_Cambio           AS impuestos,
    grd.Grd_Precio_Neto_Importe * grd.Grd_Tipo_Cambio        AS total,
    gr.Gr_Tabla                          AS origen,
    CASE WHEN cd.Cd_Documento IS NOT NULL THEN 1 ELSE 0 END AS tiene_comprobante,
    cd.Cd_Timbre_UUID                    AS uuid
FROM Gasto_Registro gr
JOIN Gasto_Registro_Documento grd
    ON grd.Gr_Folio = gr.Gr_Folio
INNER JOIN Sucursal sc
    ON sc.Sc_Cve_Sucursal = gr.Sc_Cve_Sucursal
LEFT JOIN Proveedor pv
    ON pv.Pv_Cve_Proveedor = grd.Pv_Cve_Proveedor
OUTER APPLY (
    SELECT TOP 1 Cd_Documento, Cd_Timbre_UUID
    FROM Comprobante_Digital
    WHERE Cd_Tabla = 'GASTO_REGISTRO'
      AND Cd_Documento LIKE gr.Gr_Folio + grd.Grd_ID + '%'
    ORDER BY Cd_Documento
) cd
WHERE sc.Em_Cve_Empresa = '0001'
  AND gr.Gr_Fecha >= '{fecha_ini}' AND gr.Gr_Fecha < '{fecha_fin_excl}'
  AND gr.Es_Cve_Estado <> 'CA'
ORDER BY gr.Gr_Folio, grd.Grd_ID
"""


def extract(fecha_ini: str, fecha_fin_excl: str):
    """fecha_ini inclusive, fecha_fin_excl EXCLUSIVE (a diferencia de v1, que usaba
    fechas inclusive en ambos extremos) -- pasa el primer dia del mes SIGUIENTE."""
    return q(BASE_SQL.format(fecha_ini=fecha_ini, fecha_fin_excl=fecha_fin_excl))


if __name__ == "__main__":
    fecha_ini = sys.argv[1] if len(sys.argv) > 1 else "2026-01-01"
    fecha_fin_excl = sys.argv[2] if len(sys.argv) > 2 else "2026-02-01"

    df = extract(fecha_ini, fecha_fin_excl)
    print(f"{len(df)} filas, {df['folio'].nunique()} folios unicos")
    print(f"IMPORTE total:   {df['importe'].sum():,.2f}")
    print(f"IMPUESTOS total: {df['impuestos'].sum():,.2f}")
    print(f"TOTAL total:     {df['total'].sum():,.2f}")
    print()
    print("Por origen:")
    print(df.groupby("origen", dropna=False)["total"].agg(["count", "sum"]).sort_values("sum", ascending=False))

    out_path = f"output/layout_gastos_v0_1_{fecha_ini}_a_{fecha_fin_excl}.csv"
    df.to_csv(out_path, index=False)
    print(f"\nGuardado: {out_path}")
