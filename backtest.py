# -*- coding: utf-8 -*-
"""
Walk-forward backtest na PELNEJ historii (F101).

Okna ROZLACZNE (krok = WINDOW_SESSIONS), zeby srednia i przedzial ufnosci
mialy sens - okna przesuwane o 1 sesje nakladaja sie w 90% i zawyzaja
istotnosc ~3x.

Dla kazdej pary i kierunku liczymy vs DCA (rowne transze):
  engine   - legacy silnik score (plan transz sterowany score, jak w v2)
  day1     - wszystko 1. dnia
  lastday  - wszystko ostatniego dnia
  ceiling  - najlepszy dzien okna (pelna wiedza o przyszlosci) = sufit timingu
Raportujemy srednia (pb), odchylenie, n, t, 90% CI, hit-rate oraz miary
ryzyka: rozrzut wyniku DCA vs lump sum (po to jest DCA).

Osobno "recent": ostatnie BACKTEST_RECENT_SESSIONS sesji (okres, na ktorym
silnik v2 byl strojony) - do porownania z pelna historia.
"""

import json
import math
import os
from datetime import date, datetime

import config
import indicators as ind
import signals
import planner


def _stats(edges):
    n = len(edges)
    if n == 0:
        return None
    mean = sum(edges) / n
    var = sum((e - mean) ** 2 for e in edges) / n
    sd = math.sqrt(var)
    se = sd / math.sqrt(n) if n > 1 else 0.0
    t = mean / se if se > 0 else 0.0
    z = config.BACKTEST_CI_Z
    return {
        "edge_bps_vs_dca": round(mean, 2),
        "sd_bps": round(sd, 1),
        "n_windows": n,
        "t_stat": round(t, 2),
        "ci90_lo": round(mean - z * se, 2),
        "ci90_hi": round(mean + z * se, 2),
        "hit_rate_pct": round(100.0 * sum(1 for e in edges if e > 0) / n, 1),
        "verdict": "edge" if (mean - z * se) > 0 else "no_edge",
    }


def _edge(achieved, bench, sell):
    """Przewaga w pb vs benchmark (dodatnia = lepiej dla kierunku)."""
    if sell:
        return (achieved - bench) / bench * 1e4
    return (bench - achieved) / bench * 1e4


def _direction_windows(values, dates, score_by_t, sell, high_dates, t0s, n_win):
    eng, d1, dl, ceil = [], [], [], []
    lump_vs_d1 = []
    dca_vs_d1 = []
    for t0 in t0s:
        rates_w = values[t0:t0 + n_win]
        dca = sum(rates_w) / n_win
        scores_w = [score_by_t[t] if sell else -score_by_t[t]
                    for t in range(t0, t0 + n_win)]
        w250 = values[t0 - 249:t0 + 1]
        vol_d = ind.realized_vol_daily(values[:t0 + 1], config.VOL_SESSIONS)
        half = config.RANGE_Z * vol_d * math.sqrt(n_win) * values[t0]
        levels = planner.plan_levels(w250, sell, values[t0], half)
        high_next = [dates[t0 + j + 1] in high_dates for j in range(n_win - 1)] + [False]
        achieved = planner.simulate_window(scores_w, rates_w, sell, levels,
                                           high_event_next=high_next)
        eng.append(_edge(achieved, dca, sell))
        d1.append(_edge(rates_w[0], dca, sell))
        dl.append(_edge(rates_w[-1], dca, sell))
        best = max(rates_w) if sell else min(rates_w)
        ceil.append(_edge(best, dca, sell))
        # ryzyko: wynik lump sum ostatniego dnia vs 1. dnia, i DCA vs 1. dnia
        lump_vs_d1.append(_edge(rates_w[-1], rates_w[0], sell))
        dca_vs_d1.append(_edge(dca, rates_w[0], sell))

    def sd(xs):
        if not xs:
            return 0.0
        m = sum(xs) / len(xs)
        return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))

    return {
        "engine": _stats(eng),
        "day1": _stats(d1),
        "lastday": _stats(dl),
        "ceiling_bps": round(sum(ceil) / len(ceil), 1) if ceil else None,
        "sd_lump_bps": round(sd(lump_vs_d1), 1),
        "sd_dca_bps": round(sd(dca_vs_d1), 1),
    }


def run_backtest(series, events, today=None):
    today = today or date.today()
    n_win = config.WINDOW_SESSIONS

    high_by_ccy = {}
    for e in events:
        if e["impact"] != "high":
            continue
        for c in e["currencies"]:
            high_by_ccy.setdefault(c, set()).add(e.get("effective_date", e["date"]))

    results = {"as_of": today.isoformat(),
               "engine_version": config.ENGINE_VERSION,
               "window_sessions": n_win,
               "windows": "non-overlapping",
               "pairs": {}}

    for pcfg in config.PAIRS:
        pair = pcfg["pair"]
        ser = series[pair]
        dates = [d for d, _ in ser]
        values = [v for _, v in ser]
        n = len(values)
        results["pairs"][pair] = {"n_sessions": n}
        if n < config.MIN_HISTORY + n_win:
            continue

        score_by_t = signals.compute_score_series(values)
        high_dates = set()
        for c in pcfg["affected_by"]:
            high_dates |= high_by_ccy.get(c, set())

        # okna rozlaczne od konca (ostatnie okno konczy sie na ostatniej sesji)
        t0s = list(range(n - n_win, config.MIN_HISTORY - 1, -n_win))
        t0s.reverse()
        recent_from = n - config.BACKTEST_RECENT_SESSIONS
        t0s_recent = [t0 for t0 in t0s if t0 >= recent_from]

        rec = results["pairs"][pair]
        rec["period"] = [dates[t0s[0]] if t0s else None, dates[-1]]
        for sell in (True, False):
            key = "sell" if sell else "buy"
            rec[key] = _direction_windows(values, dates, score_by_t, sell,
                                          high_dates, t0s, n_win)
            rec[key]["recent"] = (_direction_windows(values, dates, score_by_t, sell,
                                                     high_dates, t0s_recent, n_win)["engine"]
                                  if len(t0s_recent) >= 5 else None)
    return results


def load_cached(path=None):
    path = path or config.BACKTEST_FILE
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if isinstance(doc, dict) and "pairs" in doc:
                return doc
        except (ValueError, OSError):
            pass
    return None


def save_cached(doc, path=None):
    path = path or config.BACKTEST_FILE
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return path


def _cache_valid(cached, series, today):
    if not cached:
        return False
    if cached.get("engine_version") != config.ENGINE_VERSION:
        return False
    try:
        as_of = datetime.strptime(cached["as_of"], "%Y-%m-%d").date()
    except (KeyError, ValueError):
        return False
    if (today - as_of).days >= config.BACKTEST_MAX_AGE_DAYS:
        return False
    for pcfg in config.PAIRS:
        pair = pcfg["pair"]
        cached_n = (cached["pairs"].get(pair) or {}).get("n_sessions", 0)
        if len(series.get(pair, [])) - cached_n >= config.BACKTEST_MIN_NEW_SESSIONS:
            return False
    return True


def get_backtest(series, events, force=False, path=None, today=None):
    today = today or date.today()
    path = path or config.BACKTEST_FILE
    cached = load_cached(path)
    if not force and _cache_valid(cached, series, today):
        return cached, False
    doc = run_backtest(series, events, today=today)
    save_cached(doc, path)
    return doc, True
