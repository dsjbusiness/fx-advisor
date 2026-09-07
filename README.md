# FX Advisor

Narzędzie do **dyscypliny wymiany walut w oknie 14 dni** (treasury firmowe,
nie spekulacja) dla trzech par: **EUR/PLN, USD/PLN, EUR/USD**.

Statyczny panel HTML generowany w dni robocze przez GitHub Actions i publikowany
na GitHub Pages: https://dsjbusiness.github.io/fx-advisor/. Zero backendu, zero
build stepu, zero zewnętrznych bibliotek (sama biblioteka standardowa Pythona).

## Co zmieniło się w v3 (F101, wrzesień 2026)

Audyt na pełnej historii fixingów EBC (1999-2026, 27 lat, ~680 rozłącznych okien
na parę) pokazał, że aktywny plan transz sterowany score z v2 **przegrywa z DCA
o 5-10 pb na okno** w każdej parze, z 90% przedziałem ufności w całości poniżej
zera. Dodatnia "przewaga" +3 pb widoczna wcześniej na stronie pochodziła z 2 lat
danych, na których silnik był strojony, i z nakładających się okien.

Dlatego v3 nie przewiduje kursu. Robi cztery rzeczy, które mają pokrycie w danych
albo w arytmetyce:

1. **DCA** - równe transze rozłożone po oknie. Ten sam oczekiwany kurs co lump
   sum, o ~45% mniejszy rozrzut wyniku.
2. **Przechył pod carry** - gdy waluta docelowa jest oprocentowana wyżej niż
   źródłowa, wcześniejsze wykonanie ma dodatnią wartość oczekiwaną (różnica stóp
   × dni/365, dla EUR→PLN ok. +6 pb na 14 dni przy stopach z IX 2026). Transze
   są wtedy front-loaded
   (40/30/20/10), przy ujemnym carry back-loaded. Działa tylko, gdy gotówka leży
   na oprocentowanym rachunku.
3. **Omijanie dni reakcji** na wydarzenia o wysokim wpływie (RPP, EBC, FOMC,
   CPI, NFP). FOMC i dane z USA publikowane są po fixingu EBC, więc dniem reakcji
   jest następna sesja.
4. **Pozycje** - realne kwoty z deadline. Plan liczy się dla RESZTY kwoty
   i RESZTY dni, a nie od nowa co dzień.

Score z v2 (percentyl 250 sesji, tendencja) został jako **kontekst** na karcie
pary i nie steruje transzami.

## Co dostajesz

1. **Twoje pozycje** - każda z paskiem postępu, planem reszty (kwoty i daty),
   średnim kursem dotychczasowych transz, statusem (otwarta / po terminie /
   zamknięta).
