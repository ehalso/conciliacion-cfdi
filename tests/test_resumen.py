import unittest

import pandas as pd

from conciliacion.resumen import resumir

U = [f"{i:08X}-0000-0000-0000-000000000000" for i in range(1, 7)]


class Resumen(unittest.TestCase):
    def setUp(self):
        self.d = pd.DataFrame({
            "Tipo": ["Compra", "Compra", "NC proveedor", "Gasto", "Solo SAT", "Solo SAT"],
            "FOLIO": ["C1", "C1", "N1", "G1", "SAT-a", "SAT-b"],
            "UUID": [U[0], U[0], U[1], U[2], None, None],
            "XML_MONTO": [100.0, 100.0, 40.0, 50.0, None, None],
            "COMPLEMENTO_PAGO": [U[5], U[5], None, None, None, None],
            "SAT_UUID": [U[0], U[0], U[1], None, U[3], U[4]],
            "SAT_ESTATUS": ["Activo", "Activo", "Activo", None, "Activo", "Activo"],
            "SAT_TIPO_CFDI": ["Ingreso", "Ingreso", "Egreso", None, "Ingreso", "Pago"],
            "SAT_IMPORTE": [100.0, 100.0, 45.0, None, 30.0, 10.0],
            "CONC_EXISTENCIA": ["Sí", "Sí", "Sí", "No", "No", "No"],
            "CONC_IMPORTES": ["Sí", "Sí", "No", "", "No", "No"]})

        self.sat = pd.DataFrame({"tipo": ["RECIBIDO", "RECIBIDO", "RECIBIDO", "RECIBIDO", "EMITIDO"], "tc": ["I", "E", "P", "T", "N"],
                                 "n": [3, 1, 2, 4, 7], "monto": [200.0, 45.0, 10.0, 0.0, 99.0]})

    def fila(self, tipo, sec="recibidos"):
        return {f["tipo"]: f for f in resumir(self.d, self.sat)[sec]}[tipo]

    def test_cuenta_un_documento_por_uuid(self):
        r = self.fila("Ingreso")
        self.assertEqual(r["mpro"], {"n": 2, "monto": 150.0})
        self.assertEqual(r["sat"], {"n": 3, "monto": 200.0})
        self.assertEqual(r["dif"], {"n": 1, "monto": 50.0})

    def test_egreso_y_pago(self):
        self.assertEqual(self.fila("Egreso")["dif"], {"n": 0, "monto": 5.0})
        p = self.fila("Pago")
        self.assertEqual(p["mpro"], {"n": 1, "monto": None})
        self.assertEqual(p["sat"], {"n": 2, "monto": 10.0})
        self.assertIsNone(p["dif"]["monto"])

    def test_emitidos_solo_sat(self):
        n = self.fila("Nómina", "emitidos")
        self.assertEqual(n["sat"], {"n": 7, "monto": 99.0})
        self.assertIsNone(n["mpro"]["n"])
        self.assertIsNone(n["dif"]["n"])
        self.assertEqual(self.fila("Ingreso", "emitidos")["sat"], {"n": 0, "monto": 0.0})

    def test_diferencias_y_sin_sat(self):
        self.assertEqual(len(resumir(self.d, self.sat)["diferencias"]["rows"]), 4)
        self.assertEqual(resumir(self.d.drop(columns="SAT_UUID"), self.sat), {"disponible": False})
        self.assertEqual(resumir(self.d, None), {"disponible": False})


if __name__ == "__main__":
    unittest.main()
