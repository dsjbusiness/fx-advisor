# FX Advisor

Narzędzie do **timingu wymiany walut w kroczącym oknie 14 dni** (treasury
firmowe, nie spekulacja) dla trzech par: **EUR/PLN, USD/PLN, EUR/USD** -
każda para pokazana raz, z dwoma lustrzanymi kierunkami.

Statyczny panel HTML generowany codziennie przez GitHub Actions i publikowany
na GitHub Pages. Zero backendu, zero build stepu, zero zewnętrznych bibliotek
(sama biblioteka standardowa Pythona), wykresy jako inline SVG.

- Dane: kursy referencyjne EBC z **Frankfurter API** (EUR/PLN, EUR/USD;
  USD/PLN liczony krzyżowo), ~420 sesji w cache `data/history.json`,
  aktualizacja przyrostowa (dociągane tylko brakujące daty).
- Alerty e-mail przez **Resend** (opcjonalnie).

## Co dostajesz

1. **"Dziś do zrobienia"** - zagregowana lista konkretnych działań na dziś
   ze wszystkich par ("EUR→PLN: wymień 70% po ~4.2958, przed NBP 08.07").
2. **Trzy karty par** - kurs + zmiana dzienna, sparkline ~250 sesji z pasmem
   10-90 percentyla i punktem "dziś", 80% przedział na koniec okna wraz z
   przeliczeniem na pieniądze ("max zysk z timingu: ok. X PLN na 10 000 EUR"),
   oraz **dwa lustrzane werdykty** (po jednym na kierunek): score, etykieta
   Korzystnie/Neutralnie/Niekorzystnie + pewność i **konkretny plan transz**
   (procenty, poziomy kursu, daty).
3. **Tabela wydarzeń** na 14 dni (RPP, EBC, FOMC, US CPI, NFP, polskie CPI).
4. **"Skuteczność historyczna"** - backtest walk-forward, który musi
   udowodnić przewagę silnika; gdy przewaga vs DCA jest <= 0, strona wprost
   zaleca DCA dla tego kierunku.

## Metodologia (skrót)

Score S w [-100, +100] liczony **raz na parę** z perspektywy sprzedaży waluty
bazowej; kierunek kupna = dokładnie -S.

- **Poziom (waga 0.55)**: mieszany percentyl dzisiejszego kursu
  0.2 x 30 sesji + 0.3 x 90 + 0.5 x 250, mapowany na [-100, +100].
- **Tendencja (0.25)**: zwrot z 10 sesji normalizowany zmiennością
  20-sesyjną (miara t-podobna), gładko obcinany tanh.
- **Pilność mean-reversion (0.20)**: %B Bollingera (20, 2) i RSI(14).
  Skrajne wykupienie przy korzystnym poziomie = "bierz zysk TERAZ, nie czekaj
  na więcej" - podnosi pilność werdyktu, nie pewność kontynuacji.
  Symetrycznie dla wyprzedania.
- **Reżim zmienności**: 20-sesyjna zmienność zannualizowana vs własny rozkład
  roczny (niska/normalna/wysoka). Wysoka obniża pewność i poszerza transze.
- **80% przedział**: kurs +/- 1.28 x sigma dzienna x sqrt(10 sesji);
  połowa szerokości przeliczana na PLN/USD na 10 000 jednostek bazy -
  to trzyma oczekiwania w ryzach.
- Pewność (Wysoka/Średnia/Niska) ze zgodności sygnałów i reżimu zmienności.

### Plany transz (warstwa decyzyjna)

| Score S | Plan |
|---|---|
| >= 60 | 70% dziś; 25% zlecenie/alert na 90. percentylu korzystności; reszta do ostatniego bezpiecznego dnia |
| 20..60 | 45% dziś; 30% + 25% na poziomach 70. i 85. percentyla |
| -20..20 | uczciwe DCA: 3-4 równe transze w konkretnych dniach, z pominięciem dni wydarzeń high-impact |
| -60..-20 | tylko operacyjne minimum; alerty na 50. i 70. percentylu |
| <= -60 | czekaj; alerty jak wyżej |

Poziomy zleceń są zawsze **lepsze niż dzisiejszy kurs** - gdy kurs jest już
powyżej percentyla, poziom podnoszony jest o część oczekiwanego zakresu.

**Twarda zasada deadline (zawsze aktywna):** całość musi być wymieniona do
końca okna 14 dni. Plan nazywa ostatni dzień wykonania i nie może on wypadać
w dniu wydarzenia high-impact dla pary (wtedy sesja wcześniej). Im mniej dni
zostało, tym plany zbiegają do wykonania niezależnie od score (ostatnie
3 sesje domykają liniowo).

**Wydarzenia:** jeśli w oknie wypada wydarzenie high-impact dla pary, każdy
plan mówi wprost, czy wykonać przed nim - asymetria: przy korzystnym poziomie
zabezpieczenie zysku przed ryzykiem zdarzenia jest preferowane.

