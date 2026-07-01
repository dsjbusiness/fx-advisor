# -*- coding: utf-8 -*-
"""Testy warstwy decyzyjnej: konwergencja do deadline, symulator okna,
omijanie dni wydarzen."""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import planner


def _levels(v):
    return {50: v, 70: v, 85: v, 90: v}


class TestDeadlineConvergence(unittest.TestCase):
    def test_last_session_is_full(self):
        for n in (5, 10, 14):
            self.assertEqual(planner.min_cum_required(n - 1, n), 1.0)

    def test_monotonic(self):
        n = 10
        vals = [planner.min_cum_required(j, n) for j in range(n)]
        self.assertEqual(vals, sorted(vals))
        self.assertEqual(vals[0], 0.0)

    def test_ramp_last_three_sessions(self):
        n = 10
        self.assertEqual(planner.min_cum_required(6, n), 0.0)
        self.assertAlmostEqual(planner.min_cum_required(7, n), 1.0 / 3.0)
        self.assertAlmostEqual(planner.min_cum_required(8, n), 2.0 / 3.0)
        self.assertEqual(planner.min_cum_required(9, n), 1.0)


class TestSimulateWindow(unittest.TestCase):
    def test_wait_converges_to_deadline(self):
        # score bardzo ujemny, alerty nieosiagalne -> wykonanie wylacznie
        # przez rampe deadline: 1/3 @ r7, 1/3 @ r8, 1/3 @ r9
        scores = [-100.0] * 10
        rates = [1.0] * 7 + [2.0, 3.0, 4.0]
        got = planner.simulate_window(scores, rates, sell=True,
                                      levels_day0=_levels(100.0))
        self.assertAlmostEqual(got, (2.0 + 3.0 + 4.0) / 3.0, places=9)

    def test_strong_executes_70_now(self):
        scores = [100.0] * 10
        rates = [1.0] * 9 + [2.0]
        got = planner.simulate_window(scores, rates, sell=True,
                                      levels_day0=_levels(100.0))
        # 70% @ 1.0 dnia 1, reszta 30% na ostatniej sesji @ 2.0
        self.assertAlmostEqual(got, 0.7 * 1.0 + 0.3 * 2.0, places=9)

    def test_limit_fills_at_level(self):
        # strong: 25% zlecenie na 1.2; zamkniecie 1.25 przecina poziom ->
        # wypelnienie po POZIOMIE (konserwatywnie), nie po zamknieciu
        scores = [100.0] * 10
        rates = [1.0, 1.25] + [1.0] * 8
        levels = {50: 1.2, 70: 1.2, 85: 1.2, 90: 1.2}
        got = planner.simulate_window(scores, rates, sell=True, levels_day0=levels)
        self.assertAlmostEqual(got, 0.70 * 1.0 + 0.25 * 1.2 + 0.05 * 1.0, places=9)

    def test_buy_direction_mirror(self):
        # kupno bazy: limit wypelnia sie gdy kurs SPADNIE do poziomu
        scores = [100.0] * 10
        rates = [1.0, 0.8] + [1.0] * 8
        levels = {50: 0.85, 70: 0.85, 85: 0.85, 90: 0.85}
        got = planner.simulate_window(scores, rates, sell=False, levels_day0=levels)
        self.assertAlmostEqual(got, 0.70 * 1.0 + 0.25 * 0.85 + 0.05 * 1.0, places=9)

    def test_event_tomorrow_closes_position_when_favorable(self):
        # jutro (sesja 3) wydarzenie high-impact, score korzystny ->
        # domkniecie na sesji 2; drozsze sesje po wydarzeniu nieuzywane
        scores = [30.0] * 10
        rates = [1.0, 1.0, 1.0] + [5.0] * 7
        high_next = [False, False, True] + [False] * 7
        got = planner.simulate_window(scores, rates, sell=True,
                                      levels_day0=_levels(100.0),
                                      high_event_next=high_next)
        self.assertAlmostEqual(got, 1.0, places=9)

    def test_total_always_fully_executed(self):
        # niezaleznie od sciezki score, achieved jest srednia wazona z wagami
        # sumujacymi sie do 1 -> przy kursie stalym wynik == kurs
        for scores in ([-100.0] * 10, [0.0] * 10, [55.0] * 10,
                       [-100.0] * 5 + [100.0] * 5):
            got = planner.simulate_window(scores, [3.0] * 10, sell=True,
                                          levels_day0=_levels(100.0))
            self.assertAlmostEqual(got, 3.0, places=9)


