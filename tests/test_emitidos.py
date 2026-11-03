import unittest
from unittest import mock

import pandas as pd

from conciliacion import cobranza, documentos, servidor, traslados, vista
from conciliacion.documentos import TIPOS, TIPOS_CLIENTE, _plantillas
from conciliacion.reporte import construir_emitidos, construir_traslados
from conciliacion.sat import EMITIDO, RECIBIDO, TRASLADO, sql_cfdi


PER = {"ini": ["2026-02-01"], "fin": ["2026-02-28"]}


class SqlCfdi(unittest.TestCase):
    def test_recibidos_usa_emisor(self):
        q = sql_cfdi(RECIBIDO)
        self.assertIn("c.rfc_emisor AS rfc_emisor", q)
        self.assertIn("c.tipo = 'RECIBIDO'", q)

    def test_emitidos_usa_receptor(self):
        q = sql_cfdi(EMITIDO)
        self.assertIn("c.rfc_receptor AS rfc_emisor", q)
        self.assertIn("c.nombre_receptor AS nombre_emisor", q)
        self.assertNotIn("RECIBIDO", q)

    def test_solo_sat_emitidos_filtra_ingreso_egreso_pago_y_autoemitidos(self):
        q = sql_cfdi(EMITIDO, solo_sat=True)
        self.assertIn("tipo_comprobante IN ('I','E','P')", q)
        self.assertIn("c.rfc_emisor <> c.rfc_receptor", q)
        self.assertIn(":fi", q)


    def test_monto_del_pago_solo_en_emitidos(self):
        self.assertIn("pagos_monto_total", sql_cfdi(EMITIDO))
        self.assertNotIn("pagos_monto_total", sql_cfdi(RECIBIDO))
        self.assertIn("c.total AS total", sql_cfdi(RECIBIDO))


class Plantillas(unittest.TestCase):
    def test_tipos_cliente(self):
        self.assertEqual([t.tipo for t in TIPOS_CLIENTE], ["Venta", "NC cliente"])
        self.assertEqual([t.signo for t in TIPOS_CLIENTE], [1, -1])

    def test_venta_liga_poliza_por_folio_o_serie(self):
        f = _plantillas(TIPOS_CLIENTE[0])
        self.assertIn("d.SF", f["pol_ref"])
        self.assertIn("c.Fc_Serie", f["serie"])
        self.assertEqual((f["tercero"], f["exento"], f["cero"]), ("Cl_Cve_Cliente", "0008", "0007"))
        self.assertEqual(f["pc"], "VENTA")
        self.assertIn("'1120'", f["excl_pol"])

    def test_recibidos_no_cambian(self):
        f = _plantillas(next(t for t in TIPOS if t.tipo == "Compra"))
        self.assertEqual(f["pol_ref"], "pd.Pd_Referencia=d.FOLIO")
        self.assertEqual((f["tercero"], f["exento"]), ("Pv_Cve_Proveedor", "0004"))
        self.assertEqual(f["serie"], "CAST(NULL AS varchar(30))")


class Vista(unittest.TestCase):
    def d(self):
        return pd.DataFrame({"Tipo": ["NC cliente", "Venta"], "FOLIO": ["N1", "V1"], "FECHA": ["2026-02-01"] * 2,
                             "NOMBRE_PROVEEDOR": ["Cli", "Cli"], "CARGO": [0.0, 0.0], "ABONO": [0.0, 0.0]})

    def test_etiquetas_de_cliente(self):
        etq = {c["k"]: c["l"] for c in vista.columnas(self.d(), emitidos=True)}
        self.assertEqual(etq["NOMBRE_PROVEEDOR"], "Cliente")
        etq = {c["k"]: c["l"] for c in vista.columnas(self.d())}
        self.assertNotEqual(etq["NOMBRE_PROVEEDOR"], "Cliente")

    def test_orden_venta_antes_que_nc(self):
        r = vista.a_datos(self.d(), "layout", False, emitidos=True)
        ks = [c["k"] for c in r["cols"]]
        self.assertEqual([x[ks.index("Tipo")] for x in r["rows"]], ["Venta", "NC cliente"])


