# FX Advisor

Narzędzie wspierające decyzję, **czy dziś jest dobry moment** na wymianę w oknie
2-tygodniowym dla trzech kierunków:

- **EUR → PLN** (sprzedaż EUR za PLN)
- **PLN → EUR** (zakup EUR za PLN)
- **EUR → USD** (sprzedaż EUR za USD)

Plus karta kontekstowa **USD/PLN** (zasilanie konta pod akcje).

## Czego to narzędzie NIE robi

Nie prognozuje kursu i nie jest poradą inwestycyjną. W horyzoncie 2 tygodni kurs
walutowy jest blisko błądzenia losowego - nikt go wiarygodnie nie przewiduje.

## Co realnie robi (i dlaczego to pomaga)

Przy cyklicznych wymianach w obie strony liczy się nie prognoza, lecz trzy rzeczy:

1. **Położenie kursu względem ostatnich ~3 miesięcy** (waga 70%). Jeśli musisz
   wymienić w oknie 2 tygodni, to czy robisz to przy kursie z górnej, czy dolnej
   części niedawnego zakresu, ma realne znaczenie. Mierzone percentylem.
2. **Krótka tendencja** z ostatnich ~2 tygodni (waga 30%) - czy kurs idzie
   w Twoją stronę, czy przeciw. Pomaga zdecydować "teraz czy poczekać kilka dni".
3. **Wydarzenia w oknie** - decyzje EBC / Fed / NBP, które mogą gwałtownie ruszyć
   kursem. Wpadające w okno obniżają pewność i są pokazywane jako ostrzeżenie.

RSI, wstęga Bollingera i zmienność służą jako potwierdzenie i modyfikator pewności.

Wynik dla każdego kierunku: ocena w skali **-100..+100** (w Twoją stronę),
etykieta (Korzystny / Neutralny / Niekorzystny), poziom pewności i rekomendacja
po polsku - razem z sugestią **podziału wymiany na transze** (uśrednianie), które
przy braku przewagi jest zwykle najrozsądniejszą strategią.

> EUR→PLN i PLN→EUR opisują ten sam kurs z dwóch stron, więc ich oceny są zwykle
> przeciwne. To poprawne zachowanie, nie sprzeczność.

## Dane

Kursy referencyjne EBC z **Frankfurter API** (darmowe, bez klucza):
EUR/PLN i EUR/USD. USD/PLN liczony krzyżowo (EUR/PLN ÷ EUR/USD). Dane dzienne -
do decyzji w horyzoncie 2 tygodni to wystarczająca rozdzielczość.

## Uruchomienie lokalnie

Wymaga tylko Pythona 3.9+ (żadnych bibliotek do instalacji).

```bash
python main.py            # realne dane EBC -> raport fx_report.html
python main.py --demo     # dane syntetyczne (offline), do podglądu wyglądu
python main.py --no-email # nie wysyłaj maila
python main.py --out docs/index.html
```

Po uruchomieniu powstają:
- `fx_report.html` - panel decyzyjny (otwórz w przeglądarce),
- `fx_state.json` - historia ocen i kursów (audyt / wykresy w czasie).

## Stałe aktualizowanie (GitHub Actions)

W repo jest gotowy workflow `.github/workflows/fx-advisor.yml`. Domyślnie:

- uruchamia się w **dni robocze ~16:30 czasu PL** (po publikacji fixingu EBC),
- generuje raport do `docs/index.html`,
- commituje raport i historię z powrotem do repo.

Po włączeniu **GitHub Pages** (Settings → Pages → źródło: `/docs`) masz zawsze
aktualny panel pod stałym adresem - dokładnie jak w Twoich innych projektach.

Możesz też odpalić ręcznie z zakładki **Actions → FX Advisor → Run workflow**.

### E-mail (opcjonalnie, przez Resend)

Dodaj w **Settings → Secrets and variables → Actions**:

- `RESEND_API_KEY`
- `FX_EMAIL_FROM` (np. `fx@supercoinsy.pl`)
- `FX_EMAIL_TO` (np. `marketing@supercoinsy.pl`)

Mail wychodzi **tylko gdy** ocena któregoś kierunku przekracza próg
(`EMAIL_ALERT_MIN_SCORE`, domyślnie 35) **albo** w oknie wypada decyzja banku
centralnego. Dzięki temu nie dostajesz powiadomień bez powodu. Ustaw próg na `0`
w `config.py`, by dostawać raport zawsze.

## Co warto utrzymywać i co można dostroić

**Daty RPP na II połowę 2026.** W `config.py`, lista `EVENTS`, są wpisane
zweryfikowane daty EBC i Fed na cały 2026 oraz daty RPP do lipca (pewna najbliższa:
**8 lipca 2026**). Daty RPP wrzesień-grudzień **uzupełnij** z oficjalnego kalendarza:
nbp.pl → Polityka pieniężna → Kalendarz posiedzeń RPP. To 1 minuta, a wrzesień-styczeń
to Twój szczyt sezonu, więc warto. Możesz też dopisać kluczowe daty danych
(US CPI, NFP) w tym samym formacie.

**Pozostałe pokrętła w `config.py`:**

- `WINDOW_DAYS` - długość okna decyzyjnego (domyślnie 14),
- `LEVEL_WINDOW` / `TREND_WINDOW` - okna położenia i tendencji,
- `W_LEVEL` / `W_TREND` - wagi składników oceny,
- `THRESHOLDS` - progi etykiet Korzystny/Neutralny/Niekorzystny,
- `VOL_ELEVATED_RATIO` - próg uznania zmienności za podwyższoną,
- `DIRECTIONS` - kierunki; ustaw `"primary": True` przy USD/PLN, jeśli chcesz go
  traktować na równi z trzema głównymi.

## Struktura

```
fx-advisor/
├── config.py      # wszystkie ustawienia + kalendarz wydarzeń
├── engine.py      # pobieranie danych, wskaźniki, ocena, rekomendacje
├── report.py      # generator raportu HTML (samodzielny, bez zależności)
├── notify.py      # podsumowanie tekstowe, e-mail (Resend), zapis historii
├── main.py        # punkt wejścia / CLI
├── requirements.txt
└── .github/workflows/fx-advisor.yml
```

## Zastrzeżenie

Kurs w horyzoncie 2 tygodni jest w dużej mierze nieprzewidywalny. Narzędzie
porządkuje fakty i pokazuje, czy bieżący moment jest relatywnie korzystny - ale
decyzję podejmujesz samodzielnie. Nie jest to porada finansowa.
