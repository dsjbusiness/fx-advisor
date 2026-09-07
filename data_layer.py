# -*- coding: utf-8 -*-
"""
Warstwa danych FX Advisor.

1. Historia kursow EUR/PLN i EUR/USD (fixing EBC 14:15 CET), pelna od 1999,
   cache w data/history.json, aktualizacja przyrostowa. Zrodla po kolei:
   EBC SDMX (CSV) -> Frankfurter -> feed XML EBC. USD/PLN krzyzowo.
2. Fixing NBP (tabela A) - drugi punkt dnia i kurs do ksiegowania.
3. Stopy procentowe do carry (EBC SDMX, FRED; PLN z config).
4. Kalendarz wydarzen: data/events_*.yaml (prosty parser YAML).
5. Pozycje uzytkownika: data/positions.json.
"""

import csv
import io
import json
import os
import glob
import random
import ssl
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import HTTPError

import config


FRANKFURTER_HOSTS = [
    "https://api.frankfurter.dev/v1",
    "https://api.frankfurter.app",
]

ECB_90D_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
ECB_FULL_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
ECB_90D_SPAN = 85


class FxDataUnavailable(RuntimeError):
    """Zadne ze zrodel kursow nie odpowiedzialo."""


def _log(msg):
    sys.stderr.write("[data_layer] {}\n".format(msg))


def _ssl_context():
    ctx = ssl.create_default_context()
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def _http_get(url, timeout=None, user_agent=None):
    timeout = timeout or config.HTTP_TIMEOUT
    req = Request(url, headers={"User-Agent": user_agent or "fx-advisor/3.0",
                                "Accept": "*/*"})
    with urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return resp.read()


def _http_get_json(url, timeout=None):
    return json.loads(_http_get(url, timeout).decode("utf-8"))


# ===========================================================================
# ZRODLA KURSOW EBC
# ===========================================================================

def parse_sdmx_csv(text):
    """CSV z data-api.ecb.europa.eu: kolumny TIME_PERIOD, OBS_VALUE.
    Zwraca {date: float}."""
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        d, v = row.get("TIME_PERIOD"), row.get("OBS_VALUE")
        if d and v:
            try:
                out[d] = float(v)
            except ValueError:
                continue
    return out


def _fetch_ecb_sdmx(start, end):
    """Kursy EUR->PLN,USD z API SDMX EBC (dwa zapytania CSV)."""
    per_ccy = {}
    for ccy in ("PLN", "USD"):
        url = config.ECB_SDMX_URL.format(ccy=ccy, start=start.isoformat(),
                                         end=end.isoformat())
        raw = _http_get(url, timeout=config.HTTP_TIMEOUT_ECB)
        # pusta odpowiedz (HTTP 204) = brak obserwacji w zakresie
        per_ccy[ccy] = parse_sdmx_csv(raw.decode("utf-8")) if raw else {}
    out = {}
    for d, pln in per_ccy["PLN"].items():
        usd = per_ccy["USD"].get(d)
        if usd:
            out[d] = {"PLN": pln, "USD": usd}
    return out


def _fetch_frankfurter(host, start, end):
    url = host + "/{s}..{e}?base=EUR&symbols=PLN,USD".format(
        s=start.isoformat(), e=end.isoformat())
    data = _http_get_json(url)
    out = {}
    for d, row in (data.get("rates") or {}).items():
        if "PLN" in row and "USD" in row and float(row["USD"]) != 0:
            out[d] = {"PLN": float(row["PLN"]), "USD": float(row["USD"])}
    return out


def _fetch_ecb(start, end):
    """Feed XML EBC (zrodlo awaryjne). Cube[time] > Cube[currency,rate]."""
    span_days = (end - start).days
    url = ECB_90D_URL if span_days <= ECB_90D_SPAN else ECB_FULL_URL
    root = ET.fromstring(_http_get(url, timeout=config.HTTP_TIMEOUT_ECB))
    out = {}
    for day in root.iter():
        d = day.get("time")
        if not d or not (start.isoformat() <= d <= end.isoformat()):
            continue
        row = {}
        for cur in day:
            code, rate = cur.get("currency"), cur.get("rate")
            if code in ("PLN", "USD") and rate:
                row[code] = float(rate)
        if "PLN" in row and "USD" in row and row["USD"] != 0:
            out[d] = {"PLN": row["PLN"], "USD": row["USD"]}
    return out


