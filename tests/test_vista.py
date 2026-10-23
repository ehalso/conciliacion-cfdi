import unittest

import numpy as np
import pandas as pd

from conciliacion.vista import a_datos, agrupar_cuenta, val


class Val(unittest.TestCase):
    def test_vacios(self):
        for v in (None, np.nan, "", "  ", pd.NaT):
            self.assertIsNone(val(v))

    def test_redondeo_y_cero_negativo(self):
        self.assertEqual(val(1.005 + 1), 2.0)
        self.assertEqual(str(val(-0.0)), "0.0")

    def test_numpy(self):
        self.assertEqual(val(np.int64(3)), 3)


class Agrupar(unittest.TestCase):
    def test_suma_por_cuenta_y_ceco_varios(self):
        d = pd.DataFrame({"Tipo": ["Gasto"] * 3, "FOLIO": ["F1"] * 3, "CUENTA_REGISTRO": ["6100", "6100", "1140"],
                          "CECO": ["A", "B", "C"], "CARGO": [10.0, 5.0, 0.0], "ABONO": [0.0, 0.0, 15.0]})
        r = agrupar_cuenta(d).set_index("CUENTA_REGISTRO")
        self.assertEqual(r.loc["6100", "CARGO"], 15.0)
        self.assertEqual(r.loc["6100", "CECO"], "VARIOS")
        self.assertEqual(r.loc["1140", "ABONO"], 15.0)
        self.assertEqual(r.loc["1140", "CECO"], "C")


class ADatos(unittest.TestCase):
    def setUp(self):
        self.d = pd.DataFrame({
            "Tipo": ["Compra", "Gasto", "Gasto"], "FOLIO": ["C1", "G1", "G1"], "ORIGEN": [None, "registro_gasto", "registro_gasto"],
            "FECHA": ["2026-01-05"] * 3, "CECO": ["A", "A", "B"], "CUENTA_REGISTRO": ["6100", "6100", "6200"],
            "NOMBRE_PROVEEDOR": ["P1", "P2", "P2"], "CARGO": [10.0, 4.0, 6.0], "ABONO": [0.0, 0.0, 0.0],
            "SUBTOTAL_NETO": [10.0, 4.0, 6.0], "DOC_SUBTOTAL_NETO": [10.0, 10.0, 10.0], "TOTAL": [11.6, 4.64, 6.96],
            "DOC_TOTAL": [11.6, 11.6, 11.6]})

    def test_orden_por_tipo_y_fecha_formateada(self):
        r = a_datos(self.d, "layout", False)
        ks = [c["k"] for c in r["cols"]]
        self.assertEqual([x[ks.index("Tipo")] for x in r["rows"]], ["Gasto", "Gasto", "Compra"])
        self.assertEqual(r["rows"][0][ks.index("FECHA")], "05-01-2026")

    def test_layout_cifras_de_documento_solo_en_primera_fila(self):
        r = a_datos(self.d, "layout", False)
        ks = [c["k"] for c in r["cols"]]
        gasto = r["rows"][:2]
        self.assertEqual(gasto[0][ks.index("SUBTOTAL_NETO")], 10.0)
        self.assertIsNone(gasto[1][ks.index("SUBTOTAL_NETO")])

    def test_textos_se_repiten_en_gasto_registro(self):
        r = a_datos(self.d, "layout", False)
        ks = [c["k"] for c in r["cols"]]
        self.assertEqual(r["rows"][1][ks.index("NOMBRE_PROVEEDOR")], "P2")

    def test_vista_ceco_prorratea_por_linea(self):
        r = a_datos(self.d, "ceco", False)
        ks = [c["k"] for c in r["cols"]]
        self.assertEqual([x[ks.index("SUBTOTAL_NETO")] for x in r["rows"][:2]], [4.0, 6.0])

    def test_columnas_vacias_se_omiten(self):
        ks = [c["k"] for c in a_datos(self.d)["cols"]]
        self.assertNotIn("UUID", ks)
        self.assertIn("TOTAL", ks)


if __name__ == "__main__":
    unittest.main()
