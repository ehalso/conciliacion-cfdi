import unittest
from unittest import mock

import pandas as pd

from conciliacion import sat

U1, U2, U3 = ("AAAAAAAA-0000-0000-0000-000000000001", "AAAAAAAA-0000-0000-0000-000000000002",
              "AAAAAAAA-0000-0000-0000-000000000003")


def sat_falso(uuids):
    d = pd.DataFrame({"UUID_CRUCE": [U1, U2], "SAT_UUID": [U1, U2], "SAT_IMPORTE": [100.0, 50.0], "SAT_IMPORTE_COMPLEMENTO": [None, None]})
    return d[d.UUID_CRUCE.isin(uuids)]


class CruceSat(unittest.TestCase):
    def cruzar(self, d):
        with mock.patch.object(sat, "consultar_sat", lambda e, u: sat_falso(u)):
            return sat.agregar_sat(d, None)

    def test_conciliacion(self):
        d = pd.DataFrame({"UUID": [U1.lower(), U2, U3, "VARIOS", None], "TOTAL": [100.04, 80, 10, 5, 0], "Tipo": "Gasto"})
        o = self.cruzar(d)
        self.assertEqual(list(o.CONC_EXISTE_MPRO), ["Sí", "Sí", "Sí", "No", "No"])
        self.assertEqual(list(o.CONC_EXISTE_SAT), ["Sí", "Sí", "No", "", ""])
        self.assertEqual(list(o.CONC_EXISTENCIA), ["Sí", "Sí", "No", "", ""])
        self.assertEqual(list(o.CONC_IMPORTES), ["Sí", "No", "", "", ""])

    def test_importes_por_uuid_excluye_cxp_y_suma_folios(self):
        d = pd.DataFrame({"UUID": [U1, U1, U1, U2, U2],
                          "Tipo": ["Gasto", "Gasto", "CxP libre", "NC proveedor", "Gasto"],
                          "TOTAL": [60.0, 40.0, 100.0, -50.0, 0.0]})
        o = self.cruzar(d)
        self.assertEqual(list(o.CONC_IMPORTES), ["Sí"] * 5)
        self.assertEqual(list(o.DIF_IMPORTE_UUID), [0.0] * 5)

    def test_importes_con_complemento(self):
        sat_c = pd.DataFrame({"UUID_CRUCE": [U1], "SAT_UUID": [U1], "SAT_IMPORTE": [10.0], "SAT_IMPORTE_COMPLEMENTO": [90.0]})
        d = pd.DataFrame({"UUID": [U1, U1], "Tipo": "Gasto", "TOTAL": [90.0, 10.0]})
        with mock.patch.object(sat, "consultar_sat", lambda e, u: sat_c):
            o = sat.agregar_sat(d, None)
        self.assertEqual(list(o.CONC_IMPORTES), ["Sí", "Sí"])

    def test_complemento_incluido_en_el_total_no_se_suma(self):
        sat_c = pd.DataFrame({"UUID_CRUCE": [U1], "SAT_UUID": [U1], "SAT_IMPORTE": [100.0], "SAT_IMPORTE_COMPLEMENTO": [98.0]})
        d = pd.DataFrame({"UUID": [U1, U1], "Tipo": "Gasto", "TOTAL": [98.0, 2.0]})
        with mock.patch.object(sat, "consultar_sat", lambda e, u: sat_c):
            o = sat.agregar_sat(d, None)
        self.assertEqual(list(o.CONC_IMPORTES), ["Sí", "Sí"])

    def test_sin_sat_deja_el_reporte(self):
        d = pd.DataFrame({"UUID": [U1], "TOTAL": [1], "Tipo": "Gasto"})
        with mock.patch.object(sat, "consultar_sat", side_effect=RuntimeError("caído")):
            self.assertNotIn("SAT_UUID", sat.agregar_sat(d, None))


class TotalEnPesos(unittest.TestCase):
    def test_consultas_convierten_moneda_extranjera_con_tipo_cambio(self):
        for q in (sat.SQL_CFDI, sat.SQL_SOLO_SAT):
            self.assertIn("c.total * CASE WHEN c.moneda NOT IN ('MXN', 'XXX') AND c.tipo_cambio > 0 THEN c.tipo_cambio ELSE 1 END AS total", q)


