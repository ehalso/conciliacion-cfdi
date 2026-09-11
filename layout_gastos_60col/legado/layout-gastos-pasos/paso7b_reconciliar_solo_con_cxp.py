"""
Paso 7b - Acotar la reconciliacion Cargo/Abono al subconjunto de folios que
SI tienen una Cuenta_X_Pagar relacionada (sin llegar a pagos todavia).
Hipotesis: los outliers de muchas lineas contables (81-438) son folios
GASTO_DIRECTO sin CXP real (reparto interno entre centros de costo), no
folios normales con CXP.
"""
import sys
sys.path.append("..")
from connection_200_trivasadb3 import engine
import pandas as pd
from rich.table import Table
from helpers_output import console_err, resumen_err

FECHA_INI, FECHA_FIN = "2026-01-01", "2026-02-01"

def leer_query(path):
    with open(path) as f:
        return f.read().replace(":fecha_ini", f"'{FECHA_INI}'").replace(":fecha_fin", f"'{FECHA_FIN}'")

base = pd.read_csv("v01_baseline_enero2026_sin_nomina_consumo.csv")
base["FOLIO"] = base["FOLIO"].str.strip()
base["ORIGEN"] = base["ORIGEN"].fillna("GASTO_DIRECTO")

cargo_abono = pd.read_csv("v03_detalle_cuenta_enero2026.csv")
cargo_abono["FOLIO"] = cargo_abono["FOLIO"].str.strip()

con_cxp = pd.read_sql(leer_query("docs/queries/gastos/folios_con_cxp.sql"), engine)
con_cxp["FOLIO"] = con_cxp["FOLIO"].str.strip()
assert con_cxp["FOLIO"].is_unique
con_cxp["TIENE_CXP"] = con_cxp["N_CXP_FOLIOS"] > 0

n_lineas = cargo_abono.groupby("FOLIO").size().rename("N_LINEAS").reset_index()
info = base[["FOLIO", "ORIGEN"]].merge(n_lineas, on="FOLIO", how="left").fillna({"N_LINEAS": 0})
info = info.merge(con_cxp[["FOLIO", "TIENE_CXP", "Gr_Genera_Cxp"]], on="FOLIO", how="left")

# --- Split: con CXP vs sin CXP ---
t1 = Table(title="Folios y líneas contables, con CXP vs sin CXP")
t1.add_column("Grupo"); t1.add_column("Folios", justify="right")
t1.add_column("Total líneas", justify="right"); t1.add_column("Líneas/folio prom.", justify="right")
for grupo, g in info.groupby("TIENE_CXP"):
    nombre = "CON CXP" if grupo else "SIN CXP"
    t1.add_row(nombre, str(len(g)), str(int(g.N_LINEAS.sum())), f"{g.N_LINEAS.mean():.1f}")
console_err.print(t1)

# --- Los outliers, ¿tienen CXP? ---
outliers = info[info.N_LINEAS >= 50].sort_values("N_LINEAS", ascending=False)
t2 = Table(title="Folios con 50+ líneas -- ¿tienen CXP?")
t2.add_column("FOLIO"); t2.add_column("ORIGEN"); t2.add_column("N_LINEAS", justify="right")
t2.add_column("TIENE_CXP"); t2.add_column("Gr_Genera_Cxp")
for _, r in outliers.iterrows():
    t2.add_row(r.FOLIO, r.ORIGEN, str(int(r.N_LINEAS)), str(r.TIENE_CXP), str(r.Gr_Genera_Cxp))
console_err.print(t2)

resumen_err(
    folios_universo=len(info),
    folios_con_cxp=int(info.TIENE_CXP.sum()),
    folios_sin_cxp=int((~info.TIENE_CXP.fillna(False)).sum()),
    lineas_en_con_cxp=int(info[info.TIENE_CXP].N_LINEAS.sum()),
    lineas_en_sin_cxp=int(info[~info.TIENE_CXP.fillna(False)].N_LINEAS.sum()),
)

# --- Reconciliar SOLO el subconjunto con CXP ---
folios_con_cxp = info[info.TIENE_CXP]["FOLIO"]
ca_con_cxp = cargo_abono[cargo_abono.FOLIO.isin(folios_con_cxp)]
rollup = ca_con_cxp.groupby("FOLIO", as_index=False).agg(
    CARGO_TOTAL=("CARGO", "sum"), ABONO_TOTAL=("ABONO", "sum")
)
df = base[base.FOLIO.isin(folios_con_cxp)][["FOLIO", "ORIGEN", "IMPORTE"]].merge(rollup, on="FOLIO", how="left")
df[["CARGO_TOTAL", "ABONO_TOTAL"]] = df[["CARGO_TOTAL", "ABONO_TOTAL"]].fillna(0)

es_reversion = df.IMPORTE <= -1.0
df["VALOR_VALIDACION"] = df.CARGO_TOTAL
df.loc[es_reversion, "VALOR_VALIDACION"] = df.loc[es_reversion, "ABONO_TOTAL"]
df["DIFERENCIA"] = df.VALOR_VALIDACION - df.IMPORTE.abs()
df["CUADRA"] = df.DIFERENCIA.abs() < 1

n, c = len(df), df.CUADRA.sum()
resumen_err(reconciliacion_solo_con_cxp_folios=n, cuadran=int(c), pct=round(100*c/n, 2))

print("--- CSV_PARA_CLAUDE: split_con_sin_cxp ---")
print(info.groupby("TIENE_CXP").agg(folios=("FOLIO","count"), lineas=("N_LINEAS","sum")).reset_index().to_csv(index=False))

print("--- CSV_PARA_CLAUDE: outliers_50plus_con_cxp ---")
print(outliers[["FOLIO","ORIGEN","N_LINEAS","TIENE_CXP","Gr_Genera_Cxp"]].to_csv(index=False))
