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

PAGO_SETUP_SQL="""
SELECT gr.Gr_Folio AS FOLIO, gr.Gr_Referencia INTO #folios
FROM Gasto_Registro gr JOIN Sucursal s ON gr.Sc_Cve_Sucursal=s.Sc_Cve_Sucursal
WHERE gr.Gr_Fecha>=:fi AND gr.Gr_Fecha<:ff AND gr.Es_Cve_Estado<>'CA' AND s.Em_Cve_Empresa=:emp;
SELECT * INTO #cxp_d FROM (
    SELECT DISTINCT f.FOLIO, cxp.Cxp_Folio FROM #folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio=f.FOLIO
    JOIN Cuenta_X_Pagar cxp ON cxp.Cxp_Tabla='Gasto_Registro:'+f.FOLIO AND cxp.Cxp_Documento=grd.Grd_ID
    UNION
    SELECT DISTINCT f.FOLIO, cxp.Cxp_Folio FROM #folios f
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio=f.FOLIO
    JOIN Cuenta_X_Pagar cxp ON cxp.Cxp_Tabla='Cuenta_X_Pagar' AND cxp.Cxp_Referencia=grd.Grd_Referencia AND cxp.Pv_Cve_Proveedor=grd.Pv_Cve_Proveedor
    WHERE grd.Grd_Referencia IS NOT NULL AND LTRIM(RTRIM(grd.Grd_Referencia))<>''
) u;
"""
# tablas temporales: con estadisticas reales el optimizador de .207 baja esta consulta de ~68 s a ~1 s
PAGO_SQL="""WITH folios AS (SELECT * FROM #folios), cxp_d AS (SELECT * FROM #cxp_d),
pagos AS (
    SELECT cd.FOLIO, pc.Pc_ID, pc.Cxp_Folio, pc.Fp_Cve_Forma_Pago, pc.Pc_Banco, pc.Pc_Cuenta_Bancaria,
           pc.Pc_Documento, pc.Pc_Tabla, pc.Pc_Referencia,
           ROW_NUMBER() OVER (PARTITION BY cd.FOLIO ORDER BY
               CASE WHEN pc.Fp_Cve_Forma_Pago IN ('0001','0002','0003') THEN 0 ELSE 1 END,
               ABS(pc.Pc_Importe*ISNULL(pc.Pc_Tipo_Cambio,1)) DESC, pc.Cxp_Folio, pc.Pc_ID) rn
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

def pago_df(fi,ff):
    p={'fi':fi,'ff':ff,'emp':EMP}
    with engine.connect() as c:
        c.execute(text(PAGO_SETUP_SQL),p)
        d=pd.read_sql(text(PAGO_SQL),c,params=p)
        c.execute(text('DROP TABLE #folios; DROP TABLE #cxp_d'))
    d['FOLIO']=d.FOLIO.str.strip(); return d

ORIGEN_CECO_SQL="""
SELECT gr.Gr_Folio AS FOLIO, CASE WHEN ISNULL(gr.Gr_Tabla,'')='' THEN 'GASTO_DIRECTO' ELSE gr.Gr_Tabla END AS ORIGEN
FROM Gasto_Registro gr JOIN Sucursal s ON gr.Sc_Cve_Sucursal=s.Sc_Cve_Sucursal
WHERE gr.Gr_Fecha>=:fi AND gr.Gr_Fecha<:ff AND gr.Es_Cve_Estado<>'CA' AND s.Em_Cve_Empresa=:emp
"""
CECO_DESC_SQL="select Cc_Cve_Centro_Costo AS CECO, Cc_Descripcion AS CECO_DESCRIPCION from Centro_Costo"
POLIZA_COLS=['POLIZA','FECHA_POLIZA','TIPO_POLIZA','NUMERO_POLIZA','CONCEPTO_POLIZA']
IMP_DOC_COLS=['SUBTOTAL_16','SUBTOTAL_0','SUBTOTAL_EXENTA','RETENCIONES_IVA','RETENCIONES_ISR','IVA_ACREDITABLE','SUBTOTAL_NETO']

# lineas de poliza del documento (Pd_Referencia = folio) sin CECO: m24 las descarta; aqui se atribuyen por importe
POLIZA_SIN_CECO_SQL="""
SELECT gr.Gr_Folio AS FOLIO, pl.Pl_Folio AS POLIZA, pl.Pl_Fecha AS FECHA_POLIZA, pl.Pl_Tipo AS TIPO_POLIZA,
       pl.Pl_Numero AS NUMERO_POLIZA, pl.Pl_Comentario AS CONCEPTO_POLIZA,
       pd.Cc_Cve_Cuenta_Contable AS CUENTA_REGISTRO, cc.Cc_Descripcion AS NOMBRE_CUENTA_REGISTRO,
       CASE WHEN pd.Pd_Tipo=1 THEN pd.Pd_Importe ELSE 0 END AS CARGO, CASE WHEN pd.Pd_Tipo=2 THEN pd.Pd_Importe ELSE 0 END AS ABONO
