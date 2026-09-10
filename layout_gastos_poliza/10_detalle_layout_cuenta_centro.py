"""
Detalle del layout de gastos (columnas 57-60: Cuenta Registro, Nombre
Cuenta Registro, Cargo, Abono) -- N filas por folio, grano cuenta
contable x centro de costo. Directo de Poliza_Detalle, sin pasar por
Grc_Importe/Gasto_Registro_Control -- ese lado (scripts 03-09) es
diagnostico de calidad de dato, no la fuente del layout.

Grano decidido por el proyecto historico (layout-gastos-pasos/docs/
cierre_1_56_enero2026.md, seccion "Decision de diseno: Cargo/Abono
(57-60) queda aparte"): cuenta x centro, NUNCA documento -- se probo
reducir mas y quedaban folios de deprecacion/seguros/IMSS-Infonavit con
45-85 lineas legitimas (cada combinacion sucursal x tipo de activo es
una cuenta contable real, no artefacto). No existe un nivel de
agregacion mas fino que colapse a 1 fila/folio sin perder informacion
contable real.

Query: queries/v03_detalle_cuenta_centro_costo.sql -- la misma que ya
usan los scripts 03/06/07/09 para el lado de poliza, la misma que se
sirve en FlexMonster en el proyecto historico. Ya validada 100% (ref/
reconciliacion_cargo_abono_ceco.py). Este script es solo el "recorte"
explicito de esas columnas como el detalle final del layout, para unir
con el maestro (1 fila/folio) por FOLIO -- mismo patron de dos archivos
ligados que ya usaba layout-gastos-pasos.

Uso:
    python3 10_detalle_layout_cuenta_centro.py --fecha-ini 2026-01-01 --fecha-fin 2026-02-01
"""
import argparse
import sys

sys.path.insert(0, "/home/esteban/trivasa/connections")
from connection_205_trivasadb3 import engine  # default de exploracion

import pandas as pd
from sqlalchemy import text
from helpers_output import console, mostrar_tabla, resumen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fecha-ini", required=True)
    ap.add_argument("--fecha-fin", required=True)
    args = ap.parse_args()
    fi, ff = args.fecha_ini, args.fecha_fin

    with open("queries/v03_detalle_cuenta_centro_costo.sql") as f:
        sql = f.read().replace(":fecha_ini", f"'{fi}'").replace(":fecha_fin", f"'{ff}'")

    detalle = pd.read_sql(text(sql), engine)
    detalle["FOLIO"] = detalle["FOLIO"].str.strip()

    resumen(
        filas=len(detalle),
        folios=detalle.FOLIO.nunique(),
        cargo_total=f"{detalle.CARGO.sum():,.2f}",
        abono_total=f"{detalle.ABONO.sum():,.2f}",
    )
    mostrar_tabla(detalle.head(20), "Detalle layout 57-60 (muestra)")

    out = f"10_detalle_layout_cuenta_centro_{fi}_{ff}.csv"
    detalle.to_csv(out, index=False)
    console.print(f"\n[green]Guardado: {out}[/green]")
    console.print(
        "[dim]Columnas: FOLIO, CUENTA, CUENTA_DESCRIPCION, CENTRO_COSTO, "
        "CENTRO_COSTO_DESCRIPCION, CARGO, ABONO -- unir con el maestro (1 "
        "fila/folio) por FOLIO. N filas por folio, no colapsar mas.[/dim]"
    )


if __name__ == "__main__":
    main()
