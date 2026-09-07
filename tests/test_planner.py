# -*- coding: utf-8 -*-
"""Testy warstwy decyzyjnej (F101): DCA, przechyl pod carry, omijanie dni
reakcji, pozycje, legacy symulator (backtest)."""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import planner


CFG = {"pair": "EURPLN", "base": "EUR", "quote": "PLN", "label": "EUR/PLN",
       "affected_by": ["EUR", "PLN"], "unit_amount": 10000}


def _sig(current=4.30, p250=80.0, t=0.5):
    return {"current": current, "p250": p250, "trend_t": t, "range80_half": 0.03,
            "score": 0.0}


def _levels(v):
    return {50: v, 70: v, 85: v, 90: v}


class TestCarry(unittest.TestCase):
    def test_sell_eur_for_pln_positive_carry(self):
        rates = {"PLN": 3.75, "EUR": 2.25, "USD": 3.63}
        cw = planner.carry_bps(CFG, True, 14, rates)
        self.assertAlmostEqual(cw, (3.75 - 2.25) / 100 * 14 / 365 * 1e4, places=6)
        self.assertGreater(cw, config.CARRY_TILT_MIN_BPS)
        self.assertEqual(planner.carry_tilt(cw), "front")

    def test_buy_eur_mirror_negative(self):
        rates = {"PLN": 3.75, "EUR": 2.25}
        self.assertEqual(planner.carry_tilt(planner.carry_bps(CFG, False, 14, rates)), "back")

    def test_flat_when_rates_equal(self):
        rates = {"PLN": 3.0, "EUR": 3.0}
        self.assertEqual(planner.carry_tilt(planner.carry_bps(CFG, True, 14, rates)), "flat")

    def test_weights(self):
        self.assertEqual(planner.tranche_weights(4, "front"), [0.4, 0.3, 0.2, 0.1])
        self.assertEqual(planner.tranche_weights(4, "back"), [0.1, 0.2, 0.3, 0.4])
        self.assertEqual(planner.tranche_weights(4, "flat"), [0.25] * 4)
        self.assertEqual(planner.tranche_weights(0, "front"), [])
        for tilt in ("front", "back", "flat"):
            self.assertAlmostEqual(sum(planner.tranche_weights(3, tilt)), 1.0)


class TestCalendar(unittest.TestCase):
    def test_last_safe_date_avoids_event(self):
        bdays = planner.business_days(date(2026, 7, 1))
        self.assertEqual(bdays[-1], date(2026, 7, 14))
        self.assertEqual(planner.last_safe_date(bdays, {"2026-07-14"}), date(2026, 7, 13))
        self.assertEqual(planner.last_safe_date(bdays, set()), date(2026, 7, 14))

    def test_dca_dates_avoid_high_impact(self):
        bdays = planner.business_days(date(2026, 7, 1))
        dates = planner.dca_dates(bdays, {"2026-07-08"}, k=4)
        self.assertEqual(len(dates), 4)
        self.assertNotIn(date(2026, 7, 8), dates)
        self.assertEqual(dates, sorted(dates))

    def test_dca_dates_short_window(self):
        bdays = planner.business_days(date(2026, 7, 1))[:4]
        self.assertLessEqual(len(planner.dca_dates(bdays, set(), k=4)), 3)

    def test_business_days_until(self):
        days = planner.business_days_until(date(2026, 9, 7), date(2026, 9, 11))
        self.assertEqual(len(days), 5)
        self.assertEqual(planner.business_days_until(date(2026, 9, 8), date(2026, 9, 7)), [])


class TestBuildPlan(unittest.TestCase):
    def test_front_loaded_schedule_sums_to_100(self):
        plan = planner.build_plan(CFG, _sig(), [], date(2026, 9, 7), sell=True,
                                  policy_rates={"PLN": 3.75, "EUR": 2.25})
        self.assertEqual(plan["tilt"], "front")
        pcts = [p for _, _, p in plan["schedule"]]
        self.assertEqual(sum(pcts), 100)
        self.assertEqual(pcts, sorted(pcts, reverse=True))
        self.assertEqual(plan["schedule"][0][0], date(2026, 9, 7))
        self.assertIn("transza DCA 40%", plan["today_action"])

    def test_event_reaction_day_skipped(self):
        ev = [{"date": "2026-09-16", "effective_date": "2026-09-17", "source": "Fed",
               "name": "FOMC", "currencies": ["USD"], "impact": "high"}]
        cfg = dict(CFG, pair="USDPLN", base="USD", affected_by=["USD", "PLN"])
        plan = planner.build_plan(cfg, _sig(3.71), ev, date(2026, 9, 7), sell=True,
                                  policy_rates={"PLN": 3.75, "USD": 3.63})
        self.assertNotIn(date(2026, 9, 17), [d for d, _, _ in plan["schedule"]])
        self.assertTrue(any("reakcji" in l for l in plan["lines"]))

    def test_context_mentions_backtest(self):
        rec = {"engine": {"edge_bps_vs_dca": -3.0, "ci90_lo": -6.0, "ci90_hi": 0.0,
                          "n_windows": 680, "verdict": "no_edge"}}
        plan = planner.build_plan(CFG, _sig(), [], date(2026, 9, 7), sell=True,
                                  backtest_rec=rec)
        self.assertTrue(any("nie steruje" in l for l in plan["context"]))


