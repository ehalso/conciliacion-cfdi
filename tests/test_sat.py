import unittest
from unittest import mock

import pandas as pd

from conciliacion import sat

U1, U2, U3 = ("AAAAAAAA-0000-0000-0000-000000000001", "AAAAAAAA-0000-0000-0000-000000000002",
              "AAAAAAAA-0000-0000-0000-000000000003")


def sat_falso(uuids):
    d = pd.DataFrame({"UUID_CRUCE": [U1, U2], "SAT_UUID": [U1, U2], "SAT_IMPORTE": [100.0, 50.0]})
    return d[d.UUID_CRUCE.isin(uuids)]


class CruceSat(unittest.TestCase):
    def cruzar(self, d):
        with mock.patch.object(sat, "consultar_sat", lambda e, u: sat_falso(u)):
            return sat.agregar_sat(d, None)

    def test_conciliacion(self):
        d = pd.DataFrame({"UUID": [U1.lower(), U2, U3, "VARIOS", None], "XML_MONTO": [100.04, 80, 10, 5, 0]})
        o = self.cruzar(d)
        self.assertEqual(list(o.CONC_EXISTE_MPRO), ["Sí", "Sí", "Sí", "No", "No"])
        self.assertEqual(list(o.CONC_EXISTE_SAT), ["Sí", "Sí", "No", "", ""])
        self.assertEqual(list(o.CONC_EXISTENCIA), ["Sí", "Sí", "No", "", ""])
        self.assertEqual(list(o.CONC_IMPORTES), ["Sí", "No", "", "", ""])

    def test_sin_sat_deja_el_reporte(self):
        d = pd.DataFrame({"UUID": [U1], "XML_MONTO": [1]})
        with mock.patch.object(sat, "consultar_sat", side_effect=RuntimeError("caído")):
            self.assertNotIn("SAT_UUID", sat.agregar_sat(d, None))


if __name__ == "__main__":
    unittest.main()
