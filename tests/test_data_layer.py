# -*- coding: utf-8 -*-
"""Testy warstwy danych: odpornosc pobierania kursow i praca na cache.

Tlo: 2026-07-23/24 dwa biegi padly, bo Frankfurter zwrocil 520, a potem
zerwal polaczenie w trakcie odczytu (TimeoutError). Timeout nie jest
podklasa URLError, wiec nie byl lapany - skrypt umieral przed proba
hosta zapasowego.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import data_layer


ECB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-07-23">
      <Cube currency="USD" rate="1.0850"/>
      <Cube currency="PLN" rate="4.2800"/>
      <Cube currency="CHF" rate="0.9500"/>
    </Cube>
    <Cube time="2026-07-22">
      <Cube currency="USD" rate="1.0800"/>
      <Cube currency="PLN" rate="4.2700"/>
    </Cube>
  </Cube>
</gesmes:Envelope>"""


class _Patch(object):
    """Podmienia atrybuty modulu na czas testu."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.saved = {}

    def __enter__(self):
        for k, v in self.kwargs.items():
            mod = data_layer if hasattr(data_layer, k) else config
            self.saved[k] = (mod, getattr(mod, k))
            setattr(mod, k, v)
        return self

    def __exit__(self, *exc):
        for k, (mod, v) in self.saved.items():
            setattr(mod, k, v)
        return False


def _fast_retries():
    return _Patch(HTTP_RETRIES=1, HTTP_BACKOFF_S=0)


class TestFetchRange(unittest.TestCase):
    """_fetch_range musi przezyc awarie pojedynczego zrodla."""

    def test_timeout_na_pierwszym_hoscie_nie_konczy_biegu(self):
        calls = []

        def fake_json(url, timeout=None):
            calls.append(url)
            if data_layer.FRANKFURTER_HOSTS[0] in url:
                raise TimeoutError("The read operation timed out")
            return {"rates": {"2026-07-23": {"PLN": 4.28, "USD": 1.085}}}

        with _fast_retries(), _Patch(_http_get_json=fake_json):
            out = data_layer._fetch_range(date(2026, 7, 23), date(2026, 7, 23))

        self.assertEqual(out, {"2026-07-23": {"PLN": 4.28, "USD": 1.085}})
        self.assertEqual(len(calls), 2)  # host 1 padl, host 2 odpowiedzial

    def test_http_5xx_przechodzi_na_zrodlo_zapasowe_ecb(self):
        from urllib.error import HTTPError

        def fake_json(url, timeout=None):
            raise HTTPError(url, 520, "origin error", {}, None)

        def fake_get(url, timeout=None):
            self.assertIn("ecb.europa.eu", url)
            return ECB_XML.encode("utf-8")

        with _fast_retries(), _Patch(_http_get_json=fake_json, _http_get=fake_get):
            out = data_layer._fetch_range(date(2026, 7, 22), date(2026, 7, 23))

        self.assertEqual(sorted(out.keys()), ["2026-07-22", "2026-07-23"])
        self.assertAlmostEqual(out["2026-07-23"]["PLN"], 4.28)

    def test_wszystkie_zrodla_padly_daje_fxdataunavailable(self):
        def boom_json(url, timeout=None):
            raise TimeoutError("timeout")

        def boom_get(url, timeout=None):
            raise OSError("connection reset")

        with _fast_retries(), _Patch(_http_get_json=boom_json, _http_get=boom_get):
            with self.assertRaises(data_layer.FxDataUnavailable):
                data_layer._fetch_range(date(2026, 7, 23), date(2026, 7, 23))

    def test_pusta_odpowiedz_to_nie_blad(self):
        """Poranny bieg przed fixingiem EBC: brak nowych sesji w zakresie."""
        def fake_json(url, timeout=None):
            return {"rates": {}}

        with _fast_retries(), _Patch(_http_get_json=fake_json):
            self.assertEqual(
                data_layer._fetch_range(date(2026, 7, 24), date(2026, 7, 24)), {})


class TestFetchEcb(unittest.TestCase):
    def test_parsuje_xml_i_tnie_do_zakresu(self):
        with _Patch(_http_get=lambda url, timeout=None: ECB_XML.encode("utf-8")):
            out = data_layer._fetch_ecb(date(2026, 7, 23), date(2026, 7, 23))
        self.assertEqual(list(out.keys()), ["2026-07-23"])
        self.assertAlmostEqual(out["2026-07-23"]["USD"], 1.085)

    def test_pelna_historia_dla_dlugiego_zakresu(self):
        seen = []

        def fake_get(url, timeout=None):
            seen.append(url)
            return ECB_XML.encode("utf-8")

        with _Patch(_http_get=fake_get):
            data_layer._fetch_ecb(date(2025, 1, 1), date(2026, 7, 23))
        self.assertEqual(seen, [data_layer.ECB_FULL_URL])


class TestUpdateHistoryStale(unittest.TestCase):
    """Gdy zrodla milcza, swiezy cache ratuje bieg; stary - nie."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "history.json")

    def _write_cache(self, last_day):
        rates = {}
        d = last_day
        for i in range(5):
            rates[(d - timedelta(days=i)).isoformat()] = {"PLN": 4.28, "USD": 1.085}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"source": "test", "updated": last_day.isoformat(),
                       "rates": rates}, f)

    def _boom(self, start, end):
        raise data_layer.FxDataUnavailable("wszystko padlo")

    def test_swiezy_cache_konczy_sie_raportem_oznaczonym_jako_stale(self):
        today = date(2026, 7, 24)
        self._write_cache(today - timedelta(days=2))
        with _Patch(_fetch_range=self._boom):
            doc = data_layer.update_history(path=self.path, today=today)
        self.assertTrue(doc["stale"])
        self.assertEqual(doc["stale_days"], 2)
        self.assertEqual(doc["updated"], (today - timedelta(days=2)).isoformat())

    def test_za_stary_cache_przerywa_bieg(self):
        today = date(2026, 7, 24)
        self._write_cache(today - timedelta(days=config.MAX_STALE_DAYS + 1))
        with _Patch(_fetch_range=self._boom):
            with self.assertRaises(data_layer.FxDataUnavailable):
                data_layer.update_history(path=self.path, today=today)

    def test_brak_cache_przerywa_bieg(self):
        with _Patch(_fetch_range=self._boom):
            with self.assertRaises(data_layer.FxDataUnavailable):
                data_layer.update_history(path=self.path, today=date(2026, 7, 24))

    def test_udane_pobranie_zeruje_flagi(self):
        today = date(2026, 7, 24)
        self._write_cache(today - timedelta(days=2))
        ok = {today.isoformat(): {"PLN": 4.30, "USD": 1.09}}
        with _Patch(_fetch_range=lambda s, e: ok):
            doc = data_layer.update_history(path=self.path, today=today)
        self.assertFalse(doc["stale"])
        self.assertEqual(doc["stale_days"], 0)
        self.assertEqual(doc["updated"], today.isoformat())
        self.assertIn(today.isoformat(), doc["rates"])


if __name__ == "__main__":
    unittest.main()
