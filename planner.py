# -*- coding: utf-8 -*-
"""
Warstwa decyzyjna: mapowanie (score, pewnosc, wydarzenia w oknie) na
KONKRETNY plan transz - procenty, poziomy kursu, daty.

Zasady (score s dla danego kierunku; kierunek kupna bazy ma s = -S pary):
  s >= 60          : 70% dzis; 25% zlecenie/alert na 90. percentylu
                     korzystnosci (250 sesji); reszta do ostatniego
                     bezpiecznego dnia.
  20 <= s < 60     : 45% dzis; reszta w 2 transzach na poziomach
                     70. i 85. percentyla korzystnosci.
  -20 < s < 20     : uczciwe DCA - 3-4 rowne transze w konkretnych dniach,
                     z pominieciem dni wydarzen high-impact.
  -60 < s <= -20   : wymieniaj tylko to, co operacyjnie konieczne;
                     alerty na 50. i 70. percentylu korzystnosci.
  s <= -60         : czekaj; alerty na poziomach jak wyzej.

TWARDA ZASADA DEADLINE (zawsze aktywna): calosc musi byc wymieniona do
konca okna 14 dni. Plan wskazuje ostatni dzien wykonania i nie moze on
wypadac w dniu wydarzenia high-impact dla pary - wtedy sesja wczesniej.
Im mniej dni zostalo, tym plany zbiegaja do wykonania niezaleznie od score.

Ten modul zawiera tez symulator okna (simulate_window) uzywany przez
backtest - ta sama logika transz, przeliczana dzien po dniu.
"""

from datetime import date, datetime, timedelta

import config
import indicators as ind

WEEKDAYS_PL = ["pn", "wt", "śr", "cz", "pt", "so", "nd"]


# ===========================================================================
# KALENDARZ OKNA
# ===========================================================================

def business_days(start, window_days=None):
    """Dni robocze (pn-pt) w oknie [start, start + window_days - 1]."""
    window_days = window_days or config.WINDOW_DAYS
    out = []
    for i in range(window_days):
        d = start + timedelta(days=i)
        if d.weekday() < 5:
            out.append(d)
    return out


def last_safe_date(bdays, high_event_dates):
    """Ostatni dzien wykonania: ostatnia sesja okna, ktora NIE jest dniem
    wydarzenia high-impact - jesli jest, cofamy sie o sesje."""
    for d in reversed(bdays):
        if d.isoformat() not in high_event_dates:
            return d
    return bdays[-1] if bdays else None


def dca_dates(bdays, high_event_dates, k=4):
    """3-4 rowne transze rozlozone po oknie, z pominieciem dni high-impact."""
    avail = [d for d in bdays if d.isoformat() not in high_event_dates]
    if not avail:
        avail = list(bdays)
    if len(avail) < 6:
        k = min(3, len(avail))
    k = max(1, min(k, len(avail)))
    if k == 1:
        return [avail[0]]
    idxs = sorted({round(i * (len(avail) - 1) / (k - 1)) for i in range(k)})
    return [avail[i] for i in idxs]


def fmt_date(d):
    return "{:02d}.{:02d} ({})".format(d.day, d.month, WEEKDAYS_PL[d.weekday()])


# ===========================================================================
# POZIOMY I FRAKCJE
# ===========================================================================

def favorable_level(values250, q, sell):
    """Kurs na q-tym percentylu KORZYSTNOSCI kierunku (q=90 -> poziom
    lepszy niz 90% sesji z 250 dni). Dla sprzedazy bazy korzystny jest
    wysoki kurs (percentyl q), dla kupna niski (percentyl 100-q)."""
    return ind.percentile_level(values250, q if sell else 100.0 - q)


def direction_levels(values250, sell):
    return {q: favorable_level(values250, q, sell) for q in (50, 70, 85, 90)}


