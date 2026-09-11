WITH Datos AS
(
SELECT 
		ROW_NUMBER() OVER
		(
			PARTITION BY Gasto_Registro.Gr_Folio,
					Gasto_Registro_Documento.Grd_ID
			ORDER BY PolizaDetalle.Cc_Cve_Cuenta_Contable
		) AS Num,
		Gasto_Registro.Gr_Folio As OperacionId,
		Gasto_Registro_Documento.Grd_ID,
		Gasto_Registro.Gr_Fecha AS Fecha,
		Cuenta_X_Pagar.Mn_Cve_Moneda AS Moneda,
		Proveedor.Pv_Cve_Proveedor AS ClaveProveedor,
		Proveedor.Pv_R_F_C AS RFC,
		Proveedor.Pv_Descripcion AS RazonSocial,
		Pago_CXP.Pc_Banco AS Banco,
		Pago_CXP.Pc_Cuenta_Bancaria AS CuentaBancaria,
		CASE WHEN isnull(Forma_Pago.Fp_Cve_Forma_Pago ,'') = '0001'  THEN 'SI' ELSE 'NO' END Efectivo,
		ISNULL(Cheque.Ch_Folio, '') AS ChequeFolio,
		ISNULL(Cheque.Ch_Fecha, '') AS ChequeFecha,
		ISNULL(Cheque.Ch_Referencia, '') AS ChequeReferencia,
		ISNULL(MontoCobrado.Pc_Importe, '') AS ChequeImporte,
		Subtotales.Subtotal_0 AS Subtotal0,
		Subtotales.Subtotal_16 AS Subtotal16,
		Subtotales.Subtotal_Exenta AS SubtotalExenta,
		Totales.Descuento AS Descuento,
		Totales.Retencion_IVA AS RetencionIVA,
		Totales.Retencion_ISR AS RetencionISR,
		Totales.IEPS AS IEPS,
		Totales.Vn_Descuento_Global_Importe AS DescuentoGlobal,
		(Gasto_Registro_Documento.Grd_Precio_Descontado_Importe * Gasto_Registro_Documento.Grd_Tipo_Cambio) AS SubtotalNeto,
		(Gasto_Registro_Documento.Grd_Impuesto_Importe * Gasto_Registro_Documento.Grd_Tipo_Cambio) AS IVA,
		(Gasto_Registro_Documento.Grd_Precio_Descontado_Importe * Gasto_Registro_Documento.Grd_Tipo_Cambio) AS Subtotal,
		(Gasto_Registro_Documento.Grd_Precio_Neto_Importe * Gasto_Registro_Documento.Grd_Tipo_Cambio) AS Total,
		Comprobante_Digital.Cd_Timbre_UUID AS UUIDComplementoPago,
		CASE Comprobante_Digital.Cd_Tipo_CFDI
						WHEN 'I' THEN 'Ingreso'
						WHEN 'E' THEN 'Egreso'
						WHEN 'D' THEN 'Diario'
						ELSE ''
		END AS TipoComprobante,
		iSNULL(Comprobante_Digital.Cd_RFC_Emisor, '') AS XmlRfcEmisor,
		ISNULL(Comprobante_Digital.Cd_monto, 0) AS XmlMonto,
		iSNULL(Comprobante_Digital.Cd_Serie, '') AS XmlSerie,
		iSNULL(Comprobante_Digital.Cd_Serie_Folio, '') AS XmlFolio,
		Comprobante_Digital.Cd_Metdo_Pago_CFDI AS XmlMetodoPago,
		Comprobante_Digital.Cd_Metodo_Pago AS XmlFormaPago,
		PolizaDetalle.Pd_ID,
		ISNULL(PolizaDetalle.Pl_Fecha, '') AS FechaPoliza,
		ISNULL(PolizaDetalle.Pl_Folio, '') AS TipoPoliza,
		ISNULL(PolizaDetalle.Pl_Folio, '') AS FolioPoliza,
		ISNULL(PolizaDetalle.Pl_Comentario, '') As ComentarioPoliza,
		ISNULL(PolizaDetalle.Cc_Cve_Cuenta_Contable, '') AS CuentaContable,
		ISNULL(PolizaDetalle.Cc_Descripcion, '') AS DescripcionCuentaContable,
		ISNULL(PolizaDetalle.Pd_Importe, 0) AS Cargo,
		0 AS [Abono]
FROM
	Gasto_Registro_Documento
INNER JOIN Gasto_Registro on Gasto_Registro.Gr_Folio = Gasto_Registro_Documento.Gr_Folio
INNER JOIN Gasto_Registro_Control ON Gasto_Registro_Control.Gr_Folio = Gasto_Registro.Gr_Folio
	AND Gasto_Registro_Control.Grd_ID = Gasto_Registro_Documento.Grd_ID
INNER JOIN Sucursal ON Sucursal.Sc_Cve_Sucursal = Gasto_Registro.Sc_Cve_Sucursal
LEFT JOIN Cuenta_X_Pagar ON Cuenta_X_Pagar.Cxp_Tabla = 'Gasto_Registro:'+Gasto_Registro.Gr_Folio
LEFT JOIN Pago_CXP ON Pago_CXP.Cxp_Folio = Cuenta_X_Pagar.Cxp_Folio
LEFT JOIN Pago_Cxp_Comprobante ON Pago_Cxp_Comprobante.Cxp_Folio = Cuenta_X_Pagar.Cxp_Folio
LEFT JOIN Comprobante_Digital ON Comprobante_Digital.Cd_Documento LIKE Gasto_Registro.Gr_Folio + RIGHT('0000' + Gasto_Registro_Documento.Grd_ID,4) + '%'
	AND Comprobante_Digital.Cd_Tabla = 'GASTO_REGISTRO'
	AND Comprobante_Digital.Es_Cve_Estado = 'AC'
LEFT JOIN Proveedor ON Proveedor.Pv_Cve_Proveedor = Cuenta_X_Pagar.Pv_Cve_Proveedor
LEFT JOIN Forma_Pago ON Forma_Pago.Fp_Cve_Forma_Pago = Pago_CXP.Fp_Cve_Forma_Pago
LEFT JOIN Cheque ON Cheque.Ch_Folio = Pago_CXP.Pc_Documento
	AND Pago_CXP.Pc_Tabla = 'Cheque'
CROSS APPLY
(
	SELECT
		0 Descuento,
		0 AS Retencion_IVA,
		0 AS Retencion_ISR,
		0 AS IEPS,
		(0) AS Vn_Descuento_Global_Importe,
		(Gasto_Registro_Documento.Grd_Precio_Descontado_Importe * Gasto_Registro_Documento.Grd_Tipo_Cambio) AS Subtotal_Neto,
		(Gasto_Registro_Documento.Grd_Impuesto_Importe * Gasto_Registro_Documento.Grd_Tipo_Cambio) AS IVA
	FROM Gasto_Registro_Documento 
	WHERE Gasto_Registro_Documento.Gr_Folio = Gasto_Registro.Gr_Folio
)Totales
OUTER APPLY 
(
	SELECT 
	 SUM(
			CASE
					WHEN Impuesto.Im_Tasa = 16.0000
							 AND Impuesto.Im_Tipo_Factor = 'Tasa'
					THEN Gasto_Registro_Impuesto.Gri_Base_Gravable
					ELSE 0
			END
	) AS Subtotal_16,
	SUM(
			CASE
					WHEN Impuesto.Im_Tasa = 0.0000
							 AND Impuesto.Im_Tipo_Factor = 'Tasa'
					THEN Gasto_Registro_Impuesto.Gri_Base_Gravable
					ELSE 0
			END
	) AS Subtotal_0,
	SUM(
			CASE
					WHEN Impuesto.Im_Tipo_Factor = 'Exento'
					THEN Gasto_Registro_Impuesto.Gri_Base_Gravable
					ELSE 0
			END
	) AS Subtotal_Exenta
	FROM
		Gasto_Registro_Impuesto
	LEFT JOIN Impuesto ON Impuesto.Im_Cve_Impuesto = Gasto_Registro_Impuesto.Im_Cve_Impuesto
	WHERE
		Gasto_Registro_Impuesto.Gr_Folio = Gasto_Registro.Gr_Folio
	AND Gasto_Registro_Impuesto.Grd_ID = Gasto_Registro_Documento.Grd_ID
)Subtotales
OUTER APPLY 
(
	SELECT
		SUM(Pago_CXP.Pc_Importe) AS Pc_Importe
	FROM
	Cuenta_X_Pagar
	LEFT JOIN Pago_CXP ON Pago_CXP.Cxp_Folio = Cuenta_X_Pagar.Cxp_Folio
	LEFT JOIN Pago_Cxp_Comprobante ON Pago_Cxp_Comprobante.Cxp_Folio = Cuenta_X_Pagar.Cxp_Folio
	WHERE Cuenta_X_Pagar.Cxp_Tabla = 'Gasto_Registro:'+Gasto_Registro.Gr_Folio
	AND Cuenta_X_Pagar.Cxp_Documento = Gasto_Registro_Documento.Grd_ID 
)MontoCobrado
OUTER APPLY
(
    SELECT
        PD.Pd_ID,
        P.Pl_Fecha,
        P.Pl_Tipo,
        P.Pl_Folio,
        P.Pl_Comentario,
        CC.Cc_Cve_Cuenta_Contable,
        CC.Cc_Descripcion,
        SUM(PD.Pd_Importe) AS Pd_Importe,
        PD.Pd_Tipo
    FROM Poliza_Control PC
    INNER JOIN Poliza P ON P.Pl_Folio = PC.Pl_Folio
       AND P.Es_Cve_Estado = 'AC'
       AND P.Pl_Tipo = 3
    INNER JOIN Poliza_Detalle PD ON PD.Pl_Folio = P.Pl_Folio
    INNER JOIN Cuenta_Contable CC ON CC.Cc_Cve_Cuenta_Contable = PD.Cc_Cve_Cuenta_Contable
    INNER JOIN Poliza_Detalle_Comprobante PDC ON PDC.Pd_ID = PD.Pd_ID
       AND PDC.Pl_Folio = P.Pl_Folio
       AND PDC.Pdc_UUID = Comprobante_Digital.Cd_Timbre_UUID
    WHERE
        Comprobante_Digital.Cd_Timbre_UUID IS NOT NULL
        AND PC.Pc_Tabla = 'Gasto_Registro'
        AND PC.Es_Cve_Estado = 'AC'
        AND PC.Pc_Documento = Gasto_Registro.Gr_Folio
        AND PD.Pd_Referencia = Gasto_Registro.Gr_Folio
        AND PD.Pd_Tipo = 1
    GROUP BY
        PD.Pd_ID,
        P.Pl_Fecha,
        P.Pl_Tipo,
        P.Pl_Folio,
        PD.Pd_Tipo,
        P.Pl_Comentario,
        CC.Cc_Cve_Cuenta_Contable,
        CC.Cc_Descripcion

    UNION ALL

    SELECT
        PD.Pd_ID,
        P.Pl_Fecha,
        P.Pl_Tipo,
        P.Pl_Folio,
        P.Pl_Comentario,
        CC.Cc_Cve_Cuenta_Contable,
        CC.Cc_Descripcion,
        SUM(PD.Pd_Importe) AS Pd_Importe,
        PD.Pd_Tipo
    FROM Poliza_Control PC
    INNER JOIN Poliza P ON P.Pl_Folio = PC.Pl_Folio
       AND P.Es_Cve_Estado = 'AC'
       AND P.Pl_Tipo = 3
    INNER JOIN Poliza_Detalle PD ON PD.Pl_Folio = P.Pl_Folio
    INNER JOIN Cuenta_Contable CC ON CC.Cc_Cve_Cuenta_Contable = PD.Cc_Cve_Cuenta_Contable
    WHERE
        Comprobante_Digital.Cd_Timbre_UUID IS NULL
        AND PC.Pc_Tabla = 'Gasto_Registro'
        AND PC.Es_Cve_Estado = 'AC'
        AND PC.Pc_Documento = Gasto_Registro.Gr_Folio
        AND PD.Pd_Referencia = Gasto_Registro.Gr_Folio
        AND PD.Pd_Tipo = 1
    GROUP BY
        PD.Pd_ID,
        P.Pl_Fecha,
        P.Pl_Tipo,
        P.Pl_Folio,
        PD.Pd_Tipo,
        P.Pl_Comentario,
        CC.Cc_Cve_Cuenta_Contable,
        CC.Cc_Descripcion

) AS PolizaDetalle
WHERE Gasto_Registro.Es_Cve_Estado = 'AP'
	AND ISNULL(Gasto_Registro.Gr_Tabla, '') NOT IN (
    'CONSUMO_INTERNO',
    'CONTROL_COMBUSTIBLE',
    'GASTO_REGISTRO_NOMINA'
	)
	AND Sucursal.Em_Cve_Empresa = '0001'
	AND Gasto_Registro.Gr_Folio = '01-0036729'
	AND Gasto_Registro.Gr_Fecha BETWEEN'20260601' AND '20260615'
GROUP BY
	Gasto_Registro.Gr_Folio,
	Gasto_Registro_Documento.Grd_ID,
	Gasto_Registro.Gr_Fecha,
	Cuenta_X_Pagar.Mn_Cve_Moneda,
	Proveedor.Pv_Cve_Proveedor,
	Proveedor.Pv_R_F_C,
	Proveedor.Pv_Descripcion,
	Pago_CXP.Pc_Banco,
	Pago_CXP.Pc_Cuenta_Bancaria,
	Forma_Pago.Fp_Cve_Forma_Pago,
	Cheque.Ch_Folio,
	Cheque.Ch_Fecha,
	Cheque.Ch_Referencia,
	MontoCobrado.Pc_Importe,
	Comprobante_Digital.Cd_Timbre_UUID,
	Subtotales.Subtotal_0,
	Subtotales.Subtotal_16,
	Subtotales.Subtotal_Exenta,
	Totales.Descuento,
	Totales.Retencion_IVA,
	Totales.Retencion_ISR,
	Totales.IEPS,
	Totales.Vn_Descuento_Global_Importe,
	Gasto_Registro_Documento.Grd_Tipo_Cambio,
	Gasto_Registro_Documento.Grd_Impuesto_Importe,
	Gasto_Registro_Documento.Grd_Precio_Descontado_Importe,
	Gasto_Registro_Documento.Grd_Precio_Neto_Importe,
	Comprobante_Digital.Cd_Tipo_CFDI,
	Comprobante_Digital.Cd_RFC_Emisor,
	Comprobante_Digital.Cd_monto,
	Comprobante_Digital.Cd_Serie,
	Comprobante_Digital.Cd_Serie_Folio,
	Comprobante_Digital.Cd_Metdo_Pago_CFDI,
	Comprobante_Digital.Cd_Metodo_Pago,
	PolizaDetalle.Pd_ID,
	PolizaDetalle.Pl_Fecha,
	PolizaDetalle.Pl_Tipo,
	PolizaDetalle.Pl_Folio,
	PolizaDetalle.Pl_Comentario,
	PolizaDetalle.Cc_Cve_Cuenta_Contable,
	PolizaDetalle.Cc_Descripcion,
	PolizaDetalle.Pd_Importe
)
SELECT
    OperacionId,
    CASE WHEN Num = 1 THEN Fecha END AS Fecha,
		CASE WHEN Num = 1 THEN ClaveProveedor END AS ClaveProveedor,
    CASE WHEN Num = 1 THEN RFC END AS RFC,
    CASE WHEN Num = 1 THEN RazonSocial END AS RazonSocial,
    CASE WHEN Num = 1 THEN Banco END AS Banco,
    CASE WHEN Num = 1 THEN Efectivo END AS Efectivo,
    CASE WHEN Num = 1 THEN CuentaBancaria END AS CuentaBancaria,
    CASE WHEN Num = 1 THEN ChequeFecha END AS ChequeFecha,
    CASE WHEN Num = 1 THEN ChequeFolio END AS ChequeFolio,
    CASE WHEN Num = 1 THEN ChequeImporte END AS ChequeImporte,
    CASE WHEN Num = 1 THEN Subtotal0 END AS Subtotal0,
    CASE WHEN Num = 1 THEN Subtotal16 END AS Subtotal16,
    CASE WHEN Num = 1 THEN SubtotalExenta END AS SubtotalExenta,
    CASE WHEN Num = 1 THEN Descuento END AS Descuento,
    CASE WHEN Num = 1 THEN RetencionIVA END AS RetencionIVA,
    CASE WHEN Num = 1 THEN RetencionISR END AS RetencionISR,
    CASE WHEN Num = 1 THEN IEPS END AS IEPS,
    CASE WHEN Num = 1 THEN DescuentoGlobal END AS DescuentoGlobal,
    CASE WHEN Num = 1 THEN SubtotalNeto END AS SubtotalNeto,
    CASE WHEN Num = 1 THEN IVA END AS IVA,
    CASE WHEN Num = 1 THEN Subtotal END AS Subtotal,
    CASE WHEN Num = 1 THEN Total END AS Total,
    CASE WHEN Num = 1 THEN UUIDComplementoPago END AS UUIDComplementoPago,
    CASE WHEN Num = 1 THEN TipoComprobante END AS TipoComprobante,
    CASE WHEN Num = 1 THEN XmlRfcEmisor END AS XmlRfcEmisor,
    CASE WHEN Num = 1 THEN XmlMonto END AS XmlMonto,
    CASE WHEN Num = 1 THEN XmlSerie END AS XmlSerie,
    CASE WHEN Num = 1 THEN XmlFolio END AS XmlFolio,
    CASE WHEN Num = 1 THEN XmlMetodoPago END AS XmlMetodoPago,
    CASE WHEN Num = 1 THEN XmlFormaPago END AS XmlFormaPago,
		Pd_ID,
    FechaPoliza,
    TipoPoliza,
    FolioPoliza,
    ComentarioPoliza,
    CuentaContable,
    DescripcionCuentaContable,
    Cargo,
    Abono
FROM Datos
ORDER BY
    OperacionId,
		Grd_ID,
    CuentaContable;