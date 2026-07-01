# -*- coding: utf-8 -*-
"""
Czysta matematyka wskaznikow (funkcje bez stanu, latwe do testow).
Wylacznie biblioteka standardowa.
"""

import math
import statistics


def clip(v, lo=-100.0, hi=100.0):
    return max(lo, min(hi, v))


def percentile_rank(window, current):
    """Jaki % obserwacji w oknie jest <= biezacej. 0..100 (100 = najwyzszy)."""
    if not window:
        return 50.0
    below = sum(1 for v in window if v <= current)
    return 100.0 * below / len(window)


def percentile_level(window, q):
    """Wartosc na q-tym percentylu okna (interpolacja liniowa), q w 0..100."""
    if not window:
        return 0.0
    xs = sorted(window)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q / 100.0
    i = int(math.floor(pos))
    frac = pos - i
    if i + 1 >= len(xs):
        return xs[-1]
    return xs[i] + (xs[i + 1] - xs[i]) * frac


def daily_returns(values):
    out = []
    for i in range(1, len(values)):
        if values[i - 1] != 0:
            out.append(values[i] / values[i - 1] - 1.0)
    return out


def realized_vol_daily(values, n=20):
    """Odchylenie std. dziennych zwrotow z ostatnich n sesji."""
    rets = daily_returns(values[-(n + 1):])
    if len(rets) < 2:
        return 0.0
    return statistics.pstdev(rets)


def rsi(values, period=14):
    if len(values) <= period:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(values)):
        ch = values[i] - values[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_gain == 0 and avg_loss == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def bollinger_pctb(values, n=20, k=2.0):
    """%B: 0 = dolna wstega, 1 = gorna. Poza [0,1] = przebicie wstegi."""
    if len(values) < 2:
        return 0.5
    if len(values) < n:
        n = len(values)
    window = values[-n:]
    mu = statistics.fmean(window)
    sd = statistics.pstdev(window)
    if sd == 0:
        return 0.5
    upper, lower = mu + k * sd, mu - k * sd
    return (values[-1] - lower) / (upper - lower)


def sma(values, n):
    if not values:
        return 0.0
    if len(values) < n:
        n = len(values)
    return sum(values[-n:]) / n