def plan_levels(values250, sell, current, half_width):
    """Poziomy zlecen/alertow do planu. Percentyle korzystnosci z 250 sesji,
    ale zawsze LEPSZE niz dzisiejszy kurs - gdy kurs jest juz powyzej
    percentyla (np. dzis na p95), zlecenie na p90 byloby bez sensu; wtedy
    poziom podnosimy o czesc oczekiwanego zakresu 14-dniowego."""
    lv = direction_levels(values250, sell)
    sgn = 1.0 if sell else -1.0
    bump = {70: 0.20, 85: 0.35, 90: 0.50}
    for q, frac in bump.items():
        cand = current + sgn * frac * half_width
        lv[q] = max(lv[q], cand) if sell else min(lv[q], cand)
    # zachowaj monotonicznosc korzystnosci: lv70 <= lv85 <= lv90 (dla sell)
    if sell:
        lv[85] = max(lv[85], lv[70])
        lv[90] = max(lv[90], lv[85])
    else:
        lv[85] = min(lv[85], lv[70])
        lv[90] = min(lv[90], lv[85])
    return lv


def bucket_name(s):
    if s >= config.S_STRONG:
        return "strong"
    if s >= config.S_MILD:
        return "mild"
    if s > -config.S_MILD:
        return "neutral"
    if s > -config.S_STRONG:
        return "weak"
    return "wait"


def bucket_base_fraction(s, j, n):
    """Docelowa skumulowana frakcja wymieniona po sesji j (0-index) z n sesji,
    wynikajaca z samego score (bez zasady deadline)."""
    b = bucket_name(s)
    if b == "strong":
        return 0.70
    if b == "mild":
        return 0.45
    if b == "neutral":
        return (j + 1) / float(n)
    if b == "weak":
        return 0.10
    return 0.0


def min_cum_required(j, n):
    """Twarda konwergencja do deadline: ostatnie 3 sesje okna domykaja
    pozycje liniowo, ostatnia sesja = 100%. Monotonicznie rosnaca."""
    if n <= 1 or j >= n - 1:
        return 1.0
    ramp = j - (n - 4)
    return max(0.0, min(1.0, ramp / 3.0))


def limit_program(s, levels):
    """Transze zlecen/alertow ustawiane pierwszego dnia okna.
    Zwraca [(frakcja, poziom_kursu, percentyl_korzystnosci), ...]."""
    b = bucket_name(s)
    if b == "strong":
        return [(0.25, levels[90], 90)]
    if b == "mild":
        return [(0.30, levels[70], 70), (0.25, levels[85], 85)]
    if b == "weak":
        return [(0.45, levels[50], 50), (0.45, levels[70], 70)]
    if b == "wait":
        return [(0.50, levels[50], 50), (0.50, levels[70], 70)]
    return []


# ===========================================================================
# SYMULATOR OKNA (uzywany przez backtest; ta sama logika co plan)
# ===========================================================================

def simulate_window(scores, rates, sell, levels_day0, high_event_next=None):
    """Symuluje wykonanie planu w oknie n sesji, dzien po dniu.

    scores  - score kierunku na kazda sesje (przeliczany codziennie,
              wylacznie z danych dostepnych danego dnia)
    rates   - kursy zamkniecia sesji okna
    sell    - True: sprzedaz bazy (korzystny wysoki kurs)
    levels_day0 - poziomy percentylowe z dnia 1 ({50:..,70:..,85:..,90:..})
    high_event_next - opcjonalna lista bool: czy NASTEPNA sesja jest dniem
              wydarzenia high-impact dla pary

    Zwraca osiagniety kurs wazony wolumenem (suma frakcji = 1).
    """
    n = len(rates)
    program = limit_program(scores[0], levels_day0)
    filled = [False] * len(program)
    executed = 0.0
    cost = 0.0

    for j in range(n):
        s, r = scores[j], rates[j]

        # 1) zlecenia z limitem: wypelnienie po POZIOMIE (konserwatywnie),
        #    gdy zamkniecie przekroczy poziom w korzystna strone
        for idx, (frac, lvl, _q) in enumerate(program):
            if filled[idx] or executed >= 1.0:
                continue
            hit = (r >= lvl) if sell else (r <= lvl)
            if hit:
                amt = min(frac, 1.0 - executed)
                executed += amt
                cost += amt * lvl
                filled[idx] = True

        # 2) docelowa frakcja skumulowana: score + twarda zasada deadline
        target = max(bucket_base_fraction(s, j, n), min_cum_required(j, n))
        if high_event_next is not None and j < n - 1 and high_event_next[j] and s > 0:
            # jutro wydarzenie high-impact, poziom korzystny -> zamknij przed
            target = 1.0
        if j == n - 1:
            target = 1.0

        if target > executed:
            amt = min(target, 1.0) - executed
            executed += amt
            cost += amt * r

    return cost


