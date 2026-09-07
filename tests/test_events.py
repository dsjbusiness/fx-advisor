# -*- coding: utf-8 -*-
"""Straznik kalendarza (CI): pliki data/events_*.yaml musza siegac co najmniej
CALENDAR_MIN_COVERAGE_DAYS naprzod dla KAZDEJ waluty. Bez tego plan omija
zle dni, a nikt tego nie zauwazy. Plus: dzien reakcji dla publikacji po
fixingu EBC."""

import os
import sys
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config
import data_layer


class TestCalendarCoverage(unittest.TestCase):
    def setUp(self):
        self.events = data_layer.load_events(os.path.join(ROOT, "data", "events_*.yaml"))
        self.today = date.today()

    def test_calendar_loaded(self):
        self.assertGreater(len(self.events), 50)

    def test_coverage_per_currency(self):
        for ccy in ("PLN", "EUR", "USD"):
            cov = data_layer.calendar_coverage_days(self.events, self.today, ccy)
            self.assertGreaterEqual(
                cov, config.CALENDAR_MIN_COVERAGE_DAYS,
                "kalendarz {} siega tylko {} dni naprzod - dodaj data/events_RRRR.yaml"
                .format(ccy, cov))

    def test_dates_valid_and_sorted(self):
        prev = ""
        for e in self.events:
            self.assertRegex(e["date"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertGreaterEqual(e["date"], prev)
            prev = e["date"]
            self.assertIn(e["impact"], ("high", "medium"))
            self.assertTrue(e["currencies"])


class TestEffectiveDate(unittest.TestCase):
    def test_late_sources_shift_to_next_session(self):
        fomc = {"date": "2026-09-16", "source": "Fed"}   # sroda 20:00 PL
        self.assertEqual(data_layer.effective_date(fomc), "2026-09-17")
        nfp = {"date": "2026-10-02", "source": "BLS"}    # piatek 14:30 PL -> pon
        self.assertEqual(data_layer.effective_date(nfp), "2026-10-05")

    def test_nbp_same_day(self):
        self.assertEqual(data_layer.effective_date({"date": "2026-10-07", "source": "NBP"}),
                         "2026-10-07")

    def test_high_dates_for_pair_uses_effective(self):
        evs = [{"date": "2026-09-16", "effective_date": "2026-09-17", "source": "Fed",
                "currencies": ["USD"], "impact": "high", "name": "x"},
               {"date": "2026-09-09", "effective_date": "2026-09-09", "source": "NBP",
                "currencies": ["PLN"], "impact": "high", "name": "y"}]
        self.assertEqual(data_layer.high_dates_for_pair(evs, ["USD", "PLN"]),
                         {"2026-09-17", "2026-09-09"})
        self.assertEqual(data_layer.high_dates_for_pair(evs, ["EUR", "USD"]), {"2026-09-17"})

    def test_parser_strips_inline_comment(self):
        text = "year: 2027\nevents:\n  - date: 2027-01-13  # do weryfikacji\n    source: NBP\n"
        evs = data_layer.parse_events_yaml(text)
        self.assertEqual(evs[0]["date"], "2027-01-13")


if __name__ == "__main__":
    unittest.main()
