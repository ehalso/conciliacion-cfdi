"""
Generaliza reconstruir_config() (14/15/poliza_configuracion_lib.py) a TODAS
las configs usadas por los 5 origenes normales del requerimiento original
del Word (GASTO_DIRECTO, CONTROL_COMBUSTIBLE, VIAJE, ORDEN_COMPRA,
GASTO_RECLASIFICACION) -- no solo `0450`, la unica probada hasta ahora.

Motivacion: cuantificado en conversacion (2026-09-11) que `0450` cubre
79.92% de los folios de estos 5 origenes pero solo 21.03% del Cargo $ --
la mayoria del dinero (sobre todo de GASTO_DIRECTO) vive en decenas de
configs no reconstruidas. Pregunta de este script: si se generalizan TODAS,
¿cuanto sube la cobertura del "join real" (vs. rank-pairing), y donde
aplica, coincide con el resultado de rank-pairing ya validado
(07/11/12/layout_gastos_lib.py, produccion de CONT-1/CONT-2)?

Metodo:
1. Universo: los 5 origenes del Word (GASTO_DIRECTO = Gr_Tabla vacio/NULL),
   folio -> config real de su poliza.
2. Para cada config distinta, intenta reconstruir_config() -- algunas
   fallan (ValueError: sin renglones de Cargo+Centro_Costo, ej. configs
   que no resuelven CECO en absoluto) -- se documentan aparte, no es bug
   de esta generalizacion.
3. Concatena las reconstrucciones exitosas, valida por (FOLIO,CECO) contra
   Poliza_Detalle real (igual que 14, generalizado a N configs a la vez).
4. Compara cobertura ANTES (solo 0450) vs DESPUES (todas las que aplicaron).
5. Cruza contra layout_gastos_lib.reporte_completo() (rank-pairing, lo que
   ya corre en produccion en CONT-1/CONT-2) a nivel (FOLIO,CECO) -- cuanto
   coincide exacto donde ambas tecnicas tienen dato.

Uso:
    python3 18_generalizar_reconstruccion_configs.py --fecha-ini 2026-01-01 --fecha-fin 2026-04-01
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # ruta relativa -- no asumir usuario/maquina

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from sqlalchemy import text

from connection_205_trivasadb3 import engine
from poliza_configuracion_lib import reconstruir_config
from layout_gastos_lib import reporte_completo
from helpers_output import console, mostrar_tabla, resumen

EMPRESA = "0001"
ORIGEN_CASE = "CASE WHEN ISNULL(gr.Gr_Tabla,'')='' THEN 'GASTO_DIRECTO' ELSE gr.Gr_Tabla END"


def folios_por_config(fecha_ini, fecha_fin):
    """Folio -> (ORIGEN, CONFIG, CARGO real) para los 5 origenes del Word."""
    q = f"""
    SELECT
        gr.Gr_Folio AS FOLIO,
        {ORIGEN_CASE} AS ORIGEN,
        pl.Pl_Configuracion AS CONFIG,
        SUM(CASE WHEN pd.Pd_Tipo=1 THEN pd.Pd_Importe ELSE 0 END) AS CARGO
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    JOIN Poliza_Control plc ON plc.Pc_Tabla='GASTO_REGISTRO' AND plc.Pc_Documento=gr.Gr_Folio AND plc.Es_Cve_Estado<>'CA'
    JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio AND pl.Es_Cve_Estado<>'CA'
    JOIN Poliza_Detalle pd ON pd.Pl_Folio = plc.Pl_Folio AND pd.Pd_Referencia = gr.Gr_Folio
    WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
      AND gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = :emp
      AND ({ORIGEN_CASE}) IN ('GASTO_DIRECTO','CONTROL_COMBUSTIBLE','VIAJE','ORDEN_COMPRA','GASTO_RECLASIFICACION')
    GROUP BY gr.Gr_Folio, {ORIGEN_CASE}, pl.Pl_Configuracion
    """
    df = pd.read_sql(text(q), engine, params={"fi": fecha_ini, "ff": fecha_fin, "emp": EMPRESA})
    df["FOLIO"] = df.FOLIO.str.strip()
    df["CONFIG"] = df.CONFIG.str.strip()
    return df


def folios_reversion(fecha_ini, fecha_fin):
    """Folios con IMPORTE_FOLIO <= -$1 (misma regla que 07/layout_gastos_lib.py,
    IMPORTE_FOLIO_SQL) -- ahi el motor invierte Cargo/Abono: el Cargo real cae
    en Provision/Pasivo SIN centro de costo, y lo que aparece con centro de
    costo es el ABONO. reconstruir_config() no lo sabe (siempre reconstruye
    renglones de tipo Cargo de la config) -- se corrige aqui, en la
    validacion, no en el join."""
    q = f"""
    SELECT gr.Gr_Folio AS FOLIO, SUM(grd.Grd_Precio_Descontado_Importe * grd.Grd_Tipo_Cambio) AS IMPORTE_FOLIO
    FROM Gasto_Registro gr
    JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
    JOIN Gasto_Registro_Documento grd ON grd.Gr_Folio = gr.Gr_Folio
    WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
      AND gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = :emp
      AND ({ORIGEN_CASE}) IN ('GASTO_DIRECTO','CONTROL_COMBUSTIBLE','VIAJE','ORDEN_COMPRA','GASTO_RECLASIFICACION')
    GROUP BY gr.Gr_Folio
    """
    df = pd.read_sql(text(q), engine, params={"fi": fecha_ini, "ff": fecha_fin, "emp": EMPRESA})
    df["FOLIO"] = df.FOLIO.str.strip()
    return set(df[df.IMPORTE_FOLIO <= -1.0].FOLIO)


def reconstruir_todas(configs, fecha_ini, fecha_fin):
    """Intenta reconstruir_config() para cada config. Devuelve
    (df_concatenado, dict de fallas {config: motivo})."""
    partes, fallas = [], {}
    for i, cve in enumerate(configs, 1):
        try:
            r = reconstruir_config(cve, EMPRESA, fecha_ini, fecha_fin)
            if r.empty:
                fallas[cve] = "reconstruccion vacia (0 filas)"
                continue
            r["CONFIG"] = cve
            partes.append(r)
        except Exception as e:  # ValueError esperado (sin Cargo+Centro_Costo), u otro
            fallas[cve] = f"{type(e).__name__}: {e}"
        if i % 10 == 0:
            console.print(f"  ... {i}/{len(configs)} configs procesadas")
    recon = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    return recon, fallas


def validar_contra_real(recon, folios, rev):
    """Agrega la reconstruccion por (FOLIO,CECO) y compara contra
    Poliza_Detalle real -- igual que 14, sin restringir a una sola config.
    Para folios de reversion (`rev`), compara contra ABONO (Pd_Tipo=2) en
    vez de CARGO (Pd_Tipo=1) -- ver folios_reversion()."""
    recon_agg = recon.groupby(["FOLIO", "CECO"], as_index=False).IMPORTE.sum()
    in_list = ",".join(f"'{f}'" for f in folios)
    real = pd.read_sql(text(f"""
        SELECT gr.Gr_Folio AS FOLIO, pd.Pd_Centro_Costo AS CECO, pd.Pd_Tipo, SUM(pd.Pd_Importe) AS IMPORTE_PD
        FROM Gasto_Registro gr
        JOIN Poliza_Control plc ON plc.Pc_Tabla='GASTO_REGISTRO' AND plc.Pc_Documento=gr.Gr_Folio AND plc.Es_Cve_Estado<>'CA'
        JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio AND pl.Es_Cve_Estado<>'CA'
        JOIN Poliza_Detalle pd ON pd.Pl_Folio = plc.Pl_Folio AND pd.Pd_Referencia = gr.Gr_Folio
        WHERE gr.Gr_Folio IN ({in_list}) AND pd.Pd_Centro_Costo <> ''
        GROUP BY gr.Gr_Folio, pd.Pd_Centro_Costo, pd.Pd_Tipo
    """), engine)
    real["FOLIO"] = real.FOLIO.str.strip()
    tipo_esperado = real.FOLIO.isin(rev).map({True: 2, False: 1})
    real = real[real.Pd_Tipo == tipo_esperado][["FOLIO", "CECO", "IMPORTE_PD"]]
    cmp = recon_agg.merge(real, on=["FOLIO", "CECO"], how="outer")
    cmp["DIFF"] = (cmp.IMPORTE.fillna(0) - cmp.IMPORTE_PD.fillna(0)).abs()
    return cmp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", default="2026-01-01")
    ap.add_argument("--fecha-fin", default="2026-04-01")
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print(f"[bold]Generalizacion de reconstruir_config() -- {fi} a {ff}[/bold]\n")

    base = folios_por_config(fi, ff)
    configs = sorted(base.CONFIG.dropna().unique())
    console.print(f"Universo: {base.FOLIO.nunique()} folios, {len(configs)} configs distintas.\n")

    console.print(f"[bold]Reconstruyendo las {len(configs)} configs...[/bold]")
    recon, fallas = reconstruir_todas(configs, fi, ff)

    if fallas:
        f_df = pd.DataFrame(sorted(fallas.items()), columns=["CONFIG", "MOTIVO"])
        mostrar_tabla(f_df, f"Configs que fallaron ({len(fallas)}/{len(configs)})", max_filas=40)

    ok_configs = set(configs) - set(fallas)
    console.print(f"\n[green]{len(ok_configs)}/{len(configs)} configs reconstruidas con exito.[/green]")

    # --- Cobertura ANTES (solo 0450) vs DESPUES (todas las que aplicaron) ---
    base["CUBIERTO_ANTES"] = base.CONFIG == "0450"
    base["CUBIERTO_DESPUES"] = base.CONFIG.isin(ok_configs)

    for etiqueta, col in [("ANTES (solo 0450)", "CUBIERTO_ANTES"), ("DESPUES (todas las configs que aplicaron)", "CUBIERTO_DESPUES")]:
        folios_cub = base[base[col]].FOLIO.nunique()
        cargo_cub = base[base[col]].CARGO.sum()
        folios_tot = base.FOLIO.nunique()
        cargo_tot = base.CARGO.sum()
        resumen(
            etiqueta=etiqueta,
            pct_folios=f"{folios_cub/folios_tot*100:.2f}%",
            pct_cargo=f"{cargo_cub/cargo_tot*100:.2f}%",
        )

    por_origen = base.groupby("ORIGEN").apply(
        lambda g: pd.Series({
            "folios_antes_%": g[g.CUBIERTO_ANTES].FOLIO.nunique() / g.FOLIO.nunique() * 100,
            "folios_despues_%": g[g.CUBIERTO_DESPUES].FOLIO.nunique() / g.FOLIO.nunique() * 100,
            "cargo_antes_%": g[g.CUBIERTO_ANTES].CARGO.sum() / g.CARGO.sum() * 100 if g.CARGO.sum() else 0,
            "cargo_despues_%": g[g.CUBIERTO_DESPUES].CARGO.sum() / g.CARGO.sum() * 100 if g.CARGO.sum() else 0,
        }), include_groups=False
    ).round(2).reset_index()
    mostrar_tabla(por_origen, "Cobertura por origen, antes vs. despues", max_filas=10)

    if recon.empty:
        console.print("[red]Ninguna config se reconstruyo -- no hay nada que validar ni cruzar.[/red]")
        return

    # --- Folios de reversion (IMPORTE_FOLIO <= -$1) -- ahi comparamos contra
    # ABONO, no CARGO. Ver folios_reversion() y ejemplo en conversacion 2026-09-11
    # (folio 01-0035793: Cargo real va a Provision sin CECO, el CECO solo ve Abono). ---
    rev = folios_reversion(fi, ff)
    resumen(folios_reversion=f"{len(rev)} de {base.FOLIO.nunique()} folios ({len(rev)/base.FOLIO.nunique()*100:.2f}%)")

    # --- Validacion: la reconstruccion agregada, ¿cuadra contra Poliza_Detalle real? ---
    folios_cubiertos = base[base.CUBIERTO_DESPUES].FOLIO.unique().tolist()
    cmp = validar_contra_real(recon, folios_cubiertos, rev)
    cmp["CUADRA"] = cmp.DIFF < 1
    n, c = len(cmp), int(cmp.CUADRA.sum())
    resumen(validacion_join_real=f"{c}/{n} ({c/n*100:.2f}%) combinaciones (FOLIO,CECO) cuadran exacto")
    mal = cmp[~cmp.CUADRA]
    if not mal.empty:
        mostrar_tabla(mal.sort_values("DIFF", ascending=False).head(20), "Combinaciones que NO cuadran (join real, con regla de reversion aplicada)", max_filas=20)

    # --- Cruce contra rank-pairing (lo que ya corre en CONT-1/CONT-2) ---
    console.print("\n[bold]Cruzando contra rank-pairing (layout_gastos_lib.reporte_completo, produccion de CONT-1/CONT-2)...[/bold]")
    rp = reporte_completo(fi, ff, incluir_nomina=False)
    rp = rp[rp.ORIGEN != "CONSUMO_INTERNO"]  # fuera del alcance del Word
    # folios de reversion: el valor a comparar es ABONO, no CARGO (mismo criterio que validar_contra_real)
    rp["VALOR_ESPERADO"] = rp.CARGO.where(~rp.FOLIO.isin(rev), rp.ABONO)
    rp_agg = rp.groupby(["FOLIO", "CECO"], as_index=False).VALOR_ESPERADO.sum().rename(columns={"VALOR_ESPERADO": "CARGO_RANKPAIRING"})

    recon_agg = recon.groupby(["FOLIO", "CECO"], as_index=False).IMPORTE.sum().rename(columns={"IMPORTE": "CARGO_JOIN_REAL"})
    cruce = recon_agg.merge(rp_agg, on=["FOLIO", "CECO"], how="inner")
    cruce["DIFF"] = (cruce.CARGO_JOIN_REAL - cruce.CARGO_RANKPAIRING).abs()
    cruce["COINCIDE"] = cruce.DIFF < 1
    n2, c2 = len(cruce), int(cruce.COINCIDE.sum())
    resumen(
        cruce_rankpairing_vs_join_real=f"{c2}/{n2} ({c2/n2*100:.2f}%) combinaciones (FOLIO,CECO) coinciden",
        solo_en_join_real=len(recon_agg.merge(rp_agg, on=["FOLIO", "CECO"], how="left", indicator=True).query("_merge=='left_only'")),
        solo_en_rankpairing=len(recon_agg.merge(rp_agg, on=["FOLIO", "CECO"], how="right", indicator=True).query("_merge=='right_only'")),
    )
    discrepan = cruce[~cruce.COINCIDE]
    if not discrepan.empty:
        mostrar_tabla(discrepan.sort_values("DIFF", ascending=False).head(20), "Discrepancias join real vs. rank-pairing", max_filas=20)
    else:
        console.print("[green]Cero discrepancias -- donde ambas tecnicas tienen dato, coinciden exacto.[/green]")


if __name__ == "__main__":
    main()
