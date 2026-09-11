"""Extracción de líneas de `Poliza_Detalle` en los tres granos que hacen
falta para auditar la contabilización de un CFDI.

Por qué tres granos y no uno (confirmado en vivo 2026-09-11, ver
`docs/hallazgos_cuentas.md` punto 1): dentro de una misma póliza, unas
líneas llevan `Pd_Referencia` = folio del documento y otras no. El cargo a
inventario/gasto SÍ lo lleva; el cargo a IVA acreditable y el abono a
proveedores NO — llevan la fecha del día, la referencia externa del
proveedor, o nada. Por eso:

  · GRANO DOCUMENTO  (`lineas_por_documento`)
    Las líneas con `Pd_Referencia = Pc_Documento`. Es lo que ve
    `baseline_universal.py` y lo único atribuible a un CFDI concreto.
    Sirve para: ¿en qué cuenta aterrizó el gasto de este CFDI?

  · GRANO PÓLIZA     (`lineas_de_polizas`)
    TODAS las líneas de las pólizas tocadas, con referencia o sin ella.
    Sirve para: ¿el IVA/las retenciones/el pasivo de este lote de CFDI
    están completos? Como la póliza consolida el día, el cuadre aquí es
    por póliza, no por documento.

  · GRANO AUXILIAR   (`auxiliar_cuenta`)
    Todas las líneas de un rango de fechas que tocan ciertas cuentas,
    entren o no por `Poliza_Control`. Sirve para el auxiliar contable
    clásico y para cruzarlo contra el universo de CFDI del periodo.

**El auxiliar arranca de `Poliza` + `Poliza_Detalle`, nunca de
`Poliza_Control`**: hay ~3,494 pólizas manuales (`Pl_Configuracion` vacío,
0 filas en `Poliza_Control`) que cualquier consulta anclada en
`Poliza_Control` pierde en silencio — ver `trivasa-context`,
`docs/proyectos/poliza-explor/`.

Rendimiento: las consultas por lote son independientes entre sí, así que
van en paralelo (`_run_parallel`). Medido en vivo contra `mssql_205`
(2026-09-11, pendiente #8 del PROGRESS): secuencial 1.83 q/s, 4 hilos
10.0 q/s, 8 hilos 13.7 q/s, 12 hilos 15.0 q/s — la latencia por consulta
apenas sube (0.55s -> 0.57s), así que el cuello era espera de red, no la
base. Se usa 8 por default: ya da 7.5x y deja margen a la instancia.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from bridge_client import run_query, rows_as_dicts, sql_quote
from config import MPRO_TARGET

BATCH_SIZE = 150
WORKERS = 8

# Cuentas de orden: raíz de 5 dígitos (10100..10600). Ver cuentas_lib.
FILTRO_ORDEN = "AND pd.Cc_Cve_Cuenta_Contable NOT LIKE '10[1-6]00%' "

LINEA_COLS = ["origen", "documento", "poliza", "fecha_poliza", "configuracion",
              "config_descripcion", "comentario_poliza", "pd_id", "cuenta",
              "cuenta_descripcion", "tipo", "importe", "referencia",
              "centro_costo", "centro_costo_descripcion", "concepto"]

_SELECT_LINEA = (
    "SELECT pc.Pc_Tabla AS origen, pc.Pc_Documento AS documento, p.Pl_Folio AS poliza, "
    "p.Pl_Fecha AS fecha_poliza, p.Pl_Configuracion AS configuracion, "
    "pcf.Pc_Descripcion AS config_descripcion, p.Pl_Comentario AS comentario_poliza, "
    "pd.Pd_ID AS pd_id, pd.Cc_Cve_Cuenta_Contable AS cuenta, cc.Cc_Descripcion AS cuenta_descripcion, "
    "pd.Pd_Tipo AS pd_tipo, pd.Pd_Importe AS importe, pd.Pd_Referencia AS referencia, "
    "pd.Pd_Centro_Costo AS centro_costo, cco.Cc_Descripcion AS centro_costo_descripcion, "
    "pd.Pd_Concepto AS concepto "
)
_JOINS_CATALOGO = (
    "LEFT JOIN Poliza_Configuracion pcf ON pcf.Pc_Cve_Poliza_Configuracion = p.Pl_Configuracion "
    "LEFT JOIN Cuenta_Contable cc ON cc.Cc_Cve_Cuenta_Contable = pd.Cc_Cve_Cuenta_Contable "
    "LEFT JOIN Centro_Costo cco ON cco.Cc_Cve_Centro_Costo = pd.Pd_Centro_Costo "
)


def _run_parallel(sqls: list[str], target: str = MPRO_TARGET,
                   workers: int = WORKERS) -> list[dict]:
    """Ejecuta consultas independientes en paralelo y concatena las filas.
    El orden del resultado no está garantizado — los llamadores agregan."""
    if not sqls:
        return []
    if len(sqls) == 1:
        return rows_as_dicts(run_query(target, sqls[0]))
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(workers, len(sqls))) as ex:
        for res in ex.map(lambda s: rows_as_dicts(run_query(target, s)), sqls):
            out.extend(res)
    return out


def _chunks(valores: list[str], size: int = BATCH_SIZE):
    vals = sorted({v for v in valores if v is not None and str(v).strip()})
    for i in range(0, len(vals), size):
        yield vals[i:i + size]


def _normalizar(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=LINEA_COLS)
    df["importe"] = pd.to_numeric(df["importe"], errors="coerce").fillna(0.0)
    df["tipo"] = df["pd_tipo"].map({1: "Cargo", 2: "Abono"}).fillna("?")
    for c in ("cuenta", "cuenta_descripcion", "referencia", "centro_costo",
              "centro_costo_descripcion", "concepto", "config_descripcion",
              "comentario_poliza", "origen", "documento", "configuracion"):
        if c in df.columns:
            df[c] = df[c].astype("string").fillna("").str.strip()
    df["fecha_poliza"] = pd.to_datetime(df["fecha_poliza"], errors="coerce")
    return df[LINEA_COLS]


def lineas_por_documento(origen: str, documentos: list[str],
                          incluir_orden: bool = False) -> pd.DataFrame:
    """GRANO DOCUMENTO — líneas cuya `Pd_Referencia` es el folio del
    documento, dentro de pólizas activas. Mismo universo que suma
    `extract_poliza_por_origen`, sin el `GROUP BY`, y con cuenta contable
    y centro de costo resueltos contra el catálogo."""
    sqls = []
    for chunk in _chunks(documentos):
        in_list = ", ".join(sql_quote(d) for d in chunk)
        sqls.append(
            _SELECT_LINEA +
            "FROM Poliza_Control pc "
            "JOIN Poliza p ON p.Pl_Folio = pc.Pl_Folio "
            "JOIN Poliza_Detalle pd ON pd.Pl_Folio = pc.Pl_Folio AND pd.Pd_Referencia = pc.Pc_Documento "
            + _JOINS_CATALOGO +
            f"WHERE UPPER(pc.Pc_Tabla) = UPPER({sql_quote(origen)}) "
            "AND p.Es_Cve_Estado <> 'CA' "
            "AND (pcf.Pc_Descripcion IS NULL OR UPPER(pcf.Pc_Descripcion) NOT LIKE '%CUENTAS DE ORDEN%') "
            + ("" if incluir_orden else FILTRO_ORDEN) +
            f"AND pc.Pc_Documento IN ({in_list})"
        )
    return _normalizar(_run_parallel(sqls))


def polizas_de_documentos(origen: str, documentos: list[str]) -> pd.DataFrame:
    """Mapa (documento -> póliza) para un origen. Una fila por par; un
    documento puede caer en más de una póliza y una póliza agrupa muchos
    documentos (el patrón de consolidación diaria)."""
    sqls = []
    for chunk in _chunks(documentos):
        in_list = ", ".join(sql_quote(d) for d in chunk)
        sqls.append(
            "SELECT pc.Pc_Tabla AS origen, pc.Pc_Documento AS documento, p.Pl_Folio AS poliza, "
            "p.Pl_Fecha AS fecha_poliza, p.Pl_Configuracion AS configuracion, "
            "pcf.Pc_Descripcion AS config_descripcion "
            "FROM Poliza_Control pc "
            "JOIN Poliza p ON p.Pl_Folio = pc.Pl_Folio "
            "LEFT JOIN Poliza_Configuracion pcf ON pcf.Pc_Cve_Poliza_Configuracion = p.Pl_Configuracion "
            f"WHERE UPPER(pc.Pc_Tabla) = UPPER({sql_quote(origen)}) "
            "AND p.Es_Cve_Estado <> 'CA' "
            "AND (pcf.Pc_Descripcion IS NULL OR UPPER(pcf.Pc_Descripcion) NOT LIKE '%CUENTAS DE ORDEN%') "
            f"AND pc.Pc_Documento IN ({in_list})"
        )
    df = pd.DataFrame(_run_parallel(sqls))
    if df.empty:
        return pd.DataFrame(columns=["origen", "documento", "poliza", "fecha_poliza",
                                      "configuracion", "config_descripcion"])
    df["fecha_poliza"] = pd.to_datetime(df["fecha_poliza"], errors="coerce")
    for c in ("origen", "documento", "poliza", "configuracion", "config_descripcion"):
        df[c] = df[c].astype("string").fillna("").str.strip()
    return df.drop_duplicates()


def lineas_de_polizas(polizas: list[str], incluir_orden: bool = False) -> pd.DataFrame:
    """GRANO PÓLIZA — TODAS las líneas de las pólizas dadas, lleven o no
    `Pd_Referencia` al documento. Aquí sí aparecen el IVA acreditable, las
    retenciones y el abono a proveedores, que el grano documento no ve.

    `origen`/`documento` salen vacíos: una póliza consolida varios
    documentos, así que la línea no pertenece a uno solo. Usar
    `polizas_de_documentos()` si hace falta saber qué documentos ampara."""
    sqls = []
    for chunk in _chunks(polizas):
        in_list = ", ".join(sql_quote(f) for f in chunk)
        sqls.append(
            "SELECT '' AS origen, '' AS documento, p.Pl_Folio AS poliza, "
            "p.Pl_Fecha AS fecha_poliza, p.Pl_Configuracion AS configuracion, "
            "pcf.Pc_Descripcion AS config_descripcion, p.Pl_Comentario AS comentario_poliza, "
            "pd.Pd_ID AS pd_id, pd.Cc_Cve_Cuenta_Contable AS cuenta, cc.Cc_Descripcion AS cuenta_descripcion, "
            "pd.Pd_Tipo AS pd_tipo, pd.Pd_Importe AS importe, pd.Pd_Referencia AS referencia, "
            "pd.Pd_Centro_Costo AS centro_costo, cco.Cc_Descripcion AS centro_costo_descripcion, "
            "pd.Pd_Concepto AS concepto "
            "FROM Poliza p "
            "JOIN Poliza_Detalle pd ON pd.Pl_Folio = p.Pl_Folio "
            + _JOINS_CATALOGO +
            "WHERE p.Es_Cve_Estado <> 'CA' "
            + ("" if incluir_orden else FILTRO_ORDEN) +
            f"AND p.Pl_Folio IN ({in_list})"
        )
    return _normalizar(_run_parallel(sqls))


def auxiliar_cuenta(fecha_ini: str, fecha_fin: str,
                     cuentas_like: list[str] | None = None,
                     incluir_orden: bool = False,
                     empresa: str | None = None) -> pd.DataFrame:
    """GRANO AUXILIAR — todas las líneas de póliza del rango de fechas
    (`Pl_Fecha >= fecha_ini AND < fecha_fin`, fin EXCLUSIVO) que tocan las
    cuentas pedidas. `cuentas_like` son prefijos: `["1170", "2150.005"]`
    trae toda esa rama. Sin `cuentas_like` trae el auxiliar completo
    (cuidado: `Poliza_Detalle` tiene 14.4M filas en total).

    Arranca de `Poliza`, no de `Poliza_Control` — así entran también las
    pólizas manuales, que no tienen fila de control.

    Se pagina por DÍA para poder paralelizar y no pedir un rango entero en
    una sola consulta.
    """
    filtro_cuentas = ""
    if cuentas_like:
        ors = " OR ".join(f"pd.Cc_Cve_Cuenta_Contable LIKE {sql_quote(c + '%')}"
                          for c in cuentas_like)
        filtro_cuentas = f"AND ({ors}) "
    filtro_empresa = f"AND p.Em_Cve_Empresa = {sql_quote(empresa)} " if empresa else ""

    dias = pd.date_range(fecha_ini, fecha_fin, freq="D", inclusive="left")
    sqls = []
    for dia in dias:
        d0 = dia.strftime("%Y%m%d")
        d1 = (dia + pd.Timedelta(days=1)).strftime("%Y%m%d")
        sqls.append(
            "SELECT '' AS origen, '' AS documento, p.Pl_Folio AS poliza, "
            "p.Pl_Fecha AS fecha_poliza, p.Pl_Configuracion AS configuracion, "
            "pcf.Pc_Descripcion AS config_descripcion, p.Pl_Comentario AS comentario_poliza, "
            "pd.Pd_ID AS pd_id, pd.Cc_Cve_Cuenta_Contable AS cuenta, cc.Cc_Descripcion AS cuenta_descripcion, "
            "pd.Pd_Tipo AS pd_tipo, pd.Pd_Importe AS importe, pd.Pd_Referencia AS referencia, "
            "pd.Pd_Centro_Costo AS centro_costo, cco.Cc_Descripcion AS centro_costo_descripcion, "
            "pd.Pd_Concepto AS concepto "
            "FROM Poliza p "
            "JOIN Poliza_Detalle pd ON pd.Pl_Folio = p.Pl_Folio "
            + _JOINS_CATALOGO +
            "WHERE p.Es_Cve_Estado <> 'CA' "
            # Fecha en formato YYYYMMDD sin separadores: .207 corre con
            # DATEFORMAT dmy y '2026-08-01' filtraría por el mes equivocado
            # SIN lanzar error (gotcha documentado en trivasa-context).
            f"AND p.Pl_Fecha >= '{d0}' AND p.Pl_Fecha < '{d1}' "
            + filtro_empresa + filtro_cuentas
            + ("" if incluir_orden else FILTRO_ORDEN)
        )
    return _normalizar(_run_parallel(sqls))


def lineas_por_uuid(uuids: list[str], incluir_orden: bool = False) -> pd.DataFrame:
    """Líneas de póliza ligadas a un UUID por el ANEXO SAT
    (`Poliza_Detalle_Comprobante`: `Pdc_UUID` + `Pl_Folio` + `Pd_ID`), que
    es una ruta independiente de `Comprobante_Digital` -> `Poliza_Control`.

    Ojo (documentado en `src/extract_poliza.py`): el anexo NO garantiza que
    ambos lados de la partida doble queden etiquetados con el mismo UUID, y
    su cobertura es parcial (~34% de las líneas). Sirve como segunda opinión
    y para encontrar líneas que la ruta por documento no alcanza — no como
    fuente única.
    """
    sqls = []
    for chunk in _chunks([u.upper() for u in uuids if u], size=200):
        in_list = ", ".join(sql_quote(u) for u in chunk)
        sqls.append(
            "SELECT '' AS origen, pdc.Pdc_UUID AS documento, p.Pl_Folio AS poliza, "
            "p.Pl_Fecha AS fecha_poliza, p.Pl_Configuracion AS configuracion, "
            "pcf.Pc_Descripcion AS config_descripcion, p.Pl_Comentario AS comentario_poliza, "
            "pd.Pd_ID AS pd_id, pd.Cc_Cve_Cuenta_Contable AS cuenta, cc.Cc_Descripcion AS cuenta_descripcion, "
            "pd.Pd_Tipo AS pd_tipo, pd.Pd_Importe AS importe, pd.Pd_Referencia AS referencia, "
            "pd.Pd_Centro_Costo AS centro_costo, cco.Cc_Descripcion AS centro_costo_descripcion, "
            "pd.Pd_Concepto AS concepto "
            "FROM Poliza_Detalle_Comprobante pdc "
            "JOIN Poliza p ON p.Pl_Folio = pdc.Pl_Folio "
            "JOIN Poliza_Detalle pd ON pd.Pl_Folio = pdc.Pl_Folio AND pd.Pd_ID = pdc.Pd_ID "
            + _JOINS_CATALOGO +
            "WHERE p.Es_Cve_Estado <> 'CA' "
            + ("" if incluir_orden else FILTRO_ORDEN) +
            f"AND UPPER(pdc.Pdc_UUID) IN ({in_list})"
        )
    df = _normalizar(_run_parallel(sqls))
    return df.rename(columns={"documento": "uuid"})
