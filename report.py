# -*- coding: utf-8 -*-
"""
Generator raportu HTML (samodzielny plik, bez zależności).
Panel decyzyjny: trzy kierunki wymiany + kontekst USD/PLN + wydarzenia w oknie.
"""

import html
import config


# kolory wg klasy oceny: (tekst, tło, pasek)
CLS_COLORS = {
    "pos":      ("#1f7a5c", "#e7f3ed", "#1f7a5c"),
    "mild-pos": ("#2f6f57", "#eef5f0", "#3f9170"),
    "neutral":  ("#8a6212", "#faf2df", "#c79324"),
    "mild-neg": ("#a4503a", "#f8ece6", "#c8603f"),
    "neg":      ("#b3382f", "#f8eae8", "#b3382f"),
}


def _fmt(v, dp=4):
    return ("{:,." + str(dp) + "f}").format(v).replace(",", "\u00a0")


def _sparkline(values, width=240, height=44, stroke="#0b6b7a"):
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    rng = (hi - lo) or 1e-9
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = i / (n - 1) * (width - 4) + 2
        y = height - 2 - (v - lo) / rng * (height - 4)
        pts.append("{:.1f},{:.1f}".format(x, y))
    poly = " ".join(pts)
    last_x, last_y = pts[-1].split(",")
    # delikatne wype\u0142nienie pod lini\u0105
    area = "2,{h} ".format(h=height - 2) + poly + " {x},{h}".format(x=last_x, h=height - 2)
    return (
        '<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
        'role="img" aria-label="wykres ostatnich kurs\u00f3w">'
        '<polygon points="{area}" fill="{stroke}" fill-opacity="0.07"/>'
        '<polyline points="{poly}" fill="none" stroke="{stroke}" stroke-width="1.6" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
        '<circle cx="{lx}" cy="{ly}" r="2.6" fill="{stroke}"/>'
        '</svg>'
    ).format(w=width, h=height, area=area, poly=poly, stroke=stroke, lx=last_x, ly=last_y)


def _score_bar(score):
    """Pasek -100..+100, \u015brodek = 0. Zielony w prawo (dla Ciebie), czerwony w lewo."""
    pct = max(-100.0, min(100.0, score))
    half = abs(pct) / 100.0 * 50.0  # % szeroko\u015bci od \u015brodka
    if pct >= 0:
        left, w, color = 50.0, half, "#1f7a5c"
    else:
        left, w, color = 50.0 - half, half, "#b3382f"
    return (
        '<div class="sbar" role="img" aria-label="ocena {v:.0f} na 100">'
        '<div class="sbar-fill" style="left:{l:.2f}%;width:{w:.2f}%;background:{c}"></div>'
        '<div class="sbar-zero"></div>'
        '</div>'
    ).format(v=pct, l=left, w=w, c=color)


def _range_bar(a, high_good):
    """Sygnaturowy pasek: gdzie dzi\u015b kurs w zakresie [min,max] z ~3 miesi\u0119cy."""
    lo, hi, mean, cur = a["low"], a["high"], a["mean"], a["current"]
    span = (hi - lo) or 1e-9
    cur_x = max(0.0, min(100.0, (cur - lo) / span * 100.0))
    mean_x = max(0.0, min(100.0, (mean - lo) / span * 100.0))
    # tint po "dobrej" stronie dla danego kierunku
    if high_good:
        grad = "linear-gradient(90deg, rgba(179,56,47,0.10), rgba(31,122,92,0.16))"
        good_lbl_left, good_lbl_right = "taniej", "dro\u017cej"
    else:
        grad = "linear-gradient(90deg, rgba(31,122,92,0.16), rgba(179,56,47,0.10))"
        good_lbl_left, good_lbl_right = "lepiej dla Ciebie", "gorzej"
    return (
        '<div class="rb-wrap">'
        '<div class="rb-track" style="background:{grad}">'
        '<div class="rb-mean" style="left:{mx:.2f}%" title="\u015brednia"></div>'
        '<div class="rb-now" style="left:{cx:.2f}%"><span>dzi\u015b</span></div>'
        '</div>'
        '<div class="rb-ends"><span>{lo}</span><span class="rb-mid">{glr}</span><span>{hi}</span></div>'
        '</div>'
    ).format(grad=grad, mx=mean_x, cx=cur_x, lo=_fmt(lo), hi=_fmt(hi),
             glr="\u015brednia " + _fmt(mean))


