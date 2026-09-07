# -*- coding: utf-8 -*-
"""
Warstwa decyzyjna (F101).

Polityka domyslna - bez przewidywania kursu:
  1. DCA: rowne transze rozlozone po dostepnych sesjach okna,
     z pominieciem efektywnych dni wydarzen high-impact dla pary.
  2. Przechyl pod carry: jesli waluta DOCELOWA ma wyzsza stope niz zrodlowa,
     wczesniejsze wykonanie ma dodatnia wartosc oczekiwana (roznica stop x
     dni/365). Wtedy wagi transz maleja liniowo (front-load); przy ujemnym
     carry rosna (back-load). Warunek: gotowka lezy na oprocentowanym
     rachunku - inaczej carry nie istnieje.
  3. Twardy deadline: calosc do konca okna / do deadline pozycji.

Score z signals.py nie steruje transzami. Zostaje jako kontekst.

Modul zawiera tez symulatory uzywane przez backtest: legacy silnik score
(simulate_window - zeby pokazywac, ze nie pobija DCA) i DCA (simulate_dca).
"""

from datetime import date, datetime, timedelta

import config
import indicators as ind

WEEKDAYS_PL = ["pn", "wt", "śr", "cz", "pt", "so", "nd"]


# ===========================================================================
# KALENDARZ
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


def business_days_until(start, deadline):
    """Dni robocze w [start, deadline] wlacznie (pusta lista, gdy deadline
    przed start)."""
    out = []
    d = start
    while d <= deadline:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def last_safe_date(bdays, high_event_dates):
    """Ostatnia sesja okna, ktora nie jest efektywnym dniem wydarzenia."""
    for d in reversed(bdays):
        if d.isoformat() not in high_event_dates:
            return d
    return bdays[-1] if bdays else None


def dca_dates(bdays, high_event_dates, k=None):
    """k transz rozlozonych rownomiernie po sesjach bez wydarzen high-impact."""
    k = k or config.DCA_TRANCHES
    avail = [d for d in bdays if d.isoformat() not in high_event_dates]
    if not avail:
        avail = list(bdays)
    if not avail:
        return []
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
# CARRY
# ===========================================================================

def carry_bps(pair_cfg, sell, days, policy_rates):
    """Oczekiwany zysk (pb) z wykonania DZIS zamiast za `days` dni:
    (stopa waluty docelowej - stopa waluty zrodlowej) x days/365."""
    base, quote = pair_cfg["base"], pair_cfg["quote"]
    target, source = (quote, base) if sell else (base, quote)
    r_t = float(policy_rates.get(target, 0.0))
    r_s = float(policy_rates.get(source, 0.0))
    return (r_t - r_s) / 100.0 * days / 365.0 * 1e4


def carry_tilt(carry_window_bps):
    """'front' / 'back' / 'flat' w zaleznosci od carry na cale okno."""
    if carry_window_bps >= config.CARRY_TILT_MIN_BPS:
        return "front"
    if carry_window_bps <= -config.CARRY_TILT_MIN_BPS:
        return "back"
    return "flat"


def tranche_weights(k, tilt):
    """Wagi k transz sumujace sie do 1. front: malejace liniowo (k..1),
    back: rosnace, flat: rowne."""
    if k <= 0:
        return []
    if tilt == "front":
        raw = [k - i for i in range(k)]
    elif tilt == "back":
        raw = [i + 1 for i in range(k)]
    else:
        raw = [1.0] * k
    s = float(sum(raw))
    return [r / s for r in raw]


# ===========================================================================
# HARMONOGRAM DCA
# ===========================================================================

def dca_schedule(bdays, high_dates, tilt, k=None):
    """[(date, waga), ...] - k transz w dostepnych sesjach z wagami wg tilt."""
    dates = dca_dates(bdays, high_dates, k)
    w = tranche_weights(len(dates), tilt)
    return list(zip(dates, w))


def _pct_parts(schedule):
    """Wagi -> calkowite procenty sumujace sie do 100."""
    pcts = [int(round(w * 100)) for _, w in schedule]
    diff = 100 - sum(pcts)
    if pcts:
        pcts[-1] += diff
    return pcts


# ===========================================================================
# SYMULATORY (backtest)
# ===========================================================================

