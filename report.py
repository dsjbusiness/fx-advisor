# -*- coding: utf-8 -*-
"""
Generator raportu HTML (samodzielny plik, zero zaleznosci, inline SVG).

Uklad:
  1. "Dzis do zrobienia" - zagregowane konkretne dzialania ze wszystkich par
  2. Dokladnie TRZY karty par (EUR/PLN, USD/PLN, EUR/USD), kazda z dwoma
     lustrzanymi wierszami werdyktow (po jednym na kierunek)
  3. Tabela wydarzen na 14 dni
  4. "Skutecznosc historyczna" (backtest)
  5. Metodologia + zastrzezenie
"""

import html
import math
from datetime import datetime

import config
import planner

VERDICT_COLORS = {
    "pos":     ("#1f7a5c", "#e7f3ed"),
    "neutral": ("#8a6212", "#faf2df"),
    "neg":     ("#b3382f", "#f8eae8"),
}
SRC_CLS = {"NBP": "ev-PLN", "GUS": "ev-PLN", "ECB": "ev-EUR",
           "Fed": "ev-USD", "BLS": "ev-USD"}


def _fmt(v, dp=4):
    return "{:.{dp}f}".format(v, dp=dp)


def _esc(t):
    return html.escape(str(t))


# kolory kierunkow na wykresie (linie zlecen/alertow)
CHART_SELL = "#1f7a5c"
CHART_BUY = "#3d5a99"
_CHART_LEVELS_BY_BUCKET = {"strong": (90,), "mild": (70, 85),
                           "weak": (50, 70), "wait": (50, 70)}


def _stack_labels(items, min_gap=10.0, y_min=9.0, y_max=147.0):
    """Rozsuwa etykiety prawej kolumny w pionie, by sie nie nakladaly.
    items = [(y, ...), ...]; zwraca liste y po korekcie (kolejnosc wg y)."""
    order = sorted(range(len(items)), key=lambda i: items[i][0])
    ys = [max(y_min, min(y_max, items[i][0])) for i in order]
    for k in range(1, len(ys)):
        ys[k] = max(ys[k], ys[k - 1] + min_gap)
    if ys and ys[-1] > y_max:
        ys[-1] = y_max
        for k in range(len(ys) - 2, -1, -1):
            ys[k] = min(ys[k], ys[k + 1] - min_gap)
    out = [0.0] * len(items)
    for pos, i in enumerate(order):
        out[i] = ys[pos]
    return out