FROM Gasto_Registro gr JOIN Sucursal s ON gr.Sc_Cve_Sucursal=s.Sc_Cve_Sucursal
JOIN Poliza_Control plc ON plc.Pc_Tabla='GASTO_REGISTRO' AND plc.Pc_Documento=gr.Gr_Folio AND plc.Es_Cve_Estado<>'CA'
JOIN Poliza pl ON pl.Pl_Folio=plc.Pl_Folio AND pl.Es_Cve_Estado<>'CA'
JOIN Poliza_Detalle pd ON pd.Pl_Folio=plc.Pl_Folio AND pd.Pd_Referencia=gr.Gr_Folio
LEFT JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable=pd.Cc_Cve_Cuenta_Contable
WHERE gr.Gr_Fecha>=:fi AND gr.Gr_Fecha<:ff AND gr.Es_Cve_Estado<>'CA' AND s.Em_Cve_Empresa=:emp
  AND ISNULL(pd.Pd_Centro_Costo,'')=''
  AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '1170%' AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '2110%' AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '2150%'
  AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '10500%' AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '10600%'
"""
LINEA_COLS=['POLIZA','FECHA_POLIZA','TIPO_POLIZA','NUMERO_POLIZA','CONCEPTO_POLIZA','CUENTA_REGISTRO','NOMBRE_CUENTA_REGISTRO','CARGO','ABONO']

def atribuir_sin_ceco(ex,imp,fi,ff):
    """Carga a las filas completadas la linea de poliza sin CECO del mismo folio cuyo importe iguala el subtotal neto
    de su (FOLIO, CECO) del reparto (tolerancia 0.05); cada linea se usa una sola vez."""
    lin=Q(POLIZA_SIN_CECO_SQL,fi,ff)
    lin=lin[lin.FOLIO.isin(ex.FOLIO)].copy()
    if lin.empty: return ex
    lin['NET']=lin.CARGO-lin.ABONO
    meta_ix={f:list(g.index) for f,g in lin.groupby('FOLIO')}
    obj=imp.groupby(['FOLIO','CECO']).SUBTOTAL_NETO.sum()
    libre=set(lin.index); ex=ex.copy()
    for i,r in ex.iterrows():
        t=obj.get((r.FOLIO,r.CECO))
        if t is None or pd.isna(t): continue
        for j in meta_ix.get(r.FOLIO,[]):
            if j in libre and abs(lin.at[j,'NET']-t)<=0.05:
                for c in LINEA_COLS: ex.at[i,c]=lin.at[j,c]
                libre.discard(j); break
    return ex

def completar_gasto(base,imp,pv,grc,doc,ic,fi,ff):
    """Agrega filas sin cargo/abono (el documento no tiene linea de poliza con CECO que lo cubra) para que el layout
    totalice igual que RPAG008: (a) CECO del reparto del documento (Gasto_Registro_Control) sin linea de poliza y
    (b) documentos sin reparto ni linea de poliza (CECO vacio, importes del documento). Si la poliza trae una linea
    sin CECO que iguala el subtotal de esa fila, se le carga (atribucion por importe)."""
    kb=set(zip(base.FOLIO,base.CECO))
    a=grc[['FOLIO','CECO']].drop_duplicates()
    a=a[[k not in kb for k in zip(a.FOLIO,a.CECO)]].copy()
    sin_reparto=sorted(set(doc.FOLIO)-set(grc.FOLIO)-set(base.FOLIO))
    b=pd.DataFrame({'FOLIO':sin_reparto,'CECO':''})
    ex=pd.concat([a,b],ignore_index=True)
    if ex.empty: return base,imp,pv
    ex=ex.merge(Q(ORIGEN_CECO_SQL,fi,ff),on='FOLIO',how='left').merge(Q(CECO_DESC_SQL,fi,ff).assign(CECO=lambda t:t.CECO.str.strip()),on='CECO',how='left')
    pol=base.drop_duplicates('FOLIO').set_index('FOLIO')[POLIZA_COLS]
    ex=ex.join(pol,on='FOLIO'); ex['CARGO']=0.0; ex['ABONO']=0.0
    if sin_reparto:
        d=doc[doc.FOLIO.isin(sin_reparto)]
        v=d.groupby('FOLIO')[[c+'_DOC' for c in IMP_DOC_COLS]].sum().rename(columns=lambda c:c[:-4]).reset_index(); v['CECO']=''
        imp=pd.concat([imp,v],ignore_index=True,sort=False)
        w=ic[ic.FOLIO.isin(sin_reparto)].groupby(['FOLIO','CLAVE']).IMPORTE.sum().unstack('CLAVE').fillna(0).round(2)
        w.columns=['IMP_'+c for c in w.columns]; w=w.reset_index(); w['CECO']=''
        pv=pd.concat([pv,w],ignore_index=True,sort=False)
    ex=atribuir_sin_ceco(ex,imp,fi,ff)
    return pd.concat([base,ex],ignore_index=True,sort=False),imp,pv

def construir(fi,ff):
    base=m24.cargar(fi,ff); base['FOLIO']=base.FOLIO.str.strip()
    imp,doc=m21.construir(fi,ff)
    grc=pesos(fi,ff)
    ic=Q(IMP_CLAVE_SQL,fi,ff)
    x=grc.merge(ic,on=['FOLIO','Grd_ID'],how='inner'); x['V']=x.IMPORTE*x.PESO
    pv=x.groupby(['FOLIO','CECO','CLAVE']).V.sum().unstack('CLAVE').fillna(0).round(2)
    pv.columns=['IMP_'+c for c in pv.columns]; pv=pv.reset_index()
    base,imp,pv=completar_gasto(base,imp,pv,grc,doc,ic,fi,ff)
    imp['DESCUENTO']=np.nan
    prov=Q(m22.PROVEEDOR_PAGO_SQL,fi,ff).drop(columns=['ORIGEN','COBRADO_EFECTIVO','COBRADO_CHEQUE_TRANSFERENCIA','CHEQUE','CFDI_COMPROBANTE_PAGO','BANCO','CUENTA_BANCARIA','FECHA_CHEQUE','NO_CHEQUE_TRANSF','MONTO_COBRADO','FACTURA_REF'])
    pago=pago_df(fi,ff)
    xml=Q(m23.XML_CONCEPTO_SQL,fi,ff)
    ret=Q(RET_SQL,fi,ff)
    d=base.merge(imp,on=['FOLIO','CECO'],how='left').merge(pv,on=['FOLIO','CECO'],how='left')\
          .merge(prov,on='FOLIO',how='left').merge(pago,on='FOLIO',how='left').merge(xml,on='FOLIO',how='left').merge(ret.add_prefix('R_').rename(columns={'R_FOLIO':'FOLIO'}),on='FOLIO',how='left')
    return d,ic

def construir_todo(fi,ff):
    """Gastos + compras + indirectos + NC de proveedor, una fila por linea de poliza, con columna Tipo."""
    import tipos_documento as t
    d,_=construir(fi,ff); d['Tipo']='Gasto'
    partes=[d]+[t.construir_tipo(s,fi,ff,engine,EMP,PAGO_SQL) for s in t.SPECS]
    return pd.concat(partes,ignore_index=True,sort=False)

def _num(d,cols):
    for c in cols: d[c]=pd.to_numeric(d[c],errors='coerce').astype(float)

def post(d):
    d=d.copy()
    if 'Tipo' not in d: d['Tipo']='Gasto'
    for c in ('R_N','R_MONTO','R_SERIE','R_FOLIO_XML','FP_CVE','TIPO_COMPROBANTE','XML_MONTO','XML_SERIE','XML_FOLIO','NUMERO_FACTURA','FECHA_CHEQUE','ORIGEN'):
        if c not in d: d[c]=np.nan
    for c in ('TIPO_COMPROBANTE','XML_SERIE','XML_FOLIO','NUMERO_FACTURA','R_SERIE','R_FOLIO_XML','FP_CVE','ORIGEN'): d[c]=d[c].astype(object)
    imp_cols=[c for c in d.columns if c.startswith('IMP_')]
    val=['SUBTOTAL_0','SUBTOTAL_16','SUBTOTAL_EXENTA','SUBTOTAL_NETO']+imp_cols
    _num(d,['CARGO','ABONO','R_N','R_MONTO','XML_MONTO']+val)
    # cargo/abono: positivos en cargo, negativos en abono (valor absoluto)
    net=d.CARGO.fillna(0)-d.ABONO.fillna(0)
    d['CARGO']=net.clip(lower=0).round(2); d['ABONO']=(-net).clip(lower=0).round(2)
    # gastos: una linea de poliza por (FOLIO,CECO) -> prorrateo por peso de la linea; el resto de tipos trae cifras por documento
    d['_net']=(d.CARGO-d.ABONO); d['_abs']=d._net.abs()
    d['_gk']=np.where(d.Tipo=='Gasto',d.CECO.fillna('').astype(str),'')
    g=d.groupby(['Tipo','FOLIO','_gk'],sort=False)
    n=g.FOLIO.transform('size'); s_abs=g._abs.transform('sum')
    w=np.where(n==1,1.0,np.where(s_abs>0,d._abs/s_abs.replace(0,np.nan),np.nan))
    first=(g.cumcount()==0).astype(float)
    w=np.where(np.isnan(w),first,w)
    for c in val: d[c]=d[c]*w
    # sin documento (reclasificacion, nomina, consumo interno): subtotal neto = cargo-abono de la poliza
    sin=d.SUBTOTAL_NETO.isna() | (d.ORIGEN.isin(['CONSUMO_INTERNO'])&(d.SUBTOTAL_NETO.fillna(0)==0))
    d.loc[sin,'SUBTOTAL_NETO']=d.loc[sin,'_net']
    # valor del documento completo (suma de sus lineas prorrateadas): lo usa la vista Layout
    gd=d.groupby(['Tipo','FOLIO'],sort=False)
    for c in val: d['DOC_'+c]=gd[c].transform('sum').round(2)
    d['DOC_TOTAL']=(d.DOC_SUBTOTAL_NETO.fillna(0)+d[['DOC_'+c for c in imp_cols]].fillna(0).sum(axis=1)).round(2)
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
    d['ORIGEN']=d.ORIGEN.map(lambda o: None if o is None or (isinstance(o,float) and np.isnan(o)) else ORIG.get(o,str(o).lower()))
    d['FECHA_CHEQUE']=pd.to_datetime(d.FECHA_CHEQUE,errors='coerce').dt.strftime('%Y-%m-%d')
    d.loc[d.FECHA_CHEQUE.isin(['1900-01-01']),'FECHA_CHEQUE']=None
    return d.drop(columns=['_net','_abs','_gk'])

if __name__=='__main__':
    fi,ff=sys.argv[1],sys.argv[2]
    d=post(construir_todo(fi,ff)); d.to_pickle(f'rep_{fi}_{ff}.pkl'); print(d.shape)
