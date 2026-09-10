"""
Exploratorio: en vez de emparejar Gasto_Registro_Control (GRC) contra
Poliza_Detalle por ORDEN (rank-pairing, tecnica de 07/11/12 -- sin llave
real, "casan por casualidad" cuando hay mas de una linea por (FOLIO,CECO)),
reconstruir la query REAL que genero la poliza, leyendo la regla completa
de Poliza_Configuracion/_Condicion/_Detalle (ver trivasa-context/docs/
proyectos/poliza-explor/configuracion-polizas.md, sesion 2026-09-03).

Idea: Poliza_Configuracion_Detalle.Pcd_Relacion ya hace JOIN directo a
Gasto_Registro_Control por (Gr_Folio, Grd_ID) -- ese es el join real que
usa el motor para generar cada renglon de Poliza_Detalle. Si se
reconstruye ese JOIN+WHERE tal cual (por renglon, no colapsado), se puede
etiquetar cada linea de GRC con el renglon exacto que le corresponde --
sin ordenar nada, sin adivinar.

RESULTADO DE LA EXPLORACION (config 0450 "REGISTRO DE GASTOS NACIONAL",
la que domina el volumen de GASTO_DIRECTO/CONTROL_COMBUSTIBLE/VIAJE/
ORDEN_COMPRA -- 3,403 de ~3,600 folios del rango probado):

1. La reconstruccion es CORRECTA: sumada por (FOLIO,CECO) cuadra 100.00%
   contra Poliza_Detalle real (5,171/5,171 combinaciones, enero-marzo
   2026) -- confirma que el JOIN reconstruido es el mismo que uso el
   motor, no una aproximacion.

2. Responde la pregunta de fondo ("no arregla el problema de que casan
   por casualidad?"): la mayoria de las veces SI. De las 5,171
   combinaciones (FOLIO,CECO), 436 tienen mas de una linea de GRC (las
   unicas donde rank-pairing podria fallar). De esas 436:
     - 17 se resuelven en RENGLONES DISTINTOS de la configuracion --
       distincion real, no coincidencia (el motor las separa porque
       tienen Tipo_Gasto/Proveedor distinto, van a un Pcd_ID distinto).
     - 419 caen en el MISMO renglon -- el motor las suma con
       SUM(ABS(Grc_Importe)) GROUP BY Centro_Costo, SIN agrupar tambien
       por Tipo_Gasto. De esas 419, solo 20 tienen ademas mas de un
       Tipo_Gasto distinto -- esas 20 son la ambiguedad REAL e
       IRREDUCIBLE: ni reconstruyendo la query exacta del motor se puede
       saber cuanto de esa suma es de cada Tipo_Gasto, porque el propio
       motor ya descarto esa informacion al generar Poliza_Detalle (no es
       un limite de nuestra tecnica, es un limite del dato fuente).

   Neto: 5,151/5,171 (99.61%) de las combinaciones (FOLIO,CECO) quedan
   resueltas con una distincion real (una sola linea, o lineas en
   renglones distintos) -- rank-pairing deja de ser una suposicion y pasa
   a ser innecesario ahi. Solo 20/5,171 (0.39%) siguen necesitando algun
   criterio de desempate, y ese 0.39% es un piso duro, no un defecto de
   esta tecnica.

Alcance de ESTE script: solo la config 0450 (la dominante). Generalizar a
las ~66 configs restantes usadas por el resto de GASTO_DIRECTO y a las de
CONSUMO_INTERNO/GASTO_RECLASIFICACION queda pendiente -- ver funcion
`reconstruir_config()`, reusable para cualquier config con renglones de
tipo Cargo+Centro_Costo.

No reemplaza a 11/12 todavia (cobertura parcial: solo 1 de ~67 configs).
Es la prueba de que la tecnica funciona y cuanto resuelve, antes de
invertir en generalizarla.

Uso:
    python3 14_reconstruccion_via_poliza_configuracion.py --fecha-ini 2026-01-01 --fecha-fin 2026-04-01 [--config 0450]
"""
import argparse
import sys

from connection_205_trivasadb3 import engine  # default de exploracion

import pandas as pd
from sqlalchemy import text
from helpers_output import console, mostrar_tabla, resumen
from poliza_configuracion_lib import reconstruir_config  # noqa: F401 -- reexportado, ver modulo (2026-09-04)


