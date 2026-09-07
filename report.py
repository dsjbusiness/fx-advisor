# -*- coding: utf-8 -*-
"""
Generator raportu HTML (samodzielny plik, zero zaleznosci, inline SVG).

Uklad (F101):
  1. "Twoje pozycje" - realne kwoty, deadline, plan reszty, dzisiejsza transza
  2. "Dzis do zrobienia" - transze z pozycji na dzis
  3. Trzy karty par: kurs EBC + fixing NBP + kurs do ksiegowania, wykres
     (historia, stozek 80%, dni reakcji na wydarzenia, transze DCA), linia
     "dostawca vs timing", dwa kierunki: plan-szablon DCA + kontekst
  4. Tabela wydarzen (data publikacji i dzien reakcji)
  5. Backtest na pelnej historii (okna rozlaczne, 90% CI)
  6. Metodologia + zastrzezenie
"""

import html
import math
from datetime import datetime

import config
import planner

SRC_CLS = {"NBP": "ev-PLN", "GUS": "ev-PLN", "ECB": "ev-EUR",
           "Fed": "ev-USD", "BLS": "ev-USD"}
CHART_SELL = "#1f7a5c"
CHART_BUY = "#3d5a99"


def _fmt(v, dp=4):
    return "{:.{dp}f}".format(v, dp=dp)


def _money(v):
    return "{:,.0f}".format(v).replace(",", " ")


def _esc(t):
    return html.escape(str(t))


# ===========================================================================
# WYKRES
# ===========================================================================

def _decision_chart(entry, today, width=640, height=150):
    sig = entry["sig"]
    values = sig["spark_values"]
    if len(values) < 2:
        return ""
    top, bot = 16.0, 18.0
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
    halves = [half_end * math.sqrt((k + 1.0) / n_fwd) for k in range(n_fwd)]

    lo = min(min(values), current - half_end)
    hi = max(max(values), current + half_end)
    rng = (hi - lo) or 1e-9
    pad = rng * 0.05
    lo, hi = lo - pad, hi + pad
    rng = hi - lo

    def y(v):
        return height - bot - (v - lo) / rng * (height - top - bot)

    parts = []
    parts.append('<rect x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{:.1f}" '
                 'fill="#0b6b7a" fill-opacity="0.035"/>'.format(
                     x_today, top, xr - x_today, height - top - bot))
    parts.append('<line x1="{0:.1f}" y1="{1:.1f}" x2="{0:.1f}" y2="{2:.1f}" '
                 'stroke="#8a99a6" stroke-width="1" stroke-dasharray="3 3"/>'.format(
                     x_today, top, height - bot))
    up = ["{:.1f},{:.1f}".format(x(n_hist - 1 + k + 1), y(current + halves[k]))
          for k in range(n_fwd)]
    dn = ["{:.1f},{:.1f}".format(x(n_hist - 1 + k + 1), y(current - halves[k]))
          for k in range(n_fwd - 1, -1, -1)]
    cone = "{:.1f},{:.1f} ".format(x_today, y(current)) + " ".join(up + dn)
    parts.append('<polygon points="{}" fill="#0b6b7a" fill-opacity="0.10"/>'.format(cone))
    parts.append('<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" '
                 'stroke="#8a99a6" stroke-width="1" stroke-dasharray="3 4" '
                 'stroke-opacity="0.7"/>'.format(x_today, y(current), xr, y(current)))
    pts = " ".join("{:.1f},{:.1f}".format(x(i), y(v)) for i, v in enumerate(values))
    parts.append('<polyline points="{}" fill="none" stroke="#0b6b7a" '
                 'stroke-width="1.6" stroke-linejoin="round" '
                 'stroke-linecap="round"/>'.format(pts))

    # dni reakcji na wydarzenia high-impact (effective_date)
    for e in entry["high_events"]:
        d = datetime.strptime(e.get("effective_date", e["date"]), "%Y-%m-%d").date()
        if d not in fwd_days:
            continue
        xe = x(n_hist - 1 + fwd_days.index(d) + 1)
        parts.append('<line x1="{0:.1f}" y1="{1:.1f}" x2="{0:.1f}" y2="{2:.1f}" '
                     'stroke="#b3382f" stroke-width="1" stroke-dasharray="2 3" '
                     'stroke-opacity="0.55"/>'.format(xe, top, height - bot))
        parts.append('<text x="{:.1f}" y="10.5" font-size="9" fill="#b3382f" '
                     'font-weight="650" text-anchor="middle">{} {:02d}.{:02d}'
                     '</text>'.format(xe, _esc(e["source"]), d.day, d.month))

    # transze DCA (daty z planu sprzedazy; kupno ma te same sesje)
    for d, _w, p in entry["plans"]["sell"]["schedule"]:
        if d not in fwd_days:
            continue
        xt = x(n_hist - 1 + fwd_days.index(d) + 1)
        yb = height - bot
        parts.append('<polygon points="{:.1f},{:.1f} {:.1f},{:.1f} {:.1f},{:.1f}" '
                     'fill="{}"/>'.format(xt - 4, yb + 6, xt + 4, yb + 6, xt, yb + 1,
                                          CHART_SELL))

    final = entry["plans"]["sell"]["final_date"]
    if final in fwd_days:
        xd = x(n_hist - 1 + fwd_days.index(final) + 1)
        parts.append('<text x="{:.1f}" y="{:.1f}" font-size="9" fill="#14212e" '
                     'font-weight="650" text-anchor="middle">koniec okna '
                     '{:02d}.{:02d}</text>'.format(
                         max(46.0, min(xd, xr - 46.0)), height - 1.5,
                         final.day, final.month))

    for v, wgt in ((current + half_end, 400), (current - half_end, 400)):
        parts.append('<text x="{:.1f}" y="{:.1f}" font-size="9" fill="#8a99a6" '
                     'font-weight="{}">{}</text>'.format(xr + 4, y(v) + 3, wgt, _fmt(v)))
    parts.append('<circle cx="{:.1f}" cy="{:.1f}" r="3.0" fill="#14212e"/>'.format(
        x_today, y(current)))
    parts.append('<text x="{:.1f}" y="10.5" font-size="9.5" fill="#14212e" '
                 'font-weight="600" text-anchor="end">dziś</text>'.format(x_today - 4))
    return ('<svg class="spark" viewBox="0 0 {w} {h}" role="img" '
            'aria-label="ostatnie {n} sesji i projekcja okna {d} dni">{body}'
            '</svg>').format(w=width, h=height, n=n_hist, d=config.WINDOW_DAYS,
                             body="".join(parts))


