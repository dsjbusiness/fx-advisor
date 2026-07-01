# -*- coding: utf-8 -*-
"""
Silnik sygnalow - liczony RAZ NA PARE (nie na kierunek).

Wszystkie skladniki w perspektywie SPRZEDAZY waluty bazowej:
wysoki/rosnacy kurs pary = korzystnie (score dodatni). Kierunek kupna
bazy to dokladnie -S; liczymy raz, renderujemy dwa razy.

Skladniki score S in [-100, +100]:
  level  (0.55) - mieszany percentyl 0.2*p30 + 0.3*p90 + 0.5*p250
  trend  (0.25) - zwrot z 10 sesji / (zmiennosc 20-sesyjna * sqrt(10)),
                  miara t-podobna, zgladzone obciecie tanh
  mr     (0.20) - "pilnosc" z wykupienia/wyprzedania (%B, RSI):
                  skrajne wykupienie przy korzystnym poziomie = realizuj
                  zysk TERAZ (podnosi pilnosc werdyktu, nie pewnosc trwania)
"""

import math

import config
import indicators as ind


def _mr_urgency(rsi_v, pctb):
    """Pilnosc mean-reversion w [-100, +100] (w ukladzie pary:
    + = wykupienie/gorne skrajnosci, - = wyprzedanie/dolne)."""
    u = 0.0
    if rsi_v > 70:
        u += (rsi_v - 70.0) / 30.0 * 100.0
    elif rsi_v < 30:
        u -= (30.0 - rsi_v) / 30.0 * 100.0
    if pctb > 1.0:
        u += min((pctb - 1.0) * 200.0, 100.0)
    elif pctb < 0.0:
        u -= min(-pctb * 200.0, 100.0)
    return ind.clip(u)


def score_components(values):
    """Skladniki score dla prefiksu serii (ostatnia wartosc = 'dzis').
    Zwraca dict z level/trend/mr/score + surowe wskazniki."""
    current = values[-1]

    # --- poziom: mieszany percentyl ---
    pcts = []
    for w in config.LEVEL_WINDOWS:
        window = values[-min(w, len(values)):]
        pcts.append(ind.percentile_rank(window, current))
    blended = sum(w * p for w, p in zip(config.LEVEL_WEIGHTS, pcts))
    level = ind.clip((blended - 50.0) * 2.0)

    # --- trend: t-stat z 10 sesji ---
    k = config.TREND_RET_SESSIONS
    vol_d = ind.realized_vol_daily(values, config.TREND_VOL_SESSIONS)
    if len(values) > k and values[-1 - k] != 0 and vol_d > 0:
        ret_k = current / values[-1 - k] - 1.0
        t = ret_k / (vol_d * math.sqrt(k))
    else:
        t = 0.0
    trend = ind.clip(100.0 * math.tanh(t / config.TREND_TANH_SCALE))

    # --- mean reversion / pilnosc ---
    rsi_v = ind.rsi(values, config.RSI_PERIOD)
    pctb = ind.bollinger_pctb(values, config.BOLL_N, config.BOLL_K)
    mr = _mr_urgency(rsi_v, pctb)

    score = ind.clip(config.W_LEVEL * level + config.W_TREND * trend
                     + config.W_MR * mr)
    return {
        "p30": pcts[0], "p90": pcts[1], "p250": pcts[2],
        "level": level, "trend": trend, "trend_t": t,
        "rsi": rsi_v, "pctb": pctb, "mr": mr,
        "vol_daily": vol_d,
        "score": score,
    }


def vol_regime(values):
    """Rezim zmiennosci: 20-sesyjna zmiennosc zannualizowana vs wlasny
    rozklad z ~1 roku. Zwraca (vol_annual, regime) gdzie regime in
    {'low','normal','high'}."""
    n = config.VOL_SESSIONS
    cur = ind.realized_vol_daily(values, n)
    vol_ann = cur * math.sqrt(252)
    hist = []
    lookback = min(config.VOL_REGIME_LOOKBACK, len(values) - n - 1)
    for i in range(lookback):
        end = len(values) - i
        hist.append(ind.realized_vol_daily(values[:end], n))
    if len(hist) < 30 or cur == 0:
        return vol_ann, "normal"
    p = ind.percentile_rank(hist, cur)
    if p >= config.VOL_HIGH_PCT:
        return vol_ann, "high"
    if p <= config.VOL_LOW_PCT:
        return vol_ann, "low"
    return vol_ann, "normal"


def confidence(comp, regime):
    """Pewnosc z zgodnosci sygnalow i rezimu zmiennosci.
    Zwraca (0..100, 'Wysoka'/'Srednia'/'Niska' po polsku)."""
    agree = comp["level"] * comp["trend"] > 0
    conf = 45.0 + 0.25 * abs(comp["score"]) + (12.0 if agree else -12.0)
    if regime == "high":
        conf -= 18.0
    elif regime == "low":
        conf += 6.0
    conf = max(5.0, min(95.0, conf))
    if conf < 40:
        bucket = "Niska"
    elif conf <= 65:
        bucket = "Średnia"
    else:
        bucket = "Wysoka"
    return conf, bucket


def expected_range(current, vol_daily):
    """80% przedzial na koniec okna (10 sesji): kurs +/- 1.28*sigma*sqrt(10).
    Zwraca (lo, hi, half_width)."""
    half = config.RANGE_Z * vol_daily * math.sqrt(config.WINDOW_SESSIONS) * current
    return current - half, current + half, half


def compute_pair_signal(series):
    """Pelny sygnal dla pary. series = [(date_str, value), ...].
    Perspektywa: sprzedaz waluty bazowej (kierunek kupna = -score)."""
    dates = [d for d, _ in series]
    values = [v for _, v in series]
    comp = score_components(values)
    vol_ann, regime = vol_regime(values)
    conf, conf_bucket = confidence(comp, regime)
    lo80, hi80, half = expected_range(values[-1], comp["vol_daily"])

    n250 = min(250, len(values))
    w250 = values[-n250:]
    prev = values[-2] if len(values) >= 2 else values[-1]

    sig = dict(comp)
    sig.update({
        "current": values[-1],
        "prev": prev,
        "change_pct": (values[-1] / prev - 1.0) * 100.0 if prev else 0.0,
        "last_date": dates[-1],
        "vol_annual": vol_ann,
        "vol_regime": regime,
        "confidence": conf,
        "confidence_bucket": conf_bucket,
        "range80_lo": lo80,
        "range80_hi": hi80,
        "range80_half": half,
        "spark_values": w250,
        "spark_dates": dates[-n250:],
        "p10_level": ind.percentile_level(w250, 10),
        "p90_level": ind.percentile_level(w250, 90),
        "mean250": sum(w250) / len(w250),
        "values250": w250,
        "n_sessions": len(values),
    })
    return sig


def compute_score_series(values, start=None):
    """Score S (sprzedaz bazy) dla kazdego t >= start, liczony wylacznie
    z danych do t wlacznie (walk-forward, bez zagladania w przyszlosc).
    Zwraca dict {index: score}."""
    start = start if start is not None else config.MIN_HISTORY
    out = {}
    for t in range(start, len(values)):
        out[t] = score_components(values[:t + 1])["score"]
    return out
