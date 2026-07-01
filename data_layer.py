# -*- coding: utf-8 -*-
"""
Warstwa danych FX Advisor.

1. Historia kursow: ~420 sesji EUR/PLN i EUR/USD z Frankfurter API (kursy
   referencyjne EBC), cache w data/history.json, aktualizacja przyrostowa
   (dociagamy tylko brakujace daty). USD/PLN wyliczany krzyzowo.
2. Kalendarz wydarzen: pliki data/events_*.yaml (prosty podzbior YAML,
   parser ponizej - bez zewnetrznych bibliotek).
"""

import json
import os
import glob
import random
import ssl
from datetime import date, datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import config


FRANKFURTER_HOSTS = [
    "https://api.frankfurter.dev/v1",
    "https://api.frankfurter.app",   # host zapasowy
]


def _ssl_context():
    ctx = ssl.create_default_context()
    # Python 3.13+ wlacza VERIFY_X509_STRICT, ktory odrzuca niektore
    # poprawne lancuchy CA ("Basic Constraints ... not marked critical").
    # Zostawiamy normalna weryfikacje, wylaczamy tylko tryb strict.
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def _http_get_json(url, timeout=25):
    req = Request(url, headers={"User-Agent": "fx-advisor/2.0"})
    with urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_range(start, end):
    """Pobiera z Frankfurter kursy EUR->PLN,USD dla zakresu dat.
    Zwraca dict {"YYYY-MM-DD": {"PLN": float, "USD": float}}."""
    path = "/{s}..{e}?base=EUR&symbols=PLN,USD".format(
        s=start.isoformat(), e=end.isoformat())
    last_err = None
    for host in FRANKFURTER_HOSTS:
        try:
            data = _http_get_json(host + path)
            break
        except (URLError, HTTPError, ValueError) as e:
            last_err = e
            data = None
    if data is None:
        raise RuntimeError("Nie udalo sie pobrac danych FX: {}".format(last_err))
    out = {}
    for d, row in (data.get("rates") or {}).items():
        if "PLN" in row and "USD" in row and float(row["USD"]) != 0:
            out[d] = {"PLN": float(row["PLN"]), "USD": float(row["USD"])}
    return out


def load_history(path=None):
    path = path or config.HISTORY_FILE
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if isinstance(doc, dict) and isinstance(doc.get("rates"), dict):
                return doc
        except (ValueError, OSError):
            pass
    return {"source": "frankfurter/ECB", "updated": None, "rates": {}}


def save_history(doc, path=None):
    path = path or config.HISTORY_FILE
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
    return path


def update_history(path=None, today=None):
    """Aktualizacja przyrostowa: dociaga tylko daty od ostatniej w cache.
    Przy pustym cache pobiera ~TARGET_SESSIONS sesji jednym zapytaniem.
    Zwraca doc historii (po zapisie na dysk)."""
    path = path or config.HISTORY_FILE
    today = today or date.today()
    doc = load_history(path)
    rates = doc["rates"]

    if rates:
        last = max(rates.keys())
        start = datetime.strptime(last, "%Y-%m-%d").date() + timedelta(days=1)
    else:
        # ~420 sesji to ~590 dni kalendarzowych; bufor na swieta
        start = today - timedelta(days=int(config.TARGET_SESSIONS * 7 / 5) + 60)

    if start <= today:
        fetched = _fetch_range(start, today)
        rates.update(fetched)

    # przytnij do MAX_SESSIONS najnowszych sesji
    keys = sorted(rates.keys())
    if len(keys) > config.MAX_SESSIONS:
        for k in keys[:-config.MAX_SESSIONS]:
            del rates[k]

    doc["updated"] = today.isoformat()
    save_history(doc, path)
    return doc