def _chart_legend(entry):
    items = ['<span><i class="sw sw-hist"></i>ostatnie {} sesji</span>'.format(
                 len(entry["sig"]["spark_values"])),
             '<span><i class="sw sw-cone"></i>80% przedział do końca okna '
             '({} dni)</span>'.format(config.WINDOW_DAYS),
             '<span><i class="sw sw-sell"></i>transze DCA</span>',
             '<span><i class="sw sw-ev"></i>dzień reakcji na wydarzenie</span>']
    return '<div class="chart-legend">{}</div>'.format("".join(items))


# ===========================================================================
# KARTA PARY
# ===========================================================================

def _direction_col(plan):
    lines = "".join("<li>{}</li>".format(_esc(l)) for l in plan["lines"])
    ctx = "".join("<li>{}</li>".format(_esc(l)) for l in plan["context"])
    tilt_txt = {"front": "przechył: początek okna", "back": "przechył: koniec okna",
                "flat": "równe transze"}[plan["tilt"]]
    return (
        '<div class="vcol">'
        '<div class="vdir">{dir}</div>'
        '<div class="vchip"><b>DCA</b><span>{tilt} · carry {carry:+.0f} pb</span></div>'
        '<ul class="plan">{lines}</ul>'
        '<div class="ctx-h">Kontekst (nie steruje transzami)</div>'
        '<ul class="ctx">{ctx}</ul>'
        '</div>'
    ).format(dir=_esc(plan["direction_label"]), tilt=tilt_txt,
             carry=plan["carry_bps"], lines=lines, ctx=ctx)


