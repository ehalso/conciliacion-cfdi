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


class SoloSat(unittest.TestCase):
    def test_agrega_los_que_no_estan_en_mpro(self):
        crudo = pd.DataFrame({"uuid": [U1, U2, "BBBBBBBB-0000-0000-0000-000000000003"], "serie": "A", "folio": "1", "tipo_comprobante": "I",
                              "fecha": "2026-01-08T10:00:00Z", "rfc_emisor": "XAXX", "nombre_emisor": "P",
                              "total": [1.0, 2.0, 3.0], "cancelado": False, "concepto": "&amp;X"})
        lecturas = iter([crudo, pd.DataFrame({"uuid": [U1]})])
        engine = mock.MagicMock()
        with mock.patch.object(sat.pd, "read_sql", lambda *a, **k: next(lecturas)):
            d = pd.DataFrame({"Tipo": ["Gasto"], "FOLIO": ["01-1"], "UUID": [U1]})
            o = sat.agregar_solo_sat(d, engine, engine, "2026-01-01", "2026-02-01")
        n = o[o.Tipo == "Solo SAT"]
        self.assertEqual(list(n.SAT_UUID), [U2, "BBBBBBBB-0000-0000-0000-000000000003"])
        self.assertEqual(n.SAT_CONCEPTO.iloc[0], "&X")
        self.assertEqual(list(n.CONC_EXISTE_MPRO), ["No", "No"])
        self.assertEqual(n.FOLIO.nunique(), 2)


if __name__ == "__main__":
    unittest.main()