### Backtest (narzędzie musi się udowodnić)

Walk-forward po całej cache'owanej historii: dla każdego możliwego okna
14-dniowego symulowane są plany transz silnika dzień po dniu (sygnały
przeliczane codziennie wyłącznie z danych dostępnych danego dnia, zlecenia
z limitem wypełniane po poziomie - konserwatywnie, z twardą zasadą deadline).
Benchmarki: wszystko 1. dnia / wszystko ostatniego dnia / równe DCA.
Raport per para i kierunek: średnia przewaga vs DCA w punktach bazowych,
hit-rate, liczba okien. Wyniki w `data/backtest.json`; pełny przelicz
najwyżej raz na tydzień (cache), dzienny bieg zostaje szybki.

**Gdy przewaga vs DCA <= 0, panel wprost zaleca DCA dla tego kierunku** -
plan zamieniany jest na harmonogram DCA z adnotacją w werdykcie.

## Uruchomienie lokalnie

Wymaga tylko Pythona 3.9+.

```bash
python main.py                    # realne dane EBC -> fx_report.html
python main.py --demo             # dane syntetyczne (offline), podgląd
python main.py --no-email         # bez wysyłki maila
python main.py --force-backtest   # wymuś pełny przelicz backtestu
python main.py --out docs/index.html
python -m unittest discover -s tests   # testy jednostkowe
```

## Struktura

```
fx-advisor/
├── config.py           # wszystkie pokrętła (okna, wagi, progi, alerty)
├── data_layer.py       # historia (cache przyrostowy) + parser kalendarza
├── indicators.py       # czysta matematyka wskaźników (testowana)
├── signals.py          # silnik sygnałów - raz na parę
├── planner.py          # plany transz + symulator okna (wspólny z backtestem)
├── backtest.py         # walk-forward backtest z cache
├── report.py           # generator HTML (inline SVG, bez zależności)
├── notify.py           # alerty Resend + zapis stanu
├── main.py             # punkt wejścia / CLI
├── data/
│   ├── history.json    # ~420 sesji kursów (commitowane przez CI)
│   ├── backtest.json   # wyniki backtestu (cache, commitowane przez CI)
│   └── events_2026.yaml  # kalendarz wydarzeń makro
├── tests/              # testy wskaźników i logiki deadline
└── .github/workflows/fx-advisor.yml
```

## Kalendarz wydarzeń (jak edytować)

`data/events_2026.yaml` - decyzje RPP/EBC/FOMC, US CPI, polskie CPI
(flash GUS + finalny), NFP. Format wpisu:

```yaml
  - date: 2026-07-08
    source: NBP
    name: Decyzja RPP ws. stop procentowych
    currencies: [PLN]
    impact: high
```

- `currencies` - waluty, na które wydarzenie wpływa (PLN/EUR/USD);
  para jest dotknięta, gdy którakolwiek z jej walut jest na liście.
- `impact: high` - dzień omijany przez transze DCA i termin końcowy planu;
  `medium` - tylko informacyjnie w tabeli.
- **Rok 2027**: dodaj plik `data/events_2027.yaml` w tym samym formacie -
  narzędzie ładuje wszystkie pliki `data/events_*.yaml`.
- Daty RPP na II półrocze 2026 i daty US CPI zweryfikuj okresowo z
  oficjalnymi kalendarzami (nbp.pl, bls.gov) - w pliku są oznaczone
  komentarzem jako orientacyjne.

## GitHub Actions + Pages

Workflow `.github/workflows/fx-advisor.yml`: dni robocze ~08:30 i ~16:30
czasu PL (po publikacji fixingu EBC). Odpala testy, generuje raport do
`docs/index.html` i commituje raport + `data/history.json` +
`data/backtest.json` + pliki stanu. GitHub Pages: Settings → Pages →
źródło `/docs`.

### E-mail (Resend)

Sekrety w Settings → Secrets and variables → Actions: `RESEND_API_KEY`,
`FX_EMAIL_FROM`, `FX_EMAIL_TO`. Mail wychodzi, gdy:

1. score złożony któregoś kierunku przekroczy +/-60 (przejście przez próg),
2. kurs wejdzie w górny/dolny decyl zakresu 250 sesji,
3. jutro jest dzień wydarzenia high-impact dla pary z zaleconymi
   (niewykonanymi) transzami.

Temat maila zawiera konkretną linię działania. Limit raz dziennie,
chyba że pojawi się nowy powód.

## Zastrzeżenie

Kurs w horyzoncie 2 tygodni jest w dużej mierze nieprzewidywalny. Narzędzie
porządkuje fakty, wymusza dyscyplinę transz i uczciwie raportuje własną
skuteczność - nie jest prognozą ani poradą inwestycyjną. Decyzje podejmujesz
samodzielnie.
