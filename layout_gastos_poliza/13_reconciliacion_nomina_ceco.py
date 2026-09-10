"""
GASTO_REGISTRO_NOMINA -- primera investigacion (nunca antes tocado, ver
RESUMEN_CASOS.md: "sin investigar, excluido del universo").

Pregunta: como se ligan los gastos de tipo GASTO_REGISTRO_NOMINA con las
polizas contables?

Hallazgo: se ligan EXACTAMENTE por el mismo mecanismo que los 5 origenes
"normales" (CONTROL_COMBUSTIBLE, GASTO_DIRECTO, VIAJE, ORDEN_COMPRA,
GASTO_RECLASIFICACION) -- Poliza_Control (Pc_Tabla='GASTO_REGISTRO',
Pc_Documento=Gr_Folio) -> Poliza -> Poliza_Detalle (Pd_Referencia=Gr_Folio).
El comentario en queries/v03_detalle_cuenta_centro_costo.sql ("Nomina se
contabiliza por otro mecanismo, ajeno a este reporte") es INCORRECTO -- misma
situacion que ya se encontro con CONSUMO_INTERNO (tambien excluido por el
mismo comentario, y tambien resulto tener poliza real, ver 09_).

Diferencia de grano vs. los origenes normales: cada folio de nomina genera
MUCHAS mas lineas de Cargo en la poliza que Grc_ID (una por concepto --
Sueldos, Bono Por Productividad, Bono Por Puntualidad, Bono Por Asistencia,
Fondo de ahorro, Comisiones, Vacaciones, Prima Vacacional, Pagos Por Retiro,
etc. -- cada una con su propia cuenta 6xxx), mientras que Grc_Importe ya
viene agregado a nivel (Tipo_Gasto, Centro). Por eso la comparacion NO se
hace a nivel cuenta (como v03) sino a nivel (FOLIO, CENTRO) -- incluso mas
grueso que la regla (Tg_Cve_Tipo_Gasto, Centro) de 06/07, porque el Tipo_Gasto
de nomina no tiene correspondencia 1:1 limpia con las cuentas contables
desagregadas.

Cada poliza de nomina tambien trae lineas de Cargo/Abono SIN centro de costo
(Pd_Centro_Costo = '') -- reclasificaciones de pasivo dentro de la misma
poliza (ISR retenido, Cuotas IMSS, Sueldos y salarios por pagar, Fondo de
ahorro por pagar, Vales de despensa por pagar, Pension alimenticia por
enterar...). Esas lineas cierran el balance Cargo=Abono de la poliza pero no
representan gasto por centro de costo -- se excluyen de la comparacion
filtrando Pd_Centro_Costo <> '' (mismo criterio ya usado para las demas
reconciliaciones de este proyecto).

Resultado: **100.00%** (2,549/2,549 filas FOLIO x CENTRO, 270 folios,
enero-marzo 2026, empresa 0001) -- mejor resultado de cualquier origen
investigado en este proyecto hasta ahora. Los 270 folios activos (de 294
totales, 24 cancelados con Es_Cve_Estado='CA') tienen poliza ligada al
100% -- cero folios sin match.

Validacion adicional a grano MAS FINO (FOLIO, CENTRO, CONCEPTO), pregunta
de seguimiento: el 100% de arriba es a nivel centro -- no prueba que el
reparto ENTRE tipos de gasto dentro del mismo centro tambien sea correcto
(1,155 de 2,549 combinaciones FOLIO+CENTRO traen 2+ Tg_Cve_Tipo_Gasto
distintos, ej. Sueldos + Bono Productividad + Fondo de ahorro, todos en el
mismo centro -- un mal reparto entre ellos se cancelaria en la suma). No
existe FK real Tipo_Gasto->Cuenta_Contable para nomina (Tg_Cuenta_Contable
vacio en los 249 tipos de gasto, mismo hueco de ref/README.md) -- se unio
por texto normalizado (Tg_Descripcion = Cc_Descripcion exacto, ej. "BONO
POR PRODUCTIVIDAD" = "Bono Por Productividad"). Resultado: **100.00%
tambien** (6,591/6,591 filas FOLIO+CENTRO+CONCEPTO, cero conceptos
huerfanos en ningun lado) -- el reparto por concepto individual es exacto,
no solo la suma agregada por centro. Ver funcion `validar_grano_concepto()`.

Uso:
    python3 13_reconciliacion_nomina_ceco.py --fecha-ini 2026-01-01 --fecha-fin 2026-04-01
"""
import argparse
import sys

sys.path.insert(0, "/home/ealcocer/ehalso/trivasa-bi-core/connections")
from connection_205_trivasadb3 import engine  # default de exploracion

import pandas as pd
from sqlalchemy import text
from helpers_output import console, mostrar_tabla, resumen