2. **Dziś do zrobienia** - transze z pozycji na dziś, z kursem orientacyjnym.
3. **Trzy karty par** - fixing EBC i NBP, kurs do księgowania (NBP z poprzedniego
   dnia roboczego), wykres (2 miesiące historii, stożek 80% na 14 dni, dni reakcji,
   transze), linia **dostawca vs timing** ("zmiana dostawcy daje X zł na 10 000,
   timing w oknie maksymalnie Y zł, realnie ~0"), dwa kierunki z planem-szablonem
   DCA i kontekstem.
4. **Tabela wydarzeń** z datą publikacji i dniem reakcji.
5. **Backtest** na pełnej historii: okna rozłączne, 90% CI, hit-rate, sufit
   timingu przy pełnej wiedzy o przyszłości, rozrzut lump sum vs DCA.

## Pozycje

Kwota w walucie źródłowej, kierunek `sell` (sprzedaj bazę pary, np. EUR→PLN) lub
`buy` (kup bazę, np. PLN→EUR), deadline.

Z GitHuba: Actions → "FX Advisor" → Run workflow → `action: add` + para, kierunek,
kwota, deadline. Wykonane transze: `action: fill` + id pozycji, kwota, kurs.
Zamknięcie: `action: close`.

Lokalnie:

```bash
python main.py --add-position EURPLN sell 10000 2026-09-30 --note "faktura 123"
python main.py --record-fill P260907-1 4000 4.3148
python main.py --close-position P260907-1
python main.py --list-positions
```

Stan w `data/positions.json` (commitowany przez CI).

## Dane

| Źródło | Co | Uwagi |
|---|---|---|
| EBC SDMX (`data-api.ecb.europa.eu`) | fixing EUR/PLN, EUR/USD od 1999 | podstawa percentyli i backtestu; cache `data/history.json` (~7 000 sesji), przyrostowo |
| Frankfurter, feed XML EBC | te same kursy | źródła zapasowe |
| NBP API (tabela A) | fixing EUR, USD ~12:00 | drugi punkt dnia i kurs do księgowania; cache `data/nbp.json` |
| EBC SDMX (stopa depozytowa), FRED (fed funds) | stopy do carry | `data/rates.json`; PLN z `config.POLICY_RATES` (NBP nie ma API stóp - podbij po decyzji RPP) |
| `data/events_RRRR.yaml` | kalendarz | test CI wymaga pokrycia ≥ 30 dni naprzód dla każdej waluty |

Gdy źródła kursów milczą, a cache ma ≤ 5 dni, raport powstaje z cache z bannerem.

## Kalendarz wydarzeń

Format wpisu (parser: `data_layer.parse_events_yaml`, prosty podzbiór YAML):

```yaml
  - date: 2026-10-07        # dzień OGŁOSZENIA (posiedzenia: drugi dzień)
    source: NBP             # NBP | ECB | Fed | BLS | GUS
    name: Decyzja RPP ws. stop procentowych
    currencies: [PLN]
    impact: high            # high = omijany przez transze; medium = informacyjnie
```

- Dla `source: Fed` i `BLS` dzień reakcji to następna sesja (publikacja po
  fixingu EBC).
- Stan weryfikacji dat jest w komentarzach na górze każdego pliku. Na 2027
  zweryfikowane są EBC i FOMC; RPP i BLS orientacyjne - sprawdź po publikacji
  harmonogramów (XI-XII 2026).
- Test `tests/test_events.py` wywala CI, gdy kalendarz sięga mniej niż 30 dni
  naprzód dla którejś waluty.

## Dostawcy

`config.PROVIDERS` - spread w pb i opłata stała; `DEFAULT_PROVIDER` to Twój obecny
dostawca. Linia na karcie pary porównuje oszczędność ze zmiany dostawcy z sufitem
timingu z backtestu. Wpisz własne spready - domyślne są orientacyjne.

## Backtest

Walk-forward po pełnej historii: okna 10-sesyjne **rozłączne** (nakładające się
zawyżają istotność ~3×). Dla każdego kierunku symulowany jest dawny silnik score
(v2) i porównywany z równym DCA: średnia przewaga w pb, odchylenie, t, 90% CI,
hit-rate. Osobno "ostatnie 2 lata" (okres strojenia v2). Przewaga jest uznana
tylko, gdy dolna granica CI > 0. Wyniki w `data/backtest.json`, pełny przelicz
raz na tydzień (cache) - dzienny bieg trwa sekundy.

## Uruchomienie lokalnie

Python 3.9+, bez zależności.

```bash
python main.py                         # realne dane -> fx_report.html
python main.py --demo                  # dane syntetyczne, offline
python main.py --no-email
python main.py --force-backtest        # pełny przelicz (~2 min)
python main.py --out docs/index.html
python -m unittest discover -s tests   # 62 testy
```

## Struktura

```
fx-advisor/
├── config.py           # okna, stopy awaryjne, dostawcy, źródła, progi
├── data_layer.py       # historia EBC (SDMX/Frankfurter/XML), NBP, stopy, kalendarz, pozycje
├── indicators.py       # matematyka wskaźników
├── signals.py          # kontekst rynkowy (percentyle, tendencja, zmienność)
├── planner.py          # DCA + carry + dni reakcji + pozycje; legacy symulator do backtestu
├── backtest.py         # okna rozłączne, CI, sufit timingu
├── report.py           # HTML (inline SVG)
├── notify.py           # alerty Resend
├── main.py             # CLI + pozycje
├── data/
│   ├── history.json    # ~7 000 sesji EBC (CI)
│   ├── nbp.json        # fixing NBP, 120 dni (CI)
│   ├── rates.json      # stopy do carry (CI)
│   ├── positions.json  # pozycje (CI + ręcznie)
│   ├── backtest.json   # cache backtestu (CI)
│   └── events_2026.yaml, events_2027.yaml
├── tests/
└── .github/workflows/fx-advisor.yml
```

## GitHub Actions + Pages

Workflow w dni robocze (cron 06:30 i 14:30 UTC; GitHub opóźnia o 1-5 h) oraz
`workflow_dispatch` z komendami pozycji. Odpala testy, generuje raport do
`docs/index.html`, commituje raport i pliki `data/`. GitHub Pages: źródło `/docs`.

### E-mail (Resend)

Sekrety: `RESEND_API_KEY`, `FX_EMAIL_FROM`, `FX_EMAIL_TO`. Mail wychodzi, gdy:

1. pozycja ma dziś transzę (kwota, kurs orientacyjny),
2. pozycja jest po terminie albo deadline wypada jutro,
3. jutro jest dzień reakcji na wydarzenie dla pary z otwartą pozycją,
4. kurs wszedł w skrajny decyl roku (kontekst).

Temat zawiera konkretną linię działania. Raz dziennie, chyba że pojawi się nowy
powód.

## Zastrzeżenie

Na horyzoncie 2 tygodni kurs jest nieprzewidywalny - narzędzie tego nie udaje.
Porządkuje fakty, wymusza dyscyplinę transz, liczy carry i pokazuje, gdzie są
prawdziwe pieniądze (spread dostawcy). Kurs z fixingu jest orientacyjny. Nie jest
to porada inwestycyjna. Decyzje podejmujesz samodzielnie.
