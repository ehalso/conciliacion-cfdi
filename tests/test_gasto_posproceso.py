import unittest

import numpy as np
import pandas as pd

from conciliacion.gasto import emparejar_activo_fijo
from conciliacion.posproceso import post


def lineas(poliza, ref, importes, ceco="X"):
    return pd.DataFrame({"POLIZA": poliza, "REFERENCIA": ref, "FECHA_POLIZA": None, "TIPO_POLIZA": None,
                         "NUMERO_POLIZA": None, "CONCEPTO_POLIZA": None, "CUENTA_REGISTRO": "1210",
                         "NOMBRE_CUENTA_REGISTRO": "AF", "CECO": ceco, "CECO_DESCRIPCION": "d", "IMPORTE_PD": importes})


class ActivoFijo(unittest.TestCase):
    def test_un_folio_recibe_todas_sus_lineas(self):
        f = pd.DataFrame({"FOLIO": ["F1"], "REFERENCIA": ["R"], "POLIZA": ["P"], "VALOR_CMP": [30.0]})
        r = emparejar_activo_fijo(f, lineas("P", "R", [10.0, 20.0]))
        self.assertEqual(sorted(r.CARGO), [10.0, 20.0])
        self.assertTrue((r.ORIGEN == "CONSUMO_INTERNO").all())

    def test_varios_folios_se_emparejan_por_importe(self):
        f = pd.DataFrame({"FOLIO": ["F1", "F2"], "REFERENCIA": ["R"] * 2, "POLIZA": ["P"] * 2, "VALOR_CMP": [5.0, 50.0]})
        r = emparejar_activo_fijo(f, lineas("P", "R", [50.0, 5.0])).set_index("FOLIO")
        self.assertEqual(r.loc["F1", "CARGO"], 5.0)
        self.assertEqual(r.loc["F2", "CARGO"], 50.0)

    def test_linea_agregada_se_reparte_proporcional(self):
        f = pd.DataFrame({"FOLIO": ["F1", "F2"], "REFERENCIA": ["R"] * 2, "POLIZA": ["P"] * 2, "VALOR_CMP": [25.0, 75.0]})
        r = emparejar_activo_fijo(f, lineas("P", "R", [100.0])).set_index("FOLIO")
        self.assertEqual(r.loc["F1", "CARGO"], 25.0)
        self.assertEqual(r.loc["F2", "CARGO"], 75.0)


class Post(unittest.TestCase):
    def base(self):
        return pd.DataFrame({
            "Tipo": ["Gasto", "Gasto", "Compra"], "FOLIO": ["G1", "G1", "C1"], "CECO": ["A", "B", None],
            "CARGO": [30.0, 10.0, 100.0], "ABONO": [0.0, 0.0, 0.0],
            "SUBTOTAL_0": [None] * 3, "SUBTOTAL_EXENTA": [None] * 3,
            "SUBTOTAL_16": [None, None, 100.0], "SUBTOTAL_NETO": [None, None, 100.0],
            "IMP_IVA": [None, None, 16.0], "ORIGEN": ["GASTO_DIRECTO", "GASTO_DIRECTO", None],
            "XML_FORMA_PAGO": ["03", None, "VARIOS"], "XML_METODO_PAGO": ["PUE", None, None]})

    def test_cargo_abono_desde_neto(self):
        d = self.base()
        d.loc[0, ["CARGO", "ABONO"]] = [5.0, 8.0]
        r = post(d)
        self.assertEqual((r.CARGO[0], r.ABONO[0]), (0.0, 3.0))

    def test_sin_documento_usa_neto_de_poliza(self):
        r = post(self.base())
        self.assertEqual(list(r.SUBTOTAL_NETO[:2]), [30.0, 10.0])

    def test_total_es_subtotal_mas_impuestos(self):
        r = post(self.base())
        self.assertEqual(r.TOTAL[2], 116.0)
        self.assertEqual(r.DOC_TOTAL[2], 116.0)

    def test_etiquetas(self):
        r = post(self.base())
        self.assertEqual(r.ORIGEN[0], "registro_gasto")
        self.assertEqual(r.XML_FORMA_PAGO[0], "03 - Transferencia electrónica de fondos")
        self.assertEqual(r.XML_FORMA_PAGO[2], "VARIOS")
        self.assertEqual(r.XML_METODO_PAGO[0], "PUE - Pago en una sola exhibición")

    def test_prorrateo_por_peso_en_gasto(self):
        d = self.base().iloc[:2].copy()
        d["CECO"] = ["A", "A"]
        d["SUBTOTAL_NETO"] = [40.0, 40.0]
        r = post(d)
        self.assertAlmostEqual(r.SUBTOTAL_NETO.sum(), 40.0, 2)
        self.assertEqual(list(r.SUBTOTAL_NETO), [30.0, 10.0])

    def test_criterio_conciliacion(self):
        d = self.base()
        d["ORIGEN"] = ["CONSUMO_INTERNO", "GASTO_REGISTRO_NOMINA", None]
        d["GRUPO_TIPO_GASTO"] = [None, None, "0011"]
        r = post(d)
        self.assertEqual(list(r.CRITERIO_CONCILIACION), ["Consumo interno", "Nómina", "Provisión contable"])

    def test_sin_criterio_conciliacion_queda_vacio(self):
        r = post(self.base())
        self.assertTrue(r.CRITERIO_CONCILIACION.isna().all())

    def test_costo_estandar_y_provision_por_tipo_gasto_individual(self):
        d = self.base()
        d["TIPO_GASTO"] = ["0060", "0102", None]  # Llantas (costo estándar), Cuentas Incobrables
        r = post(d)
        self.assertEqual(list(r.CRITERIO_CONCILIACION)[:2], ["Costo estándar", "Provisión contable"])

    def test_costo_estandar_tiene_prioridad_sobre_grupo_mixto(self):
        d = self.base()
        d["TIPO_GASTO"] = ["0060", None, None]
        d["GRUPO_TIPO_GASTO"] = ["0005", None, None]  # grupo mixto (costo estándar + cuenta de balance)
        r = post(d)
        self.assertEqual(r.CRITERIO_CONCILIACION[0], "Costo estándar")

    def test_retencion_unica_sustituye_xml(self):
        d = self.base()
        d["R_N"] = [1, 1, np.nan]
        d["R_MONTO"] = [99.0, 99.0, np.nan]
        d["R_SERIE"] = ["S", "S", None]
        d["R_FOLIO_XML"] = ["77", "77", None]
        r = post(d)
        self.assertEqual(r.XML_MONTO[0], 99.0)
        self.assertEqual(r.NUMERO_FACTURA[0], "77")
        self.assertTrue(r.TIPO_COMPROBANTE[0].startswith("R - "))


if __name__ == "__main__":
    unittest.main()