def _provider_line(entry, bt_pair):
    cfg, sig = entry["cfg"], entry["sig"]
    unit = float(cfg["unit_amount"])
    rate = sig["current"]
    provs = config.PROVIDERS
    cur = provs[config.DEFAULT_PROVIDER]
    best = min(provs, key=lambda p: p["spread_bps"])
    save_bps = cur["spread_bps"] - best["spread_bps"]
    save_money = save_bps / 1e4 * unit * rate
    ceiling = None
    if bt_pair and bt_pair.get("sell") and bt_pair["sell"].get("ceiling_bps") is not None:
        ceiling = bt_pair["sell"]["ceiling_bps"] / 1e4 * unit * rate
    eng = (bt_pair or {}).get("sell", {}).get("engine") if bt_pair else None
    real = eng["edge_bps_vs_dca"] / 1e4 * unit * rate if eng else None
    txt = ("Dostawca: <b>{cur}</b> (spread {cs:.0f} pb). Zmiana na <b>{best}</b> "
           "({bs:.0f} pb) daje ok. <b>{sm} {q}</b> na każde {u} {b}.").format(
               cur=_esc(cur["name"]), cs=cur["spread_bps"], best=_esc(best["name"]),
               bs=best["spread_bps"], sm=_money(save_money), q=cfg["quote"],
               u=_money(unit), b=cfg["base"])
    if ceiling is not None:
        txt += (" Timing w oknie: sufit ok. {c} {q} przy pełnej wiedzy o "
                "przyszłości").format(c=_money(ceiling), q=cfg["quote"])
        if real is None:
            txt += "."
        elif real >= 0:
            txt += ", aktywny plan z backtestu dawał ok. {} {} lepiej niż DCA.".format(
                _money(real), cfg["quote"])
        else:
            txt += ", aktywny plan z backtestu wychodził ok. {} {} GORZEJ niż DCA.".format(
                _money(-real), cfg["quote"])
    if cur["fee_fixed"]:
        txt += " Opłata stała {:.0f} {} × {} transze.".format(
            cur["fee_fixed"], cfg["quote"], config.DCA_TRANCHES)
    return '<div class="prov-line">{}</div>'.format(txt)


def _fixing_line(entry):
    cfg, sig = entry["cfg"], entry["sig"]
    nbp = entry.get("nbp")
    parts = ["EBC 14:15 ({}): <b>{}</b>".format(_esc(sig["last_date"]), _fmt(sig["current"]))]
    if nbp:
        parts.append("NBP tab. A ({}): <b>{}</b>".format(_esc(nbp["last_date"]), _fmt(nbp["last"])))
        if nbp.get("acc"):
            parts.append("kurs do księgowania (NBP z {}): <b>{}</b>".format(
                _esc(nbp["acc_date"]), _fmt(nbp["acc"])))
    return '<div class="fix-line">{}</div>'.format(" · ".join(parts))


def _pair_card(entry, today, bt_pair):
    cfg, sig = entry["cfg"], entry["sig"]
    change = sig["change_pct"]
    ch_cls = "up" if change > 0.005 else ("down" if change < -0.005 else "flat")
    ch_sign = "+" if change > 0 else ""
    money = sig["range80_half"] * cfg["unit_amount"]
    money_txt = ("połowa szerokości = ok. {} {} na każde {} {}").format(
        _money(money), cfg["quote"], _money(float(cfg["unit_amount"])), cfg["base"])
    vol_pl = {"low": "niska", "normal": "normalna", "high": "wysoka"}[sig["vol_regime"]]
    badges = ""
    for e in entry["high_events"]:
        d = datetime.strptime(e.get("effective_date", e["date"]), "%Y-%m-%d").date()
        badges += '<span class="badge badge-{src}">{src} reakcja {dd:02d}.{mm:02d}</span>'.format(
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
        '{fixing}'
        '{badges}'
        '<div class="spark-wrap">{spark}</div>'
        '{legend}'
        '<div class="range-line">80% przedział na koniec okna ({win} dni): '
        '<b>{lo} - {hi}</b> · {money} · zmienność: {vol}</div>'
        '{prov}'
        '<div class="verdicts">{vsell}{vbuy}</div>'
        '</article>'
    ).format(label=_esc(cfg["label"]), rate=_fmt(sig["current"]),
             chcls=ch_cls, sign=ch_sign, ch=change, fixing=_fixing_line(entry),
             badges=badges, spark=_decision_chart(entry, today),
             legend=_chart_legend(entry), win=config.WINDOW_DAYS,
             lo=_fmt(sig["range80_lo"]), hi=_fmt(sig["range80_hi"]),
             money=_esc(money_txt), vol=vol_pl, prov=_provider_line(entry, bt_pair),
             vsell=_direction_col(entry["plans"]["sell"]),
             vbuy=_direction_col(entry["plans"]["buy"]))


