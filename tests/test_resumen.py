import unittest

import pandas as pd

from conciliacion.resumen import diferencias, resumir

SAT = pd.DataFrame({"tipo": ["RECIBIDO", "RECIBIDO", "RECIBIDO", "RECIBIDO", "EMITIDO"], "tc": ["I", "E", "P", "T", "N"],
                    "n": [3, 1, 2, 4, 7], "monto": [200.0, 45.0, 10.0, 0.0, 99.0]})
REC = {"Ingreso": {"n": 2, "monto": 150.0}, "Pago": {"n": 1, "monto": None}}
EMI = {"Ingreso": {"n": 5, "monto": 90.0}, "Pago": {"n": 2, "monto": None}}


def fila(r, tipo, sec="recibidos"):
    return {f["tipo"]: f for f in r[sec]}[tipo]


class Resumen(unittest.TestCase):
    def test_ingreso_y_faltantes(self):
        r = fila(resumir(SAT, REC, EMI), "Ingreso")
        self.assertEqual((r["sat"], r["mpro"], r["dif"]), ({"n": 3, "monto": 200.0}, {"n": 2, "monto": 150.0}, {"n": 1, "monto": 50.0}))
        e = fila(resumir(SAT, REC, EMI), "Egreso")
        self.assertEqual((e["mpro"], e["dif"]), ({"n": 0, "monto": 0}, {"n": 1, "monto": 45.0}))

    def test_pago_sin_monto_en_mpro(self):
        p = fila(resumir(SAT, REC, EMI), "Pago")
        self.assertEqual(p["dif"], {"n": 1, "monto": None})

    def test_nomina_y_retencion(self):
        r = resumir(SAT, REC, EMI, None)
        n = fila(r, "Nómina", "emitidos")
        self.assertEqual(n["sat"], {"n": 7, "monto": 99.0})
        self.assertIsNone(n["mpro"]["n"])
        ret = fila(r, "Retención", "emitidos")
        self.assertEqual((ret["sat"]["n"], ret["dif"]["n"]), (None, None))
        con = pd.DataFrame({"tipo": ["EMITIDO"], "n": [3], "monto": [30.0]})
        ret = fila(resumir(SAT, REC, {**EMI, "Retención": {"n": 3, "monto": 30.0}}, con), "Retención", "emitidos")
        self.assertEqual(ret["dif"], {"n": 0, "monto": 0.0})

    def test_sin_sat(self):
        self.assertEqual(resumir(None, REC, EMI), {"disponible": False})

    def test_diferencias(self):
        d = pd.DataFrame({"Tipo": ["Compra", "Compra", "Gasto"], "FOLIO": ["A", "B", "C"], "CONC_EXISTENCIA": ["Sí", "No", "Sí"],
                          "CONC_IMPORTES": ["Sí", "", "No"], "SAT_UUID": [None, None, None]})
        r = diferencias(d)
        self.assertEqual([x[1] for x in r["rows"]], ["B", "C"])
        self.assertEqual(diferencias(d.drop(columns="SAT_UUID")), {"cols": [], "rows": []})


if __name__ == "__main__":
    unittest.main()
