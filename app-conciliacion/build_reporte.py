import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'layout_gastos_poliza'))
# Credenciales: variables de entorno MSSQL_205_* (ver README); este script no las guarda.
import re, json, sys
import numpy as np, pandas as pd
from importlib import import_module
from sqlalchemy import text
m22=import_module('22_bloque_proveedor_pago'); m23=import_module('23_bloque_xml_concepto')
m24=import_module('24_bloque_poliza_directo'); m21=import_module('21_impuestos_por_ceco')
from connection_205_trivasadb3 import engine
EMP='0001'
def Q(sql,fi,ff): 
    d=pd.read_sql(text(sql),engine,params={'fi':fi,'ff':ff,'emp':EMP})
    if 'FOLIO' in d: d['FOLIO']=d.FOLIO.str.strip()
    return d

# ---- impuestos por clave (documento x clave) ----
IMP_CLAVE_SQL="""
SELECT gr.Gr_Folio AS FOLIO, grd.Grd_ID, gri.Im_Cve_Impuesto AS CLAVE,
       SUM(gri.Gri_Importe)*grd.Grd_Tipo_Cambio AS IMPORTE
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal=s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio=grd.Gr_Folio
JOIN Gasto_Registro_Impuesto gri ON gri.Gr_Folio=grd.Gr_Folio AND gri.Grd_ID=grd.Grd_ID
WHERE gr.Gr_Fecha>=:fi AND gr.Gr_Fecha<:ff AND gr.Es_Cve_Estado<>'CA' AND s.Em_Cve_Empresa=:emp
GROUP BY gr.Gr_Folio, grd.Grd_ID, gri.Im_Cve_Impuesto, grd.Grd_Tipo_Cambio
"""
CAT_SQL="select Im_Cve_Impuesto CLAVE, Im_Descripcion DESCR from Impuesto"

def pesos(fi,ff):
    grc=Q(m21.GRC_POR_DOC_SQL,fi,ff)
    grc['ABS']=grc.Grc_Importe.abs(); grc['PESO']=grc.Grc_Factor.fillna(0)
    sf=grc.groupby(['FOLIO','Grd_ID']).PESO.transform('sum'); ti=grc.groupby(['FOLIO','Grd_ID']).ABS.transform('sum')
    z=sf<0.01; grc.loc[z,'PESO']=(grc.ABS/ti)[z]; grc['PESO']=grc.PESO.fillna(0)
    return grc

