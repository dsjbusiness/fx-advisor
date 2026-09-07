# -*- coding: utf-8 -*-
"""
Alerty e-mail (Resend) + utrwalanie stanu (F101).

Mail wychodzi, gdy:
  1. ktoras pozycja ma dzis transze DCA (kwota, para, kurs orientacyjny),
  2. pozycja jest po terminie albo deadline wypada jutro,
  3. jutro jest dzien reakcji na wydarzenie high-impact dla pary z otwarta
     pozycja (nie wymieniaj jutro; jesli masz transze - dzis),
  4. kurs wszedl w skrajny decyl 250 sesji (kontekst, informacyjnie).

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
    if int(analysis.get("stale_days") or 0):
        lines.append("UWAGA: zrodla kursow niedostepne - dane starsze o {} dni".format(
            analysis["stale_days"]))
    lines.append("-" * 64)
    lines.append("POZYCJE:")
    if analysis["positions"]:
        for p in analysis["positions"]:
            lines.append("  {} {} {} {:,.0f} {} do {} [{}]".format(
                p["id"], p["label"], p["direction_label"], p["amount"], p["src_ccy"],
                p["deadline"].isoformat(), p["status"]).replace(",", " "))
            for l in p["lines"]:
                lines.append("     " + l)
    else:
        lines.append("  brak pozycji")
    lines.append("")
    for entry in analysis["pair_entries"]:
        cfg, sig = entry["cfg"], entry["sig"]
        nbp = entry.get("nbp") or {}
        lines.append("{}  EBC {:.4f} ({:+.2f}%){}  p250={:.0f}".format(
            cfg["label"], sig["current"], sig["change_pct"],
            "  NBP {:.4f}".format(nbp["last"]) if nbp else "", sig["p250"]))
        for key in ("sell", "buy"):
            p = entry["plans"][key]
            lines.append("  {:<28} {}".format(p["direction_label"], p["lines"][0]))
        lines.append("")
    lines.append("DZIS DO ZROBIENIA:")
    todo = [("{}: {}".format(p["id"], p["today_action"]))
            for p in analysis["positions"] if p["today_action"]]
    if not todo and not analysis["positions"] and config.THEORETICAL_MODE:
        for entry in analysis["pair_entries"]:
            cfg = entry["cfg"]
            for key in ("sell", "buy"):
                plan = entry["plans"][key]
                if plan["schedule"] and plan["schedule"][0][0].isoformat() == analysis["today"]:
                    d, w, pct = plan["schedule"][0]
                    src = cfg["base"] if plan["sell"] else cfg["quote"]
                    tgt = cfg["quote"] if plan["sell"] else cfg["base"]
                    todo.append("[teoretycznie] {}→{}: transza {}% = {:,.0f} {} na kazde "
                                "{:,.0f} {} po ~{:.4f}".format(
                                    src, tgt, pct, cfg["unit_amount"] * w, src,
                                    float(cfg["unit_amount"]), src,
                                    entry["sig"]["current"]).replace(",", " "))
    if todo:
        for t in todo:
            lines.append("  - " + t)
    else:
        lines.append("  brak transz na dzis")
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
    today_s = str(analysis["today"])[:10]
    today = datetime.strptime(today_s, "%Y-%m-%d").date()
    tomorrow = (today + timedelta(days=1)).isoformat()
    prev = (state or {}).get("prev") or {}
    reasons = []
    action = None
    new_prev = {}

    # 1-3: pozycje
    open_pairs = {}
    for p in analysis["positions"]:
        if p["status"] == "open":
            open_pairs.setdefault(p["pair"], []).append(p)
        if p["today_action"]:
            reasons.append("{}: {}".format(p["id"], p["today_action"]))
            action = action or "{} {}".format(p["id"], p["today_action"])
        if p["status"] == "overdue":
            reasons.append("{}: po terminie - wymien reszte {:,.0f} {} dzis".format(
                p["id"], p["remaining"], p["src_ccy"]).replace(",", " "))
            action = action or "{} po terminie: wymien {:,.0f} {}".format(
                p["id"], p["remaining"], p["src_ccy"]).replace(",", " ")
        elif p["status"] == "open" and p["deadline"].isoformat() == tomorrow:
            reasons.append("{}: deadline jutro - zostalo {:,.0f} {}".format(
                p["id"], p["remaining"], p["src_ccy"]).replace(",", " "))

    for entry in analysis["pair_entries"]:
        cfg, sig = entry["cfg"], entry["sig"]
        pair = cfg["pair"]
        p_state = prev.get(pair) or {}
        decile = _decile_flag(sig["p250"])
        new_prev[pair] = {"decile": decile}
        base, quote = cfg["base"], cfg["quote"]

        if pair in open_pairs:
            for e in entry["high_events"]:
                if e.get("effective_date", e["date"]) == tomorrow:
                    reasons.append("{}: jutro dzien reakcji na {} ({}) - nie wymieniaj "
                                   "jutro; transze na dzis wykonaj dzis".format(
                                       cfg["label"], e["name"], e["source"]))

        # 4. kontekst: wejscie w skrajny decyl
        if decile and decile != p_state.get("decile"):
            if decile == "top":
                reasons.append("{}: kurs {:.4f} w gornym decylu roku (kontekst: "
                               "korzystnie dla {}→{})".format(
                                   cfg["label"], sig["current"], base, quote))
            else:
                reasons.append("{}: kurs {:.4f} w dolnym decylu roku (kontekst: "
                               "korzystnie dla {}→{})".format(
                                   cfg["label"], sig["current"], quote, base))

    signature = "|".join(sorted(reasons))
    new_state = {
        "last_sent_date": (state or {}).get("last_sent_date"),
        "last_signature": (state or {}).get("last_signature", ""),
        "prev": new_prev,
    }
    if not reasons:
        return False, [], "", new_state
    sent_today = new_state["last_sent_date"] == today_s
    already_sent = set(new_state["last_signature"].split("|")) if \
        new_state["last_signature"] else set()
    fresh = [r for r in reasons if r not in already_sent]
    if sent_today and not fresh:
        return False, reasons, "", new_state
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
            "User-Agent": "fx-advisor/3.0 (+https://github.com/dsjbusiness/fx-advisor)",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=20) as resp:
            new_state["last_sent_date"] = str(analysis["today"])[:10]
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
    path = path or config.STATE_FILE
    snapshot = {
        "ts": analysis["generated_at"],
        "data_date": analysis["data_date"],
        "p250": {e["cfg"]["pair"]: round(e["sig"]["p250"], 1)
                 for e in analysis["pair_entries"]},
        "rates": {e["cfg"]["pair"]: round(e["sig"]["current"], 4)
                  for e in analysis["pair_entries"]},
        "positions_open": sum(1 for p in analysis["positions"] if p["status"] == "open"),
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
