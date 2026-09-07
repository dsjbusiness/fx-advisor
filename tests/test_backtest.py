# -*- coding: utf-8 -*-
"""Backtest F101: okna rozlaczne, statystyki z CI, sufit timingu."""

import os
import sys
import random
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import backtest


def _series(n=700, seed=3):
    rng = random.Random(seed)
    d = date(2020, 1, 1)
    out = {"EURPLN": [], "EURUSD": [], "USDPLN": []}
    pv, uv = 4.3, 1.1
    while len(out["EURPLN"]) < n:
        if d.weekday() < 5:
            pv *= 1 + rng.gauss(0, 0.004)
            uv *= 1 + rng.gauss(0, 0.004)
            out["EURPLN"].append((d.isoformat(), pv))
            out["EURUSD"].append((d.isoformat(), uv))
            out["USDPLN"].append((d.isoformat(), pv / uv))
        d += timedelta(days=1)
    return out


class TestStats(unittest.TestCase):
    def test_stats_ci(self):
        s = backtest._stats([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(s["n_windows"], 4)
        self.assertAlmostEqual(s["edge_bps_vs_dca"], 2.5)
        self.assertLess(s["ci90_lo"], 2.5)
        self.assertGreater(s["ci90_hi"], 2.5)
        self.assertEqual(s["hit_rate_pct"], 100.0)
        self.assertIsNone(backtest._stats([]))

    def test_verdict_requires_ci_above_zero(self):
        self.assertEqual(backtest._stats([5.0, 5.1, 4.9, 5.0])["verdict"], "edge")
        self.assertEqual(backtest._stats([5.0, -5.0, 5.0, -5.0])["verdict"], "no_edge")


class TestRunBacktest(unittest.TestCase):
    def test_non_overlapping_windows_and_keys(self):
        series = _series()
        res = backtest.run_backtest(series, [], today=date(2026, 9, 7))
        self.assertEqual(res["windows"], "non-overlapping")
        n = len(series["EURPLN"])
        expected = len(range(n - config.WINDOW_SESSIONS, config.MIN_HISTORY - 1,
                             -config.WINDOW_SESSIONS))
        for pair in ("EURPLN", "USDPLN", "EURUSD"):
            rec = res["pairs"][pair]
            self.assertEqual(rec["n_sessions"], n)
            for key in ("sell", "buy"):
                self.assertEqual(rec[key]["engine"]["n_windows"], expected)
                self.assertIn("ci90_lo", rec[key]["engine"])
                self.assertGreaterEqual(rec[key]["ceiling_bps"], 0.0)
                # DCA ma mniejszy rozrzut niz lump sum ostatniego dnia
                self.assertLess(rec[key]["sd_dca_bps"], rec[key]["sd_lump_bps"])

    def test_edge_sign_convention(self):
        # sprzedaz: osiagniety kurs wyzszy niz benchmark = dodatnia przewaga
        self.assertGreater(backtest._edge(1.01, 1.0, True), 0)
        self.assertLess(backtest._edge(1.01, 1.0, False), 0)


if __name__ == "__main__":
    unittest.main()