PAGO_SQL="""
WITH folios AS (
    SELECT gr.Gr_Folio AS FOLIO, gr.Gr_Referencia
    FROM Gasto_Registro gr JOIN Sucursal s ON gr.Sc_Cve_Sucursal=s.Sc_Cve_Sucursal
    WHERE gr.Gr_Fecha>=:fi AND gr.Gr_Fecha<:ff AND gr.Es_Cve_Estado<>'CA' AND s.Em_Cve_Empresa=:emp
),
cxp_g AS (SELECT DISTINCT f.FOLIO, cxp.Cxp_Folio FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio=f.FOLIO
    JOIN Cuenta_X_Pagar cxp ON cxp.Cxp_Tabla='Gasto_Registro:'+f.FOLIO AND cxp.Cxp_Documento=grd.Grd_ID),
cxp_r AS (SELECT DISTINCT f.FOLIO, cxp.Cxp_Folio FROM folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio=f.FOLIO
    JOIN Cuenta_X_Pagar cxp ON cxp.Cxp_Tabla='Cuenta_X_Pagar' AND cxp.Cxp_Referencia=grd.Grd_Referencia AND cxp.Pv_Cve_Proveedor=grd.Pv_Cve_Proveedor
    WHERE grd.Grd_Referencia IS NOT NULL AND LTRIM(RTRIM(grd.Grd_Referencia))<>''),
cxp_d AS (SELECT * FROM cxp_g UNION SELECT * FROM cxp_r),
pagos AS (
    SELECT cd.FOLIO, pc.Pc_ID, pc.Cxp_Folio, pc.Fp_Cve_Forma_Pago, pc.Pc_Banco, pc.Pc_Cuenta_Bancaria,
           pc.Pc_Documento, pc.Pc_Tabla, pc.Pc_Referencia,
           ROW_NUMBER() OVER (PARTITION BY cd.FOLIO ORDER BY
               CASE WHEN pc.Fp_Cve_Forma_Pago IN ('0001','0002','0003') THEN 0 ELSE 1 END,
               ABS(pc.Pc_Importe*ISNULL(pc.Pc_Tipo_Cambio,1)) DESC, pc.Pc_ID) rn
    FROM cxp_d cd JOIN Pago_CXP pc ON pc.Cxp_Folio=cd.Cxp_Folio AND pc.Es_Cve_Estado<>'CA'
),
rep AS (SELECT * FROM pagos WHERE rn=1),
formas AS (
    SELECT t.FOLIO, STUFF((SELECT ' / '+x.Fp_Descripcion FROM (SELECT DISTINCT p.FOLIO, fp.Fp_Descripcion FROM pagos p JOIN Forma_Pago fp ON fp.Fp_Cve_Forma_Pago=p.Fp_Cve_Forma_Pago) x
        WHERE x.FOLIO=t.FOLIO ORDER BY x.Fp_Descripcion FOR XML PATH('')),1,3,'') AS FORMA_PAGO
    FROM (SELECT DISTINCT FOLIO FROM pagos) t
),
monto AS (
    SELECT cd.FOLIO, SUM(pc.Pc_Importe*ISNULL(pc.Pc_Tipo_Cambio,1)) AS MONTO_COBRADO
    FROM cxp_d cd JOIN Pago_CXP pc ON pc.Cxp_Folio=cd.Cxp_Folio AND pc.Es_Cve_Estado<>'CA' GROUP BY cd.FOLIO
),
cpago AS (
    SELECT cd.FOLIO, COUNT(DISTINCT pcc.Pcc_Timbre_UUID) n, MIN(pcc.Pcc_Timbre_UUID) u,
           (SELECT MIN(cdg.Cd_Timbre_Fecha) FROM Comprobante_Digital cdg WHERE cdg.Cd_Timbre_UUID=MIN(pcc.Pcc_Timbre_UUID)) AS fc
    FROM cxp_d cd JOIN Pago_Cxp_Comprobante pcc ON pcc.Cxp_Folio=cd.Cxp_Folio GROUP BY cd.FOLIO
)
SELECT f.FOLIO, f.Gr_Referencia AS REFERENCIA,
  fm.FORMA_PAGO,
  r.Fp_Cve_Forma_Pago AS FP_CVE,
  COALESCE(NULLIF(LTRIM(RTRIM(r.Pc_Banco)),''), bn.Bn_Descripcion) AS BANCO,
  COALESCE(NULLIF(LTRIM(RTRIM(r.Pc_Cuenta_Bancaria)),''), bc.Bc_Cuenta) AS CUENTA_BANCARIA,
  ch.Ch_Fecha AS FECHA_CHEQUE,
  COALESCE(ch.Ch_Folio, NULLIF(LTRIM(RTRIM(r.Pc_Documento)),'')) AS FOLIO_PAGO,
  COALESCE(NULLIF(LTRIM(RTRIM(r.Pc_Referencia)),''), NULLIF(LTRIM(RTRIM(ch.Ch_Referencia)),'')) AS NO_CHEQUE_TRANSF,
  m.MONTO_COBRADO,
  CASE WHEN cp.n>=2 THEN 'VARIOS' ELSE cp.u END AS COMPLEMENTO_PAGO,
  CASE WHEN cp.n>=2 THEN NULL ELSE cp.fc END AS FECHA_COMPLEMENTO_PAGO
FROM folios f
LEFT JOIN rep r ON r.FOLIO=f.FOLIO
LEFT JOIN formas fm ON fm.FOLIO=f.FOLIO
LEFT JOIN Anticipo_CXP an ON r.Pc_Tabla='ANTICIPO_CXP' AND an.An_Folio=r.Pc_Documento
LEFT JOIN Cheque ch ON ch.Ch_Folio = CASE WHEN r.Pc_Tabla='Cheque' THEN r.Pc_Documento
                                          WHEN r.Pc_Tabla='ANTICIPO_CXP' AND an.An_Tabla='CHEQUE' THEN an.An_Documento END
LEFT JOIN Banco_Cuenta bc ON bc.Bc_Cve_Banco_Cuenta=COALESCE(ch.Bc_Cve_Banco_Cuenta, an.Bc_Cve_Banco_Cuenta)
LEFT JOIN Banco bn ON bn.Bn_Cve_Banco=bc.Bn_Cve_Banco
LEFT JOIN monto m ON m.FOLIO=f.FOLIO
LEFT JOIN cpago cp ON cp.FOLIO=f.FOLIO
"""

