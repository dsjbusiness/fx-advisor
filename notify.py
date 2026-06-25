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


def _email_on(analysis):
    """Czy wys\u0142a\u0107 maila? Tylko gdy mocny sygna\u0142 lub wydarzenie w oknie."""
    enabled = os.environ.get("FX_EMAIL_ENABLED", "1" if config.EMAIL_ENABLED else "0") == "1"
    if not enabled:
        return False
    if config.EMAIL_ALERT_MIN_SCORE <= 0:
        return True
    if analysis["events"]:
        return True
    for r in analysis["results"]:
        if r["direction"]["primary"] and abs(r["favorability"]) >= config.EMAIL_ALERT_MIN_SCORE:
            return True
    return False


def send_email(analysis, html_body):
    if not _email_on(analysis):
        return False, "pomini\u0119to (brak mocnego sygna\u0142u / wydarzenia lub wy\u0142\u0105czone)"
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
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
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=20) as resp:
            return True, "wys\u0142ano (HTTP {})".format(resp.status)
    except (URLError, HTTPError) as e:
        return False, "b\u0142\u0105d wysy\u0142ki: {}".format(e)


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
