# -*- coding: utf-8 -*-
"""
Silnik doradcy walutowego.

Co robi:
  1. Pobiera dzienne kursy referencyjne EBC (EUR/PLN, EUR/USD) z Frankfurter API
     (darmowe, bez klucza, dane EBC). USD/PLN wyliczane jako EUR/PLN / EUR/USD.
  2. Liczy proste, czytelne wska\u017aniki: po\u0142o\u017cenie w zakresie (percentyl + z-score),
     kr\u00f3tk\u0105 tendencj\u0119, RSI, zmienno\u015b\u0107, wst\u0119g\u0119 Bollingera.
  3. Dla ka\u017cdego kierunku wymiany liczy "favorability" (-100..+100 w Twoj\u0105 stron\u0119),
     etykiet\u0119, pewno\u015b\u0107 i rekomendacj\u0119 po polsku - plus sugesti\u0119 podzia\u0142u wymiany.

\u017badnych zewn\u0119trznych bibliotek - tylko biblioteka standardowa Pythona.
To narz\u0119dzie wspiera decyzj\u0119, nie jest prognoz\u0105 ani porad\u0105 inwestycyjn\u0105.
"""

import json
import math
import statistics
import random
from datetime import date, datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import config


# ===========================================================================
# 1. POBIERANIE DANYCH
# ===========================================================================

FRANKFURTER_HOSTS = [
    "https://api.frankfurter.dev/v1",
    "https://api.frankfurter.app",   # zapasowy host
]