class TestPositionPlan(unittest.TestCase):
    def _pos(self, **kw):
        base = {"id": "P1", "pair": "EURPLN", "direction": "sell", "amount": 10000,
                "deadline": "2026-09-18", "fills": []}
        base.update(kw)
        return base

    def test_open_position_plans_remaining(self):
        pos = self._pos(fills=[{"date": "2026-09-04", "amount": 4000, "rate": 4.32}])
        p = planner.position_plan(pos, CFG, _sig(), [], date(2026, 9, 7),
                                  policy_rates={"PLN": 3.75, "EUR": 2.25})
        self.assertEqual(p["status"], "open")
        self.assertAlmostEqual(p["remaining"], 6000.0)
        self.assertAlmostEqual(sum(s["amount"] for s in p["schedule"]), 6000.0, places=6)
        self.assertAlmostEqual(p["avg_rate"], 4.32)
        self.assertEqual(p["schedule"][0]["date"], date(2026, 9, 7))
        self.assertGreater(p["today_amount"], 0)

    def test_done_position(self):
        pos = self._pos(fills=[{"date": "2026-09-04", "amount": 10000, "rate": 4.32}])
        p = planner.position_plan(pos, CFG, _sig(), [], date(2026, 9, 7))
        self.assertEqual(p["status"], "done")
        self.assertIsNone(p["today_action"])

    def test_overdue_position(self):
        pos = self._pos(deadline="2026-09-04")
        p = planner.position_plan(pos, CFG, _sig(), [], date(2026, 9, 7))
        self.assertEqual(p["status"], "overdue")
        self.assertAlmostEqual(p["today_amount"], 10000.0)
        self.assertIn("wymień", p["today_action"])

    def test_position_avoids_reaction_day(self):
        ev = [{"date": "2026-09-09", "effective_date": "2026-09-09", "source": "NBP",
               "name": "RPP", "currencies": ["PLN"], "impact": "high"}]
        pos = self._pos(deadline="2026-09-11")
        p = planner.position_plan(pos, CFG, _sig(), ev, date(2026, 9, 7))
        self.assertNotIn(date(2026, 9, 9), [s["date"] for s in p["schedule"]])


class TestLegacySimulator(unittest.TestCase):
    """Legacy silnik score zostaje tylko po to, by backtest pokazywal, ze nie
    pobija DCA - jego logika musi byc deterministyczna."""

    def test_wait_converges_to_deadline(self):
        scores = [-100.0] * 10
        rates = [1.0] * 7 + [2.0, 3.0, 4.0]
        got = planner.simulate_window(scores, rates, sell=True, levels_day0=_levels(100.0))
        self.assertAlmostEqual(got, (2.0 + 3.0 + 4.0) / 3.0, places=9)

    def test_strong_executes_70_now(self):
        got = planner.simulate_window([100.0] * 10, [1.0] * 9 + [2.0], sell=True,
                                      levels_day0=_levels(100.0))
        self.assertAlmostEqual(got, 0.7 * 1.0 + 0.3 * 2.0, places=9)

    def test_total_always_fully_executed(self):
        for scores in ([-100.0] * 10, [0.0] * 10, [55.0] * 10):
            got = planner.simulate_window(scores, [3.0] * 10, sell=True,
                                          levels_day0=_levels(100.0))
            self.assertAlmostEqual(got, 3.0, places=9)

    def test_simulate_dca(self):
        self.assertAlmostEqual(planner.simulate_dca([1.0, 2.0, 3.0, 4.0], [0.25] * 4), 2.5)


if __name__ == "__main__":
    unittest.main()
