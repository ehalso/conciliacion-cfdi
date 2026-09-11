"""
Layout de registro de gastos - v1

Vista base (detalle) segun el requerimiento de auditoria (Bates y Asociados).
Ver docs/02_modelo_datos.md para el grafo de joins y docs/01_hallazgos_excel_referencia.md
para los bugs conocidos del Excel de referencia que esta version corrige por diseno:

  - Ancla en Gasto_Registro -> excluye CONSUMO_INTERNO y GASTO_REGISTRO_NOMINA automaticamente
    (esas operaciones no existen en esa tabla).
  - No trunca Poliza_Detalle: trae TODAS las lineas (Pd_Referencia = Gr_Folio, Pd_Tipo = 1).

Nota de diseno (v1 -> v1.1): la cabecera (pago/proveedor/factura/XML) y el detalle de poliza
(cargo por cuenta contable x centro de costo) se extraen en DOS consultas separadas y se
combinan en pandas. Combinarlas en un solo JOIN de SQL multiplicaba el Cargo por cada pago
parcial (Pago_CXP puede tener varias filas por Cxp_Folio), inflando el total de cargos. Ver
docs/03_hito_v1.md.
"""
from db import q

HEADER_SQL = """
WITH pago_top AS (
    SELECT
        cxp.Cxp_Folio, cxp.Cxp_Tabla, cxp.Cxp_Documento,
        pc.Pc_ID, pc.Pc_Fecha, pc.Pc_Tabla AS Pc_Instrumento, pc.Pc_Documento,
        pc.Pc_Referencia, pc.Pc_Banco, pc.Pc_Cuenta_Bancaria, pc.Pc_Importe,
        fp.Fp_Descripcion,
        ROW_NUMBER() OVER (PARTITION BY cxp.Cxp_Folio ORDER BY pc.Pc_Fecha, pc.Pc_ID) AS rn
    FROM Cuenta_X_Pagar cxp
    LEFT JOIN Pago_CXP pc ON pc.Cxp_Folio = cxp.Cxp_Folio
    LEFT JOIN Forma_Pago fp ON fp.Fp_Cve_Forma_Pago = pc.Fp_Cve_Forma_Pago
    WHERE cxp.Cxp_Tabla LIKE 'Gasto_Registro:%'
),
comprobante_top AS (
    SELECT
        pcc.Cxp_Folio, pcc.Pc_ID, pcc.Pcc_Serie_Folio, pcc.Pcc_Timbre_UUID,
        pcc.Pcc_Tipo_Comprobante,
        ROW_NUMBER() OVER (PARTITION BY pcc.Cxp_Folio, pcc.Pc_ID ORDER BY pcc.Pcc_Id) AS rn
    FROM Pago_Cxp_Comprobante pcc
)
SELECT
    gr.Gr_Folio                        AS [Operacion (ID)],
    grd.Grd_ID                         AS [Grd_ID],
    grd.Grd_Fecha                      AS [Fecha],
    grd.Mn_Cve_Moneda                  AS [Moneda],
    pv.Pv_Cve_Proveedor                AS [Clave del proveedor],
    pv.Pv_R_F_C                        AS [RFC del proveedor],
    pv.Pv_Descripcion                  AS [Nombre del proveedor],
    cxp.Cxp_Folio                      AS [Cxp_Folio],
    pt.Pc_Fecha                        AS [Fecha de cheque],
    pt.Pc_Instrumento                  AS [Instrumento de pago],
    pt.Pc_Documento                    AS [CFDI Comprobante de pago],
    pt.Pc_Referencia                   AS [No.Cheque o No.Transf],
    pt.Pc_Banco                        AS [Banco],
    pt.Pc_Cuenta_Bancaria              AS [Cuenta bancaria],
    pt.Pc_Importe                      AS [Monto Cobrado],
    pt.Fp_Descripcion                  AS [Forma de pago],
    ct.Pcc_Serie_Folio                 AS [Numero de factura],
    ct.Pcc_Timbre_UUID                 AS [UUID],
    ct.Pcc_Tipo_Comprobante            AS [Tipo de comprobante cve],
    cd.Cd_Tipo_Comprobante_CFDI        AS [Tipo de comprobante],
    cd.Cd_Timbre_Fecha                 AS [Fecha Factura],
    cd.Cd_RFC_Emisor                   AS [XML RFC EMISOR],
    cd.Cd_Monto                        AS [XML MONTO],
    cd.Cd_Serie                        AS [XML SERIE],
    cd.Cd_Serie_Folio                  AS [XML FOLIO],
    cd.Cd_Metodo_Pago                  AS [XML METODO PAGO],
    cd.Cd_Forma_Pago                   AS [XML FORMA PAGO],
    grd.Grd_Precio_Descontado_Importe  AS [Subtotal Neto],
    grd.Grd_Impuesto_Importe           AS [Impuesto Importe],
    grd.Grd_Precio_Neto_Importe        AS [Total]
FROM Gasto_Registro gr
JOIN Gasto_Registro_Documento grd
    ON grd.Gr_Folio = gr.Gr_Folio
LEFT JOIN Proveedor pv
    ON pv.Pv_Cve_Proveedor = grd.Pv_Cve_Proveedor
LEFT JOIN Cuenta_X_Pagar cxp
    ON cxp.Cxp_Tabla = 'Gasto_Registro:' + gr.Gr_Folio
   AND cxp.Cxp_Documento = grd.Grd_ID
LEFT JOIN pago_top pt
    ON pt.Cxp_Folio = cxp.Cxp_Folio AND pt.rn = 1
LEFT JOIN comprobante_top ct
    ON ct.Cxp_Folio = cxp.Cxp_Folio AND ct.Pc_ID = pt.Pc_ID AND ct.rn = 1
LEFT JOIN Comprobante_Digital cd
    ON cd.Cd_Tabla = 'GASTO_REGISTRO'
   AND cd.Cd_Documento LIKE gr.Gr_Folio + grd.Grd_ID + '%'
WHERE gr.Gr_Fecha >= '{start}' AND gr.Gr_Fecha < '{end}'
  AND gr.Es_Cve_Estado <> 'CA'  -- excluye folios cancelados ('AC'=activo, 'AP'=aplicado son validos; ver docs/03_hito_v1.md)
ORDER BY gr.Gr_Folio, grd.Grd_ID
"""