RET_SQL="""
SELECT gr.Gr_Folio AS FOLIO, COUNT(DISTINCT cd.Cd_Timbre_UUID) AS N, MIN(cd.Cd_Timbre_UUID) AS UUID,
       MIN(cr.Cd_Monto) AS MONTO, MIN(cr.Cd_Serie) AS SERIE, MIN(cr.Cd_Serie_Folio) AS FOLIO_XML, MIN(cd.Cd_RFC_Emisor) AS RFC
FROM Gasto_Registro gr JOIN Sucursal s ON gr.Sc_Cve_Sucursal=s.Sc_Cve_Sucursal
JOIN Comprobante_Digital cd ON cd.Cd_Tabla='GASTO_REGISTRO' AND cd.Cd_Documento LIKE gr.Gr_Folio+'%' AND cd.Es_Cve_Estado='AC' AND cd.Cd_Tipo_CFDI='RETENCIONES'
LEFT JOIN Comprobante_Digital cr ON cr.Cd_Tabla='CONSTANCIA_RETENCION' AND cr.Cd_Timbre_UUID=cd.Cd_Timbre_UUID AND cr.Es_Cve_Estado='AC'
WHERE gr.Gr_Fecha>=:fi AND gr.Gr_Fecha<:ff AND gr.Es_Cve_Estado<>'CA' AND s.Em_Cve_Empresa=:emp
GROUP BY gr.Gr_Folio
"""
FORMA_SAT={'01':'Efectivo','02':'Cheque nominativo','03':'Transferencia electrónica de fondos','04':'Tarjeta de crédito','05':'Monedero electrónico','06':'Dinero electrónico','08':'Vales de despensa','12':'Dación en pago','13':'Pago por subrogación','14':'Pago por consignación','15':'Condonación','17':'Compensación','23':'Novación','24':'Confusión','25':'Remisión de deuda','26':'Prescripción o caducidad','27':'A satisfacción del acreedor','28':'Tarjeta de débito','29':'Tarjeta de servicios','30':'Aplicación de anticipos','31':'Intermediario pagos','99':'Por definir'}
METODO={'PUE':'PUE - Pago en una sola exhibición','PPD':'PPD - Pago en parcialidades o diferido'}
ORIG={'GASTO_DIRECTO':'registro_gasto','COMPROBACION_GASTO':'comprobacion_gasto','ORDEN_COMPRA':'orden_compra','CONTROL_COMBUSTIBLE':'control_combustible','VIAJE':'viaje','GASTO_RECLASIFICACION':'gasto_reclasificacion','CONSUMO_INTERNO':'consumo_interno','GASTO_REGISTRO_NOMINA':'gasto_registro_nomina'}

def construir(fi,ff):
    base=m24.cargar(fi,ff); base['FOLIO']=base.FOLIO.str.strip()
    imp,_=m21.construir(fi,ff)
    grc=pesos(fi,ff)
    ic=Q(IMP_CLAVE_SQL,fi,ff)
    x=grc.merge(ic,on=['FOLIO','Grd_ID'],how='inner'); x['V']=x.IMPORTE*x.PESO
    pv=x.groupby(['FOLIO','CECO','CLAVE']).V.sum().unstack('CLAVE').fillna(0).round(2)
    pv.columns=['IMP_'+c for c in pv.columns]; pv=pv.reset_index()
    imp['DESCUENTO']=np.nan
    prov=Q(m22.PROVEEDOR_PAGO_SQL,fi,ff).drop(columns=['ORIGEN','COBRADO_EFECTIVO','COBRADO_CHEQUE_TRANSFERENCIA','CHEQUE','CFDI_COMPROBANTE_PAGO','BANCO','CUENTA_BANCARIA','FECHA_CHEQUE','NO_CHEQUE_TRANSF','MONTO_COBRADO','FACTURA_REF'])
    pago=Q(PAGO_SQL,fi,ff)
    xml=Q(m23.XML_CONCEPTO_SQL,fi,ff)
    ret=Q(RET_SQL,fi,ff)
    d=base.merge(imp,on=['FOLIO','CECO'],how='left').merge(pv,on=['FOLIO','CECO'],how='left')\
          .merge(prov,on='FOLIO',how='left').merge(pago,on='FOLIO',how='left').merge(xml,on='FOLIO',how='left').merge(ret.add_prefix('R_').rename(columns={'R_FOLIO':'FOLIO'}),on='FOLIO',how='left')
    return d,ic

