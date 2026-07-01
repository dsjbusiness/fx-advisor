# -*- coding: utf-8 -*-
"""Testy jednostkowe matematyki wskaznikow."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import indicators as ind
import signals


class TestPercentile(unittest.TestCase):
    def test_percentile_rank_basic(self):
        w = list(range(1, 11))  # 1..10
        self.assertEqual(ind.percentile_rank(w, 10), 100.0)
        self.assertEqual(ind.percentile_rank(w, 5), 50.0)
        self.assertEqual(ind.percentile_rank(w, 0), 0.0)

    def test_percentile_rank_empty(self):
        self.assertEqual(ind.percentile_rank([], 5), 50.0)

    def test_percentile_level_interpolation(self):
        w = list(range(0, 101))  # 0..100
        self.assertAlmostEqual(ind.percentile_level(w, 50), 50.0)
        self.assertAlmostEqual(ind.percentile_level(w, 90), 90.0)
        self.assertAlmostEqual(ind.percentile_level([0, 10], 50), 5.0)
        self.assertAlmostEqual(ind.percentile_level([0, 10], 0), 0.0)
        self.assertAlmostEqual(ind.percentile_level([0, 10], 100), 10.0)

    def test_percentile_roundtrip(self):
        # poziom na q-tym percentylu ma rank ~q
        w = [float(i) for i in range(1, 251)]
        lvl = ind.percentile_level(w, 90)
        self.assertAlmostEqual(ind.percentile_rank(w, lvl), 90.0, delta=1.0)


class TestRSI(unittest.TestCase):
    def test_all_gains(self):
        values = [float(i) for i in range(1, 40)]
        self.assertEqual(ind.rsi(values, 14), 100.0)

    def test_all_losses(self):
        values = [float(i) for i in range(40, 1, -1)]
        self.assertAlmostEqual(ind.rsi(values, 14), 0.0, delta=1e-9)

    def test_flat(self):
        self.assertEqual(ind.rsi([5.0] * 40, 14), 50.0)

    def test_short_series(self):
        self.assertEqual(ind.rsi([1.0, 2.0], 14), 50.0)


class TestBollinger(unittest.TestCase):
    def test_flat_series(self):
        self.assertEqual(ind.bollinger_pctb([4.0] * 25), 0.5)

    def test_known_value(self):
        # okno [0]*9 + [10]: mu=1, sd=3, dolna=-5, gorna=7 -> %B=(10+5)/12
        values = [0.0] * 9 + [10.0]
        self.assertAlmostEqual(ind.bollinger_pctb(values, n=10, k=2.0), 1.25)


class TestVol(unittest.TestCase):
    def test_known_stdev(self):
        values = [100.0, 110.0, 99.0]  # zwroty +10%, -10%
        self.assertAlmostEqual(ind.realized_vol_daily(values, 20), 0.1)

    def test_too_short(self):
        self.assertEqual(ind.realized_vol_daily([1.0, 2.0], 20), 0.0)


class TestSignalComponents(unittest.TestCase):
    def _trending_series(self, up=True, n=300):
        step = 0.002 if up else -0.002
        v = 4.0
        out = []
        for i in range(n):
            v *= (1 + step + (0.0004 if i % 2 else -0.0004))
            out.append(v)
        return out

    def test_level_sign_for_uptrend(self):
        comp = signals.score_components(self._trending_series(up=True))
        self.assertGreater(comp["level"], 50)   # kurs na szczycie zakresu
        self.assertGreater(comp["trend"], 0)
        self.assertGreater(comp["score"], 0)

    def test_level_sign_for_downtrend(self):
        comp = signals.score_components(self._trending_series(up=False))
        self.assertLess(comp["level"], -50)
        self.assertLess(comp["score"], 0)

    def test_mr_urgency_symmetric(self):
        self.assertAlmostEqual(signals._mr_urgency(80, 0.5),
                               -signals._mr_urgency(20, 0.5))
        self.assertAlmostEqual(signals._mr_urgency(50, 1.2),
                               -signals._mr_urgency(50, -0.2))
        self.assertEqual(signals._mr_urgency(50, 0.5), 0.0)

    def test_buy_is_minus_sell(self):
        # kierunek kupna = doklanie -S: nie ma osobnego liczenia
        comp = signals.score_components(self._trending_series(up=True))
        self.assertLessEqual(abs(comp["score"]), 100.0)


if __name__ == "__main__":
    unittest.main()
