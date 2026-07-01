# -*- coding: utf-8 -*-
"""
Alerty e-mail (Resend) + utrwalanie stanu.

Mail wychodzi, gdy:
  1. score zlozony ktoregos kierunku przekroczy +/-60 (przejscie przez prog),
  2. kurs wejdzie w gorny lub dolny decyl zakresu 250 sesji (przejscie),
  3. jutro jest dzien wydarzenia high-impact dla pary, ktora ma zalecone
     (niewykonane) transze - przypomnienie "wykonaj przed publikacja".

Temat maila zawiera konkretna linie dzialania.
Limit: raz dziennie, chyba ze pojawi sie nowy powod (inna sygnatura).
"""

import os
import json
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import config


# ===========================================================================
# PODSUMOWANIE TEKSTOWE
# ===========================================================================

def text_summary(analysis):
    lines = []
    lines.append("FX ADVISOR  -  {}".format(analysis["generated_at"]))
    lines.append("dane (fixing EBC): {}{}".format(
        analysis["data_date"], "   [DEMO]" if analysis["demo"] else ""))
    lines.append("-" * 64)
    todo = []
    for entry in analysis["pair_entries"]:
        cfg, sig = entry["cfg"], entry["sig"]
        lines.append("{}  kurs {:.4f} ({:+.2f}%)  S={:+.0f}  pewnosc: {}".format(
            cfg["label"], sig["current"], sig["change_pct"], sig["score"],
            sig["confidence_bucket"]))
        for key in ("sell", "buy"):
            p = entry["plans"][key]
            lines.append("  {:<28} {:>4}  {}".format(
                p["direction_label"], "{:+.0f}".format(p["score"]), p["verdict"]))
            if p["today_action"]:
                todo.append("{}: {}".format(p["direction_label"], p["today_action"]))
        lines.append("")
    lines.append("DZIS DO ZROBIENIA:")
    if todo:
        for t in todo:
            lines.append("  - " + t)
    else:
        lines.append("  brak pilnych dzialan")
    return "\n".join(lines)


# ===========================================================================
# STAN
# ===========================================================================

def _email_state_path(path=None):
    return path or config.EMAIL_STATE_FILE


def load_email_state(path=None):
    p = _email_state_path(path)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("last_sent_date", None)
                data.setdefault("last_signature", "")
                data.setdefault("prev", {})
                return data
        except (ValueError, OSError):
            pass
    return {"last_sent_date": None, "last_signature": "", "prev": {}}


def save_email_state(state, path=None):
    p = _email_state_path(path)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return p


def _decile_flag(p250):
    if p250 >= 100.0 - config.ALERT_DECILE:
        return "top"
    if p250 <= config.ALERT_DECILE:
        return "bottom"
    return None


# ===========================================================================
# DECYZJA O ALERCIE
# ===========================================================================

def decide_email(analysis, state):
    """Czysta decyzja (bez wysylki, bez zapisu):
    (wyslac, powody[], temat, nowy_stan)."""
    today = str(analysis["generated_at"])[:10]
    prev = (state or {}).get("prev") or {}
    reasons = []
    new_prev = {}

    for entry in analysis["pair_entries"]:
        cfg, sig = entry["cfg"], entry["sig"]
        pair = cfg["pair"]
        s = sig["score"]
        p_state = prev.get(pair) or {}
        prev_s = p_state.get("score")
        decile = _decile_flag(sig["p250"])
        new_prev[pair] = {"score": round(s, 1), "decile": decile}

        base, quote = cfg["base"], cfg["quote"]
        sell_lbl = "{}→{}".format(base, quote)
        buy_lbl = "{}→{}".format(quote, base)

        # 1. przejscie score przez +/-60 (alert w KORZYSTNYM kierunku)
        if prev_s is not None:
            if s >= config.ALERT_SCORE_CROSS > prev_s:
                reasons.append("{}: score przekroczyl +{} ({:+.0f})".format(
                    sell_lbl, config.ALERT_SCORE_CROSS, s))
            if s <= -config.ALERT_SCORE_CROSS < prev_s:
                reasons.append("{}: score przekroczyl +{} ({:+.0f})".format(
                    buy_lbl, config.ALERT_SCORE_CROSS, -s))

        # 2. wejscie kursu w skrajny decyl 250 sesji
        if decile and decile != p_state.get("decile"):
            if decile == "top":
                reasons.append("{}: kurs {} wszedl w gorny decyl 250 sesji "
                               "(korzystnie dla {})".format(
                                   cfg["label"], "{:.4f}".format(sig["current"]), sell_lbl))
            else:
                reasons.append("{}: kurs {} wszedl w dolny decyl 250 sesji "
                               "(korzystnie dla {})".format(
                                   cfg["label"], "{:.4f}".format(sig["current"]), buy_lbl))

        # 3. jutro wydarzenie high-impact, a para ma zalecone transze
        tomorrow = (datetime.strptime(analysis["today"], "%Y-%m-%d")
                    + timedelta(days=1)).strftime("%Y-%m-%d")
        for e in entry["high_events"]:
            if e["date"] != tomorrow:
                continue
            for key in ("sell", "buy"):
                p = entry["plans"][key]
                if p["bucket"] in ("strong", "mild") and not p["dca_override"]:
                    reasons.append("jutro {} ({}) - wykonaj zaplanowane transze "
                                   "{} PRZED publikacja".format(
                                       e["name"], e["source"],
                                       sell_lbl if key == "sell" else buy_lbl))

    signature = "|".join(sorted(reasons))
    new_state = {
        "last_sent_date": (state or {}).get("last_sent_date"),
        "last_signature": (state or {}).get("last_signature", ""),
        "prev": new_prev,
    }

    if not reasons:
        return False, [], "", new_state
    sent_today = new_state["last_sent_date"] == today
    already_sent = set(new_state["last_signature"].split("|")) if \
        new_state["last_signature"] else set()
    fresh = [r for r in reasons if r not in already_sent]
    if sent_today and not fresh:
        # wszystkie biezace powody byly juz dzis zgloszone - nie spamuj
        return False, reasons, "", new_state

    # temat: konkretna linia dzialania (najmocniejszy plan), inaczej 1. powod
    action = None
    best = -1.0
    for entry in analysis["pair_entries"]:
        for key in ("sell", "buy"):
            p = entry["plans"][key]
            if p["today_action"] and p["score"] > best:
                best = p["score"]
                cfg = entry["cfg"]
                short = ("{}→{}".format(cfg["base"], cfg["quote"]) if p["sell"]
                         else "{}→{}".format(cfg["quote"], cfg["base"]))
                action = "{} {}".format(short, p["today_action"])
    subject = "{}: {}".format(config.EMAIL_SUBJECT_PREFIX, action or reasons[0])
    new_state["_pending_signature"] = signature
    return True, reasons, subject, new_state