def simulate_dca(rates, weights):
    """Kurs wazony wolumenem dla transz na sesjach rates[i] z wagami."""
    return sum(w * r for w, r in zip(weights, rates))


# --- legacy silnik score (zachowany wylacznie do backtestu) ---

def favorable_level(values250, q, sell):
    return ind.percentile_level(values250, q if sell else 100.0 - q)


def direction_levels(values250, sell):
    return {q: favorable_level(values250, q, sell) for q in (50, 70, 85, 90)}


def plan_levels(values250, sell, current, half_width):
    lv = direction_levels(values250, sell)
    sgn = 1.0 if sell else -1.0
    bump = {70: 0.20, 85: 0.35, 90: 0.50}
    for q, frac in bump.items():
        cand = current + sgn * frac * half_width
        lv[q] = max(lv[q], cand) if sell else min(lv[q], cand)
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
    if n <= 1 or j >= n - 1:
        return 1.0
    ramp = j - (n - 4)
    return max(0.0, min(1.0, ramp / 3.0))


def limit_program(s, levels):
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


def simulate_window(scores, rates, sell, levels_day0, high_event_next=None):
    """Legacy: plan transz sterowany score, dzien po dniu (jak w v2)."""
    n = len(rates)
    program = limit_program(scores[0], levels_day0)
    filled = [False] * len(program)
    executed = 0.0
    cost = 0.0
    for j in range(n):
        s, r = scores[j], rates[j]
        for idx, (frac, lvl, _q) in enumerate(program):
            if filled[idx] or executed >= 1.0:
                continue
            hit = (r >= lvl) if sell else (r <= lvl)
            if hit:
                amt = min(frac, 1.0 - executed)
                executed += amt
                cost += amt * lvl
                filled[idx] = True
        target = max(bucket_base_fraction(s, j, n), min_cum_required(j, n))
        if high_event_next is not None and j < n - 1 and high_event_next[j] and s > 0:
            target = 1.0
        if j == n - 1:
            target = 1.0
        if target > executed:
            amt = min(target, 1.0) - executed
            executed += amt
            cost += amt * r
    return cost


# ===========================================================================
# KONTEKST (score jako informacja)
# ===========================================================================

def context_lines(sig, sell, backtest_rec=None):
    """Zdania kontekstu dla kierunku - bez zalecen wykonawczych."""
    p = sig["p250"] if sell else 100.0 - sig["p250"]
    t = sig["trend_t"] if sell else -sig["trend_t"]
    lines = ["Kurs jest korzystniejszy niż {:.0f}% sesji z ostatniego roku "
             "(percentyl korzystności 250 sesji).".format(p)]
    if abs(t) >= 1.0:
        lines.append("Tendencja z 10 sesji: {:+.1f}σ {} - to opis, nie prognoza."
                     .format(t, "na Twoją korzyść" if t > 0 else "na Twoją niekorzyść"))
    if backtest_rec and backtest_rec.get("engine"):
        eng = backtest_rec["engine"]
        lines.append("Aktywny plan sterowany tym kontekstem na pełnej historii "
                     "({} okien rozłącznych): {:+.1f} pb vs DCA, 90% przedział "
                     "[{:+.1f}; {:+.1f}] - dlatego nie steruje transzami."
                     .format(eng["n_windows"], eng["edge_bps_vs_dca"],
                             eng["ci90_lo"], eng["ci90_hi"]))
    return lines


# ===========================================================================
# PLAN-SZABLON NA OKNO 14 DNI (na karcie pary)
# ===========================================================================

