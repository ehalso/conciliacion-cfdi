import unittest

import pandas as pd

from conciliacion.complemento import resumir


class Resumir(unittest.TestCase):
    def test_uno_varios_y_duplicados(self):
        c = pd.DataFrame({"FACTURA": ["A", "A", "B", "B", "B"], "COMPLEMENTO": ["P1", "P1", "P2", "P3", "P3"],
                          "FECHA": pd.to_datetime(["2026-01-05"] * 5)})
        r = resumir(c)
        self.assertEqual(r.loc["A", "COMPLEMENTO"], "P1")
        self.assertEqual(r.loc["A", "FECHA"], pd.Timestamp("2026-01-05"))
        self.assertEqual(r.loc["B", "COMPLEMENTO"], "VARIOS")
        self.assertTrue(pd.isna(r.loc["B", "FECHA"]))


if __name__ == "__main__":
    unittest.main()
