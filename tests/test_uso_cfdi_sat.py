import unittest

import pandas as pd

from conciliacion.uso_cfdi_sat import completar_uso_cfdi


class UsoCfdiSatTest(unittest.TestCase):
    d = pd.DataFrame({"UUID": ["E36DFC89-9DB6-4F62-A75B-8108A7417BDA"], "CLAVE_USO_BIEN_SERVICIO": [None],
                      "DESCRIPCION_USO_BIEN_SERVICIO": [None]})

    def test_sin_engine_sat_no_cambia(self):
        self.assertTrue(completar_uso_cfdi(self.d, None, None).equals(self.d))

    def test_sat_caido_no_rompe(self):
        class Roto:
            def connect(self):
                raise RuntimeError("sin conexion")
        self.assertTrue(completar_uso_cfdi(self.d, Roto(), None).equals(self.d))

    def test_sin_faltantes_no_consulta(self):
        d = self.d.assign(CLAVE_USO_BIEN_SERVICIO="G03")
        self.assertTrue(completar_uso_cfdi(d, object(), None).equals(d))


if __name__ == "__main__":
    unittest.main()