def _http_get_json(url, timeout=20):
    req = Request(url, headers={"User-Agent": "fx-advisor/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_timeseries():
    """
    Zwraca dict: {"EURPLN": [(date, val), ...], "EURUSD": [...], "USDPLN": [...]}
    posortowane rosn\u0105co po dacie. Wy\u0142\u0105cznie dni robocze (fixing EBC).
    """
    end = date.today()
    start = end - timedelta(days=config.HISTORY_DAYS)
    path = "/{s}..{e}?base=EUR&symbols=PLN,USD".format(s=start.isoformat(), e=end.isoformat())

    data = None
    last_err = None
    for host in FRANKFURTER_HOSTS:
        try:
            data = _http_get_json(host + path)
            break
        except (URLError, HTTPError, ValueError) as e:
            last_err = e
            continue
    if data is None:
        raise RuntimeError("Nie uda\u0142o si\u0119 pobra\u0107 danych FX: {}".format(last_err))

    rates = data.get("rates", {})
    eurpln, eurusd, usdpln = [], [], []
    for d in sorted(rates.keys()):
        row = rates[d]
        if "PLN" not in row or "USD" not in row:
            continue
        pln = float(row["PLN"])
        usd = float(row["USD"])
        eurpln.append((d, pln))
        eurusd.append((d, usd))
        if usd != 0:
            usdpln.append((d, pln / usd))
    return {"EURPLN": eurpln, "EURUSD": eurusd, "USDPLN": usdpln}


def fetch_timeseries_demo(seed=7):
    """
    Dane syntetyczne (b\u0142\u0105dzenie losowe z lekk\u0105 rewersj\u0105) - do testu offline
    i podgl\u0105du raportu, gdy nie ma dost\u0119pu do sieci. Realistyczne poziomy.
    """
    rng = random.Random(seed)
    n_days = config.HISTORY_DAYS
    # punkty startowe zbli\u017cone do realnych poziom\u00f3w
    eurpln_anchor, eurusd_anchor = 4.28, 1.085
    eurpln_v, eurusd_v = eurpln_anchor, eurusd_anchor
    eurpln, eurusd, usdpln = [], [], []
    today = date.today()
    bdays = []
    d = today - timedelta(days=n_days)
    while d <= today:
        if d.weekday() < 5:  # tylko dni robocze
            bdays.append(d)
        d += timedelta(days=1)
    for d in bdays:
        # mean-reverting random walk
        eurpln_v += 0.18 * (eurpln_anchor - eurpln_v) * 0.05 + rng.gauss(0, 0.012)
        eurusd_v += 0.18 * (eurusd_anchor - eurusd_v) * 0.05 + rng.gauss(0, 0.004)
        ds = d.isoformat()
        eurpln.append((ds, round(eurpln_v, 4)))
        eurusd.append((ds, round(eurusd_v, 4)))
        usdpln.append((ds, round(eurpln_v / eurusd_v, 4)))
    return {"EURPLN": eurpln, "EURUSD": eurusd, "USDPLN": usdpln}


# ===========================================================================
# 2. WSKA\u0179NIKI
# ===========================================================================

def _vals(series):
    return [v for _, v in series]


def sma(values, n):
    if len(values) < n:
        n = len(values)
    return sum(values[-n:]) / n


def percentile_rank(window, current):
    """Jaki % obserwacji w oknie jest <= bie\u017c\u0105cej. 0..100 (100 = najwy\u017cszy)."""
    if not window:
        return 50.0
    below = sum(1 for v in window if v <= current)
    return 100.0 * below / len(window)


def zscore(window, current):
    if len(window) < 2:
        return 0.0
    mu = statistics.fmean(window)
    sd = statistics.pstdev(window)
    if sd == 0:
        return 0.0
    return (current - mu) / sd


def daily_returns(values):
    out = []
    for i in range(1, len(values)):
        if values[i - 1] != 0:
            out.append(values[i] / values[i - 1] - 1.0)
    return out


def realized_vol(values, n):
    rets = daily_returns(values[-(n + 1):]) if len(values) > n else daily_returns(values)
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
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def bollinger_pctb(values, n=20, k=2.0):
    """%B: 0 = dolna wst\u0119ga, 1 = g\u00f3rna. Poza [0,1] = przebicie."""
    if len(values) < n:
        n = len(values)
    window = values[-n:]
    mu = statistics.fmean(window)
    sd = statistics.pstdev(window)
    if sd == 0:
        return 0.5
    upper, lower = mu + k * sd, mu - k * sd
    return (values[-1] - lower) / (upper - lower)


# ===========================================================================
# 3. ANALIZA PARY (niezale\u017cna od kierunku)
# ===========================================================================

def analyze_pair(series):
    values = _vals(series)
    current = values[-1]
    n = min(config.LEVEL_WINDOW, len(values))
    level_window = values[-n:]

    low = min(level_window)
    high = max(level_window)
    mean = statistics.fmean(level_window)
    pct = percentile_rank(level_window, current)     # 0..100
    z = zscore(level_window, current)

    # kr\u00f3tka tendencja: z-score ruchu z TREND_WINDOW dni
    k = config.TREND_WINDOW
    ret_k = (current / values[-1 - k] - 1.0) if len(values) > k and values[-1 - k] != 0 else 0.0
    s1 = statistics.pstdev(daily_returns(values[-(config.VOL_LONG + 1):])) if len(values) > 5 else 0.0
    expected_k_move = s1 * math.sqrt(k) if s1 > 0 else 1e-9
    trend_z = ret_k / expected_k_move
    trend_pair = 100.0 * math.tanh(trend_z / 1.5)     # -100..+100 (dla samej pary)

    ma_fast = sma(values, 5)
    ma_slow = sma(values, 20)

    vol_s = realized_vol(values, config.VOL_SHORT)
    vol_l = realized_vol(values, config.VOL_LONG)
    vol_ratio = (vol_s / vol_l) if vol_l > 0 else 1.0
    vol_elevated = vol_ratio >= config.VOL_ELEVATED_RATIO

    return {
        "current": current,
        "low": low,
        "high": high,
        "mean": mean,
        "pct": pct,
        "z": z,
        "ret_k": ret_k,
        "trend_pair": trend_pair,
        "ma_fast": ma_fast,
        "ma_slow": ma_slow,
        "rsi": rsi(values, config.RSI_PERIOD),
        "pctb": bollinger_pctb(values),
        "vol_short": vol_s,
        "vol_long": vol_l,
        "vol_ratio": vol_ratio,
        "vol_elevated": vol_elevated,
        "spark": values[-config.SPARK_POINTS:],
        "n_level": n,
        "last_date": series[-1][0],
    }


# ===========================================================================
# 4. WYDARZENIA W OKNIE
# ===========================================================================

def events_in_window(window_days=None):
    window_days = window_days or config.WINDOW_DAYS
    today = date.today()
    horizon = today + timedelta(days=window_days)
    out = []
    for ds, bank, ccy, desc, impact in config.EVENTS:
        try:
            ed = datetime.strptime(ds, "%Y-%m-%d").date()
        except ValueError:
            continue
        if today <= ed <= horizon:
            out.append({
                "date": ds,
                "days_ahead": (ed - today).days,
                "bank": bank,
                "currency": ccy,
                "desc": desc,
                "impact": impact,
            })
    out.sort(key=lambda e: e["date"])
    return out


# ===========================================================================
# 5. OCENA KIERUNKU + REKOMENDACJA
# ===========================================================================

def _label_for(score):
    t = config.THRESHOLDS
    if score >= t["strong_pos"]:
        return "Korzystny", "pos"
    if score >= t["mild_pos"]:
        return "Lekko korzystny", "mild-pos"
    if score > t["mild_neg"]:
        return "Neutralny", "neutral"
    if score > t["strong_neg"]:
        return "Lekko niekorzystny", "mild-neg"
    return "Niekorzystny", "neg"


def _confidence(favorability, level_score, trend_score, vol_elevated, has_event):
    conf = 40.0 + 0.5 * abs(favorability)
    if level_score * trend_score < 0:        # sygna\u0142y si\u0119 k\u0142\u00f3c\u0105
        conf -= 20.0
    if vol_elevated:
        conf -= 15.0
    if has_event:
        conf -= 15.0
    conf = max(5.0, min(95.0, conf))
    if conf < 35:
        bucket = "Niska"
    elif conf <= 65:
        bucket = "\u015arednia"
    else:
        bucket = "Wysoka"
    return conf, bucket


def _recommendation(level_score, trend_score, vol_elevated, win_events, affected):
    lvl = "korzystny" if level_score > 15 else ("niekorzystny" if level_score < -15 else "neutralny")
    trd = "popraw" if trend_score > 15 else ("pogorsz" if trend_score < -15 else "plaski")

    if lvl == "korzystny" and trd == "pogorsz":
        action = "Dzia\u0142aj teraz"
        why = "Kurs jest korzystny, ale w ostatnich dniach zaczyna si\u0119 pogarsza\u0107 dla Ciebie. Dobry moment, by nie zwleka\u0107."
    elif lvl == "korzystny" and trd == "popraw":
        action = "Korzystnie - mo\u017cesz roz\u0142o\u017cy\u0107 w czasie"
        why = "Poziom jest dobry i nadal poprawia si\u0119 na Twoj\u0105 korzy\u015b\u0107. Mo\u017cesz wymieni\u0107 cz\u0119\u015b\u0107 teraz, a reszt\u0119 obserwowa\u0107."
    elif lvl == "korzystny":
        action = "Korzystnie - rozs\u0105dny moment"
        why = "Kurs jest w korzystnej cz\u0119\u015bci ostatniego zakresu. Rozs\u0105dny moment na wymian\u0119; rozwa\u017c podzia\u0142 na transze."
    elif lvl == "neutralny":
        action = "Neutralnie - podziel wymian\u0119"
        why = "Kurs jest blisko \u015brodka ostatniego zakresu. Brak wyra\u017anej przewagi - najlepiej podzieli\u0107 wymian\u0119 na transze (u\u015brednianie)."
    elif lvl == "niekorzystny" and trd == "popraw":
        action = "Niekorzystnie, ale poprawia si\u0119"
        why = "Poziom jest s\u0142aby, lecz tendencja idzie w Twoj\u0105 stron\u0119. Je\u015bli mo\u017cesz, poczekaj; je\u015bli musisz - podziel wymian\u0119."
    elif lvl == "niekorzystny" and trd == "pogorsz":
        action = "Niekorzystnie i pogarsza si\u0119"
        why = "Kurs jest s\u0142aby i nadal idzie przeciw Tobie. Je\u015bli nie musisz - wstrzymaj si\u0119; je\u015bli musisz - podziel na mniejsze transze."
    else:
        action = "Niekorzystnie"
        why = "Kurs jest w s\u0142abej cz\u0119\u015bci zakresu. Je\u015bli mo\u017cesz, poczekaj; w razie konieczno\u015bci podziel wymian\u0119."

    notes = []
    if vol_elevated:
        notes.append("Podwy\u017cszona zmienno\u015b\u0107 - tym bardziej dziel wymian\u0119 na mniejsze cz\u0119\u015bci.")
    relevant = [e for e in win_events if e["currency"] in affected]
    if relevant:
        ev = relevant[0]
        notes.append(
            "W oknie wypada {desc} ({bank}, za {d} dni) - mo\u017ce gwa\u0142townie ruszy\u0107 kursem; "
            "rozwa\u017c wymian\u0119 przed posiedzeniem lub podzia\u0142.".format(
                desc=ev["desc"], bank=ev["bank"], d=ev["days_ahead"]))
    return action, why, notes


def evaluate_direction(direction, pair_analysis, win_events):
    a = pair_analysis
    high_good = direction["high_good"]

    # sk\u0142adnik POZIOMU z percentyla (0..100) -> -100..+100 w Twoj\u0105 stron\u0119
    if high_good:
        level_score = (a["pct"] - 50.0) * 2.0
        trend_score = a["trend_pair"]
    else:
        level_score = (50.0 - a["pct"]) * 2.0
        trend_score = -a["trend_pair"]

    favorability = config.W_LEVEL * level_score + config.W_TREND * trend_score
    favorability = max(-100.0, min(100.0, favorability))

    label, label_cls = _label_for(favorability)
    has_event = any(e["currency"] in direction["affected_by"] for e in win_events)
    conf, conf_bucket = _confidence(favorability, level_score, trend_score, a["vol_elevated"], has_event)
    action, why, notes = _recommendation(level_score, trend_score, a["vol_elevated"],
                                         win_events, direction["affected_by"])

    return {
        "direction": direction,
        "favorability": favorability,
        "level_score": level_score,
        "trend_score": trend_score,
        "label": label,
        "label_cls": label_cls,
        "confidence": conf,
        "confidence_bucket": conf_bucket,
        "action": action,
        "why": why,
        "notes": notes,
        "pair": a,
    }


# ===========================================================================
# 6. G\u0141\u00d3WNA ANALIZA
# ===========================================================================

def run_analysis(demo=False):
    series = fetch_timeseries_demo() if demo else fetch_timeseries()
    pair_analyses = {p: analyze_pair(series[p]) for p in ("EURPLN", "EURUSD", "USDPLN")}
    win_events = events_in_window()

    results = []
    for d in config.DIRECTIONS:
        a = pair_analyses[d["pair"]]
        results.append(evaluate_direction(d, a, win_events))

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_date": pair_analyses["EURPLN"]["last_date"],
        "demo": demo,
        "results": results,
        "events": win_events,
        "pairs": pair_analyses,
    }