# ===========================================================================
# POZYCJE + DZIS
# ===========================================================================

def _positions_section(positions):
    if not positions:
        return ('<section class="pos"><h2>Twoje pozycje</h2>'
                '<p class="pos-empty">Brak otwartych pozycji. Dodaj kwotę i deadline: '
                'GitHub → Actions → „FX Advisor” → Run workflow (action: add), '
                'albo lokalnie <code>python main.py --add-position EURPLN sell 10000 '
                '2026-09-30</code>. Wykonane transze zapisuj przez '
                '<code>--record-fill</code>. Plan poniżej liczy się dla RESZTY kwoty '
                'i RESZTY dni.</p></section>')
    cards = ""
    for p in positions:
        st_cls = {"open": "st-open", "done": "st-done", "overdue": "st-over"}[p["status"]]
        st_txt = {"open": "otwarta", "done": "zamknięta", "overdue": "po terminie"}[p["status"]]
        lines = "".join("<li>{}</li>".format(_esc(l)) for l in p["lines"])
        prog = 100.0 * p["done"] / p["amount"] if p["amount"] else 0.0
        cards += (
            '<div class="pos-card">'
            '<div class="pos-h"><b>{id}</b> · {label} · {dir} · {amt} {src} '
            '· do {dl} <span class="st {cls}">{st}</span></div>'
            '<div class="bar"><div class="bar-fill" style="width:{prog:.0f}%"></div></div>'
            '<ul class="plan">{lines}</ul>{note}'
            '</div>'
        ).format(id=_esc(p["id"]), label=_esc(p["label"]), dir=_esc(p["direction_label"]),
                 amt=_money(p["amount"]), src=p["src_ccy"],
                 dl=planner.fmt_date(p["deadline"]), cls=st_cls, st=st_txt, prog=prog,
                 lines=lines,
                 note=('<p class="pos-note">{}</p>'.format(_esc(p["note"])) if p["note"] else ""))
    return '<section class="pos"><h2>Twoje pozycje</h2>{}</section>'.format(cards)


def _todo_box(analysis):
    items = []
    for p in analysis["positions"]:
        if p["today_action"]:
            items.append("<b>{}</b>: {}".format(_esc(p["id"]), _esc(p["today_action"])))
    theo = ""
    if not analysis["positions"] and config.THEORETICAL_MODE:
        # tryb teoretyczny: transze szablonow na dzis, na unit_amount pary
        for entry in analysis["pair_entries"]:
            cfg = entry["cfg"]
            for key in ("sell", "buy"):
                plan = entry["plans"][key]
                if not plan["schedule"] or plan["schedule"][0][0].isoformat() != analysis["today"]:
                    continue
                d, w, pct = plan["schedule"][0]
                src = cfg["base"] if plan["sell"] else cfg["quote"]
                tgt = cfg["quote"] if plan["sell"] else cfg["base"]
                unit = float(cfg["unit_amount"])
                theo += ("<li><b>{}→{}</b>: transza {}% = {} {} po ~{} "
                         "<span class='theo-u'>(na każde {} {})</span></li>").format(
                    src, tgt, pct, _money(unit * w), src, _fmt(entry["sig"]["current"]),
                    _money(unit), src)
    if items:
        body = "<ul>{}</ul>".format("".join("<li>{}</li>".format(t) for t in items))
    elif analysis["positions"]:
        body = "<p>Dziś żadna pozycja nie ma transzy. Następne transze widać w planach pozycji.</p>"
    elif theo:
        body = ("<p class='theo-h'>Tryb teoretyczny - brak pozycji, więc kwoty liczone "
                "na każde {} jednostek waluty źródłowej wg planów-szablonów z kart par:</p>"
                "<ul>{}</ul>").format(_money(10000), theo)
    else:
        body = ("<p>Brak pozycji i żaden szablon nie ma dziś transzy. Plany na kartach "
                "par to szablony „gdybyś dziś zaczynał okno {} dni”.</p>").format(
                    config.WINDOW_DAYS)
    cov = analysis.get("calendar_coverage_days", 0)
    warn = ""
    if cov < config.CALENDAR_MIN_COVERAGE_DAYS:
        warn = ('<p class="todo-warn">Kalendarz wydarzeń sięga tylko {} dni naprzód - '
                'uzupełnij data/events_*.yaml.</p>').format(cov)
    return ('<section class="todo"><h2>Dziś do zrobienia</h2>{}{}'
            '<p class="todo-note">Kwoty pochodzą z Twoich pozycji. Kurs orientacyjny '
            'z fixingu - sprawdź kwotowanie u dostawcy; wymieniaj w godzinach 9-16, '
            'nie w piątek po południu.</p></section>').format(body, warn)