def _card(res, primary=True):
    d = res["direction"]
    a = res["pair"]
    tcol, bg, bar = CLS_COLORS.get(res["label_cls"], CLS_COLORS["neutral"])

    pct = a["pct"]
    pct_txt = "wy\u017cszy ni\u017c {:.0f}% dni z ostatnich {} sesji".format(pct, a["n_level"])
    rsi_v = a["rsi"]
    rsi_state = "wykupienie" if rsi_v >= 70 else ("wyprzedanie" if rsi_v <= 30 else "neutralnie")
    trend_arrow = "\u2197" if a["trend_pair"] > 8 else ("\u2198" if a["trend_pair"] < -8 else "\u2192")
    trend_txt = "ro\u015bnie" if a["trend_pair"] > 8 else ("spada" if a["trend_pair"] < -8 else "stabilnie")
    vol_txt = "podwy\u017cszona" if a["vol_elevated"] else "normalna"

    notes_html = ""
    if res["notes"]:
        items = "".join("<li>{}</li>".format(html.escape(n)) for n in res["notes"])
        notes_html = '<ul class="notes">{}</ul>'.format(items)

    spark = _sparkline(a["spark"], stroke=bar)

    # Karta dwukierunkowa (kontekst USD/PLN) ma w etykiecie oba kierunki:
    # "USD -> PLN / PLN -> USD". Samo "Korzystny" jest wtedy mylace, bo werdykt
    # liczony jest dla kierunku high_good = pierwszego na liscie. Dopisz wiec do
    # werdyktu kierunek, ktorego dotyczy, zeby bylo jasne, w ktora strone jest
    # korzystnie (przy favorability < 0 korzystny jest kierunek przeciwny).
    verdict_text = res["label"]
    if " / " in d["label"] and res["label_cls"] != "neutral":
        parts = [p.strip() for p in d["label"].split(" / ")]
        if len(parts) == 2:
            scored_dir = parts[0]          # werdykt opisuje kierunek high_good
            verdict_text = "{}: {}".format(res["label"], scored_dir)

    return """
    <article class="card {cardcls}" style="--accent:{bar}">
      <header class="card-h">
        <div>
          <div class="dir">{label}</div>
          <div class="dir-sub">{desc}</div>
        </div>
        <div class="rate">
          <div class="rate-v">{rate}</div>
          <div class="rate-l">kurs ({pair})</div>
        </div>
      </header>

      <div class="verdict" style="color:{tcol};background:{bg}">
        <span class="verdict-l">{verdict}</span>
        <span class="verdict-c">pewno\u015b\u0107: {conf}</span>
      </div>

      <div class="score-row">
        <span class="score-end neg">niekorzystnie</span>
        {scorebar}
        <span class="score-end pos">korzystnie</span>
      </div>

      {rangebar}

      <div class="spark-wrap">{spark}</div>

      <div class="metrics">
        <div><span class="m-l">Po\u0142o\u017cenie</span><span class="m-v">{pct:.0f}\u00b7percentyl</span></div>
        <div><span class="m-l">Tendencja {arrow}</span><span class="m-v">{trend}</span></div>
        <div><span class="m-l">RSI</span><span class="m-v">{rsi:.0f} \u00b7 {rsistate}</span></div>
        <div><span class="m-l">Zmienno\u015b\u0107</span><span class="m-v">{vol}</span></div>
      </div>

      <div class="reco">
        <div class="reco-a">{action}</div>
        <p class="reco-w">{why}</p>
        {notes}
      </div>
    </article>
    """.format(
        cardcls="card-primary" if primary else "card-context",
        bar=bar, label=html.escape(d["label"]), desc=html.escape(d["desc"]),
        rate=_fmt(a["current"]), pair=d["pair"],
        verdict=html.escape(verdict_text), conf=html.escape(res["confidence_bucket"]),
        tcol=tcol, bg=bg,
        scorebar=_score_bar(res["favorability"]),
        rangebar=_range_bar(a, d["high_good"]),
        spark=spark,
        pct=pct, pct_txt=pct_txt, arrow=trend_arrow, trend=trend_txt,
        rsi=rsi_v, rsistate=rsi_state, vol=vol_txt,
        action=html.escape(res["action"]), why=html.escape(res["why"]),
        notes=notes_html,
    )