GRC_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    grc.Cc_Cve_Centro_Costo AS CENTRO,
    SUM(grc.Grc_Importe) AS IMPORTE_GRC
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
JOIN Gasto_Registro_Control grc ON grc.Gr_Folio = grd.Gr_Folio AND grc.Grd_ID = grd.Grd_ID
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND gr.Gr_Tabla = 'GASTO_REGISTRO_NOMINA'
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, grc.Cc_Cve_Centro_Costo
"""

# Nota: NO se filtra por Pc_Tabla/Pd_Referencia de forma distinta a los
# origenes normales -- es el mismo join que v03_detalle_cuenta_centro_costo.sql,
# solo que aqui SI se incluye GASTO_REGISTRO_NOMINA (esa query lo excluye).
PD_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    pd.Pd_Centro_Costo AS CENTRO,
    SUM(CASE WHEN pd.Pd_Tipo = 1 THEN pd.Pd_Importe ELSE 0 END) AS CARGO,
    SUM(CASE WHEN pd.Pd_Tipo = 2 THEN pd.Pd_Importe ELSE 0 END) AS ABONO
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc
    ON plc.Pc_Tabla = 'GASTO_REGISTRO'
   AND plc.Pc_Documento = gr.Gr_Folio
   AND plc.Es_Cve_Estado <> 'CA'
JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio AND pl.Es_Cve_Estado <> 'CA'
JOIN Poliza_Detalle pd ON pd.Pl_Folio = plc.Pl_Folio AND pd.Pd_Referencia = gr.Gr_Folio
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND gr.Gr_Tabla = 'GASTO_REGISTRO_NOMINA'
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, pd.Pd_Centro_Costo
"""

# --- Validacion a grano mas fino: (FOLIO, CENTRO, CONCEPTO) ------------------
# No existe FK real Tipo_Gasto->Cuenta_Contable para nomina (Tg_Cuenta_Contable
# vacio en los 249 tipos, mismo hueco ya documentado en ref/README.md) -- se
# une por texto normalizado (Tg_Descripcion = Cc_Descripcion exacto). Fragil
# si el catalogo cambia de redaccion, pero es lo unico disponible y confirmado
# sin huerfanos en ninguno de los dos lados (ver salida de validar_grano_concepto).
GRC_CONCEPTO_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    UPPER(LTRIM(RTRIM(tg.Tg_Descripcion))) AS CONCEPTO,
    grc.Cc_Cve_Centro_Costo AS CENTRO,
    SUM(grc.Grc_Importe) AS IMPORTE_GRC
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Gasto_Registro_Documento grd ON gr.Gr_Folio = grd.Gr_Folio
JOIN Gasto_Registro_Control grc ON grc.Gr_Folio = grd.Gr_Folio AND grc.Grd_ID = grd.Grd_ID
JOIN Tipo_Gasto tg ON tg.Tg_Cve_Tipo_Gasto = grd.Tg_Cve_Tipo_Gasto
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND gr.Gr_Tabla = 'GASTO_REGISTRO_NOMINA'
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, tg.Tg_Descripcion, grc.Cc_Cve_Centro_Costo
"""

PD_CONCEPTO_SQL = """
SELECT
    gr.Gr_Folio AS FOLIO,
    UPPER(LTRIM(RTRIM(cc.Cc_Descripcion))) AS CONCEPTO,
    pd.Pd_Centro_Costo AS CENTRO,
    SUM(pd.Pd_Importe) AS CARGO
FROM Gasto_Registro gr
JOIN Sucursal s ON gr.Sc_Cve_Sucursal = s.Sc_Cve_Sucursal
JOIN Poliza_Control plc ON plc.Pc_Tabla = 'GASTO_REGISTRO' AND plc.Pc_Documento = gr.Gr_Folio AND plc.Es_Cve_Estado <> 'CA'
JOIN Poliza pl ON pl.Pl_Folio = plc.Pl_Folio AND pl.Es_Cve_Estado <> 'CA'
JOIN Poliza_Detalle pd ON pd.Pl_Folio = plc.Pl_Folio AND pd.Pd_Referencia = gr.Gr_Folio AND pd.Pd_Tipo = 1
JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable
WHERE gr.Gr_Fecha >= :fecha_ini AND gr.Gr_Fecha < :fecha_fin
  AND gr.Es_Cve_Estado <> 'CA'
  AND s.Em_Cve_Empresa = '0001'
  AND gr.Gr_Tabla = 'GASTO_REGISTRO_NOMINA'
  AND pd.Pd_Centro_Costo <> ''
