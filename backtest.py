# -*- coding: utf-8 -*-
"""
Walk-forward backtest: narzedzie musi samo udowodnic swoja przewage.

Dla kazdego mozliwego okna 14-dniowego (10 sesji) w calej cache'owanej
historii symulujemy plany transz, ktore silnik wygenerowalby dzien po dniu
(score przeliczany codziennie WYLACZNIE z danych dostepnych danego dnia,
z twarda zasada deadline) i liczymy osiagniety kurs wazony wolumenem.

Benchmarki: (a) wszystko 1. dnia, (b) wszystko ostatniego dnia,
(c) rowne DCA. Raport per para i kierunek: srednia przewaga vs DCA w pb,
hit-rate (% okien lepszych niz DCA), liczba okien.

Cache w data/backtest.json: pelny przelicz najwyzej raz na tydzien albo
gdy przybedzie >= BACKTEST_MIN_NEW_SESSIONS nowych sesji / zmieni sie
wersja silnika.
"""

import json
import os
from datetime import date, datetime

import math

import config
import indicators as ind
import signals
import planner


def _window_metrics(achieved, day1, lastday, dca, sell):
    """Przewaga w punktach bazowych vs benchmarki (dodatnia = lepiej)."""
    if sell:
        e = lambda bench: (achieved - bench) / bench * 10000.0
    else:
        e = lambda bench: (bench - achieved) / bench * 10000.0
    return {"vs_dca": e(dca), "vs_day1": e(day1), "vs_last": e(lastday)}


def run_backtest(series, events, today=None):
    """Pelny przelicz. series = data_layer.series_from_history(...),
    events = data_layer.load_events(). Zwraca dict wynikow."""
    today = today or date.today()
    n_win = config.WINDOW_SESSIONS

    # zbiory dat wydarzen high-impact per waluta
    high_by_ccy = {}
    for e in events:
        if e["impact"] != "high":
            continue
        for c in e["currencies"]:
            high_by_ccy.setdefault(c, set()).add(e["date"])

    results = {"as_of": today.isoformat(),
               "engine_version": config.ENGINE_VERSION,
               "window_sessions": n_win,
               "pairs": {}}

    for pcfg in config.PAIRS:
        pair = pcfg["pair"]
        ser = series[pair]
        dates = [d for d, _ in ser]
        values = [v for _, v in ser]
        n = len(values)
        results["pairs"][pair] = {}
        if n < config.MIN_HISTORY + n_win:
            continue

        score_by_t = signals.compute_score_series(values)
        high_dates = set()
        for c in pcfg["affected_by"]:
            high_dates |= high_by_ccy.get(c, set())

        n_sessions_used = n
        for sell in (True, False):
            edges = []
            for t0 in range(config.MIN_HISTORY, n - n_win + 1):
                rates_w = values[t0:t0 + n_win]
                scores_w = [score_by_t[t] if sell else -score_by_t[t]
                            for t in range(t0, t0 + n_win)]
                w250 = values[t0 - 249:t0 + 1]
                # te same poziomy, ktore plan wypisalby uzytkownikowi 1. dnia
                vol_d = ind.realized_vol_daily(values[:t0 + 1],
                                               config.VOL_SESSIONS)
                half = (config.RANGE_Z * vol_d
                        * math.sqrt(config.WINDOW_SESSIONS) * values[t0])
                levels = planner.plan_levels(w250, sell, values[t0], half)
                high_next = [dates[t0 + j + 1] in high_dates
                             for j in range(n_win - 1)] + [False]
                achieved = planner.simulate_window(
                    scores_w, rates_w, sell, levels, high_event_next=high_next)
                dca = sum(rates_w) / len(rates_w)
                edges.append(_window_metrics(
                    achieved, rates_w[0], rates_w[-1], dca, sell))

            n_windows = len(edges)
            key = "sell" if sell else "buy"
            if n_windows == 0:
                results["pairs"][pair][key] = None
                continue
            mean = lambda k: sum(e[k] for e in edges) / n_windows
            hits = sum(1 for e in edges if e["vs_dca"] > 0)
            results["pairs"][pair][key] = {
                "edge_bps_vs_dca": round(mean("vs_dca"), 2),
                "edge_bps_vs_day1": round(mean("vs_day1"), 2),
                "edge_bps_vs_lastday": round(mean("vs_last"), 2),
                "hit_rate_pct": round(100.0 * hits / n_windows, 1),
                "n_windows": n_windows,
            }
        results["pairs"][pair]["n_sessions"] = n_sessions_used

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
    # przelicz, gdy przybylo duzo nowych sesji
    for pcfg in config.PAIRS:
        pair = pcfg["pair"]
        cached_n = (cached["pairs"].get(pair) or {}).get("n_sessions", 0)
        if len(series.get(pair, [])) - cached_n >= config.BACKTEST_MIN_NEW_SESSIONS:
            return False
    return True


def get_backtest(series, events, force=False, path=None, today=None):
    """Zwraca (wyniki, czy_przeliczono). Dzienne uruchomienie korzysta
    z cache; pelny przelicz raz na tydzien / przy zmianie wersji."""
    today = today or date.today()
    path = path or config.BACKTEST_FILE
    cached = load_cached(path)
    if not force and _cache_valid(cached, series, today):
        return cached, False
    doc = run_backtest(series, events, today=today)
    save_cached(doc, path)
    return doc, True