class Cobranza(unittest.TestCase):
    def cab(self):
        base = dict(FECHA="2026-02-03", CLAVE_PROVEEDOR="1", FOLIO_PAGO="R1", SALDO_ANTERIOR=100.0, SALDO_INSOLUTO=0.0, IMPORTE_PAGADO=100.0,
                    SUBTOTAL_NETO=86.21, IMP_0006=13.79, TOTAL_SQL=100.0, PARCIALIDAD=1.0)
        return pd.DataFrame([
            {**base, "FOLIO": "A", "PP_ID": "0001", "FACTURA_PAGADA": "F1", "UUID_FACTURA_PAGADA": "U1"},
            {**base, "FOLIO": "B", "PP_ID": "0001", "FACTURA_PAGADA": "F2", "UUID_FACTURA_PAGADA": "U2"},
            {**base, "FOLIO": "B", "PP_ID": "0002", "FACTURA_PAGADA": "F3", "UUID_FACTURA_PAGADA": "U3"},
        ])

    def test_un_documento_por_folio_suma_importes(self):
        d = cobranza._documentos(self.cab()).set_index("FOLIO")
        self.assertEqual(len(d), 2)
        self.assertEqual(d.loc["B", "TOTAL_SQL"], 200.0)
        self.assertEqual(d.loc["B", "FACTURA_PAGADA"], "VARIOS")
        self.assertTrue(pd.isna(d.loc["B", "SALDO_INSOLUTO"]))
        self.assertEqual((d.loc["A", "FACTURA_PAGADA"], d.loc["A", "PARCIALIDAD"]), ("F1", "1"))

    def test_poliza_recibo_compartido(self):
        def fila(folio, tot, pd_id, cargo, abono):
            return dict(FOLIO=folio, PDOC="P" + folio, RECIBO="R1", TOTAL_COBRO=tot, POLIZA="L1", PD_ID=pd_id, CARGO=cargo, ABONO=abono)
        filas = [fila(f, t, i, c, a) for f, t in (("A", 100.0), ("B", 50.0)) for i, c, a in
                 (("01", 150.0, 0.0), ("02", 0.0, 100.01), ("03", 0.0, 50.0), ("04", 0.0, 9.0))]
        r = cobranza._lineas_poliza(pd.DataFrame(filas))
        self.assertEqual(len(r), 4)
        por = r.groupby("FOLIO")[["CARGO", "ABONO"]].sum()
        self.assertEqual(por.loc["A"].tolist(), [150.0, 109.01])
        self.assertEqual(por.loc["B"].tolist(), [0.0, 50.0])

    def test_orden_y_tipo(self):
        self.assertEqual(cobranza.TIPO, "Cobranza")
        self.assertLess(vista.ORDEN_TIPO["NC cliente"], vista.ORDEN_TIPO["Cobranza"])
        self.assertIn("pp.Es_Cve_Estado<>'CA'", cobranza.sql.COBRANZA_SETUP)


class Servidor(unittest.TestCase):
    def test_sentido_por_omision_recibidos(self):
        self.assertEqual(servidor._parametros(PER)[4], "recibidos")

    def test_sentido_invalido(self):
        with self.assertRaises(ValueError):
            servidor._parametros({**PER, "sentido": ["otro"]})

    def test_emitidos_requiere_mssql(self):
        with mock.patch.object(servidor, "BACKEND", "postgres"), self.assertRaises(ValueError):
            servidor._parametros({**PER, "sentido": ["emitidos"]})
        with mock.patch.object(servidor, "BACKEND", "mssql"):
            self.assertEqual(servidor._parametros({**PER, "sentido": ["emitidos"]})[4], "emitidos")


class Reporte(unittest.TestCase):
    def test_emitidos_rechaza_postgres(self):
        eng = mock.Mock()
        eng.dialect.name = "postgresql"
        with self.assertRaises(RuntimeError):
            construir_emitidos(eng, "2026-02-01", "2026-03-01")

    def test_traslados_rechaza_postgres(self):
        eng = mock.Mock()
        eng.dialect.name = "postgresql"
        with self.assertRaises(RuntimeError):
            construir_traslados(eng, "2026-02-01", "2026-03-01")