def _decision_chart(entry, today, width=640, height=150):
    """Wykres decyzyjny: krotka historia (SPARK_SESSIONS) + okno 14 dni.
    W strefie okna: stozek 80% przedzialu, poziomy zlecen/alertow obu
    kierunkow, dni wydarzen high-impact i deadline."""
    sig = entry["sig"]
    values = sig["spark_values"]
    if len(values) < 2:
        return ""
    top, bot = 16.0, 16.0
    xl, xr = 6.0, width - 58.0
    current = sig["current"]
    half_end = sig["range80_half"]

    last_hist = datetime.strptime(sig["last_date"], "%Y-%m-%d").date()
    fwd_days = [d for d in planner.business_days(today) if d > last_hist]
    if not fwd_days:
        fwd_days = planner.business_days(today)[-1:]
    n_hist, n_fwd = len(values), len(fwd_days)
    total = n_hist + n_fwd

    def x(i):
        return xl + i / (total - 1.0) * (xr - xl)

    x_today = x(n_hist - 1)

    # stozek: polowka rosnie ~sqrt(sesji), koniec = range80_half z raportu
    halves = [half_end * math.sqrt((k + 1.0) / n_fwd) for k in range(n_fwd)]

    # poziomy zlecen/alertow obu kierunkow (bez DCA/neutral - tam nie ma zlecen)
    lvl_specs = []
    for key, color in (("sell", CHART_SELL), ("buy", CHART_BUY)):
        plan = entry["plans"][key]
        if plan["dca_override"] or plan["bucket"] == "neutral":
            continue
        for q in _CHART_LEVELS_BY_BUCKET[plan["bucket"]]:
            lvl_specs.append((plan["levels"][q], color))

    lo = min(min(values), current - half_end)
    hi = max(max(values), current + half_end)
    rng = (hi - lo) or 1e-9
    pad = rng * 0.05
    lo, hi = lo - pad, hi + pad
    rng = hi - lo

    def y(v):
        return height - bot - (v - lo) / rng * (height - top - bot)

    parts = []

    # strefa okna + separator "dzis"
    parts.append('<rect x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" '
                 'fill="#0b6b7a" fill-opacity="0.035"/>'.format(
                     x_today, top, xr - x_today, height - top - bot))
    parts.append('<line x1="{0:.1f}" y1="{1:.1f}" x2="{0:.1f}" y2="{2:.1f}" '
                 'stroke="#8a99a6" stroke-width="1" stroke-dasharray="3 3"/>'.format(
                     x_today, top, height - bot))

    # stozek 80%
    up = ["{:.1f},{:.1f}".format(x(n_hist - 1 + k + 1), y(current + halves[k]))
          for k in range(n_fwd)]
    dn = ["{:.1f},{:.1f}".format(x(n_hist - 1 + k + 1), y(current - halves[k]))
          for k in range(n_fwd - 1, -1, -1)]
    cone = "{:.1f},{:.1f} ".format(x_today, y(current)) + " ".join(up + dn)
    parts.append('<polygon points="{}" fill="#0b6b7a" fill-opacity="0.10"/>'.format(cone))
    parts.append('<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" '
                 'stroke="#8a99a6" stroke-width="1" stroke-dasharray="3 4" '
                 'stroke-opacity="0.7"/>'.format(x_today, y(current), xr, y(current)))

    # historia
    pts = " ".join("{:.1f},{:.1f}".format(x(i), y(v)) for i, v in enumerate(values))
    parts.append('<polyline points="{}" fill="none" stroke="#0b6b7a" '
                 'stroke-width="1.6" stroke-linejoin="round" '
                 'stroke-linecap="round"/>'.format(pts))

    # wydarzenia high-impact w oknie
    for e in entry["high_events"]:
        d = datetime.strptime(e["date"], "%Y-%m-%d").date()
        if d not in fwd_days:
            continue
        xe = x(n_hist - 1 + fwd_days.index(d) + 1)
        parts.append('<line x1="{0:.1f}" y1="{1:.1f}" x2="{0:.1f}" y2="{2:.1f}" '
                     'stroke="#b3382f" stroke-width="1" stroke-dasharray="2 3" '
                     'stroke-opacity="0.55"/>'.format(xe, top, height - bot))
        parts.append('<text x="{:.1f}" y="10.5" font-size="9" fill="#b3382f" '
                     'font-weight="650" text-anchor="middle">{} {:02d}.{:02d}'
                     '</text>'.format(xe, _esc(e["source"]), d.day, d.month))

    # deadline (ostatni bezpieczny dzien wykonania)
    final = entry["plans"]["sell"]["final_date"]
    if final in fwd_days:
        xd = x(n_hist - 1 + fwd_days.index(final) + 1)
        parts.append('<line x1="{0:.1f}" y1="{1:.1f}" x2="{0:.1f}" y2="{2:.1f}" '
                     'stroke="#14212e" stroke-width="1.4"/>'.format(
                         xd, height - bot, height - bot + 5))
        parts.append('<text x="{:.1f}" y="{:.1f}" font-size="9" fill="#14212e" '
                     'font-weight="650" text-anchor="middle">koniec okna '
                     '{:02d}.{:02d}</text>'.format(
                         max(46.0, min(xd, xr - 46.0)), height - 2.5,
                         final.day, final.month))

    # poziomy zlecen/alertow (kropkowane, tylko w strefie okna)
    lvl_items = []
    for v, color in lvl_specs:
        in_range = lo <= v <= hi
        yy = max(top, min(height - bot, y(v)))
        parts.append('<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" '
                     'stroke="{}" stroke-width="1.2" stroke-dasharray="2 3" '
                     'stroke-opacity="{}"/>'.format(
                         x_today, yy, xr, yy, color, "0.9" if in_range else "0.4"))
        arrow = "" if in_range else ("&#8593; " if y(v) < top else "&#8595; ")
        lvl_items.append((yy, "{}{}".format(arrow, _fmt(v)), color, 650))

    # prawa kolumna etykiet: krance stozka + poziomy
    lvl_items.append((y(current + half_end), _fmt(current + half_end), "#8a99a6", 400))
    lvl_items.append((y(current - half_end), _fmt(current - half_end), "#8a99a6", 400))
    for (_, txt, color, wgt), lab_y in zip(lvl_items, _stack_labels(lvl_items)):
        parts.append('<text x="{:.1f}" y="{:.1f}" font-size="9" fill="{}" '
                     'font-weight="{}">{}</text>'.format(
                         xr + 4, lab_y + 3, color, wgt, txt))

    # punkt i etykieta "dzis"
    parts.append('<circle cx="{:.1f}" cy="{:.1f}" r="3.0" fill="#14212e"/>'.format(
        x_today, y(current)))
    parts.append('<text x="{:.1f}" y="10.5" font-size="9.5" fill="#14212e" '
                 'font-weight="600" text-anchor="end">dziś</text>'.format(x_today - 4))

    return ('<svg class="spark" viewBox="0 0 {w} {h}" role="img" '
            'aria-label="ostatnie {n} sesji i projekcja okna {d} dni">{body}'
            '</svg>').format(w=width, h=height, n=n_hist, d=config.WINDOW_DAYS,
                             body="".join(parts))