# ===========================================================================
# WYDARZENIA / BACKTEST
# ===========================================================================

def _events_section(events):
    if not events:
        return ('<section class="events"><h2>Wydarzenia w oknie ({d} dni)</h2>'
                '<p class="ev-empty">Brak zaplanowanych publikacji i decyzji '
                'w najbliższych {d} dniach.</p></section>').format(d=config.WINDOW_DAYS)
    rows = ""
    for e in events:
        d = datetime.strptime(e["date"], "%Y-%m-%d").date()
        eff = datetime.strptime(e.get("effective_date", e["date"]), "%Y-%m-%d").date()
        imp = ("<span class='imp imp-high'>wysoki</span>" if e["impact"] == "high"
               else "<span class='imp imp-med'>średni</span>")
        eff_txt = planner.fmt_date(eff) if eff != d else "ten sam dzień"
        da = e["days_ahead"]
        when = ("dziś" if da == 0 else
                ("za {} dni".format(da) if da > 0 else "{} dni temu".format(-da)))
        rows += (
            '<tr><td class="ev-d">{dt}<span>{when}</span></td>'
            '<td><span class="ev-bank {cls}">{src}</span></td>'
            '<td>{name}</td><td>{ccy}</td><td>{imp}</td><td class="ev-eff">{eff}</td></tr>'
        ).format(dt=planner.fmt_date(d), when=when,
                 cls=SRC_CLS.get(e["source"], "ev-EUR"), src=_esc(e["source"]),
                 name=_esc(e["name"]), ccy="/".join(e["currencies"]), imp=imp, eff=eff_txt)
    return (
        '<section class="events"><h2>Wydarzenia w oknie ({d} dni)</h2>'
        '<p class="ev-note-s">Dzień reakcji = sesja, w której kurs odpowiada na '
        'publikację dla kogoś wymieniającego w godzinach pracy. FOMC (20:00 PL) i dane '
        'z USA (14:30 PL) wypadają po fixingu - reakcja jest następnego dnia. Transze '
        'DCA omijają dni reakcji dla wydarzeń o wysokim wpływie.</p>'
        '<table class="ev-table"><thead><tr><th>publikacja</th><th></th><th>wydarzenie</th>'
        '<th>waluty</th><th>wpływ</th><th>dzień reakcji</th></tr></thead>'
        '<tbody>{rows}</tbody></table></section>'
    ).format(d=config.WINDOW_DAYS, rows=rows)