GROUP BY gr.Sc_Cve_Sucursal, gr.Gr_Folio, cc.Cc_Descripcion, pd.Pd_Centro_Costo
"""


def validar_grano_concepto(fi, ff):
    """Repite la comparacion a nivel (FOLIO, CENTRO, CONCEPTO) -- responde si
    el reparto ENTRE tipos de gasto dentro del mismo centro tambien es exacto,
    no solo la suma agregada por centro (ver docstring del modulo)."""
    grc = pd.read_sql(text(GRC_CONCEPTO_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    grc["FOLIO"] = grc["FOLIO"].str.strip()
    grc["CENTRO"] = grc["CENTRO"].str.strip()

    pdd = pd.read_sql(text(PD_CONCEPTO_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    pdd["FOLIO"] = pdd["FOLIO"].str.strip()
    pdd["CENTRO"] = pdd["CENTRO"].str.strip()

    comp = grc.merge(pdd, on=["FOLIO", "CENTRO", "CONCEPTO"], how="outer")
    comp["IMPORTE_GRC"] = comp["IMPORTE_GRC"].fillna(0)
    comp["CARGO"] = comp["CARGO"].fillna(0)
    comp["DIFERENCIA"] = (comp.IMPORTE_GRC - comp.CARGO).abs()
    comp["CUADRA"] = comp.DIFERENCIA < 1

    n, c = len(comp), int(comp.CUADRA.sum())
    solo_grc = set(grc.CONCEPTO) - set(pdd.CONCEPTO)
    solo_pd = set(pdd.CONCEPTO) - set(grc.CONCEPTO)
    console.print(
        f"\n[bold]Grano fino (FOLIO, CENTRO, CONCEPTO via texto):[/bold] "
        f"{n} filas, {c} cuadran ({100*c/n:.2f}%) | "
        f"conceptos huerfanos GRC={len(solo_grc)} PD={len(solo_pd)}"
    )
    mal = comp[~comp.CUADRA]
    if len(mal):
        mostrar_tabla(mal.sort_values("DIFERENCIA", ascending=False), "Grano fino -- fuera de cuadre", max_filas=20)
    return comp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    console.print("[bold]GASTO_REGISTRO_NOMINA -- Grc_Importe vs Poliza_Detalle a nivel (FOLIO, CENTRO)[/bold]")

    grc = pd.read_sql(text(GRC_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    grc["FOLIO"] = grc["FOLIO"].str.strip()
    grc["CENTRO"] = grc["CENTRO"].str.strip()

    pd_df = pd.read_sql(text(PD_SQL), engine, params={"fecha_ini": fi, "fecha_fin": ff})
    pd_df["FOLIO"] = pd_df["FOLIO"].str.strip()
    pd_df["CENTRO"] = pd_df["CENTRO"].str.strip()

    folios_grc = set(grc.FOLIO)
    folios_pd = set(pd_df.FOLIO)
    sin_poliza = folios_grc - folios_pd
    console.print(f"Folios GASTO_REGISTRO_NOMINA: {len(folios_grc)}  |  con poliza ligada: {len(folios_pd)}  |  SIN poliza: {len(sin_poliza)}")

    # Lineas sin centro de costo = reclasificaciones de pasivo dentro de la
    # misma poliza (ISR, IMSS, sueldos/fondo de ahorro por pagar...) -- no
    # son gasto por centro, se excluyen de la comparacion.
    pd_con_centro = pd_df[pd_df.CENTRO != ""].groupby(["FOLIO", "CENTRO"], as_index=False)["CARGO"].sum()

    comp = grc.merge(pd_con_centro, on=["FOLIO", "CENTRO"], how="outer")
    comp["IMPORTE_GRC"] = comp["IMPORTE_GRC"].fillna(0)
    comp["CARGO"] = comp["CARGO"].fillna(0)
    comp["DIFERENCIA"] = (comp.IMPORTE_GRC - comp.CARGO).abs()
    comp["CUADRA"] = comp.DIFERENCIA < 1

    n, c = len(comp), int(comp.CUADRA.sum())
    resumen(filas=n, cuadran=c, pct=f"{100*c/n:.2f}%", folios=len(folios_grc), folios_sin_poliza=len(sin_poliza))

    mal = comp[~comp.CUADRA]
    console.print(f"\n[bold red]Filas que NO cuadran:[/bold red] {len(mal)} ({mal.FOLIO.nunique()} folios)")
    if len(mal):
        mostrar_tabla(mal.sort_values("DIFERENCIA", ascending=False), "Fuera de cuadre", max_filas=20)

    comp.to_csv(f"13_reconciliacion_nomina_ceco_{fi}_{ff}.csv", index=False)
    console.print(f"\n[green]Guardado: 13_reconciliacion_nomina_ceco_{fi}_{ff}.csv[/green]")

    validar_grano_concepto(fi, ff)


if __name__ == "__main__":
    main()
