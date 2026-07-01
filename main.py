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
    return p.parse_args(argv)


def run_analysis(demo=False, force_backtest=False):
    today = date.today()

    if demo:
        hist = data_layer.demo_history(today=today)
        series = data_layer.series_from_history(hist)
        events = data_layer.load_events()
        bt = backtest.run_backtest(series, events, today=today)  # w pamieci
        bt_recomputed = True
    else:
        hist = data_layer.update_history(today=today)
        series = data_layer.series_from_history(hist)
        events = data_layer.load_events()
        bt, bt_recomputed = backtest.get_backtest(
            series, events, force=force_backtest, today=today)

    win_events = data_layer.events_in_window(events, today)

    pair_entries = []
    for pcfg in config.PAIRS:
        ser = series[pcfg["pair"]]
        sig = signals.compute_pair_signal(ser)
        bt_pair = (bt.get("pairs") or {}).get(pcfg["pair"]) or {}
        plans = {
            "sell": planner.build_plan(pcfg, sig, win_events, today,
                                       sell=True, backtest_rec=bt_pair.get("sell")),
            "buy": planner.build_plan(pcfg, sig, win_events, today,
                                      sell=False, backtest_rec=bt_pair.get("buy")),
        }
        high_events = data_layer.events_for_pair(
            win_events, pcfg["affected_by"], impact="high")
        pair_entries.append({
            "cfg": pcfg,
            "sig": sig,
            "plans": plans,
            "high_events": high_events,
        })

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "today": today.isoformat(),
        "data_date": pair_entries[0]["sig"]["last_date"],
        "demo": demo,
        "pair_entries": pair_entries,
        "events": win_events,
        "backtest": bt,
        "backtest_recomputed": bt_recomputed,
    }


def main(argv=None):
    # konsola Windows (cp1250) nie zna znakow typu "→" - nie wywalaj sie na print
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    args = parse_args(argv if argv is not None else sys.argv[1:])

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

    if not args.no_email and not args.demo:
        ok, msg = notify.send_email(analysis, html_doc)
        if not args.quiet:
            print("e-mail:      {}".format(msg))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