def _backtest_section(bt):
    if not bt or not bt.get("pairs"):
        return ('<section class="bt"><h2>Skuteczność historyczna</h2>'
                '<p>Backtest niedostępny (za mało historii).</p></section>')
    rows = ""
    period = None
    for pcfg in config.PAIRS:
        pair = pcfg["pair"]
        pdata = bt["pairs"].get(pair) or {}
        period = period or pdata.get("period")
        for key, sell in (("sell", True), ("buy", False)):
            rec = pdata.get(key)
            if not rec or not rec.get("engine"):
                continue
            eng = rec["engine"]
            base, quote = pcfg["base"], pcfg["quote"]
            lbl = "{}→{}".format(base, quote) if sell else "{}→{}".format(quote, base)
            recent = rec.get("recent")
            rec_txt = ("{:+.1f}".format(recent["edge_bps_vs_dca"]) if recent else "-")
            verdict = ("<span class='bt-pos'>przewaga potwierdzona</span>"
                       if eng["verdict"] == "edge"
                       else "<span class='bt-neg'>brak przewagi - DCA</span>")
            rows += (
                '<tr><td class="bt-dir">{lbl}</td>'
                '<td class="num">{edge:+.1f} pb</td>'
                '<td class="num">[{lo:+.1f}; {hi:+.1f}]</td>'
                '<td class="num">{hit:.0f}%</td>'
                '<td class="num">{n}</td>'
                '<td class="num">{rec}</td>'
                '<td class="num">{ceil:.0f} pb</td>'
                '<td class="num">{sdl:.0f} / {sdd:.0f}</td>'
                '<td>{v}</td></tr>'
            ).format(lbl=lbl, edge=eng["edge_bps_vs_dca"], lo=eng["ci90_lo"],
                     hi=eng["ci90_hi"], hit=eng["hit_rate_pct"], n=eng["n_windows"],
                     rec=rec_txt, ceil=rec.get("ceiling_bps") or 0.0,
                     sdl=rec.get("sd_lump_bps") or 0.0, sdd=rec.get("sd_dca_bps") or 0.0,
                     v=verdict)
    per = "{} - {}".format(period[0], period[1]) if period and period[0] else "-"
    return (
        '<section class="bt"><h2>Skuteczność historyczna (backtest)</h2>'
        '<p class="bt-note">Pełna historia fixingów EBC ({per}), okna {d}-dniowe '
        '<b>rozłączne</b>. „Silnik” = dawny aktywny plan sterowany score (v2); '
        'przewaga vs równe DCA w pb z 90% przedziałem ufności. „Ostatnie 2 lata” = '
        'okres, na którym silnik był strojony. „Sufit” = najlepszy dzień okna przy '
        'pełnej wiedzy o przyszłości. „Rozrzut” = odchylenie wyniku wszystko-ostatniego-'
        'dnia / DCA względem 1. dnia - po to jest DCA: ten sam oczekiwany kurs, '
        'mniejsze ryzyko. Przewaga jest uznana tylko, gdy dolna granica CI &gt; 0.</p>'
        '<div class="tbl-wrap"><table class="bt-table"><thead><tr><th>Kierunek</th>'
        '<th>silnik vs DCA</th><th>90% CI</th><th>hit</th><th>okien</th>'
        '<th>ost. 2 lata</th><th>sufit</th><th>rozrzut lump/DCA</th><th>wniosek</th>'
        '</tr></thead><tbody>{rows}</tbody></table></div>'
        '<p class="bt-meta">stan: {as_of} · silnik v{ver}</p></section>'
    ).format(per=_esc(per), d=config.WINDOW_DAYS, rows=rows,
             as_of=_esc(bt.get("as_of", "-")), ver=_esc(bt.get("engine_version", "-")))


def _rates_line(analysis):
    pr = analysis.get("policy_rates") or {}
    rates = pr.get("rates") or config.POLICY_RATES
    srcs = pr.get("sources") or {}
    parts = ["{} {:.2f}% ({})".format(c, rates.get(c, 0.0), _esc(srcs.get(c, "config")))
             for c in ("PLN", "EUR", "USD")]
    return "Stopy do carry: " + " · ".join(parts)