class Traslados(unittest.TestCase):
    def test_solo_sat_son_los_tipo_t_autoemitidos(self):
        q = sql_cfdi(TRASLADO, solo_sat=True)
        self.assertIn("c.tipo_comprobante = 'T'", q)
        self.assertIn("c.rfc_emisor = c.rfc_receptor", q)
        self.assertIn("k.uuid IS NULL", q)

    def test_cruce_por_uuid_sin_filtrar_tipo(self):
        q = sql_cfdi(TRASLADO)
        self.assertIn("upper(c.uuid) = ANY(:uuids)", q)
        self.assertNotIn("tipo_comprobante", q.split("WHERE")[1])

    def test_sql_una_fila_por_folio_con_cfdi_vigente_o_el_mas_reciente(self):
        self.assertIn("GROUP BY t.Tr_Folio", traslados.sql.TRASLADO_SETUP)
        self.assertIn("LEFT JOIN", traslados.sql.TRASLADO_SQL)
        self.assertIn("Cd_Tabla='TRASLADO'", traslados.sql.TRASLADO_SQL)
        self.assertIn("Ccp_Tabla='TRASLADO'", traslados.sql.TRASLADO_SQL)

    def test_conciliar_estatus_solo_donde_hay_uuid_en_ambos(self):
        d = pd.DataFrame({"CONC_EXISTE_MPRO": ["Sí", "Sí", "Sí", "No"], "CONC_EXISTE_SAT": ["Sí", "Sí", "No", "Sí"],
                          "XML_ESTATUS": ["Activo", "Activo", "Activo", None], "SAT_ESTATUS": ["Activo", "Cancelado", None, "Activo"]})
        self.assertEqual(traslados.conciliar_estatus(d).CONC_ESTATUS.tolist(), ["Sí", "No", "", ""])

    def test_sentido_traslados(self):
        with mock.patch.object(servidor, "BACKEND", "postgres"), self.assertRaises(ValueError):
            servidor._parametros({**PER, "sentido": ["traslados"]})
        with mock.patch.object(servidor, "BACKEND", "mssql"):
            self.assertEqual(servidor._parametros({**PER, "sentido": ["traslados"]})[4], "traslados")

    def test_vista_sin_poliza_ni_importes(self):
        d = pd.DataFrame({"Tipo": ["Traslado", "Traslado"], "FOLIO": ["T1", "T2"], "FECHA": ["2026-02-01"] * 2,
                          "ORIGEN": ["REMISION", "PEDIDO"], "UUID": ["A", None], "COSTO": [10.0, 5.5]})
        r = vista.a_datos(d, "layout", True, traslados=True)
        ks = [c["k"] for c in r["cols"]]
        self.assertEqual(ks, ["Tipo", "ORIGEN", "FOLIO", "FECHA", "COSTO", "UUID"])
        self.assertFalse(r["agrupar"])
        self.assertEqual(len(r["rows"]), 2)


if __name__ == "__main__":
    unittest.main()


class Multiempresa(unittest.TestCase):
    """Comprobante_Digital es multiempresa y no tiene columna de empresa: se acota por el prefijo del folio -> Sucursal."""

    def test_existencia_en_mpro_acotada_a_la_empresa(self):
        from conciliacion import sat
        for q in (sat.SQL_EN_MPRO, sat.SQL_EN_MPRO_PG):
            self.assertIn(":emp", q)
            self.assertRegex(q.lower(), r"join sucursal s on s\.sc_cve_sucursal = '00' (\+|\|\|) left\(cd\.cd_documento, 2\)")

    def test_solo_sat_pasa_la_empresa(self):
        from conciliacion import sat
        from conciliacion.config import EMPRESA
        llamadas = []

        class Con:
            def __enter__(s): return s
            def __exit__(s, *a): return False

        class Eng:
            def __init__(s, nombre): s.dialect = mock.Mock(name=nombre); s.dialect.name = nombre
            def connect(s): return Con()

        def lee(q, con, params=None):
            llamadas.append(params)
            if "fi" in params:
                return pd.DataFrame({"uuid": ["A" * 36], "serie": [""], "folio": [""], "tipo_comprobante": ["I"], "fecha": [pd.Timestamp("2026-02-02")],
                                     "rfc_emisor": ["X"], "nombre_emisor": ["X"], "total": [1.0], "cancelado": [False],
                                     "concepto": [None], "uso_cfdi": [None], "complemento": [None]})
            return pd.DataFrame({"uuid": []})

        with mock.patch.object(sat.pd, "read_sql", lee):
            sat.agregar_solo_sat(pd.DataFrame({"Tipo": []}), Eng("postgresql"), Eng("mssql"), "2026-02-01", "2026-03-01")
        self.assertEqual(llamadas[-1]["emp"], EMPRESA)

    def test_resumen_mpro_acotado_a_la_empresa(self):
        from conciliacion import resumen
        self.assertIn("Em_Cve_Empresa = :emp", resumen.SQL_MPRO)
        self.assertIn("cd.Es_Cve_Estado", resumen.SQL_MPRO)