def _events_section(events):
    if not events:
        return ('<section class="events events-none">'
                '<h2>Wydarzenia w oknie ({d} dni)</h2>'
                '<p>Brak zaplanowanych decyzji banków centralnych w najbli\u017cszych {d} dniach. '
                'To sprzyja spokojniejszemu kursowi.</p></section>').format(d=config.WINDOW_DAYS)
    rows = ""
    for e in events:
        rows += (
            '<tr><td class="ev-d">{date}<span>za {days} dni</span></td>'
            '<td><span class="ev-bank ev-{ccy}">{bank}</span></td>'
            '<td>{desc}</td>'
            '<td class="ev-ccy">{ccy}</td></tr>'
        ).format(date=e["date"], days=e["days_ahead"], bank=html.escape(e["bank"]),
                 desc=html.escape(e["desc"]), ccy=e["currency"])
    return (
        '<section class="events">'
        '<h2>Wydarzenia w oknie ({d} dni)</h2>'
        '<p class="events-note">Decyzje w tym okresie mog\u0105 gwa\u0142townie ruszy\u0107 kursem. '
        'Przy wymianie w tych dniach rozwa\u017c podzia\u0142 lub wymian\u0119 przed posiedzeniem.</p>'
        '<table class="ev-table"><tbody>{rows}</tbody></table>'
        '</section>'
    ).format(d=config.WINDOW_DAYS, rows=rows)