def build_html(analysis):
    today = datetime.strptime(analysis["today"], "%Y-%m-%d").date()
    bt = analysis["backtest"] or {}
    cards = "".join(_pair_card(e, today, (bt.get("pairs") or {}).get(e["cfg"]["pair"]))
                    for e in analysis["pair_entries"])
    banners = ""
    if analysis["demo"]:
        banners += ('<div class="demo-banner">TRYB DEMO - dane syntetyczne. '
                    'Uruchom bez flagi --demo, by pobrać realne kursy EBC.</div>')
    stale_days = int(analysis.get("stale_days") or 0)
    if stale_days:
        banners += ('<div class="demo-banner">UWAGA: źródła kursów były '
                    'niedostępne - raport policzony na danych z {d} '
                    '({n} dni wstecz).</div>').format(
                        d=_esc(analysis["data_date"]), n=stale_days)
    return TEMPLATE.format(
        generated=_esc(analysis["generated_at"]),
        data_date=_esc(analysis["data_date"]),
        window=config.WINDOW_DAYS,
        sell_c=CHART_SELL,
        buy_c=CHART_BUY,
        demo_banner=banners,
        positions=_positions_section(analysis["positions"]),
        todo=_todo_box(analysis),
        cards=cards,
        events=_events_section(analysis["events"]),
        backtest=_backtest_section(bt),
        rates_line=_rates_line(analysis),
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
  code {{ font-size:11.5px; background:#eef2f5; padding:1px 5px; border-radius:4px; }}

  .pos {{ margin:20px 0 0; background:var(--surface); border:1px solid var(--line);
    border-radius:12px; padding:18px 20px 12px; }}
  .pos-empty {{ font-size:13px; color:var(--muted); margin:0 0 6px; }}
  .pos-card {{ border-top:1px solid var(--line); padding:12px 0 8px; }}
  .pos-card:first-of-type {{ border-top:none; padding-top:0; }}
  .pos-h {{ font-size:13.5px; font-variant-numeric:tabular-nums; }}
  .st {{ font-size:10.5px; font-weight:650; padding:2px 8px; border-radius:12px; margin-left:6px; }}
  .st-open {{ background:#e7f3ed; color:#1f7a5c; }}
  .st-done {{ background:#eef2f5; color:#5f7180; }}
  .st-over {{ background:#f8eae8; color:#b3382f; }}
  .bar {{ height:6px; background:#eef2f5; border-radius:4px; margin:8px 0; }}
  .bar-fill {{ height:100%; background:#1f7a5c; border-radius:4px; }}
  .pos-note {{ font-size:12px; color:var(--muted); margin:4px 0 0; }}

  .todo {{ margin:18px 0 22px; background:#10222b; color:#e8f1f4; border-radius:12px;
    padding:16px 20px 12px; }}
  .todo h2 {{ color:#7fd0de; }}
  .todo ul {{ margin:0; padding-left:20px; }}
  .todo li {{ margin-bottom:6px; font-size:14.5px; }}
  .todo li b {{ color:#7fd0de; font-variant-numeric:tabular-nums; }}
  .todo p {{ margin:0; font-size:13.5px; color:#b9cdd4; }}
  .todo-note {{ margin-top:10px !important; font-size:11px !important; color:#7d97a1 !important; }}
  .todo-warn {{ margin-top:8px !important; font-size:12px !important; color:#f2c37b !important; }}
  .theo-h {{ margin-bottom:8px !important; font-size:12.5px !important; }}
  .theo-u {{ font-size:11px; color:#7d97a1; }}

  .card {{ background:var(--surface); border:1px solid var(--line); border-radius:12px;
    padding:18px 20px 16px; margin-bottom:18px; }}
  .card-h {{ display:flex; justify-content:space-between; align-items:baseline; gap:10px; }}
  .pair-name {{ font-size:20px; font-weight:700; letter-spacing:-0.01em; }}
  .pair-rate {{ display:flex; align-items:baseline; gap:10px; }}
  .rate-v {{ font-size:22px; font-weight:650; font-variant-numeric:tabular-nums; }}
  .rate-ch {{ font-size:13px; font-weight:600; font-variant-numeric:tabular-nums; }}
  .rate-up {{ color:#1f7a5c; }} .rate-down {{ color:#b3382f; }} .rate-flat {{ color:var(--faint); }}
  .fix-line {{ font-size:12px; color:var(--muted); margin-top:4px; font-variant-numeric:tabular-nums; }}
  .fix-line b {{ color:var(--ink); font-weight:600; }}
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
  .sw-ev {{ background:#b3382f; opacity:0.6; }}
  .range-line {{ font-size:12.5px; color:var(--muted); padding:8px 0 8px; }}
  .range-line b {{ color:var(--ink); font-variant-numeric:tabular-nums; }}
  .prov-line {{ font-size:12.5px; color:#2c3a47; background:#f4f7f9; padding:8px 11px;
    border-radius:8px; margin-bottom:12px; }}
  .prov-line b {{ font-weight:650; }}

  .verdicts {{ display:grid; grid-template-columns:1fr 1fr; gap:0 22px; margin-top:6px;
    border-top:1px solid var(--line); padding-top:14px; }}
  .vcol {{ min-width:0; }}
  .vcol + .vcol {{ border-left:1px solid var(--line); padding-left:22px; }}
  .vdir {{ font-size:13.5px; font-weight:700; margin-bottom:8px; }}
  .vchip {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap;
    padding:7px 11px; border-radius:8px; margin-bottom:9px; background:#e7f3ed; color:#1f7a5c; }}
  .vchip b {{ font-size:14px; }}
  .vchip span {{ font-size:11px; opacity:0.85; }}
  .plan {{ margin:0; padding-left:18px; }}
  .plan li {{ font-size:12.5px; margin-bottom:5px; color:#2c3a47;
    font-variant-numeric:tabular-nums; }}
  .ctx-h {{ font-size:10.5px; text-transform:uppercase; letter-spacing:0.06em;
    color:var(--faint); margin:10px 0 4px; font-weight:650; }}
  .ctx {{ margin:0; padding-left:18px; }}
  .ctx li {{ font-size:11.5px; color:var(--muted); margin-bottom:3px; }}

  .events, .bt {{ margin-top:26px; background:var(--surface); border:1px solid var(--line);
    border-radius:12px; padding:18px 20px; }}
  .ev-note-s, .bt-note {{ font-size:12.5px; color:var(--muted); margin:0 0 12px; }}
  .ev-empty {{ font-size:13px; color:var(--muted); margin:0; }}
  .tbl-wrap {{ overflow-x:auto; }}
  .ev-table, .bt-table {{ width:100%; border-collapse:collapse; }}
  .ev-table td, .bt-table td, .bt-table th, .ev-table th {{ padding:8px 6px;
    border-top:1px solid var(--line); font-size:12.5px; vertical-align:middle; }}
  .bt-table th, .ev-table th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:0.05em;
    color:var(--faint); text-align:left; border-top:none; }}
  .ev-d {{ font-variant-numeric:tabular-nums; font-weight:600; white-space:nowrap; }}
  .ev-d span {{ display:block; font-size:10.5px; color:var(--faint); font-weight:400; }}
  .ev-eff {{ font-variant-numeric:tabular-nums; white-space:nowrap; color:var(--muted); }}
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
  }}
</style>
</head>
<body>
<div class="wrap">

  <header class="top">
    <div>
      <h1>FX Advisor</h1>
      <div class="sub">Dyscyplina wymiany walut w oknie {window} dni: DCA, carry, kalendarz</div>
    </div>
    <div class="meta">
      wygenerowano: <b>{generated}</b><br>
      dane (fixing EBC): <b>{data_date}</b>
    </div>
  </header>

  {demo_banner}

  {positions}

  {todo}

  {cards}

  {events}

  {backtest}

  <section class="method">
    <p><b>Metodologia (v3).</b> Na horyzoncie 2 tygodni kurs zachowuje sie jak
    bladzenie losowe: oczekiwany kurs jest taki sam kazdego dnia okna, roznia sie
    tylko ryzyko i koszty. Dlatego plan to DCA (rowne transze rozlozone po oknie,
    z pominieciem dni reakcji na wydarzenia o wysokim wplywie), z przechylem pod
    carry: gdy waluta docelowa jest oprocentowana wyzej niz zrodlowa, wczesniejsze
    wykonanie ma dodatnia wartosc oczekiwana (roznica stop x dni/365) - transze
    sa front-loaded; przy ujemnym carry back-loaded. {rates_line}.
    Kontekst rynkowy (percentyl 250 sesji, tendencja) jest pokazywany, ale nie
    steruje transzami - backtest na pelnej historii EBC (okna rozlaczne, 90% CI)
    nie wykazal przewagi aktywnego planu. 80% przedzial: kurs +/- 1.28 x sigma
    dzienna x sqrt(10). Dane: fixing EBC 14:15 CET (API SDMX EBC, zapasowo
    Frankfurter i feed XML EBC); fixing NBP tabela A do ksiegowania; USD/PLN
    krzyzowo z EBC.</p>
    <p><b>Zastrzezenie.</b> Narzedzie porzadkuje fakty, wymusza dyscypline transz
    i uczciwie raportuje wlasna skutecznosc - nie jest prognoza ani porada
    inwestycyjna. Kurs z fixingu jest orientacyjny; realny koszt to spread
    dostawcy. Decyzje podejmujesz samodzielnie.</p>
  </section>

</div>
</body>
</html>"""