POLIZA_SQL = """
WITH grupo_arbol AS (
    SELECT Gcc_Cve_Grupo_Cuenta_Contable, Gcc_Padre, Gcc_Cve_Grupo_Cuenta_Contable AS raiz
    FROM Grupo_Cuenta_Contable
    WHERE Gcc_Padre = '0' OR Gcc_Padre = '' OR Gcc_Padre IS NULL
    UNION ALL
    SELECT g.Gcc_Cve_Grupo_Cuenta_Contable, g.Gcc_Padre, t.raiz
    FROM Grupo_Cuenta_Contable g
    JOIN grupo_arbol t ON g.Gcc_Padre = t.Gcc_Cve_Grupo_Cuenta_Contable
)
SELECT
    gr.Gr_Folio                AS [Operacion (ID)],
    pl.Pl_Fecha                AS [Fecha de poliza],
    pl.Pl_Tipo                 AS [Tipo de poliza],
    pl.Pl_Folio                AS [Numero de poliza],
    pl.Pl_Comentario           AS [Concepto de poliza],
    pd.Pd_ID                   AS [Pd_ID],
    pd.Cc_Cve_Cuenta_Contable  AS [Cuenta Registro],
    cc.Cc_Descripcion          AS [Nombre Cuenta Registro],
    pd.Pd_Centro_Costo         AS [Centro de Costo],
    CASE WHEN pd.Pd_Tipo = 1 THEN pd.Pd_Importe ELSE 0 END AS [Cargo],
    CASE WHEN pd.Pd_Tipo = 2 THEN pd.Pd_Importe ELSE 0 END AS [Abono]
FROM Gasto_Registro gr
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
JOIN Poliza pl
    ON pl.Pl_Folio = plc.Pl_Folio
JOIN Poliza_Detalle pd
    ON pd.Pl_Folio = plc.Pl_Folio
   AND pd.Pd_Referencia = gr.Gr_Folio
   -- sin filtro de Pd_Tipo: Pd_Referencia=Gr_Folio ya acota a las lineas de ESTA operacion.
   -- Tipo 1 = cargo, Tipo 2 = abono (normalmente proveedor/retenciones referenciadas por
   -- num. de factura, pero en reclasificaciones (ver docs/03_hito_v1.md) el abono SI
   -- referencia el Gr_Folio -- de ahi que antes se perdiera ese lado del asiento).
LEFT JOIN Cuenta_Contable cc
    ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable
LEFT JOIN grupo_arbol ga
    ON ga.Gcc_Cve_Grupo_Cuenta_Contable = cc.Cc_Grupo_Cuenta_Contable
WHERE gr.Gr_Fecha >= '{start}' AND gr.Gr_Fecha < '{end}'
  AND gr.Es_Cve_Estado <> 'CA'             -- excluye folios de gasto cancelados ('AC' y 'AP' son validos)
  AND (ga.raiz IS NULL OR ga.raiz <> 'H')  -- excluye 'CUENTAS DE ORDEN' (H): postings de memo/control
                                            -- duplicadas del mismo folio en una 2a poliza (ver docs/03_hito_v1.md)
  AND pl.Es_Cve_Estado <> 'CA'             -- excluye polizas canceladas/sustituidas
  AND (pd.Pd_Tipo = 1 OR (pd.Pd_Tipo = 2 AND ga.raiz = 'F'))
      -- Tipo 2 solo se incluye si la cuenta es de Grupo 'Gastos' (F): es el lado abono de una
      -- reclasificacion. Tipo 2 sobre Pasivo/Proveedor (grupo 'B') se excluye: es la cuenta por
      -- pagar del proveedor, no forma parte de la seccion "Cuenta Registro" del layout.
ORDER BY gr.Gr_Folio, pd.Pd_ID
"""