def _gauge(score):
    """Pasek score -100..+100, srodek = 0."""
    pct = max(-100.0, min(100.0, score))
    half = abs(pct) / 100.0 * 50.0
    if pct >= 0:
        left, w, color = 50.0, half, "#1f7a5c"
    else:
        left, w, color = 50.0 - half, half, "#b3382f"
    return (
        '<div class="gauge-row"><span class="gauge-end">-100</span>'
        '<div class="gauge" role="img" aria-label="score {v:+.0f}">'
        '<div class="gauge-fill" style="left:{l:.1f}%;width:{w:.1f}%;background:{c}"></div>'
        '<div class="gauge-zero"></div></div>'
        '<span class="gauge-end">+100</span>'
        '<span class="gauge-val">{v:+.0f}</span></div>'
    ).format(v=pct, l=left, w=w, c=color)


def _verdict_col(plan):
    tcol, bg = VERDICT_COLORS[plan["verdict_cls"]]
    lines = "".join("<li>{}</li>".format(_esc(l)) for l in plan["lines"])
    ev = ""
    if plan["event_note"]:
        ev = '<p class="ev-note">{}</p>'.format(_esc(plan["event_note"]))
    bt_chip = ""
    if plan["dca_override"]:
        bt_chip = '<span class="chip chip-bt">backtest: stosuj DCA</span>'
    return (
        '<div class="vcol">'
        '<div class="vdir">{dir}</div>'
        '{gauge}'
        '<div class="vchip" style="color:{tcol};background:{bg}">'
        '<b>{verdict}</b><span>pewność: {conf}</span>{bt}</div>'
        '<ul class="plan">{lines}</ul>'
        '{ev}'
        '</div>'
    ).format(dir=_esc(plan["direction_label"]), gauge=_gauge(plan["score"]),
             tcol=tcol, bg=bg, verdict=_esc(plan["verdict"]),
             conf=_esc(plan["confidence_bucket"]), bt=bt_chip,
             lines=lines, ev=ev)


def _chart_legend(entry):
    cfg = entry["cfg"]
    items = ['<span><i class="sw sw-hist"></i>ostatnie {} sesji</span>'.format(
                 len(entry["sig"]["spark_values"])),
             '<span><i class="sw sw-cone"></i>80% przedział do końca okna '
             '({} dni)</span>'.format(config.WINDOW_DAYS)]
    for key, cls in (("sell", "sw-sell"), ("buy", "sw-buy")):
        plan = entry["plans"][key]
        if plan["dca_override"] or plan["bucket"] == "neutral":
            continue
        base = cfg["base"]
        lbl = ("zlecenia: sprzedaż {}".format(base) if key == "sell"
               else "zlecenia: kupno {}".format(base))
        items.append('<span><i class="sw {}"></i>{}</span>'.format(cls, _esc(lbl)))
    return '<div class="chart-legend">{}</div>'.format("".join(items))