class TestCalendar(unittest.TestCase):
    def test_last_safe_date_avoids_event(self):
        # 2026-07-01 (sr) + 14 dni -> ostatnia sesja 2026-07-14 (wt)
        bdays = planner.business_days(date(2026, 7, 1))
        self.assertEqual(bdays[-1], date(2026, 7, 14))
        safe = planner.last_safe_date(bdays, {"2026-07-14"})
        self.assertEqual(safe, date(2026, 7, 13))

    def test_last_safe_date_no_event(self):
        bdays = planner.business_days(date(2026, 7, 1))
        self.assertEqual(planner.last_safe_date(bdays, set()), date(2026, 7, 14))

    def test_dca_dates_avoid_high_impact(self):
        bdays = planner.business_days(date(2026, 7, 1))
        high = {"2026-07-08"}  # RPP w srodku okna
        dates = planner.dca_dates(bdays, high, k=4)
        self.assertEqual(len(dates), 4)
        self.assertNotIn(date(2026, 7, 8), dates)
        self.assertEqual(dates, sorted(dates))

    def test_dca_dates_short_window(self):
        bdays = planner.business_days(date(2026, 7, 1))[:4]
        dates = planner.dca_dates(bdays, set(), k=4)
        self.assertLessEqual(len(dates), 3)


class TestPlanLevels(unittest.TestCase):
    def test_levels_always_better_than_today_sell(self):
        # kurs dzis na samym szczycie zakresu - surowy p90 bylby PONIZEJ
        # dzisiejszego kursu; plan_levels musi podniesc poziomy powyzej
        values = [4.0 + 0.001 * i for i in range(250)]
        current = values[-1]
        lv = planner.plan_levels(values, sell=True, current=current,
                                 half_width=0.02)
        for q in (70, 85, 90):
            self.assertGreater(lv[q], current)
        self.assertLessEqual(lv[70], lv[85])
        self.assertLessEqual(lv[85], lv[90])

    def test_levels_always_better_than_today_buy(self):
        values = [4.25 - 0.001 * i for i in range(250)]  # kurs na dnie
        current = values[-1]
        lv = planner.plan_levels(values, sell=False, current=current,
                                 half_width=0.02)
        for q in (70, 85, 90):
            self.assertLess(lv[q], current)
        self.assertGreaterEqual(lv[70], lv[85])
        self.assertGreaterEqual(lv[85], lv[90])

    def test_raw_percentile_kept_when_far_from_top(self):
        # kurs w srodku zakresu: percentyl 90 jest naturalnie lepszy niz
        # dzis i nie powinien byc ruszony
        values = sorted([4.0 + 0.001 * i for i in range(250)])
        current = values[125]
        lv = planner.plan_levels(values, sell=True, current=current,
                                 half_width=0.001)
        import indicators as ind
        self.assertAlmostEqual(lv[90], ind.percentile_level(values, 90))


class TestBuildPlan(unittest.TestCase):
    def _sig(self, score):
        values = [4.0 + 0.001 * i for i in range(250)]
        return {
            "score": score, "current": values[-1], "values250": values,
            "confidence_bucket": "Średnia", "range80_half": 0.02,
        }

    def _cfg(self):
        return {"pair": "EURPLN", "base": "EUR", "quote": "PLN",
                "label": "EUR/PLN", "affected_by": ["EUR", "PLN"],
                "unit_amount": 10000}

    def test_strong_plan_names_final_date(self):
        plan = planner.build_plan(self._cfg(), self._sig(75), [],
                                  date(2026, 7, 1), sell=True)
        self.assertEqual(plan["bucket"], "strong")
        self.assertIsNotNone(plan["today_action"])
        self.assertEqual(plan["final_date"], date(2026, 7, 14))
        self.assertTrue(any("najpozniej" in l for l in plan["lines"]))

    def test_buy_is_mirror(self):
        plan = planner.build_plan(self._cfg(), self._sig(75), [],
                                  date(2026, 7, 1), sell=False)
        self.assertEqual(plan["score"], -75)
        self.assertEqual(plan["bucket"], "wait")
        self.assertIsNone(plan["today_action"])

    def test_backtest_override_forces_dca(self):
        rec = {"edge_bps_vs_dca": -1.5, "hit_rate_pct": 45.0, "n_windows": 100}
        plan = planner.build_plan(self._cfg(), self._sig(75), [],
                                  date(2026, 7, 1), sell=True, backtest_rec=rec)
        self.assertTrue(plan["dca_override"])
        self.assertTrue(any("DCA" in l for l in plan["lines"]))

    def test_event_note_present_when_high_event(self):
        ev = [{"date": "2026-07-08", "source": "NBP", "name": "Decyzja RPP",
               "currencies": ["PLN"], "impact": "high", "days_ahead": 7}]
        plan = planner.build_plan(self._cfg(), self._sig(75), ev,
                                  date(2026, 7, 1), sell=True)
        self.assertIsNotNone(plan["event_note"])
        self.assertIn("PRZED", plan["event_note"])
        self.assertIn("przed NBP 08.07", plan["today_action"])

    def test_final_date_steps_before_event(self):
        # wydarzenie high-impact w ostatnim dniu okna -> final dzien wczesniej
        ev = [{"date": "2026-07-14", "source": "NBP", "name": "Decyzja RPP",
               "currencies": ["PLN"], "impact": "high", "days_ahead": 13}]
        plan = planner.build_plan(self._cfg(), self._sig(0), ev,
                                  date(2026, 7, 1), sell=True)
        self.assertEqual(plan["final_date"], date(2026, 7, 13))


if __name__ == "__main__":
    unittest.main()
