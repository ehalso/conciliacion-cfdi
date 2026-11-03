import unittest
from unittest import mock

import pandas as pd

from conciliacion import documentos, servidor, vista
from conciliacion.documentos import TIPOS, TIPOS_CLIENTE, _plantillas
from conciliacion.reporte import construir_emitidos
from conciliacion.sat import EMITIDO, RECIBIDO, sql_cfdi


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

    def test_solo_sat_emitidos_filtra_ingreso_egreso_y_autoemitidos(self):
        q = sql_cfdi(EMITIDO, solo_sat=True)
        self.assertIn("tipo_comprobante IN ('I','E')", q)
        self.assertIn("c.rfc_emisor <> c.rfc_receptor", q)
        self.assertIn(":fi", q)


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


class Servidor(unittest.TestCase):
    def test_sentido_por_omision_recibidos(self):
        self.assertFalse(servidor._parametros(PER)[4])

    def test_sentido_invalido(self):
        with self.assertRaises(ValueError):
            servidor._parametros({**PER, "sentido": ["otro"]})

    def test_emitidos_requiere_mssql(self):
        with mock.patch.object(servidor, "BACKEND", "postgres"), self.assertRaises(ValueError):
            servidor._parametros({**PER, "sentido": ["emitidos"]})
        with mock.patch.object(servidor, "BACKEND", "mssql"):
            self.assertTrue(servidor._parametros({**PER, "sentido": ["emitidos"]})[4])


class Reporte(unittest.TestCase):
    def test_emitidos_rechaza_postgres(self):
        eng = mock.Mock()
        eng.dialect.name = "postgresql"
        with self.assertRaises(RuntimeError):
            construir_emitidos(eng, "2026-02-01", "2026-03-01")


if __name__ == "__main__":
    unittest.main()