def _pair_card(entry, today):
    cfg, sig = entry["cfg"], entry["sig"]
    change = sig["change_pct"]
    ch_cls = "up" if change > 0.005 else ("down" if change < -0.005 else "flat")
    ch_sign = "+" if change > 0 else ""

    money = sig["range80_half"] * cfg["unit_amount"]
    money_txt = ("maksymalny realny zysk z timingu: ok. {:,.0f} {} na każde "
                 "{:,.0f} {}").format(money, cfg["quote"], float(cfg["unit_amount"]),
                                      cfg["base"]).replace(",", " ")

    vol_pl = {"low": "niska", "normal": "normalna", "high": "wysoka"}[sig["vol_regime"]]

    badges = ""
    for e in entry["high_events"]:
        d = datetime.strptime(e["date"], "%Y-%m-%d").date()
        badges += '<span class="badge badge-{src}">{src} {dd:02d}.{mm:02d}</span>'.format(
            src=_esc(e["source"]), dd=d.day, mm=d.month)
    if badges:
        badges = '<div class="badges">{}</div>'.format(badges)

    return (
        '<article class="card">'
        '<header class="card-h">'
        '<div class="pair-name">{label}</div>'
        '<div class="pair-rate"><span class="rate-v">{rate}</span>'
        '<span class="rate-ch rate-{chcls}">{sign}{ch:.2f}%</span></div>'
        '</header>'
        '{badges}'
        '<div class="spark-wrap">{spark}</div>'
        '{legend}'
        '<div class="range-line">80% przedział na koniec okna ({win} dni): '
        '<b>{lo} - {hi}</b> · {money} · zmienność: {vol}</div>'
        '<div class="verdicts">{vsell}{vbuy}</div>'
        '</article>'
    ).format(label=_esc(cfg["label"]), rate=_fmt(sig["current"]),
             chcls=ch_cls, sign=ch_sign, ch=change, badges=badges,
             spark=_decision_chart(entry, today), legend=_chart_legend(entry),
             win=config.WINDOW_DAYS,
             lo=_fmt(sig["range80_lo"]), hi=_fmt(sig["range80_hi"]),
             money=_esc(money_txt), vol=vol_pl,
             vsell=_verdict_col(entry["plans"]["sell"]),
             vbuy=_verdict_col(entry["plans"]["buy"]))


def _todo_box(analysis):
    items = []
    for entry in analysis["pair_entries"]:
        cfg = entry["cfg"]
        for key in ("sell", "buy"):
            plan = entry["plans"][key]
            if not plan["today_action"]:
                continue
            base, quote = cfg["base"], cfg["quote"]
            short = "{}→{}".format(base, quote) if plan["sell"] else \
                    "{}→{}".format(quote, base)
            items.append((abs(plan["score"]),
                          "<b>{}</b>: {}".format(_esc(short), _esc(plan["today_action"]))))
    items.sort(key=lambda x: -x[0])
    if items:
        lis = "".join("<li>{}</li>".format(t) for _, t in items)
        body = "<ul>{}</ul>".format(lis)
    else:
        body = ("<p>Brak pilnych działań na dziś - żaden kierunek nie wymaga "
                "wymiany dzisiaj. Alerty i terminy końcowe planu pilnują reszty.</p>")
    return ('<section class="todo"><h2>Dziś do zrobienia</h2>{}'
            '<p class="todo-note">Działania warunkowe - dotyczą kwot, które '
            'faktycznie masz do wymiany w danym kierunku w oknie {d} dni.</p>'
            '</section>').format(body, d=config.WINDOW_DAYS)


