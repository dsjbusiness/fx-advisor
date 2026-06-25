# -*- coding: utf-8 -*-
"""
Powiadomienia i utrwalanie stanu (opcjonalne).
- Podsumowanie tekstowe do konsoli / maila.
- Wysy\u0142ka e-mail przez Resend (REST, bez dodatkowych bibliotek).
- Zapis stanu do JSON (audyt / wykresy w czasie).

E-mail w\u0142\u0105cza si\u0119 ustawieniem zmiennych \u015brodowiskowych:
  FX_EMAIL_ENABLED=1
  RESEND_API_KEY=...
opcjonalnie FX_EMAIL_FROM / FX_EMAIL_TO nadpisuj\u0105 wartosci z config.py
"""

import os
import json
import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import config


def text_summary(analysis):
    lines = []
    lines.append("FX ADVISOR  -  {}".format(analysis["generated_at"]))
    lines.append("dane (fixing EBC): {}{}".format(
        analysis["data_date"], "   [DEMO]" if analysis["demo"] else ""))
    lines.append("okno decyzyjne: {} dni".format(config.WINDOW_DAYS))
    lines.append("-" * 60)
    for r in analysis["results"]:
        if not r["direction"]["primary"]:
            continue
        a = r["pair"]
        lines.append("{:<12} {}  (ocena {:+.0f}/100, pewno\u015b\u0107: {})".format(
            r["direction"]["label"], r["label"], r["favorability"], r["confidence_bucket"]))
        lines.append("   kurs {:.4f} | percentyl {:.0f} | RSI {:.0f} | zmienno\u015b\u0107 {}".format(
            a["current"], a["pct"], a["rsi"],
            "podwy\u017cszona" if a["vol_elevated"] else "normalna"))
        lines.append("   -> {}".format(r["action"]))
        for n in r["notes"]:
            lines.append("      \u00b7 {}".format(n))
        lines.append("")
    if analysis["events"]:
        lines.append("WYDARZENIA W OKNIE:")
        for e in analysis["events"]:
            lines.append("   {} (za {} dni) {} - {} [{}]".format(
                e["date"], e["days_ahead"], e["bank"], e["desc"], e["currency"]))
    else:
        lines.append("WYDARZENIA W OKNIE: brak")
    return "\n".join(lines)


def _favorable_set(analysis):
    """Slownik {id glownego kierunku: czy KORZYSTNY teraz}.
    Korzystny = favorability dodatnia i >= progu (etykieta "Korzystny")."""
    thr = config.EMAIL_ALERT_MIN_SCORE
    out = {}
    for r in analysis["results"]:
        if r["direction"]["primary"]:
            out[r["direction"]["id"]] = bool(r["favorability"] >= thr)
    return out


def _email_state_path(path=None):
    return path or getattr(config, "EMAIL_STATE_FILE", "fx_email_state.json")


def load_email_state(path=None):
    """Stan wysylki maila: kiedy ostatnio wyslano + zestaw korzystnych par z
    poprzedniego uruchomienia (do wykrycia przeskoku na korzystna)."""
    p = _email_state_path(path)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("last_sent_date", None)
                data.setdefault("prev_favorable", {})
                return data
        except (ValueError, OSError):
            pass
    return {"last_sent_date": None, "prev_favorable": {}}


def save_email_state(state, path=None):
    p = _email_state_path(path)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return p


def decide_email(analysis, state):
    """Czysta decyzja, bez wysylki i bez zapisu: (wyslac, powod, nowy_stan).

    Zasady:
      - mail tylko gdy ktoras GLOWNA para jest teraz KORZYSTNA,
      - najwyzej raz na dobe (doba wg daty z generated_at),
      - WYJATEK od limitu raz/dobe: jesli ktoras para wlasnie przeskoczyla na
        korzystna (jest korzystna teraz, a nie byla przy poprzednim uruchomieniu)
        - wyslij nawet jesli mail juz dzis poszedl.
    """
    today = str(analysis["generated_at"])[:10]
    fav_now = _favorable_set(analysis)
    prev_fav = (state or {}).get("prev_favorable") or {}
    any_fav = any(fav_now.values())
    transition = any(v and not prev_fav.get(d, False) for d, v in fav_now.items())
    sent_today = (state or {}).get("last_sent_date") == today

    new_state = {
        "last_sent_date": (state or {}).get("last_sent_date"),
        "prev_favorable": fav_now,
    }
    if not any_fav:
        return False, "pominieto (zadna glowna para nie jest korzystna)", new_state
    if sent_today and not transition:
        return False, "pominieto (mail juz dzis wyslany; brak nowej pary korzystnej)", new_state
    powod = "nagla zmiana pary na korzystna" if (sent_today and transition) else "para korzystna"
    return True, powod, new_state


def send_email(analysis, html_body):
    enabled = os.environ.get("FX_EMAIL_ENABLED", "1" if config.EMAIL_ENABLED else "0") == "1"
    if not enabled:
        return False, "pominieto (wysylka wylaczona)"

    state = load_email_state()
    do_send, why, new_state = decide_email(analysis, state)
    if not do_send:
        save_email_state(new_state)   # zapamietaj biezacy zestaw korzystnych par
        return False, why

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        save_email_state(new_state)
        return False, "brak RESEND_API_KEY"

    payload = {
        "from": os.environ.get("FX_EMAIL_FROM", config.EMAIL_FROM),
        "to": [os.environ.get("FX_EMAIL_TO", config.EMAIL_TO)],
        "subject": config.EMAIL_SUBJECT + "  ({})".format(analysis["data_date"]),
        "html": html_body,
        "text": text_summary(analysis),
    }
    req = Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            # Bez tego urllib wysyla UA "Python-urllib/3.x", ktory bot-protection
            # Cloudflare przed api.resend.com odrzuca z bledem 1010 (403).
            "User-Agent": "fx-advisor/1.0 (+https://github.com/dsjbusiness/fx-advisor)",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=20) as resp:
            new_state["last_sent_date"] = str(analysis["generated_at"])[:10]
            save_email_state(new_state)
            return True, "wyslano (HTTP {}) - {}".format(resp.status, why)
    except HTTPError as e:
        # Resend zwraca szczegoly bledu w ciele odpowiedzi (np. niezweryfikowana
        # domena nadawcy) - bez tego widzisz samo "403 Forbidden".
        try:
            body = e.read().decode("utf-8", "replace").strip()
        except Exception:
            body = ""
        save_email_state(new_state)
        return False, "blad wysylki: HTTP {} {}".format(e.code, body)
    except URLError as e:
        save_email_state(new_state)
        return False, "blad wysylki: {}".format(e)


def save_state(analysis, path=None):
    """Dopisuje skrót dzisiejszej oceny do pliku JSON (lista wpis\u00f3w)."""
    path = path or config.STATE_FILE
    snapshot = {
        "ts": analysis["generated_at"],
        "data_date": analysis["data_date"],
        "scores": {r["direction"]["id"]: round(r["favorability"], 1)
                   for r in analysis["results"]},
        "rates": {p: round(analysis["pairs"][p]["current"], 4)
                  for p in analysis["pairs"]},
    }
    history = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except (ValueError, OSError):
            history = []
    # nie duplikuj wpisu dla tej samej daty danych
    history = [h for h in history if h.get("data_date") != snapshot["data_date"]]
    history.append(snapshot)
    history = history[-400:]  # ogranicz rozmiar
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    return path
