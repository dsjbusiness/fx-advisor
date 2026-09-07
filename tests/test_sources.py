# -*- coding: utf-8 -*-
"""Parsery nowych zrodel (F101): EBC SDMX CSV, NBP JSON, widok NBP,
stopy do carry, pozycje."""

import json
import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import data_layer


SDMX_CSV = """KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS
EXR.D.PLN.EUR.SP00.A,D,PLN,EUR,SP00,A,2026-09-03,4.3211,A
EXR.D.PLN.EUR.SP00.A,D,PLN,EUR,SP00,A,2026-09-04,4.3148,A
EXR.D.PLN.EUR.SP00.A,D,PLN,EUR,SP00,A,2026-09-05,,A
"""

NBP_JSON = {"table": "A", "currency": "euro", "code": "EUR",
            "rates": [{"no": "171/A/NBP/2026", "effectiveDate": "2026-09-03", "mid": 4.3211},
                      {"no": "172/A/NBP/2026", "effectiveDate": "2026-09-04", "mid": 4.3179}]}


class TestParsers(unittest.TestCase):
    def test_sdmx_csv(self):
        out = data_layer.parse_sdmx_csv(SDMX_CSV)
        self.assertEqual(out, {"2026-09-03": 4.3211, "2026-09-04": 4.3148})

    def test_nbp_json(self):
        out = data_layer.parse_nbp_json(NBP_JSON)
        self.assertEqual(out["2026-09-04"], 4.3179)

    def test_nbp_view_accounting_rate_is_previous_day(self):
        doc = {"rates": {"2026-09-03": {"EUR": 4.3211, "USD": 3.71},
                         "2026-09-04": {"EUR": 4.3179, "USD": 3.70}}}
        v = data_layer.nbp_view(doc, date(2026, 9, 4))
        self.assertEqual(v["EURPLN"]["last"], 4.3179)
        self.assertEqual(v["EURPLN"]["acc_date"], "2026-09-03")
        self.assertEqual(v["USDPLN"]["acc"], 3.71)
        v2 = data_layer.nbp_view(doc, date(2026, 9, 7))
        self.assertEqual(v2["EURPLN"]["acc_date"], "2026-09-04")

    def test_sdmx_source_first(self):
        self.assertEqual(data_layer._sources()[0][0], "ecb sdmx")


class TestRatesAndPositions(unittest.TestCase):
    def test_load_rates_fallback_to_config(self):
        with tempfile.TemporaryDirectory() as td:
            doc = data_layer.load_rates(os.path.join(td, "rates.json"))
            self.assertEqual(doc["rates"], config.POLICY_RATES)

    def test_positions_roundtrip_and_ids(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "positions.json")
            doc = data_layer.load_positions(path)
            self.assertEqual(doc["positions"], [])
            pid = data_layer.new_position_id(doc, date(2026, 9, 7))
            self.assertEqual(pid, "P260907-1")
            doc["positions"].append({"id": pid})
            self.assertEqual(data_layer.new_position_id(doc, date(2026, 9, 7)), "P260907-2")
            data_layer.save_positions(doc, path)
            self.assertEqual(data_layer.load_positions(path)["positions"][0]["id"], pid)


if __name__ == "__main__":
    unittest.main()