def _events_section(events):
    if not events:
        return ('<section class="events"><h2>Wydarzenia w oknie ({d} dni)</h2>'
                '<p class="ev-empty">Brak zaplanowanych publikacji i decyzji '
                'w najbliższych {d} dniach.</p></section>').format(d=config.WINDOW_DAYS)
    rows = ""
    for e in events:
        d = datetime.strptime(e["date"], "%Y-%m-%d").date()
        imp = ("<span class='imp imp-high'>wysoki</span>" if e["impact"] == "high"
               else "<span class='imp imp-med'>średni</span>")
        rows += (
            '<tr><td class="ev-d">{dt}<span>za {days} dni</span></td>'
            '<td><span class="ev-bank {cls}">{src}</span></td>'
            '<td>{name}</td><td>{ccy}</td><td>{imp}</td></tr>'
        ).format(dt=planner.fmt_date(d), days=e["days_ahead"],
                 cls=SRC_CLS.get(e["source"], "ev-EUR"), src=_esc(e["source"]),
                 name=_esc(e["name"]), ccy="/".join(e["currencies"]), imp=imp)
    return (
        '<section class="events"><h2>Wydarzenia w oknie ({d} dni)</h2>'
        '<p class="ev-note-s">Wszystkie źródła: decyzje NBP/EBC/Fed oraz kluczowe '
        'publikacje makro (CPI, NFP). Dni o wysokim wpływie są omijane przez '
        'transze DCA i termin końcowy planu.</p>'
        '<table class="ev-table"><tbody>{rows}</tbody></table></section>'
    ).format(d=config.WINDOW_DAYS, rows=rows)


def _backtest_section(bt):
    if not bt or not bt.get("pairs"):
        return ('<section class="bt"><h2>Skuteczność historyczna</h2>'
                '<p>Backtest niedostępny (za mało historii w cache).</p></section>')
    rows = ""
    for pcfg in config.PAIRS:
        pair = pcfg["pair"]
        pdata = bt["pairs"].get(pair) or {}
        for key, sell in (("sell", True), ("buy", False)):
            rec = pdata.get(key)
            if not rec:
                continue
            base, quote = pcfg["base"], pcfg["quote"]
            lbl = "{}→{}".format(base, quote) if sell else "{}→{}".format(quote, base)
            edge = rec["edge_bps_vs_dca"]
            if edge > 0:
                verdict = "<span class='bt-pos'>sygnał daje przewagę</span>"
            else:
                verdict = "<span class='bt-neg'>brak przewagi - stosuj DCA</span>"
            rows += (
                '<tr><td class="bt-dir">{lbl}</td>'
                '<td class="num">{edge:+.1f} pb</td>'
                '<td class="num">{hit:.0f}%</td>'
                '<td class="num">{d1:+.1f} pb</td>'
                '<td class="num">{dl:+.1f} pb</td>'
                '<td class="num">{n}</td><td>{v}</td></tr>'
            ).format(lbl=lbl, edge=edge, hit=rec["hit_rate_pct"],
                     d1=rec["edge_bps_vs_day1"], dl=rec["edge_bps_vs_lastday"],
                     n=rec["n_windows"], v=verdict)
    return (
        '<section class="bt"><h2>Skuteczność historyczna (backtest)</h2>'
        '<p class="bt-note">Walk-forward na całej cache\'owanej historii: dla '
        'każdego możliwego okna {d}-dniowego symulowano plany transz silnika '
        'dzień po dniu (sygnały przeliczane codziennie, z twardym terminem '
        'końcowym). Przewaga = kurs osiągnięty vs benchmark, w punktach '
        'bazowych (1 pb = 0.01%). Gdy przewaga vs DCA jest &le;0, narzędzie '
        'wprost zaleca DCA dla tego kierunku.</p>'
        '<table class="bt-table"><thead><tr><th>Kierunek</th><th>vs DCA</th>'
        '<th>hit-rate</th><th>vs 1. dzień</th><th>vs ostatni</th>'
        '<th>okien</th><th>wniosek</th></tr></thead><tbody>{rows}</tbody></table>'
        '<p class="bt-meta">stan: {as_of} · silnik v{ver}</p></section>'
    ).format(d=config.WINDOW_DAYS, rows=rows, as_of=_esc(bt.get("as_of", "-")),
             ver=_esc(bt.get("engine_version", "-")))