def build_plan(pair_cfg, sig, events, today, sell, policy_rates=None,
               backtest_rec=None, window_days=None):
    """Plan-szablon: 'gdybys dzis zaczynal okno 14 dni w tym kierunku'.
    events = pelna lista wydarzen (z effective_date)."""
    policy_rates = policy_rates or config.POLICY_RATES
    window_days = window_days or config.WINDOW_DAYS
    base, quote = pair_cfg["base"], pair_cfg["quote"]
    dir_label = "Sprzedajesz {} → kupujesz {}".format(base if sell else quote,
                                                      quote if sell else base)
    current = sig["current"]
    bdays = business_days(today, window_days)
    # okno po DNIU REAKCJI: NFP z piatku przed oknem reaguje w poniedzialek
    end_iso = (today + timedelta(days=window_days - 1)).isoformat()
    win = [e for e in events
           if today.isoformat() <= e.get("effective_date", e["date"]) <= end_iso]
    pair_events = [e for e in win if any(c in pair_cfg["affected_by"]
                                         for c in e["currencies"])]
    high_events = [e for e in pair_events if e["impact"] == "high"]
    high_dates = {e.get("effective_date", e["date"]) for e in high_events}
    final_date = last_safe_date(bdays, high_dates)

    cw = carry_bps(pair_cfg, sell, window_days, policy_rates)
    tilt = carry_tilt(cw)
    schedule = dca_schedule(bdays, high_dates, tilt)
    pcts = _pct_parts(schedule)

    lines = []
    parts = ["{}% - {}".format(p, fmt_date(d)) for (d, _), p in zip(schedule, pcts)]
    lines.append("DCA w {} transzach: {}".format(len(schedule), "; ".join(parts)))
    target, source = (quote, base) if sell else (base, quote)
    if tilt == "front":
        lines.append("Przechył na początek okna: {} oprocentowany wyżej niż {} "
                     "(carry ok. {:+.0f} pb na {} dni). Działa tylko, gdy {} "
                     "leży na oprocentowanym rachunku.".format(
                         target, source, cw, window_days, target))
    elif tilt == "back":
        lines.append("Przechył na koniec okna: {} oprocentowany niżej niż {} "
                     "(carry ok. {:+.0f} pb na {} dni) - trzymaj {} jak najdłużej, "
                     "o ile leży na oprocentowanym rachunku.".format(
                         target, source, cw, window_days, source))
    else:
        lines.append("Równe transze: różnica stóp {} vs {} nie zmienia wyniku "
                     "w tym oknie (carry {:+.1f} pb).".format(target, source, cw))
    if high_events:
        names = ", ".join("{} {}".format(e["source"], fmt_date(
            datetime.strptime(e.get("effective_date", e["date"]), "%Y-%m-%d").date()))
            for e in high_events)
        lines.append("Transze omijają dni reakcji na: {}.".format(names))
    lines.append("Całość najpóźniej {} (twardy koniec okna).".format(fmt_date(final_date)))

    today_action = None
    if schedule and schedule[0][0] == today:
        today_action = "transza DCA {}% po ~{:.4f}".format(pcts[0], current)

    return {
        "direction_label": dir_label,
        "sell": sell,
        "pair": pair_cfg["pair"],
        "lines": lines,
        "context": context_lines(sig, sell, backtest_rec),
        "schedule": [(d, w, p) for (d, w), p in zip(schedule, pcts)],
        "tilt": tilt,
        "carry_bps": cw,
        "today_action": today_action,
        "final_date": final_date,
        "high_events": high_events,
        "backtest_rec": backtest_rec,
    }


# ===========================================================================
# POZYCJE (realny plan dla pozostalej kwoty)
# ===========================================================================