def validar_contra_poliza_real(recon, cve, empresa, fecha_ini, fecha_fin):
    """Suma la reconstruccion por (FOLIO,CECO) y la compara contra
    Poliza_Detalle real -- confirma que el JOIN reconstruido es el mismo
    que uso el motor (y no una aproximacion)."""
    recon_agg = recon.groupby(["FOLIO", "CECO"], as_index=False).IMPORTE.sum()
    real = pd.read_sql(text("""
        SELECT gr.Gr_Folio AS FOLIO, pd.Pd_Centro_Costo AS CECO, SUM(pd.Pd_Importe) AS IMPORTE_PD
        FROM Gasto_Registro gr
        JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
        JOIN Poliza_Control plc ON plc.Pc_Tabla='GASTO_REGISTRO' AND plc.Pc_Documento=gr.Gr_Folio AND plc.Es_Cve_Estado<>'CA'
        JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio
        JOIN Poliza_Detalle pd ON pd.Pl_Folio = plc.Pl_Folio AND pd.Pd_Referencia = gr.Gr_Folio
        WHERE gr.Gr_Fecha >= :fi AND gr.Gr_Fecha < :ff
          AND gr.Es_Cve_Estado <> 'CA' AND s.Em_Cve_Empresa = :emp AND pl.Es_Cve_Estado <> 'CA'
          AND pl.Pl_Configuracion = :cve AND pd.Pd_Tipo = 1 AND pd.Pd_Centro_Costo <> ''
        GROUP BY gr.Gr_Folio, pd.Pd_Centro_Costo
    """), engine, params={"fi": fecha_ini, "ff": fecha_fin, "emp": empresa, "cve": cve})
    real["FOLIO"] = real.FOLIO.str.strip()

    cmp = recon_agg.merge(real, on=["FOLIO", "CECO"], how="outer")
    cmp["DIFF"] = (cmp.IMPORTE.fillna(0) - cmp.IMPORTE_PD.fillna(0)).abs()
    return cmp


def analizar_ambiguedad(recon):
    """Cuantifica cuanto de la ambiguedad de rank-pairing es real
    (irreducible, el motor la descarta) vs recuperable (renglones
    distintos, el motor SI distingue)."""
    grp = recon.groupby(["FOLIO", "CECO"])
    multi = grp.filter(lambda g: len(g) > 1)

    def resumen_grupo(g):
        return pd.Series({
            "n_lineas": len(g),
            "n_renglones_distintos": g.RENGLON.nunique(),
            "n_tipogasto_distintos": g.TIPO_GASTO.nunique(),
        })

    res = multi.groupby(["FOLIO", "CECO"]).apply(resumen_grupo).reset_index()
    mismo_renglon = res[res.n_renglones_distintos == 1]
    distinto_renglon = res[res.n_renglones_distintos > 1]
    irreducible = mismo_renglon[mismo_renglon.n_tipogasto_distintos > 1]
    return dict(
        total_folio_ceco=grp.ngroups,
        con_mas_de_1_linea=multi.groupby(["FOLIO", "CECO"]).ngroups,
        recuperable_renglon_distinto=len(distinto_renglon),
        mismo_renglon=len(mismo_renglon),
        irreducible_multi_tipo_gasto=len(irreducible),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    ap.add_argument("--empresa", default="0001")
    ap.add_argument("--config", default="0450", help="Poliza_Configuracion a reconstruir (default: 0450, la dominante)")
    args = ap.parse_args()

    console.print(f"[bold]14 -- Reconstruccion via Poliza_Configuracion (config {args.config})[/bold]")

    recon = reconstruir_config(args.config, args.empresa, args.fecha_ini, args.fecha_fin)
    console.print(f"Renglones de cargo+CeCo reconstruidos: lineas GRC etiquetadas = {len(recon)}")

    cmp = validar_contra_poliza_real(recon, args.config, args.empresa, args.fecha_ini, args.fecha_fin)
    n, c = len(cmp), int((cmp.DIFF < 1).sum())
    resumen(validacion_folio_ceco=n, cuadran=c, pct=f"{100*c/n:.2f}%")
    if c < n:
        mostrar_tabla(cmp[cmp.DIFF >= 1].head(20), "Combinaciones (FOLIO,CECO) que NO cuadran contra Poliza_Detalle real")

    amb = analizar_ambiguedad(recon)
    console.print(
        f"\n[bold]Ambiguedad de rank-pairing, cuantificada:[/bold]\n"
        f"  (FOLIO,CECO) totales: {amb['total_folio_ceco']}\n"
        f"  con mas de 1 linea de GRC (unicas donde rank-pairing podria fallar): {amb['con_mas_de_1_linea']}\n"
        f"    -> recuperable (renglones distintos, distincion real del motor): {amb['recuperable_renglon_distinto']}\n"
        f"    -> mismo renglon (el motor ya sumo, sin distinguir Tipo_Gasto): {amb['mismo_renglon']}\n"
        f"       -> de esas, con >1 Tipo_Gasto real (ambiguedad IRREDUCIBLE, ni el motor la resuelve): "
        f"{amb['irreducible_multi_tipo_gasto']}"
    )

    reporte = recon.copy()
    reporte["ORIGEN"] = "GASTO_DIRECTO_o_similar (config " + args.config + ")"
    reporte["METODO_MATCH"] = "CONFIG_REAL"
    out = f"14_reconstruccion_config_{args.config}_{args.fecha_ini}_{args.fecha_fin}.csv"
    reporte.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]")


if __name__ == "__main__":
    main()