def extract_header(start_date: str, end_date_exclusive: str):
    return q(HEADER_SQL.format(start=start_date, end=end_date_exclusive))


def extract_poliza(start_date: str, end_date_exclusive: str):
    return q(POLIZA_SQL.format(start=start_date, end=end_date_exclusive))


def merge_header_poliza(header: "pd.DataFrame", poliza: "pd.DataFrame"):
    """Combina cabecera (grano Grd_ID) y poliza (grano Pd_ID) por operacion.

    OJO: un merge relacional simple `on='Operacion (ID)'` hace un producto cartesiano cuando
    una operacion tiene mas de un Grd_ID (documento multiple, ~2.7% de los folios de enero
    2025) Y varias lineas de poliza -- para un puñado de folios eso infla el detalle de unas
    decenas de filas a decenas de miles. Los Grd_ID de una misma operacion no se corresponden
    1:1 con lineas de poliza especificas (`Poliza_Detalle.Pd_Referencia` solo referencia el
    `Gr_Folio`, no el `Grd_ID`), asi que la relacion correcta no es relacional -- es posicional,
    igual que se ve en el Excel de referencia (fila 1 trae cabecera + 1a linea de poliza, filas
    siguientes solo traen columnas de poliza). Por eso se hace un merge posicional (zip) por
    operacion en vez de un join relacional."""
    h = header.copy()
    p = poliza.copy()
    h["_rn"] = h.groupby("Operacion (ID)").cumcount()
    p["_rn"] = p.groupby("Operacion (ID)").cumcount()
    merged = h.merge(p, on=["Operacion (ID)", "_rn"], how="outer", suffixes=("", "_poliza"))
    return merged.drop(columns="_rn").sort_values(["Operacion (ID)"]).reset_index(drop=True)


def extract_base_view(start_date: str, end_date_exclusive: str):
    """start_date inclusivo, end_date_exclusive exclusivo (YYYY-MM-DD).

    Vista base (detalle): 1 fila por linea de poliza (cuenta contable x centro de costo),
    con los datos de cabecera (pago/proveedor/factura/XML) en la primera fila de cada
    operacion (ver `merge_header_poliza`). Si un folio de gasto no tiene ninguna linea de
    poliza encontrada (folio sin contabilizar, o solo cuenta de orden), se conserva la
    cabecera con las columnas de poliza en NULL."""
    header = extract_header(start_date, end_date_exclusive)
    poliza = extract_poliza(start_date, end_date_exclusive)
    return merge_header_poliza(header, poliza)


def group_by_cuenta_contable(header, poliza):
    """Vista 2 del requerimiento: una fila por (Operacion, Cuenta Registro),
    sumando Cargo/Abono a traves de los centros de costo. Corrige el bug
    documentado en docs/01_hallazgos_excel_referencia.md (#2).

    OJO (fix post-v1): se agrupa `poliza` de forma independiente y luego se pega la
    cabecera (1 fila por operacion, no repetida por Grd_ID) -- agrupar sobre el `detail`
    ya fusionado (salida de `merge_header_poliza`) rompe la garantia de "una sola fila
    por operacion" en cuanto una operacion tiene mas lineas de poliza que filas de
    cabecera, porque las columnas de cabecera quedan en NULL en las filas de mas y el
    groupby las trata como un grupo distinto."""
    poliza_group_cols = ["Operacion (ID)", "Cuenta Registro", "Nombre Cuenta Registro"]
    poliza_group_cols = [c for c in poliza_group_cols if c in poliza.columns]
    cargo_abono = (
        poliza.groupby(poliza_group_cols, dropna=False, as_index=False)[["Cargo", "Abono"]]
        .sum()
    )
    header_dedup = header.sort_values("Operacion (ID)").drop_duplicates(
        subset="Operacion (ID)", keep="first"
    )
    merged = header_dedup.merge(cargo_abono, on="Operacion (ID)", how="outer")
    merged[["Cargo", "Abono"]] = merged[["Cargo", "Abono"]].fillna(0)
    return merged