def _sources():
    src = [("ecb sdmx", _fetch_ecb_sdmx)]
    src += [("frankfurter " + h, (lambda h: lambda s, e: _fetch_frankfurter(h, s, e))(h))
            for h in FRANKFURTER_HOSTS]
    src.append(("ecb xml", _fetch_ecb))
    return src


def _fetch_range(start, end):
    """Pobiera kursy dla zakresu dat, probujac po kolei kazde zrodlo.
    Wyjatki sieciowe to OSError (URLError, HTTPError, TimeoutError)."""
    errors = []
    for label, fetch in _sources():
        for attempt in range(1, config.HTTP_RETRIES + 1):
            try:
                out = fetch(start, end)
                if errors:
                    _log("dane pobrane z: {} (po {} nieudanych probach)".format(
                        label, len(errors)))
                return out
            except (OSError, ValueError, ET.ParseError) as e:
                errors.append("{} (proba {}): {}: {}".format(
                    label, attempt, type(e).__name__, e))
            _log("nieudane pobranie -> " + errors[-1])
            if attempt < config.HTTP_RETRIES:
                time.sleep(config.HTTP_BACKOFF_S * attempt)
    raise FxDataUnavailable(
        "Nie udalo sie pobrac danych FX z zadnego zrodla:\n  " +
        "\n  ".join(errors))


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
    return {"source": "ECB (SDMX/Frankfurter/XML)", "updated": None, "rates": {}}


def save_history(doc, path=None):
    path = path or config.HISTORY_FILE
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return path


def update_history(path=None, today=None):
    """Aktualizacja przyrostowa + jednorazowe dopelnienie historii wstecz
    do HISTORY_START (F101: pelna historia do backtestu).

    Gdy zrodla padna, a cache jest swiezy (do MAX_STALE_DAYS), raport
    powstaje na cache z flaga stale."""
    path = path or config.HISTORY_FILE
    today = today or date.today()
    doc = load_history(path)
    rates = doc["rates"]
    hist_start = datetime.strptime(config.HISTORY_START, "%Y-%m-%d").date()

    # 1) dopelnienie wstecz (raz; potem cache siega HISTORY_START)
    if rates:
        first = datetime.strptime(min(rates.keys()), "%Y-%m-%d").date()
        if first > hist_start + timedelta(days=14) and not doc.get("backfilled"):
            try:
                older = _fetch_range(hist_start, first - timedelta(days=1))
                rates.update(older)
                doc["backfilled"] = True
                _log("dopelniono historie wstecz: +{} sesji".format(len(older)))
            except FxDataUnavailable as e:
                _log("dopelnienie wstecz nieudane (sprobuje nastepnym razem): {}".format(e))

    # 2) przyrost do przodu
    if rates:
        last = max(rates.keys())
        start = datetime.strptime(last, "%Y-%m-%d").date() + timedelta(days=1)
    else:
        start = hist_start

    stale_days = 0
    if start <= today:
        try:
            rates.update(_fetch_range(start, today))
            doc["updated"] = today.isoformat()
            if not rates:
                raise FxDataUnavailable("zrodla odpowiedzialy, ale bez zadnych kursow")
        except FxDataUnavailable as e:
            if not rates:
                raise
            last_date = datetime.strptime(max(rates.keys()), "%Y-%m-%d").date()
            stale_days = (today - last_date).days
            if stale_days > config.MAX_STALE_DAYS:
                raise FxDataUnavailable(
                    "{}\nCache ma juz {} dni (limit {}) - przerywam.".format(
                        e, stale_days, config.MAX_STALE_DAYS))
            _log("UWAGA: brak swiezych kursow, jade na cache z {} ({} dni)".format(
                last_date.isoformat(), stale_days))
    else:
        doc["updated"] = today.isoformat()

    keys = sorted(rates.keys())
    if len(keys) > config.MAX_SESSIONS:
        for k in keys[:-config.MAX_SESSIONS]:
            del rates[k]

    doc["stale"] = stale_days > 0
    doc["stale_days"] = stale_days
    doc["source"] = "ECB (SDMX/Frankfurter/XML)"
    save_history(doc, path)
    return doc


def series_from_history(doc):
    """{"EURPLN": [(date_str, val), ...], "EURUSD": ..., "USDPLN": ...}"""
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
    n = n_sessions or 900
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
# FIXING NBP (tabela A)
# ===========================================================================