# ===========================================================================
# WYSYLKA (Resend)
# ===========================================================================

def send_email(analysis, html_body):
    enabled = os.environ.get(
        "FX_EMAIL_ENABLED", "1" if config.EMAIL_ENABLED else "0") == "1"
    if not enabled:
        return False, "pominieto (wysylka wylaczona)"

    state = load_email_state()
    do_send, reasons, subject, new_state = decide_email(analysis, state)
    if not do_send:
        save_email_state(new_state)
        return False, ("pominieto (brak nowych powodow)" if reasons
                       else "pominieto (brak warunkow alertu)")

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        save_email_state(new_state)
        return False, "brak RESEND_API_KEY"

    body_text = text_summary(analysis) + "\n\nPOWODY ALERTU:\n" + \
        "\n".join("  - " + r for r in reasons)
    payload = {
        "from": os.environ.get("FX_EMAIL_FROM", config.EMAIL_FROM),
        "to": [os.environ.get("FX_EMAIL_TO", config.EMAIL_TO)],
        "subject": subject,
        "html": html_body,
        "text": body_text,
    }
    req = Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            # Bez tego urllib wysyla UA "Python-urllib/3.x", ktory bot-protection
            # Cloudflare przed api.resend.com odrzuca z bledem 1010 (403).
            "User-Agent": "fx-advisor/2.0 (+https://github.com/dsjbusiness/fx-advisor)",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=20) as resp:
            new_state["last_sent_date"] = str(analysis["generated_at"])[:10]
            new_state["last_signature"] = new_state.pop("_pending_signature", "")
            save_email_state(new_state)
            return True, "wyslano (HTTP {}): {}".format(resp.status, subject)
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace").strip()
        except Exception:
            body = ""
        new_state.pop("_pending_signature", None)
        save_email_state(new_state)
        return False, "blad wysylki: HTTP {} {}".format(e.code, body)
    except URLError as e:
        new_state.pop("_pending_signature", None)
        save_email_state(new_state)
        return False, "blad wysylki: {}".format(e)


# ===========================================================================
# HISTORIA OCEN
# ===========================================================================

def save_state(analysis, path=None):
    """Dopisuje skrot dzisiejszej oceny do pliku JSON (audyt)."""
    path = path or config.STATE_FILE
    snapshot = {
        "ts": analysis["generated_at"],
        "data_date": analysis["data_date"],
        "scores": {e["cfg"]["pair"]: round(e["sig"]["score"], 1)
                   for e in analysis["pair_entries"]},
        "rates": {e["cfg"]["pair"]: round(e["sig"]["current"], 4)
                  for e in analysis["pair_entries"]},
    }
    history = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except (ValueError, OSError):
            history = []
    history = [h for h in history if h.get("data_date") != snapshot["data_date"]]
    history.append(snapshot)
    history = history[-400:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    return path
