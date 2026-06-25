#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FX Advisor - punkt wej\u015bcia.

U\u017cycie:
  python main.py                 # realne dane EBC + raport HTML + (opcjonalnie) mail
  python main.py --demo          # dane syntetyczne (offline), do podgl\u0105du
  python main.py --no-email      # nie wysy\u0142aj maila niezale\u017cnie od ustawie\u0144
  python main.py --out raport.html

Domy\u015blnie zapisuje raport do fx_report.html i historie do fx_state.json.
"""

import os
import sys
import argparse

import engine
import report
import notify


def parse_args(argv):
    p = argparse.ArgumentParser(description="FX Advisor")
    p.add_argument("--demo", action="store_true", help="dane syntetyczne offline")
    p.add_argument("--out", default="fx_report.html", help="\u015bcie\u017cka raportu HTML")
    p.add_argument("--no-email", action="store_true", help="wy\u0142\u0105cz wysy\u0142k\u0119 maila")
    p.add_argument("--quiet", action="store_true", help="bez podsumowania w konsoli")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    analysis = engine.run_analysis(demo=args.demo)
    html_doc = report.build_html(analysis)

    # Utworz katalog docelowy, jesli nie istnieje (np. docs/ w swiezym repo).
    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html_doc)

    state_path = notify.save_state(analysis)

    if not args.quiet:
        print(notify.text_summary(analysis))
        print("-" * 60)
        print("raport HTML: {}".format(args.out))
        print("historia:    {}".format(state_path))

    if not args.no_email and not args.demo:
        ok, msg = notify.send_email(analysis, html_doc)
        if not args.quiet:
            print("e-mail:      {}".format(msg))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