def parse_nbp_json(doc):
    """Odpowiedz api.nbp.pl -> {date: mid}."""
    out = {}
    for r in (doc.get("rates") or []):
        d, mid = r.get("effectiveDate"), r.get("mid")
        if d and mid:
            out[d] = float(mid)
    return out


def load_nbp(path=None):
    path = path or config.NBP_FILE
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if isinstance(doc, dict) and isinstance(doc.get("rates"), dict):
                return doc
        except (ValueError, OSError):
            pass
    return {"source": "NBP tabela A", "updated": None, "rates": {}}


def update_nbp(path=None, today=None):
    """Dociaga fixing NBP EUR i USD (max 93 dni na zapytanie). Blad sieci nie
    przerywa biegu - zostaje cache. Zwraca doc {rates: {date: {EUR, USD}}}."""
    path = path or config.NBP_FILE
    today = today or date.today()
    doc = load_nbp(path)
    rates = doc["rates"]
    if rates:
        start = datetime.strptime(max(rates.keys()), "%Y-%m-%d").date() + timedelta(days=1)
    else:
        start = today - timedelta(days=config.NBP_KEEP_DAYS)
    start = max(start, today - timedelta(days=90))
    if start <= today:
        got = {}
        try:
            for ccy in ("EUR", "USD"):
                url = config.NBP_API_URL.format(ccy=ccy.lower(), start=start.isoformat(),
                                                end=today.isoformat())
                try:
                    raw = _http_get(url)
                except HTTPError as e:
                    if e.code == 404:    # "Brak danych" = weekend / przed publikacja
                        continue
                    raise
                if not raw:
                    continue
                for d, mid in parse_nbp_json(json.loads(raw.decode("utf-8"))).items():
                    got.setdefault(d, {})[ccy] = mid
            for d, row in got.items():
                if "EUR" in row and "USD" in row:
                    rates[d] = row
            doc["updated"] = today.isoformat()
        except (OSError, ValueError) as e:
            _log("NBP niedostepne ({}: {}) - zostaje cache".format(type(e).__name__, e))
    keep = today - timedelta(days=config.NBP_KEEP_DAYS)
    for k in [k for k in rates if k < keep.isoformat()]:
        del rates[k]
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
    return doc


def nbp_view(nbp_doc, today):
    """Dla kart par: ostatni fixing NBP i kurs do ksiegowania (ostatni fixing
    z dnia PRZED dzisiejszym). Zwraca {"EURPLN": {...}, "USDPLN": {...}}."""
    rates = nbp_doc.get("rates") or {}
    if not rates:
        return {}
    days = sorted(rates.keys())
    last = days[-1]
    before = [d for d in days if d < today.isoformat()]
    acc = before[-1] if before else None
    out = {}
    for pair, ccy in (("EURPLN", "EUR"), ("USDPLN", "USD")):
        out[pair] = {
            "last_date": last, "last": rates[last][ccy],
            "acc_date": acc, "acc": rates[acc][ccy] if acc else None,
        }
    return out


# ===========================================================================
# STOPY PROCENTOWE (carry)
# ===========================================================================

def load_rates(path=None):
    path = path or config.RATES_FILE
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if isinstance(doc, dict) and isinstance(doc.get("rates"), dict):
                return doc
        except (ValueError, OSError):
            pass
    return {"rates": dict(config.POLICY_RATES), "as_of": config.POLICY_RATES_AS_OF,
            "sources": {k: "config" for k in config.POLICY_RATES}}


def update_policy_rates(path=None, today=None):
    """EUR: stopa depozytowa EBC (SDMX). USD: efektywna fed funds (FRED).
    PLN: config (NBP nie ma API stop). Blad = zostaje poprzednia wartosc."""
    path = path or config.RATES_FILE
    today = today or date.today()
    doc = load_rates(path)
    rates, sources = doc["rates"], doc.setdefault("sources", {})
    # PLN zawsze z config (jedyne miejsce, gdzie da sie go zaktualizowac)
    rates["PLN"] = config.POLICY_RATES["PLN"]
    sources["PLN"] = "config {}".format(config.POLICY_RATES_AS_OF)
    try:
        vals = parse_sdmx_csv(_http_get(config.ECB_DFR_URL,
                                        timeout=config.HTTP_TIMEOUT_ECB).decode("utf-8"))
        if vals:
            d = max(vals)
            rates["EUR"] = vals[d]
            sources["EUR"] = "ECB DFR od {}".format(d)
    except (OSError, ValueError) as e:
        _log("stopa EBC niedostepna: {}".format(e))
    try:
        url = config.FRED_DFF_URL.format(
            start=(today - timedelta(days=40)).isoformat())
        # CDN FRED zawiesza odpowiedz dla nieznanych User-Agentow (urllib
        # dostaje timeout), a curl-owy UA przechodzi w <1 s.
        lines = _http_get(url, timeout=config.HTTP_TIMEOUT_ECB,
                          user_agent="curl/8.4.0").decode("utf-8").strip().splitlines()
        last = None
        for ln in reversed(lines):
            parts = ln.split(",")
            if len(parts) == 2 and parts[1] not in (".", ""):
                last = parts
                break
        if last:
            rates["USD"] = float(last[1])
            sources["USD"] = "FRED DFF {}".format(last[0])
    except (OSError, ValueError) as e:
        _log("stopa Fed niedostepna: {}".format(e))
    doc["as_of"] = today.isoformat()
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
    return doc


