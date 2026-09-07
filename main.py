#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FX Advisor - punkt wejscia.

Uzycie:
  python main.py                    # realne dane EBC + raport HTML + alerty
  python main.py --demo             # dane syntetyczne (offline), do podgladu
  python main.py --no-email         # nie wysylaj maila
  python main.py --force-backtest   # wymus pelny przelicz backtestu
  python main.py --out docs/index.html

Pozycje (kwota + deadline; plan liczy sie dla RESZTY):
  python main.py --add-position EURPLN sell 10000 2026-09-30 [--note "faktura X"]
  python main.py --record-fill P260907-1 4500 4.3148 [--fill-date 2026-09-07]
  python main.py --close-position P260907-1
  python main.py --list-positions
Komendy pozycji zapisuja data/positions.json i koncza bieg (bez raportu).
"""

import os
import sys
import argparse
from datetime import date, datetime

import config
import data_layer
import signals
import planner
import backtest
import report
import notify


def parse_args(argv):
    p = argparse.ArgumentParser(description="FX Advisor")
    p.add_argument("--demo", action="store_true", help="dane syntetyczne offline")
    p.add_argument("--out", default="fx_report.html", help="sciezka raportu HTML")
    p.add_argument("--no-email", action="store_true", help="wylacz wysylke maila")
    p.add_argument("--force-backtest", action="store_true",
                   help="pelny przelicz backtestu (ignoruj cache)")
    p.add_argument("--quiet", action="store_true", help="bez podsumowania w konsoli")
    p.add_argument("--add-position", nargs=4, metavar=("PAIR", "DIR", "AMOUNT", "DEADLINE"),
                   help="nowa pozycja: para (EURPLN), kierunek (sell|buy), kwota, deadline")
    p.add_argument("--note", default="", help="notatka do --add-position")
    p.add_argument("--record-fill", nargs=3, metavar=("ID", "AMOUNT", "RATE"),
                   help="zapisz wykonana transze pozycji")
    p.add_argument("--fill-date", default=None, help="data transzy (domyslnie dzis)")
    p.add_argument("--close-position", metavar="ID", help="zamknij pozycje (usun)")
    p.add_argument("--list-positions", action="store_true")
    return p.parse_args(argv)


# ===========================================================================
# POZYCJE (CLI)
# ===========================================================================

def _pair_cfg(pair):
    for pc in config.PAIRS:
        if pc["pair"] == pair.upper():
            return pc
    raise SystemExit("nieznana para: {} (dostepne: {})".format(
        pair, ", ".join(pc["pair"] for pc in config.PAIRS)))


def handle_positions(args, today):
    doc = data_layer.load_positions()
    if args.add_position:
        pair, direction, amount, deadline = args.add_position
        pc = _pair_cfg(pair)
        direction = direction.lower()
        if direction not in ("sell", "buy"):
            raise SystemExit("kierunek: sell (sprzedaj baze) albo buy (kup baze)")
        try:
            amount = float(str(amount).replace(" ", "").replace(",", "."))
            dl = datetime.strptime(deadline, "%Y-%m-%d").date()
        except ValueError:
            raise SystemExit("kwota liczba, deadline RRRR-MM-DD")
        if amount <= 0:
            raise SystemExit("kwota musi byc dodatnia")
        pos = {"id": data_layer.new_position_id(doc, today), "pair": pc["pair"],
               "direction": direction, "amount": amount, "deadline": dl.isoformat(),
               "created": today.isoformat(), "fills": [], "note": args.note or ""}
        doc["positions"].append(pos)
        data_layer.save_positions(doc)
        print("dodano pozycje {}: {} {} {:,.0f} do {}".format(
            pos["id"], pc["label"], direction, amount, dl.isoformat()).replace(",", " "))
        return True
    if args.record_fill:
        pid, amount, rate = args.record_fill
        pos = next((p for p in doc["positions"] if p.get("id") == pid), None)
        if not pos:
            raise SystemExit("brak pozycji {}".format(pid))
        try:
            amount = float(str(amount).replace(" ", "").replace(",", "."))
            rate = float(str(rate).replace(",", "."))
        except ValueError:
            raise SystemExit("kwota i kurs musza byc liczbami")
        fd = args.fill_date or today.isoformat()
        datetime.strptime(fd, "%Y-%m-%d")
        pos.setdefault("fills", []).append({"date": fd, "amount": amount, "rate": rate})
        data_layer.save_positions(doc)
        done = sum(float(f["amount"]) for f in pos["fills"])
        print("zapisano transze {}: {:,.0f} po {:.4f} (wykonane {:,.0f} z {:,.0f})".format(
            pid, amount, rate, done, float(pos["amount"])).replace(",", " "))
        return True
    if args.close_position:
        before = len(doc["positions"])
        doc["positions"] = [p for p in doc["positions"] if p.get("id") != args.close_position]
        if len(doc["positions"]) == before:
            raise SystemExit("brak pozycji {}".format(args.close_position))
        data_layer.save_positions(doc)
        print("usunieto pozycje {}".format(args.close_position))
        return True
    if args.list_positions:
        if not doc["positions"]:
            print("brak pozycji")
        for p in doc["positions"]:
            done = sum(float(f.get("amount", 0)) for f in p.get("fills") or [])
            print("{} {} {} {:,.0f} (wykonane {:,.0f}) do {} {}".format(
                p["id"], p["pair"], p["direction"], float(p["amount"]), done,
                p["deadline"], p.get("note", "")).replace(",", " "))
        return True
    return False


# ===========================================================================
# ANALIZA
# ===========================================================================

def run_analysis(demo=False, force_backtest=False):
    today = date.today()

    events = data_layer.load_events()
    if demo:
        hist = data_layer.demo_history(today=today)
        series = data_layer.series_from_history(hist)
        bt = backtest.run_backtest(series, events, today=today)
        bt_recomputed = True
        nbp_doc = {"rates": {}}
        rates_doc = data_layer.load_rates()
    else:
        hist = data_layer.update_history(today=today)
        series = data_layer.series_from_history(hist)
        bt, bt_recomputed = backtest.get_backtest(
            series, events, force=force_backtest, today=today)
        nbp_doc = data_layer.update_nbp(today=today)
        rates_doc = data_layer.update_policy_rates(today=today)

    policy_rates = rates_doc["rates"]
    win_events = data_layer.events_in_window(events, today)
    nbp_v = data_layer.nbp_view(nbp_doc, today)

    pair_entries = []
    sig_by_pair = {}
    for pcfg in config.PAIRS:
        ser = series[pcfg["pair"]]
        sig = signals.compute_pair_signal(ser)
        sig_by_pair[pcfg["pair"]] = sig
        bt_pair = (bt.get("pairs") or {}).get(pcfg["pair"]) or {}
        plans = {
            "sell": planner.build_plan(pcfg, sig, events, today, sell=True,
                                       policy_rates=policy_rates,
                                       backtest_rec=bt_pair.get("sell")),
            "buy": planner.build_plan(pcfg, sig, events, today, sell=False,
                                      policy_rates=policy_rates,
                                      backtest_rec=bt_pair.get("buy")),
        }
        high_events = data_layer.events_for_pair(
            win_events, pcfg["affected_by"], impact="high")
        pair_entries.append({
            "cfg": pcfg,
            "sig": sig,
            "plans": plans,
            "high_events": high_events,
            "nbp": nbp_v.get(pcfg["pair"]),
        })

    positions = []
    for pos in data_layer.load_positions()["positions"]:
        pc = next((c for c in config.PAIRS if c["pair"] == pos.get("pair")), None)
        if not pc or pos.get("pair") not in sig_by_pair:
            continue
        try:
            positions.append(planner.position_plan(pos, pc, sig_by_pair[pc["pair"]],
                                                   events, today, policy_rates))
        except (KeyError, ValueError) as e:
            sys.stderr.write("[main] pomijam pozycje {}: {}\n".format(pos.get("id"), e))
    positions.sort(key=lambda p: ({"overdue": 0, "open": 1, "done": 2}[p["status"]],
                                  p["deadline"]))

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "today": today.isoformat(),
        "data_date": pair_entries[0]["sig"]["last_date"],
        "demo": demo,
        "stale_days": int(hist.get("stale_days") or 0),
        "pair_entries": pair_entries,
        "positions": positions,
        "events": win_events,
        "backtest": bt,
        "backtest_recomputed": bt_recomputed,
        "policy_rates": rates_doc,
        "calendar_coverage_days": data_layer.calendar_coverage_days(events, today),
    }


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    args = parse_args(argv if argv is not None else sys.argv[1:])
    if handle_positions(args, date.today()):
        return 0

    analysis = run_analysis(demo=args.demo, force_backtest=args.force_backtest)
    html_doc = report.build_html(analysis)

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html_doc)

    state_path = notify.save_state(analysis)

    if not args.quiet:
        print(notify.text_summary(analysis))
        print("-" * 64)
        print("raport HTML: {}".format(args.out))
        print("historia:    {}".format(state_path))
        print("backtest:    {}".format(
            "przeliczono" if analysis["backtest_recomputed"] else "z cache"))
        cov = analysis["calendar_coverage_days"]
        if cov < config.CALENDAR_MIN_COVERAGE_DAYS:
            print("UWAGA: kalendarz wydarzen siega tylko {} dni naprzod".format(cov))

    if not args.no_email and not args.demo:
        ok, msg = notify.send_email(analysis, html_doc)
        if not args.quiet:
            print("e-mail:      {}".format(msg))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