def series_from_history(doc):
    """Zwraca {"EURPLN": [(date_str, val), ...], "EURUSD": ..., "USDPLN": ...}
    posortowane rosnaco po dacie."""
    eurpln, eurusd, usdpln = [], [], []
    for d in sorted(doc["rates"].keys()):
        row = doc["rates"][d]
        pln, usd = float(row["PLN"]), float(row["USD"])
        eurpln.append((d, pln))
        eurusd.append((d, usd))
        usdpln.append((d, pln / usd))
    return {"EURPLN": eurpln, "EURUSD": eurusd, "USDPLN": usdpln}


def demo_history(seed=7, today=None, n_sessions=None):
    """Syntetyczna historia (bladzenie losowe z rewersja) do pracy offline."""
    rng = random.Random(seed)
    today = today or date.today()
    n = n_sessions or config.TARGET_SESSIONS
    bdays = []
    d = today
    while len(bdays) < n:
        if d.weekday() < 5:
            bdays.append(d)
        d -= timedelta(days=1)
    bdays.reverse()
    eurpln_anchor, eurusd_anchor = 4.28, 1.085
    pv, uv = eurpln_anchor, eurusd_anchor
    rates = {}
    for d in bdays:
        pv += 0.18 * (eurpln_anchor - pv) * 0.05 + rng.gauss(0, 0.012)
        uv += 0.18 * (eurusd_anchor - uv) * 0.05 + rng.gauss(0, 0.004)
        rates[d.isoformat()] = {"PLN": round(pv, 4), "USD": round(uv, 4)}
    return {"source": "demo", "updated": today.isoformat(), "rates": rates}


# ===========================================================================
# KALENDARZ WYDARZEN (prosty parser YAML dla naszego formatu)
# ===========================================================================

def _parse_scalar(v):
    v = v.strip()
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(x) for x in inner.split(",")]
    return v


def parse_events_yaml(text):
    """Parser podzbioru YAML uzywanego w data/events_*.yaml:
    klucze top-level (year, events), lista slownikow ('- klucz: wartosc'),
    wartosci: skalar / lista inline [A, B]. Komentarze: cale linie z #."""
    events = []
    current = None
    in_events = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
            # klucz top-level
            key, _, val = stripped.partition(":")
            in_events = (key.strip() == "events")
            continue
        if not in_events:
            continue
        if stripped.startswith("- "):
            if current:
                events.append(current)
            current = {}
            stripped = stripped[2:].strip()
            if not stripped:
                continue
        if ":" in stripped and current is not None:
            key, _, val = stripped.partition(":")
            current[key.strip()] = _parse_scalar(val)
    if current:
        events.append(current)
    return events


def load_events(pattern=None):
    """Laduje wszystkie pliki data/events_*.yaml. Zwraca liste dictow:
    {date, source, name, currencies: [..], impact} posortowana po dacie."""
    pattern = pattern or config.EVENTS_GLOB
    out = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        for ev in parse_events_yaml(text):
            if not ev.get("date"):
                continue
            cur = ev.get("currencies") or []
            if isinstance(cur, str):
                cur = [cur]
            out.append({
                "date": str(ev["date"]),
                "source": str(ev.get("source", "")),
                "name": str(ev.get("name", "")),
                "currencies": [str(c) for c in cur],
                "impact": str(ev.get("impact", "medium")),
            })
    out.sort(key=lambda e: e["date"])
    return out


def events_in_window(events, start, window_days=None):
    """Wydarzenia w [start, start + window_days - 1]."""
    window_days = window_days or config.WINDOW_DAYS
    end = start + timedelta(days=window_days - 1)
    out = []
    for e in events:
        try:
            ed = datetime.strptime(e["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if start <= ed <= end:
            e2 = dict(e)
            e2["days_ahead"] = (ed - start).days
            out.append(e2)
    return out


def events_for_pair(events, affected_by, impact=None):
    """Filtr wydarzen dotykajacych ktorejs z walut pary."""
    out = [e for e in events if any(c in affected_by for c in e["currencies"])]
    if impact:
        out = [e for e in out if e["impact"] == impact]
    return out