def build_html(analysis):
    primary_cards = "".join(_card(r, primary=True)
                            for r in analysis["results"] if r["direction"]["primary"])
    context_cards = "".join(_card(r, primary=False)
                            for r in analysis["results"] if not r["direction"]["primary"])

    context_block = ""
    if context_cards:
        context_block = (
            '<h2 class="ctx-h">Kontekst dodatkowy</h2>'
            '<div class="grid grid-ctx">{}</div>'.format(context_cards))

    demo_banner = ""
    if analysis["demo"]:
        demo_banner = ('<div class="demo-banner">TRYB DEMO - dane syntetyczne. '
                       'Uruchom bez flagi --demo, by pobra\u0107 realne kursy EBC.</div>')

    return TEMPLATE.format(
        generated=analysis["generated_at"],
        data_date=analysis["data_date"],
        window=config.WINDOW_DAYS,
        demo_banner=demo_banner,
        primary_cards=primary_cards,
        context_block=context_block,
        events=_events_section(analysis["events"]),
        level_window=config.LEVEL_WINDOW,
        trend_window=config.TREND_WINDOW,
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="apple-touch-icon" href="favicon.svg">
<title>FX Advisor - przegl\u0105d wymiany walut</title>
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
  .wrap {{ max-width:1080px; margin:0 auto; padding:28px 20px 56px; }}
  .mono {{ font-variant-numeric:tabular-nums; font-feature-settings:"tnum"; }}

  header.top {{ display:flex; justify-content:space-between; align-items:flex-end;
    flex-wrap:wrap; gap:12px; border-bottom:2px solid var(--ink); padding-bottom:16px; }}
  .top h1 {{ font-size:clamp(20px,3vw,26px); margin:0; letter-spacing:-0.02em; }}
  .top .sub {{ color:var(--muted); font-size:13px; margin-top:4px; }}
  .top .meta {{ text-align:right; font-size:12px; color:var(--muted);
    font-variant-numeric:tabular-nums; }}
  .top .meta b {{ color:var(--ink); font-weight:600; }}

  .caveat {{ margin:18px 0 6px; padding:12px 14px; border-left:3px solid var(--accent);
    background:#e9f1f3; color:#143b42; font-size:13px; border-radius:0 6px 6px 0; }}
  .caveat b {{ color:#0b6b7a; }}
  .demo-banner {{ margin:14px 0; padding:8px 12px; background:#fbf2df; color:#8a6212;
    font-size:12px; border-radius:6px; letter-spacing:0.02em; }}

  h2 {{ font-size:14px; text-transform:uppercase; letter-spacing:0.08em;
    color:var(--muted); margin:34px 0 14px; font-weight:600; }}
  .ctx-h {{ margin-top:30px; }}

  .grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); }}
  .grid-ctx {{ grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); }}

  .card {{ background:var(--surface); border:1px solid var(--line); border-radius:12px;
    padding:18px 18px 16px; display:flex; flex-direction:column; }}
  .card-context {{ background:#f7f9fb; }}
  .card-h {{ display:flex; justify-content:space-between; align-items:flex-start; gap:10px; }}
  .dir {{ font-size:18px; font-weight:650; letter-spacing:-0.01em; }}
  .dir-sub {{ font-size:12px; color:var(--faint); margin-top:2px; }}
  .rate {{ text-align:right; }}
  .rate-v {{ font-size:18px; font-weight:600; font-variant-numeric:tabular-nums;
    color:var(--ink); }}
  .rate-l {{ font-size:11px; color:var(--faint); }}

  .verdict {{ display:flex; justify-content:space-between; align-items:center;
    margin:14px 0 12px; padding:9px 12px; border-radius:8px; font-weight:650; }}
  .verdict-l {{ font-size:15px; }}
  .verdict-c {{ font-size:11px; font-weight:500; opacity:0.85; text-transform:lowercase; }}

  .score-row {{ display:flex; align-items:center; gap:8px; margin-bottom:14px; }}
  .score-end {{ font-size:9.5px; text-transform:uppercase; letter-spacing:0.04em;
    color:var(--faint); white-space:nowrap; }}
  .sbar {{ position:relative; flex:1; height:8px; background:#eef2f5; border-radius:5px; }}
  .sbar-fill {{ position:absolute; top:0; height:100%; border-radius:5px;
    transition:width .5s ease, left .5s ease; }}
  .sbar-zero {{ position:absolute; left:50%; top:-3px; width:1.5px; height:14px;
    background:var(--faint); transform:translateX(-50%); }}

  .rb-wrap {{ margin:10px 0 14px; }}
  .rb-track {{ position:relative; height:10px; border-radius:5px; border:1px solid var(--line); }}
  .rb-mean {{ position:absolute; top:-3px; width:1.5px; height:16px; background:var(--faint); }}
  .rb-now {{ position:absolute; top:50%; transform:translate(-50%,-50%); width:11px; height:11px;
    background:var(--ink); border:2px solid #fff; border-radius:50%;
    box-shadow:0 0 0 1px var(--ink); }}
  .rb-now span {{ position:absolute; top:-19px; left:50%; transform:translateX(-50%);
    font-size:10px; color:var(--ink); font-weight:600; white-space:nowrap; }}
  .rb-ends {{ display:flex; justify-content:space-between; margin-top:7px;
    font-size:10.5px; color:var(--faint); font-variant-numeric:tabular-nums; }}
  .rb-mid {{ color:var(--muted); }}

  .spark-wrap {{ margin:2px 0 14px; }}
  .spark {{ width:100%; height:44px; display:block; }}

  .metrics {{ display:grid; grid-template-columns:1fr 1fr; gap:8px 14px;
    padding:12px 0; border-top:1px solid var(--line); border-bottom:1px solid var(--line); }}
  .metrics > div {{ display:flex; justify-content:space-between; font-size:12px; }}
  .m-l {{ color:var(--muted); }}
  .m-v {{ font-weight:600; font-variant-numeric:tabular-nums; }}

  .reco {{ margin-top:13px; }}
  .reco-a {{ font-weight:650; font-size:13.5px; color:var(--accent); }}
  .reco-w {{ font-size:12.5px; color:#3a4956; margin:5px 0 0; }}
  .notes {{ margin:9px 0 0; padding-left:16px; }}
  .notes li {{ font-size:11.5px; color:var(--muted); margin-bottom:4px; }}

  .events {{ margin-top:38px; background:var(--surface); border:1px solid var(--line);
    border-radius:12px; padding:18px 20px; }}
  .events h2 {{ margin:0 0 4px; }}
  .events-note {{ font-size:12.5px; color:var(--muted); margin:0 0 12px; }}
  .events-none p {{ font-size:13px; color:var(--muted); margin:0; }}
  .ev-table {{ width:100%; border-collapse:collapse; }}
  .ev-table td {{ padding:9px 6px; border-top:1px solid var(--line); font-size:13px;
    vertical-align:middle; }}
  .ev-d {{ font-variant-numeric:tabular-nums; font-weight:600; white-space:nowrap; }}
  .ev-d span {{ display:block; font-size:10.5px; color:var(--faint); font-weight:400; }}
  .ev-bank {{ display:inline-block; padding:2px 9px; border-radius:20px; font-size:11px;
    font-weight:600; }}
  .ev-EUR {{ background:#e9f1f3; color:#0b6b7a; }}
  .ev-USD {{ background:#edeff5; color:#3d5a99; }}
  .ev-PLN {{ background:#f8eae8; color:#b3382f; }}
  .ev-ccy {{ text-align:right; color:var(--faint); font-size:11px; font-weight:600; }}

  footer {{ margin-top:34px; padding-top:18px; border-top:1px solid var(--line);
    font-size:11.5px; color:var(--faint); }}
  footer p {{ margin:0 0 8px; }}
  footer b {{ color:var(--muted); }}

  @media (max-width:560px) {{
    .verdict {{ flex-direction:column; align-items:flex-start; gap:3px; }}
    .top .meta {{ text-align:left; }}
  }}
  @media (prefers-reduced-motion:reduce) {{
    .sbar-fill {{ transition:none; }}
  }}
</style>
</head>
<body>
<div class="wrap">

  <header class="top">
    <div>
      <h1>FX Advisor</h1>
      <div class="sub">Wsparcie decyzji o wymianie walut \u00b7 okno {window} dni</div>
    </div>
    <div class="meta">
      wygenerowano: <b>{generated}</b><br>
      dane (fixing EBC): <b>{data_date}</b>
    </div>
  </header>

  {demo_banner}

  <div class="caveat">
    <b>Jak to czyta\u0107.</b> To nie jest prognoza kursu ani porada inwestycyjna.
    Narz\u0119dzie pokazuje, czy <b>dzi\u015b</b> dostajesz kurs korzystny na tle ostatnich
    tygodni, w kt\u00f3r\u0105 stron\u0119 idzie kr\u00f3tka tendencja i czy w Twoim oknie wypada
    decyzja banku centralnego. Przy cyklicznych wymianach najlepszy efekt daje zwykle
    <b>podzia\u0142 kwoty na transze</b>, a nie polowanie na jeden idealny dzie\u0144.
  </div>

  <h2>Twoje kierunki wymiany</h2>
  <div class="grid">{primary_cards}</div>

  {context_block}

  {events}

  <footer>
    <p><b>Metodologia.</b> Po\u0142o\u017cenie (waga 70%) = percentyl bie\u017c\u0105cego kursu w oknie
    {level_window} sesji. Tendencja (waga 30%) = znormalizowany ruch z {trend_window} sesji.
    RSI, wst\u0119ga Bollingera i zmienno\u015b\u0107 s\u0142u\u017c\u0105 jako potwierdzenie i modyfikator pewno\u015bci.
    EUR/PLN i EUR/USD to kursy referencyjne EBC (\u017ar\u00f3d\u0142o: Frankfurter API); USD/PLN wyliczany
    krzy\u017cowo. EUR\u2192PLN i PLN\u2192EUR opisuj\u0105 ten sam kurs z dw\u00f3ch stron, wi\u0119c ich oceny s\u0105
    zwykle przeciwne - to poprawne zachowanie, nie sprzeczno\u015b\u0107.</p>
    <p><b>Zastrze\u017cenie.</b> Kurs w horyzoncie 2 tygodni jest w du\u017cej mierze nieprzewidywalny.
    Decyzj\u0119 podejmujesz samodzielnie. Nie jestem doradc\u0105 finansowym.</p>
  </footer>

</div>
</body>
</html>"""