def build_html(analysis):
    today = datetime.strptime(analysis["today"], "%Y-%m-%d").date()
    cards = "".join(_pair_card(e, today) for e in analysis["pair_entries"])
    banners = ""
    if analysis["demo"]:
        banners += ('<div class="demo-banner">TRYB DEMO - dane syntetyczne. '
                    'Uruchom bez flagi --demo, by pobrać realne kursy EBC.</div>')
    stale_days = int(analysis.get("stale_days") or 0)
    if stale_days:
        banners += ('<div class="demo-banner">UWAGA: źródła kursów były '
                    'niedostępne — raport policzony na danych z {d} '
                    '({n} dni wstecz). Plany i poziomy mogą być '
                    'nieaktualne.</div>').format(
                        d=_esc(analysis["data_date"]), n=stale_days)

    return TEMPLATE.format(
        generated=_esc(analysis["generated_at"]),
        data_date=_esc(analysis["data_date"]),
        window=config.WINDOW_DAYS,
        sell_c=CHART_SELL,
        buy_c=CHART_BUY,
        demo_banner=banners,
        todo=_todo_box(analysis),
        cards=cards,
        events=_events_section(analysis["events"]),
        backtest=_backtest_section(analysis["backtest"]),
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="apple-touch-icon" href="favicon.svg">
<title>FX Advisor - plan wymiany walut</title>
<style>
  :root {{
    --bg:#eceff3; --surface:#ffffff; --ink:#14212e; --muted:#5f7180;
    --faint:#8a99a6; --line:#dde4ea; --accent:#0b6b7a;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    line-height:1.5; -webkit-font-smoothing:antialiased;
  }}
  .wrap {{ max-width:1020px; margin:0 auto; padding:26px 18px 56px; }}

  header.top {{ display:flex; justify-content:space-between; align-items:flex-end;
    flex-wrap:wrap; gap:12px; border-bottom:2px solid var(--ink); padding-bottom:14px; }}
  .top h1 {{ font-size:clamp(20px,3vw,26px); margin:0; letter-spacing:-0.02em; }}
  .top .sub {{ color:var(--muted); font-size:13px; margin-top:3px; }}
  .top .meta {{ text-align:right; font-size:12px; color:var(--muted);
    font-variant-numeric:tabular-nums; }}
  .top .meta b {{ color:var(--ink); font-weight:600; }}
  .demo-banner {{ margin:14px 0 0; padding:8px 12px; background:#fbf2df; color:#8a6212;
    font-size:12px; border-radius:6px; }}

  h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:0.08em;
    color:var(--muted); margin:0 0 12px; font-weight:650; }}

  .todo {{ margin:20px 0 22px; background:#10222b; color:#e8f1f4; border-radius:12px;
    padding:16px 20px 12px; }}
  .todo h2 {{ color:#7fd0de; }}
  .todo ul {{ margin:0; padding-left:20px; }}
  .todo li {{ margin-bottom:6px; font-size:14.5px; }}
  .todo li b {{ color:#7fd0de; font-variant-numeric:tabular-nums; }}
  .todo p {{ margin:0; font-size:13.5px; color:#b9cdd4; }}
  .todo-note {{ margin-top:10px !important; font-size:11px !important; color:#7d97a1 !important; }}

  .card {{ background:var(--surface); border:1px solid var(--line); border-radius:12px;
    padding:18px 20px 16px; margin-bottom:18px; }}
  .card-h {{ display:flex; justify-content:space-between; align-items:baseline; gap:10px; }}
  .pair-name {{ font-size:20px; font-weight:700; letter-spacing:-0.01em; }}
  .pair-rate {{ display:flex; align-items:baseline; gap:10px; }}
  .rate-v {{ font-size:22px; font-weight:650; font-variant-numeric:tabular-nums; }}
  .rate-ch {{ font-size:13px; font-weight:600; font-variant-numeric:tabular-nums; }}
  .rate-up {{ color:#1f7a5c; }} .rate-down {{ color:#b3382f; }} .rate-flat {{ color:var(--faint); }}

  .badges {{ margin:8px 0 0; display:flex; flex-wrap:wrap; gap:6px; }}
  .badge {{ font-size:11px; font-weight:650; padding:2px 9px; border-radius:20px; }}
  .badge-NBP, .badge-GUS {{ background:#f8eae8; color:#b3382f; }}
  .badge-ECB {{ background:#e9f1f3; color:#0b6b7a; }}
  .badge-Fed, .badge-BLS {{ background:#edeff5; color:#3d5a99; }}

  .spark-wrap {{ margin:12px 0 2px; }}
  .spark {{ width:100%; height:auto; display:block; }}
  .chart-legend {{ display:flex; flex-wrap:wrap; gap:3px 16px; font-size:11px;
    color:var(--muted); margin:2px 0 4px; }}
  .chart-legend i {{ display:inline-block; width:12px; height:3px; border-radius:2px;
    margin-right:5px; vertical-align:middle; }}
  .sw-hist {{ background:#0b6b7a; }}
  .sw-cone {{ background:#0b6b7a; opacity:0.22; height:8px; }}
  .sw-sell {{ background:{sell_c}; }}
  .sw-buy {{ background:{buy_c}; }}
  .range-line {{ font-size:12.5px; color:var(--muted); padding:8px 0 12px;
    border-bottom:1px solid var(--line); }}
  .range-line b {{ color:var(--ink); font-variant-numeric:tabular-nums; }}

  .verdicts {{ display:grid; grid-template-columns:1fr 1fr; gap:0 22px; margin-top:14px; }}
  .vcol {{ min-width:0; }}
  .vcol + .vcol {{ border-left:1px solid var(--line); padding-left:22px; }}
  .vdir {{ font-size:13.5px; font-weight:700; margin-bottom:8px; }}
  .gauge-row {{ display:flex; align-items:center; gap:7px; margin-bottom:8px; }}
  .gauge-end {{ font-size:9px; color:var(--faint); font-variant-numeric:tabular-nums; }}
  .gauge {{ position:relative; flex:1; height:8px; background:#eef2f5; border-radius:5px; }}
  .gauge-fill {{ position:absolute; top:0; height:100%; border-radius:5px; }}
  .gauge-zero {{ position:absolute; left:50%; top:-3px; width:1.5px; height:14px;
    background:var(--faint); transform:translateX(-50%); }}
  .gauge-val {{ font-size:12px; font-weight:700; font-variant-numeric:tabular-nums;
    min-width:34px; text-align:right; }}
  .vchip {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap;
    padding:7px 11px; border-radius:8px; margin-bottom:9px; }}
  .vchip b {{ font-size:14px; }}
  .vchip span {{ font-size:11px; opacity:0.85; }}
  .chip-bt {{ background:#14212e; color:#fff !important; padding:2px 8px;
    border-radius:12px; font-weight:650; opacity:1 !important; }}
  .plan {{ margin:0; padding-left:18px; }}
  .plan li {{ font-size:12.5px; margin-bottom:5px; color:#2c3a47;
    font-variant-numeric:tabular-nums; }}
  .ev-note {{ font-size:11.5px; color:#8a6212; background:#faf2df; padding:7px 10px;
    border-radius:7px; margin:9px 0 0; }}

  .events, .bt {{ margin-top:26px; background:var(--surface); border:1px solid var(--line);
    border-radius:12px; padding:18px 20px; }}
  .ev-note-s, .bt-note {{ font-size:12.5px; color:var(--muted); margin:0 0 12px; }}
  .ev-empty {{ font-size:13px; color:var(--muted); margin:0; }}
  .ev-table, .bt-table {{ width:100%; border-collapse:collapse; }}
  .ev-table td, .bt-table td, .bt-table th {{ padding:8px 6px;
    border-top:1px solid var(--line); font-size:12.5px; vertical-align:middle; }}
  .bt-table th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:0.05em;
    color:var(--faint); text-align:left; border-top:none; }}
  .ev-d {{ font-variant-numeric:tabular-nums; font-weight:600; white-space:nowrap; }}
  .ev-d span {{ display:block; font-size:10.5px; color:var(--faint); font-weight:400; }}
  .ev-bank {{ display:inline-block; padding:2px 9px; border-radius:20px; font-size:11px;
    font-weight:600; }}
  .ev-EUR {{ background:#e9f1f3; color:#0b6b7a; }}
  .ev-USD {{ background:#edeff5; color:#3d5a99; }}
  .ev-PLN {{ background:#f8eae8; color:#b3382f; }}
  .imp {{ font-size:10.5px; font-weight:650; padding:2px 8px; border-radius:12px; }}
  .imp-high {{ background:#f8eae8; color:#b3382f; }}
  .imp-med {{ background:#faf2df; color:#8a6212; }}

  .bt-dir {{ font-weight:650; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .num {{ font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .bt-pos {{ color:#1f7a5c; font-weight:650; }}
  .bt-neg {{ color:#b3382f; font-weight:650; }}
  .bt-meta {{ margin:10px 0 0; font-size:11px; color:var(--faint); }}

  .method {{ margin-top:26px; font-size:12px; color:var(--muted);
    border-top:1px solid var(--line); padding-top:16px; }}
  .method p {{ margin:0 0 8px; }}
  .method b {{ color:var(--ink); }}

  @media (max-width:640px) {{
    .verdicts {{ grid-template-columns:1fr; }}
    .vcol + .vcol {{ border-left:none; padding-left:0; border-top:1px solid var(--line);
      padding-top:14px; margin-top:14px; }}
    .top .meta {{ text-align:left; }}
    .bt-table th:nth-child(4), .bt-table td:nth-child(4),
    .bt-table th:nth-child(5), .bt-table td:nth-child(5) {{ display:none; }}
  }}
</style>
</head>
<body>
<div class="wrap">

  <header class="top">
    <div>
      <h1>FX Advisor</h1>
      <div class="sub">Plan wymiany walut w kroczacym oknie {window} dni</div>
    </div>
    <div class="meta">
      wygenerowano: <b>{generated}</b><br>
      dane (fixing EBC): <b>{data_date}</b>
    </div>
  </header>

  {demo_banner}

  {todo}

  {cards}

  {events}

  {backtest}

  <section class="method">
    <p><b>Metodologia.</b> Score S (-100..+100, liczony raz na pare; kierunek
    przeciwny = -S) = 0.55 x poziom + 0.25 x tendencja + 0.20 x pilnosc.
    Poziom: mieszany percentyl kursu (0.2 x 30 sesji + 0.3 x 90 + 0.5 x 250).
    Tendencja: zwrot z 10 sesji normalizowany zmiennoscia 20-sesyjna (miara
    t-podobna). Pilnosc: skrajne wykupienie/wyprzedanie (%B Bollingera, RSI 14) -
    przy korzystnym poziomie skrajnosc PODNOSI pilnosc realizacji ("bierz teraz,
    nie czekaj na wiecej"), nie pewnosc kontynuacji. Pewnosc werdyktu wynika ze
    zgodnosci sygnalow i rezimu zmiennosci (wysoka zmiennosc obniza pewnosc
    i poszerza transze). 80% przedzial: kurs +/- 1.28 x sigma dzienna x sqrt(10).
    Wykres pokazuje tylko ostatnie ~2 miesiace i projekcje okna {window} dni
    (stozek 80%, poziomy zlecen, wydarzenia, deadline) - dluzsza historia
    (250 sesji) sluzy wylacznie do liczenia percentyli, nie do patrzenia.
    Poziomy zlecen lezace poza 80% przedzialem okna sa oznaczane jako malo
    realne. Twarda zasada: calosc wymieniona do konca okna {window} dni, nigdy
    w dniu wydarzenia high-impact. Dane: kursy referencyjne EBC (Frankfurter
    API); USD/PLN wyliczany krzyzowo.</p>
    <p><b>Zastrzezenie.</b> Kurs w horyzoncie 2 tygodni jest w duzej mierze
    nieprzewidywalny. Narzedzie porzadkuje fakty i wymusza dyscypline transz -
    nie jest prognoza ani porada inwestycyjna. Decyzje podejmujesz samodzielnie.</p>
  </section>

</div>
</body>
</html>"""
