import unittest

import pandas as pd

from conciliacion.atribucion import VARIOS, atribuir_documento
from conciliacion.vista import a_datos


def _base(filas):
    return pd.DataFrame([dict(FOLIO="F1", ORIGEN="registro_gasto", CUENTA_REGISTRO=c, CECO=ceco, CARGO=imp, ABONO=0.0,
                              NOMBRE_CUENTA_REGISTRO="x", CECO_DESCRIPCION="y") for c, ceco, imp in filas])


class AtribucionTest(unittest.TestCase):
    docs = pd.DataFrame({"FOLIO": ["F1", "F1"], "DOC_ID": ["0001", "0002"]})
    firmas = {("F1", "0001"): ("P1", "U1"), ("F1", "0002"): ("P2", "U2")}

    def reparto(self, filas):
        return pd.DataFrame(filas, columns=["FOLIO", "Grd_ID", "CECO", "Grc_Importe"]).assign(Grc_Factor=1.0)

    def test_atribuye_por_ceco_e_importe(self):
        r = self.reparto([("F1", "0001", "A", 100.0), ("F1", "0002", "A", 50.0)])
        out = atribuir_documento(_base([("6100", "A", 100.0), ("6100", "A", 50.0)]), r, self.docs, self.firmas)
        self.assertEqual(list(out.DOC_ID), ["0001", "0002"])

    def test_linea_suma_los_renglones_de_un_documento_en_el_ceco(self):
        r = self.reparto([("F1", "0001", "A", 30.0), ("F1", "0001", "A", 20.0), ("F1", "0002", "A", 70.0)])
        out = atribuir_documento(_base([("6100", "A", 50.0), ("6100", "A", 70.0)]), r, self.docs, self.firmas)
        self.assertEqual(list(out.DOC_ID), ["0001", "0002"])

    def test_mezcla_queda_varios_y_documento_sin_linea_se_agrega(self):
        r = self.reparto([("F1", "0001", "A", 100.0), ("F1", "0002", "A", 50.0)])
        out = atribuir_documento(_base([("6100", "A", 150.0)]), r, self.docs, self.firmas)
        self.assertEqual(list(out.DOC_ID[:1]), [VARIOS])
        self.assertEqual(set(out.DOC_ID), {VARIOS, "0001", "0002"})
        self.assertTrue((out[out.DOC_ID != VARIOS].CARGO == 0).all())

    def test_misma_firma_toma_menor_id(self):
        r = self.reparto([("F1", "0001", "A", 100.0), ("F1", "0002", "A", 100.0)])
        f = {("F1", "0001"): ("P1", "U1"), ("F1", "0002"): ("P1", "U1")}
        out = atribuir_documento(_base([("6100", "A", 100.0)]), r, self.docs, f)
        self.assertEqual(out.DOC_ID.iloc[0], "0001")

    def test_folio_de_un_documento_no_cambia(self):
        d1 = pd.DataFrame({"FOLIO": ["F1"], "DOC_ID": ["0001"]})
        out = atribuir_documento(_base([("6100", "A", 10.0)]), self.reparto([("F1", "0001", "A", 10.0)]), d1, {})
        self.assertTrue(out.DOC_ID.isna().all())

    def test_vista_un_bloque_por_documento(self):
        d = _base([("6100", "A", 100.0), ("6200", "A", 50.0)]).assign(
            Tipo="Gasto", DOC_ID=["0001", "0002"], NOMBRE_PROVEEDOR=["P1", "P2"], DOC_TOTAL=[116.0, 58.0],
            TOTAL=[116.0, 58.0], SUBTOTAL_NETO=[100.0, 50.0], FECHA="2026-01-01")
        out = a_datos(d)
        k = [c["k"] for c in out["cols"]]
        self.assertEqual([r[k.index("NOMBRE_PROVEEDOR")] for r in out["rows"]], ["P1", "P2"])
        self.assertEqual([r[k.index("TOTAL")] for r in out["rows"]], [116.0, 58.0])

    def test_pago_por_documento(self):
        from conciliacion.gasto import _pago_por_documento
        d = pd.DataFrame({"FOLIO": ["F1", "F1", "F1", "F2"], "DOC_ID": ["0001", "0002", VARIOS, None],
                          "MONTO_COBRADO": [300.0, 300.0, 300.0, 5.0]})
        pagos = pd.DataFrame({"FOLIO": ["F1"], "DOC_ID": ["0001"], "MONTO_COBRADO": [100.0]})
        out = _pago_por_documento(d, pagos)
        self.assertEqual(out.MONTO_COBRADO.iloc[0], 100.0)
        self.assertTrue(out.MONTO_COBRADO.iloc[1:3].isna().all())
        self.assertEqual(out.MONTO_COBRADO.iloc[3], 5.0)


if __name__ == "__main__":
    unittest.main()