def post(d):
    d=d.copy()
    # cargo/abono: positivos en cargo, negativos en abono (valor absoluto)
    net=d.CARGO.fillna(0)-d.ABONO.fillna(0)
    d['CARGO']=net.clip(lower=0).round(2); d['ABONO']=(-net).clip(lower=0).round(2)
    # subtotales/impuestos: una linea de poliza por (FOLIO,CECO) -> prorrateo por peso de la linea para no duplicar
    imp_cols=[c for c in d.columns if c.startswith('IMP_')]
    val=['SUBTOTAL_0','SUBTOTAL_16','SUBTOTAL_EXENTA','SUBTOTAL_NETO']+imp_cols
    d['_net']=(d.CARGO-d.ABONO)
    g=d.groupby(['FOLIO','CECO'])
    n=g.FOLIO.transform('size'); s_abs=g._net.transform(lambda s:s.abs().sum())
    w=np.where(n==1,1.0,np.where(s_abs>0,d._net.abs()/s_abs.replace(0,np.nan),np.nan))
    first=(g.cumcount()==0).astype(float)
    w=np.where(np.isnan(w),first,w)
    for c in val: d[c]=d[c]*w
    # sin documento (reclasificacion, nomina, consumo interno): subtotal neto = cargo-abono de la poliza
    sin=d.SUBTOTAL_NETO.isna() | (d.ORIGEN.isin(['CONSUMO_INTERNO'])&(d.SUBTOTAL_NETO.fillna(0)==0))
    d.loc[sin,'SUBTOTAL_NETO']=d.loc[sin,'_net']
    for c in val: d[c]=d[c].round(2)
    d['DESCUENTO']=np.nan; d['DESCUENTO_GLOBAL']=np.nan
    d['TOTAL']=(d.SUBTOTAL_NETO.fillna(0)+d[imp_cols].fillna(0).sum(axis=1)).round(2)
    # flags de pago
    fp=d.FP_CVE
    d['CHEQUE']=np.where(fp.isna(),None,np.where(fp=='0002','SI','NO'))
    # retenciones
    r=d.R_N.fillna(0)>=1
    d.loc[r&(d.R_N==1),'TIPO_COMPROBANTE']='R - Retenciones e información de pagos'
    d.loc[r&(d.R_N>=2),'TIPO_COMPROBANTE']='VARIOS'
    one=r&(d.R_N==1)
    d.loc[one,'XML_MONTO']=d.R_MONTO[one]; d.loc[one,'XML_SERIE']=d.R_SERIE[one]; d.loc[one,'XML_FOLIO']=d.R_FOLIO_XML[one]
    d.loc[one,'NUMERO_FACTURA']=d.R_FOLIO_XML[one]
    # forma / metodo XML con descripcion
    def ff_(v):
        if v is None or (isinstance(v,float) and np.isnan(v)) or str(v).strip()=='' : return None
        v=str(v).strip(); return v if v=='VARIOS' else f"{v} - {FORMA_SAT.get(v,'')}".rstrip(' -')
    d['XML_FORMA_PAGO']=d.XML_FORMA_PAGO.map(ff_)
    d['XML_METODO_PAGO']=d.XML_METODO_PAGO.map(lambda v: METODO.get(str(v).strip(),v) if v is not None and str(v).strip()!='' else None)
    d['ORIGEN']=d.ORIGEN.map(lambda o: ORIG.get(o,str(o).lower()))
    d['FECHA_CHEQUE']=pd.to_datetime(d.FECHA_CHEQUE,errors='coerce').dt.strftime('%Y-%m-%d')
    d.loc[d.FECHA_CHEQUE.isin(['1900-01-01']),'FECHA_CHEQUE']=None
    return d

if __name__=='__main__':
    fi,ff=sys.argv[1],sys.argv[2]
    d,ic=construir(fi,ff); d=post(d); d.to_pickle(f'rep_{fi}_{ff}.pkl'); print(d.shape)