def _parse_date(s):
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def position_plan(pos, pair_cfg, sig, events, today, policy_rates=None):
    """Plan dla POZOSTALEJ kwoty i POZOSTALYCH sesji pozycji.

    pos = {id, pair, direction: 'sell'|'buy', amount, deadline,
           fills: [{date, amount, rate}], note}
    Zwraca dict ze statusem, harmonogramem, dzisiejsza transza."""
    policy_rates = policy_rates or config.POLICY_RATES
    sell = pos.get("direction", "sell") == "sell"
    base, quote = pair_cfg["base"], pair_cfg["quote"]
    amount = float(pos.get("amount", 0.0))
    fills = pos.get("fills") or []
    done = sum(float(f.get("amount", 0.0)) for f in fills)
    remaining = max(0.0, amount - done)
    deadline = _parse_date(pos["deadline"])
    current = sig["current"]
    src_ccy = base if sell else quote
    tgt_ccy = quote if sell else base

    avg_rate = None
    if done > 0:
        wsum = sum(float(f.get("amount", 0.0)) * float(f.get("rate", 0.0)) for f in fills
                   if f.get("rate"))
        amt_r = sum(float(f.get("amount", 0.0)) for f in fills if f.get("rate"))
        avg_rate = wsum / amt_r if amt_r else None

    if remaining <= 1e-9:
        status = "done"
    elif deadline < today:
        status = "overdue"
    else:
        status = "open"

    bdays = business_days_until(today, deadline) if status == "open" else [today]
    days_left = (deadline - today).days if status == "open" else 0
    pair_high = [e for e in events if e["impact"] == "high"
                 and any(c in pair_cfg["affected_by"] for c in e["currencies"])
                 and today.isoformat() <= e.get("effective_date", e["date"])
                 <= deadline.isoformat()]
    high_dates = {e.get("effective_date", e["date"]) for e in pair_high}
    cw = carry_bps(pair_cfg, sell, max(days_left, 1), policy_rates)
    tilt = carry_tilt(cw)
    k = config.DCA_TRANCHES if len(bdays) >= 6 else min(3, len(bdays))
    schedule = dca_schedule(bdays, high_dates, tilt, k) if status != "done" else []
    pcts = _pct_parts(schedule)
    sched = []
    for (d, w), p in zip(schedule, pcts):
        sched.append({"date": d, "weight": w, "pct": p, "amount": remaining * w})

    today_amount = 0.0
    for s in sched:
        if s["date"] == today:
            today_amount = s["amount"]
    if status == "overdue":
        today_amount = remaining
        sched = [{"date": today, "weight": 1.0, "pct": 100, "amount": remaining}]

    final_date = last_safe_date(bdays, high_dates) if bdays else today
    dir_label = "{} → {}".format(src_ccy, tgt_ccy)
    lines = []
    if status == "done":
        lines.append("Pozycja zamknięta: {:,.0f} {} wymienione{}.".format(
            amount, src_ccy,
            " po średnio {:.4f}".format(avg_rate) if avg_rate else "").replace(",", " "))
    else:
        # bez przecinka w zdaniu: replace(",", " ") sluzy separatorom tysiecy
        lines.append("Zostało {:,.0f} {} z {:,.0f} ({:.0f}% wykonane) - "
                     "{} dni do {}.".format(
                         remaining, src_ccy, amount, 100.0 * done / amount if amount else 0,
                         days_left, fmt_date(deadline)).replace(",", " "))
        if status == "overdue":
            lines.append("Deadline minął - wymień resztę dziś po kursie rynkowym.")
        else:
            parts = ["{:,.0f} {} - {}".format(s["amount"], src_ccy, fmt_date(s["date"]))
                     .replace(",", " ") for s in sched]
            lines.append("Plan reszty: {}".format("; ".join(parts)))
            if tilt == "front":
                lines.append("Przechył na początek (carry {:+.0f} pb do deadline: {} "
                             "oprocentowany wyżej niż {}).".format(cw, tgt_ccy, src_ccy))
            elif tilt == "back":
                lines.append("Przechył na koniec (carry {:+.0f} pb: {} oprocentowany "
                             "wyżej niż {}).".format(cw, src_ccy, tgt_ccy))
            if pair_high:
                lines.append("Omijane dni reakcji: {}.".format(", ".join(
                    "{} {}".format(e["source"], fmt_date(_parse_date(
                        e.get("effective_date", e["date"])))) for e in pair_high)))
        if avg_rate:
            lines.append("Dotychczas: {:,.0f} {} po średnio {:.4f}.".format(
                done, src_ccy, avg_rate).replace(",", " "))

    today_action = None
    if today_amount > 0:
        today_action = "wymień {:,.0f} {} → {} po ~{:.4f}".format(
            today_amount, src_ccy, tgt_ccy, current).replace(",", " ")

    return {
        "id": pos.get("id"),
        "pair": pair_cfg["pair"],
        "label": pair_cfg["label"],
        "sell": sell,
        "direction_label": dir_label,
        "status": status,
        "amount": amount,
        "done": done,
        "remaining": remaining,
        "deadline": deadline,
        "days_left": days_left,
        "avg_rate": avg_rate,
        "schedule": sched,
        "today_amount": today_amount,
        "today_action": today_action,
        "final_date": final_date,
        "tilt": tilt,
        "carry_bps": cw,
        "lines": lines,
        "note": pos.get("note", ""),
        "src_ccy": src_ccy,
        "tgt_ccy": tgt_ccy,
        "current": current,
    }