# ===========================================================================
# PLAN NA DZIS (widok na zywo)
# ===========================================================================

def _verdict(s):
    if s >= config.S_MILD:
        return "Korzystnie", "pos"
    if s > -config.S_MILD:
        return "Neutralnie", "neutral"
    return "Niekorzystnie", "neg"


def _fmt_rate(v):
    return "{:.4f}".format(v)


def _dca_lines(bdays, high_dates, current):
    dates = dca_dates(bdays, high_dates)
    pct = 100 // len(dates)
    rest = 100 - pct * (len(dates) - 1)
    parts = []
    for i, d in enumerate(dates):
        p = rest if i == len(dates) - 1 else pct
        parts.append("{}% - {}".format(p, fmt_date(d)))
    return dates, ["DCA w {} rownych transzach: {}".format(len(dates), "; ".join(parts)),
                   "Pierwsza transza dzis po kursie rynkowym (~{})".format(_fmt_rate(current))]


def build_plan(pair_cfg, sig, win_events, today, sell, backtest_rec=None):
    """Buduje konkretny plan transz dla jednego kierunku pary.

    pair_cfg     - wpis z config.PAIRS
    sig          - sygnal pary z signals.compute_pair_signal
    win_events   - wydarzenia w oknie (data_layer.events_in_window)
    today        - date
    sell         - True: sprzedaz bazy, False: kupno bazy (s = -S)
    backtest_rec - wynik backtestu dla tego kierunku (dict albo None);
                   edge <= 0 wymusza uczciwe zalecenie DCA
    """
    s = sig["score"] if sell else -sig["score"]
    base, quote = pair_cfg["base"], pair_cfg["quote"]
    dir_label = "Sprzedajesz {} → kupujesz {}".format(base if sell else quote,
                                                      quote if sell else base)
    current = sig["current"]
    values250 = sig["values250"]
    levels = plan_levels(values250, sell, current, sig.get("range80_half", 0.0))

    pair_events = [e for e in win_events
                   if any(c in pair_cfg["affected_by"] for c in e["currencies"])]
    high_events = [e for e in pair_events if e["impact"] == "high"]
    high_dates = {e["date"] for e in high_events}

    bdays = business_days(today)
    final_date = last_safe_date(bdays, high_dates)
    bucket = bucket_name(s)
    verdict, verdict_cls = _verdict(s)

    lines = []
    today_action = None
    dca_sched = None

    # --- uczciwosc backtestu: brak przewagi -> zalecamy DCA ---
    dca_override = bool(backtest_rec and backtest_rec.get("edge_bps_vs_dca") is not None
                        and backtest_rec["edge_bps_vs_dca"] <= 0)

    if dca_override:
        dca_sched, dca_l = _dca_lines(bdays, high_dates, current)
        lines.append("Backtest nie wykazal przewagi sygnalu dla tego kierunku "
                     "({:+.0f} pb vs DCA) - uczciwe zalecenie: DCA.".format(
                         backtest_rec["edge_bps_vs_dca"]))
        lines.extend(dca_l)
        if today in dca_sched:
            today_action = "transza DCA {}% po ~{}".format(
                100 // len(dca_sched), _fmt_rate(current))
    elif bucket == "strong":
        lines.append("Dzis: wymien 70% po kursie rynkowym (~{})".format(_fmt_rate(current)))
        lines.append("25%: zlecenie/alert na {} (cel: 90. percentyl korzystnosci "
                     "z 250 sesji, zawsze lepiej niz dzis)".format(_fmt_rate(levels[90])))
        lines.append("Pozostale 5% - najpozniej {}".format(fmt_date(final_date)))
        today_action = "wymien 70% po ~{}".format(_fmt_rate(current))
    elif bucket == "mild":
        lines.append("Dzis: wymien 45% po kursie rynkowym (~{})".format(_fmt_rate(current)))
        lines.append("30%: zlecenie/alert na {} (cel: 70. percentyl korzystnosci)".format(
            _fmt_rate(levels[70])))
        lines.append("25%: zlecenie/alert na {} (cel: 85. percentyl korzystnosci)".format(
            _fmt_rate(levels[85])))
        lines.append("Niezrealizowane transze - najpozniej {}".format(fmt_date(final_date)))
        today_action = "wymien 45% po ~{}".format(_fmt_rate(current))
    elif bucket == "neutral":
        dca_sched, dca_l = _dca_lines(bdays, high_dates, current)
        lines.append("Brak wyraznej przewagi - uczciwa odpowiedz to usrednianie.")
        lines.extend(dca_l)
        if today in dca_sched:
            today_action = "transza DCA {}% po ~{}".format(
                100 // len(dca_sched), _fmt_rate(current))
    elif bucket == "weak":
        lines.append("Wymien teraz tylko to, co operacyjnie konieczne (ok. 10%).")
        lines.append("Alert: {} (50. percentyl korzystnosci) - wymien ok. 45%".format(
            _fmt_rate(levels[50])))
        lines.append("Alert: {} (70. percentyl korzystnosci) - wymien kolejne 45%".format(
            _fmt_rate(levels[70])))
        lines.append("Calosc bezwzglednie do {} (twarda zasada okna)".format(
            fmt_date(final_date)))
    else:  # wait
        lines.append("Czekaj - kurs w niekorzystnej czesci zakresu.")
        lines.append("Alert: {} (50. percentyl korzystnosci) - wymien ok. 50%".format(
            _fmt_rate(levels[50])))
        lines.append("Alert: {} (70. percentyl korzystnosci) - reszta".format(
            _fmt_rate(levels[70])))
        lines.append("Calosc bezwzglednie do {} (twarda zasada okna)".format(
            fmt_date(final_date)))

    # --- wydarzenia: kazdy plan mowi wprost, czy wykonac przed ---
    event_note = None
    if high_events:
        ev = high_events[0]
        ed = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        ev_txt = "{} ({}, {})".format(ev["name"], ev["source"], fmt_date(ed))
        if s >= config.S_MILD:
            event_note = ("Wykonaj zaplanowane transze PRZED: {}. Poziom jest juz "
                          "korzystny - asymetria: zdarzenie moze zabrac wiecej, niz da. "
                          "Zabezpiecz to, co masz na stole.").format(ev_txt)
            if today_action:
                today_action += ", przed {} {:02d}.{:02d}".format(
                    ev["source"], ed.day, ed.month)
        elif s > -config.S_MILD:
            event_note = ("W oknie wypada {}. Transze DCA omijaja ten dzien - "
                          "nie wymieniaj w sam dzien publikacji.").format(ev_txt)
        else:
            event_note = ("Czekasz na lepszy poziom, ale {} moze ruszyc kursem "
                          "w obie strony. Nie planuj wymiany na sam dzien "
                          "publikacji; ostatni bezpieczny dzien to {}.").format(
                              ev_txt, fmt_date(final_date))

    return {
        "direction_label": dir_label,
        "sell": sell,
        "score": s,
        "bucket": bucket,
        "verdict": verdict,
        "verdict_cls": verdict_cls,
        "confidence_bucket": sig["confidence_bucket"],
        "lines": lines,
        "today_action": today_action,
        "final_date": final_date,
        "event_note": event_note,
        "levels": levels,
        "dca_dates": dca_sched,
        "dca_override": dca_override,
        "backtest_rec": backtest_rec,
        "pair": pair_cfg["pair"],
    }