class SoloSat(unittest.TestCase):
    def test_agrega_los_que_no_estan_en_mpro(self):
        crudo = pd.DataFrame({"uuid": [U1, U2, "BBBBBBBB-0000-0000-0000-000000000003"], "serie": "A", "folio": "1", "tipo_comprobante": "I",
                              "fecha": "2026-01-08T10:00:00Z", "rfc_emisor": "XAXX", "nombre_emisor": "P",
                              "total": [1.0, 2.0, 3.0], "cancelado": False, "concepto": "&amp;X", "uso_cfdi": "G03", "complemento": None})
        lecturas = iter([crudo, pd.DataFrame({"uuid": [U1], "tabla": "COMPRA", "folio": "05-1", "estado": "AC"})])
        engine = mock.MagicMock()
        with mock.patch.object(sat.pd, "read_sql", lambda *a, **k: next(lecturas)):
            d = pd.DataFrame({"Tipo": ["Gasto"], "FOLIO": ["01-1"], "UUID": [U1]})
            o = sat.agregar_solo_sat(d, engine, engine, "2026-01-01", "2026-02-01")
        n = o[o.Tipo == "Solo SAT"]
        self.assertEqual(list(n.SAT_UUID), [U2, "BBBBBBBB-0000-0000-0000-000000000003"])
        self.assertEqual(n.SAT_CONCEPTO.iloc[0], "&X")
        self.assertEqual(list(n.CONC_EXISTE_MPRO), ["No", "No"])
        self.assertEqual(n.FOLIO.nunique(), 2)

    def test_en_mpro_con_documento_de_otro_periodo(self):
        crudo = pd.DataFrame({"uuid": [U1, U2, "BBBBBBBB-0000-0000-0000-000000000003"], "serie": "A", "folio": "1", "tipo_comprobante": "I",
                              "fecha": "2026-01-08T10:00:00Z", "rfc_emisor": "XAXX", "nombre_emisor": "P",
                              "total": [1.0, 2.0, 3.0], "cancelado": False, "concepto": "X", "uso_cfdi": "G03", "complemento": None})
        lecturas = iter([crudo, pd.DataFrame({"uuid": [U1, U2, U2], "tabla": ["COMPRA", "CUENTA_X_PAGAR", "GASTO_REGISTRO"], "folio": ["05-1", "05-9", "01-0000007"], "estado": "AC"})])
        engine = mock.MagicMock()
        with mock.patch.object(sat.pd, "read_sql", lambda *a, **k: next(lecturas)):
            d = pd.DataFrame({"Tipo": ["Gasto"], "FOLIO": ["01-1"], "UUID": [U1]})
            o = sat.agregar_solo_sat(d, engine, engine, "2026-01-01", "2026-02-01")
        n = o.set_index("SAT_UUID")
        self.assertEqual((n.loc[U2, "Tipo"], n.loc[U2, "FOLIO"]), ("Otro periodo (Gasto)", "01-0000007"))
        self.assertEqual((n.loc[U2, "CONC_EXISTE_MPRO"], n.loc[U2, "CONC_IMPORTES"]), ("Sí", ""))
        self.assertEqual(n.loc[U2, "CONC_EXISTENCIA"], "No")
        self.assertEqual(n.loc["BBBBBBBB-0000-0000-0000-000000000003", "Tipo"], "Solo SAT")
        self.assertNotIn(U1, list(o[o.Tipo != "Gasto"].SAT_UUID))

    def test_no_agrega_complementos_de_pago(self):
        crudo = pd.DataFrame({"uuid": [U2, "BBBBBBBB-0000-0000-0000-000000000003"], "serie": "A", "folio": "1", "tipo_comprobante": ["I", "P"],
                              "fecha": "2026-01-08T10:00:00Z", "rfc_emisor": "XAXX", "nombre_emisor": "P",
                              "total": [2.0, 0.0], "cancelado": False, "concepto": "X", "uso_cfdi": "G03", "complemento": None})
        lecturas = iter([crudo, pd.DataFrame({"uuid": ["BBBBBBBB-0000-0000-0000-000000000003"], "tabla": "COMPRA", "folio": "05-1", "estado": "AC"})])
        engine = mock.MagicMock()
        with mock.patch.object(sat.pd, "read_sql", lambda *a, **k: next(lecturas)):
            o = sat.agregar_solo_sat(pd.DataFrame({"Tipo": ["Gasto"], "FOLIO": ["01-1"], "UUID": [U1]}), engine, engine, "2026-01-01", "2026-02-01")
        self.assertEqual(list(o.SAT_UUID.dropna()), [U2])


if __name__ == "__main__":
    unittest.main()
