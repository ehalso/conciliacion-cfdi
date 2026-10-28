import unittest

import numpy as np
import pandas as pd

from conciliacion.vista import CRITERIOS_ORDEN, a_datos, agrupar_cuenta, resumen_conciliacion, val


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


class ResumenConciliacion(unittest.TestCase):
    def base(self):
        # G1: consumo interno (2 líneas, mismo folio, no debe duplicarse); G2: sin criterio, con CFDI en el SAT
        return pd.DataFrame({
            "Tipo": ["Gasto", "Gasto", "Gasto"], "FOLIO": ["G1", "G1", "G2"],
            "CRITERIO_CONCILIACION": ["Consumo interno", "Consumo interno", None],
            "DOC_TOTAL": [100.0, 100.0, 50.0], "SAT_IMPORTE": [None, None, 45.0], "UUID": [None, None, "U1"]})

    def test_sin_columna_criterio_no_hay_resumen(self):
        self.assertEqual(resumen_conciliacion(pd.DataFrame({"Tipo": ["Gasto"], "FOLIO": ["G1"]})), [])

    def test_agrupa_por_folio_sin_duplicar_lineas(self):
        r = {f["criterio"]: f for f in resumen_conciliacion(self.base())}
        self.assertEqual(r["Consumo interno"]["mpro"], 100.0)
        self.assertEqual(r["Nómina"]["mpro"], 0.0)

    def test_resto_y_cruce_sat(self):
        r = {f["criterio"]: f for f in resumen_conciliacion(self.base())}
        self.assertEqual(r["Resto (debe conciliar)"]["mpro"], 50.0)
        self.assertEqual(r["Σ SAT cruzado"]["mpro"], 45.0)
        self.assertEqual(r["Σ SAT cruzado"]["sub"], True)
        self.assertEqual(r["Diferencia"]["mpro"], 5.0)

    def test_porcentaje_sobre_total(self):
        r = {f["criterio"]: f for f in resumen_conciliacion(self.base())}
        self.assertAlmostEqual(r["Consumo interno"]["pct"], 66.7, places=1)

    def test_incluye_otros_tipos_en_el_resto(self):
        # Compra/Indirecto/NC/CxP no tienen CRITERIO_CONCILIACION (solo aplica a Gasto): entran completos al resto.
        d = pd.concat([self.base(), pd.DataFrame({
            "Tipo": ["Compra"], "FOLIO": ["C1"], "CRITERIO_CONCILIACION": [None], "DOC_TOTAL": [1000.0],
            "SAT_IMPORTE": [None]})], ignore_index=True)
        r = {f["criterio"]: f for f in resumen_conciliacion(d)}
        self.assertEqual(r["Resto (debe conciliar)"]["mpro"], 1050.0)

    def test_solo_sat_no_cuenta_como_movimiento_mpro(self):
        d = pd.concat([self.base(), pd.DataFrame({
            "Tipo": ["Solo SAT"], "FOLIO": ["SAT-ABC"], "CRITERIO_CONCILIACION": [None], "DOC_TOTAL": [9999.0],
            "SAT_IMPORTE": [9999.0], "UUID": [None]})], ignore_index=True)
        r = {f["criterio"]: f for f in resumen_conciliacion(d)}
        self.assertEqual(r["Resto (debe conciliar)"]["mpro"], 50.0)

    def test_sin_criterio_conciliacion_todo_va_al_resto(self):
        d = pd.DataFrame({"Tipo": ["Compra"], "FOLIO": ["C1"], "DOC_TOTAL": [1000.0]})
        r = {f["criterio"]: f for f in resumen_conciliacion(d)}
        self.assertEqual(r["Resto (debe conciliar)"]["mpro"], 1000.0)
        self.assertEqual(r["Consumo interno"]["mpro"], 0.0)

    def test_mismo_uuid_en_varios_folios_no_se_duplica_en_sat(self):
        # Un solo CFDI (p. ej. factura consolidada de PASE) puede cubrir varios folios de Gasto distintos.
        d = pd.DataFrame({
            "Tipo": ["Gasto"] * 3, "FOLIO": ["G1", "G2", "G3"], "CRITERIO_CONCILIACION": [None, None, None],
            "DOC_TOTAL": [50.0, 30.0, 20.0], "SAT_IMPORTE": [45.0, 45.0, 45.0], "UUID": ["U1", "U1", "U1"]})
        r = {f["criterio"]: f for f in resumen_conciliacion(d)}
        self.assertEqual(r["Resto (debe conciliar)"]["mpro"], 100.0)
        self.assertEqual(r["Σ SAT cruzado"]["mpro"], 45.0)


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

    def test_incluye_resumen_de_conciliacion(self):
        self.d["CRITERIO_CONCILIACION"] = [None, None, None]
        r = a_datos(self.d)
        self.assertIn("resumen", r)
        self.assertEqual({f["criterio"] for f in r["resumen"]}, {*CRITERIOS_ORDEN, "Resto (debe conciliar)"})


if __name__ == "__main__":
    unittest.main()