# ===========================================================================
# KALENDARZ WYDARZEN
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
    events = []
    current = None
    in_events = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
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
            current[key.strip()] = _parse_scalar(val.split(" #")[0])
    if current:
        events.append(current)
    return events


def next_business_day(d):
    d = d + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def effective_date(ev):
    """Sesja, w ktorej kurs (dla kogos wymieniajacego w godzinach pracy)
    reaguje na wydarzenie: publikacje po fixingu (Fed, BLS) -> nastepna sesja."""
    try:
        d = datetime.strptime(ev["date"], "%Y-%m-%d").date()
    except ValueError:
        return ev["date"]
    if ev.get("source") in config.LATE_SOURCES:
        return next_business_day(d).isoformat()
    return d.isoformat()


def load_events(pattern=None):
    """Wszystkie data/events_*.yaml -> lista {date, effective_date, source,
    name, currencies, impact} posortowana po dacie."""
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
            rec = {
                "date": str(ev["date"]),
                "source": str(ev.get("source", "")),
                "name": str(ev.get("name", "")),
                "currencies": [str(c) for c in cur],
                "impact": str(ev.get("impact", "medium")),
            }
            rec["effective_date"] = effective_date(rec)
            out.append(rec)
    out.sort(key=lambda e: e["date"])
    return out


def events_in_window(events, start, window_days=None):
    window_days = window_days or config.WINDOW_DAYS
    end = start + timedelta(days=window_days - 1)
    out = []
    for e in events:
        try:
            ed = datetime.strptime(e["date"], "%Y-%m-%d").date()
            eff = datetime.strptime(e.get("effective_date", e["date"]), "%Y-%m-%d").date()
        except ValueError:
            continue
        # wydarzenie liczy sie, gdy publikacja ALBO dzien reakcji wpada w okno
        if start <= ed <= end or start <= eff <= end:
            e2 = dict(e)
            e2["days_ahead"] = (ed - start).days
            out.append(e2)
    return out


def events_for_pair(events, affected_by, impact=None):
    out = [e for e in events if any(c in affected_by for c in e["currencies"])]
    if impact:
        out = [e for e in out if e["impact"] == impact]
    return out


def high_dates_for_pair(events, affected_by):
    """Zbior efektywnych dat (ISO) wydarzen high-impact dla pary."""
    return {e.get("effective_date", e["date"])
            for e in events_for_pair(events, affected_by, impact="high")}


def calendar_coverage_days(events, today, currency=None):
    """Ile dni naprzod (od today) siega kalendarz high-impact
    (opcjonalnie dla jednej waluty). 0 = brak przyszlych wydarzen."""
    best = 0
    for e in events:
        if e["impact"] != "high":
            continue
        if currency and currency not in e["currencies"]:
            continue
        try:
            ed = datetime.strptime(e["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        best = max(best, (ed - today).days)
    return best


# ===========================================================================
# POZYCJE UZYTKOWNIKA
# ===========================================================================

def load_positions(path=None):
    path = path or config.POSITIONS_FILE
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            if isinstance(doc, dict) and isinstance(doc.get("positions"), list):
                return doc
        except (ValueError, OSError):
            pass
    return {"positions": []}


def save_positions(doc, path=None):
    path = path or config.POSITIONS_FILE
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return path


def new_position_id(doc, today):
    base = "P{}".format(today.strftime("%y%m%d"))
    ids = {p.get("id") for p in doc["positions"]}
    for k in range(1, 100):
        cand = "{}-{}".format(base, k)
        if cand not in ids:
            return cand
    return "{}-{}".format(base, random.randint(100, 999))
