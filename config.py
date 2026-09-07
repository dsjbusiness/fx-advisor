# -*- coding: utf-8 -*-
"""
Konfiguracja FX Advisor. Wszystkie pokretla sa tutaj, logika w pozostalych
modulach:
  data_layer.py  - pobieranie i cache historii (EBC SDMX, Frankfurter, XML EBC),
                   fixing NBP, stopy procentowe, kalendarz wydarzen, pozycje
  indicators.py  - czysta matematyka wskaznikow
  signals.py     - kontekst rynkowy (percentyle, tendencja, zmiennosc)
  planner.py     - warstwa decyzyjna: DCA z przechylem pod carry + pozycje
  backtest.py    - walk-forward backtest na pelnej historii (okna rozlaczne)
  report.py      - generator HTML
  notify.py      - alerty e-mail (Resend) + zapis stanu

F101 (2026-09): silnik score przestal sterowac transzami. Audyt na 27 latach
fixingow EBC pokazal, ze aktywny plan nie pobija DCA. Domyslna polityka to
DCA + przechyl pod carry + omijanie dni RPP; score zostal jako kontekst.
"""

# ---------------------------------------------------------------------------
# OKNO DECYZYJNE
# ---------------------------------------------------------------------------
WINDOW_DAYS = 14          # domyslne okno (dni kalendarzowe) dla planu-szablonu
WINDOW_SESSIONS = 10      # ~10 dni roboczych w oknie 14-dniowym

SPARK_SESSIONS = 40       # ~2 miesiace historii widoczne na wykresie

# ---------------------------------------------------------------------------
# HISTORIA DANYCH
# ---------------------------------------------------------------------------
HISTORY_START = "1999-01-04"  # poczatek fixingow EBC (pelna historia)
MAX_SESSIONS = 9000           # twardy limit rozmiaru cache (~35 lat)
MIN_HISTORY = 250             # minimum sesji do policzenia percentyli

# Pobieranie kursow. Kolejnosc zrodel: EBC SDMX (CSV, pelna historia jednym
# zapytaniem) -> Frankfurter -> feed XML EBC.
ECB_SDMX_URL = ("https://data-api.ecb.europa.eu/service/data/EXR/"
                "D.{ccy}.EUR.SP00.A?format=csvdata&startPeriod={start}&endPeriod={end}")
HTTP_TIMEOUT = 20
HTTP_TIMEOUT_ECB = 60     # pelna historia SDMX/XML
HTTP_RETRIES = 2
HTTP_BACKOFF_S = 3
MAX_STALE_DAYS = 5

DATA_DIR = "data"
HISTORY_FILE = "data/history.json"
BACKTEST_FILE = "data/backtest.json"
EVENTS_GLOB = "data/events_*.yaml"
NBP_FILE = "data/nbp.json"
RATES_FILE = "data/rates.json"
POSITIONS_FILE = "data/positions.json"

# Fixing NBP (tabela A, publikacja ok. 12:00 czasu PL). Drugi punkt dnia dla
# par z PLN i kurs do ksiegowania (faktury/VAT: kurs z poprzedniego dnia
# roboczego). Tylko do wyswietlenia - percentyle licza sie na EBC.
NBP_API_URL = ("https://api.nbp.pl/api/exchangerates/rates/a/{ccy}/"
               "{start}/{end}/?format=json")
NBP_KEEP_DAYS = 120       # ile dni fixingu NBP trzymamy w cache

# ---------------------------------------------------------------------------
# STOPY PROCENTOWE (carry)
# ---------------------------------------------------------------------------
# Wartosci awaryjne, gdy zrodla online milcza. NBP nie ma API stop -
# aktualizuj po decyzjach RPP (kalendarz je zna).
POLICY_RATES = {"PLN": 3.75, "EUR": 2.25, "USD": 3.63}
POLICY_RATES_AS_OF = "2026-09-07"
# Zrodla online (opcjonalne): stopa depozytowa EBC (SDMX) i efektywna
# stopa fed funds (FRED). PLN: static.
ECB_DFR_URL = ("https://data-api.ecb.europa.eu/service/data/FM/"
               "B.U2.EUR.4F.KR.DFR.LEV?format=csvdata&lastNObservations=1")
# cosd = poczatek zakresu; bez niego FRED zwraca cala historie od 1954 (wolno)
FRED_DFF_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF&cosd={start}"

# Przechyl DCA pod carry: gdy oczekiwany zysk z wczesniejszego wykonania
# (roznica stop x dni / 365) przekracza ten prog, transze sa front-loaded
# (liniowo malejace wagi); przy ujemnym carry - back-loaded.
CARRY_TILT_MIN_BPS = 2.0
DCA_TRANCHES = 4          # domyslna liczba transz w oknie

# Tryb teoretyczny: gdy nie ma zadnej pozycji, "Dzis do zrobienia" pokazuje
# dzisiejsze transze planow-szablonow przeliczone na unit_amount kazdej pary.
THEORETICAL_MODE = True

# ---------------------------------------------------------------------------
# DOSTAWCY (spread + oplata stala) - do linii "dostawca vs timing"
# ---------------------------------------------------------------------------
PROVIDERS = [
    {"name": "Bank (tabela kursow)", "spread_bps": 150.0, "fee_fixed": 0.0},
    {"name": "Kantor internetowy", "spread_bps": 15.0, "fee_fixed": 0.0},
    {"name": "Wise / Revolut Business", "spread_bps": 40.0, "fee_fixed": 0.0},
]
DEFAULT_PROVIDER = 0      # indeks w PROVIDERS - Twoj dzisiejszy dostawca

# ---------------------------------------------------------------------------
# KALENDARZ WYDARZEN
# ---------------------------------------------------------------------------
# Publikacje po fixingu EBC (14:15 CET): FOMC ~20:00 PL, CPI/NFP USA 14:30 PL.
# Reakcja kursu dla kogos, kto wymienia w godzinach pracy, jest NASTEPNEGO
# dnia - ten dzien omijamy (effective_date = nastepna sesja).
LATE_SOURCES = ("Fed", "BLS")
CALENDAR_MIN_COVERAGE_DAYS = 30   # test CI: kalendarz musi siegac tyle dni naprzod

# ---------------------------------------------------------------------------
# KONTEKST RYNKOWY (dawny silnik score - teraz tylko informacyjnie)
# ---------------------------------------------------------------------------
LEVEL_WINDOWS = (30, 90, 250)
LEVEL_WEIGHTS = (0.20, 0.30, 0.50)

TREND_RET_SESSIONS = 10
TREND_VOL_SESSIONS = 20
TREND_TANH_SCALE = 2.0

RSI_PERIOD = 14
RSI_LOOKBACK = 300        # RSI liczony z ostatnich N sesji (wygladzanie Wildera
                          # i tak zapomina dalej; bez tego backtest jest O(n^2))
BOLL_N = 20
BOLL_K = 2.0

VOL_SESSIONS = 20
VOL_REGIME_LOOKBACK = 250
VOL_LOW_PCT = 25.0
VOL_HIGH_PCT = 75.0

RANGE_Z = 1.28            # 80% przedzial: kurs +/- 1.28*sigma*sqrt(10)

W_LEVEL = 0.55
W_TREND = 0.25
W_MR = 0.20

S_STRONG = 60
S_MILD = 20

# ---------------------------------------------------------------------------
# PARY
# ---------------------------------------------------------------------------
PAIRS = [
    {
        "pair": "EURPLN", "base": "EUR", "quote": "PLN",
        "label": "EUR/PLN",
        "affected_by": ["EUR", "PLN"],
        "unit_amount": 10000,
    },
    {
        "pair": "USDPLN", "base": "USD", "quote": "PLN",
        "label": "USD/PLN",
        "affected_by": ["USD", "PLN"],
        "unit_amount": 10000,
    },
    {
        "pair": "EURUSD", "base": "EUR", "quote": "USD",
        "label": "EUR/USD",
        "affected_by": ["EUR", "USD"],
        "unit_amount": 10000,
    },
]

# ---------------------------------------------------------------------------
# BACKTEST
# ---------------------------------------------------------------------------
ENGINE_VERSION = "3.0"        # zmiana wersji wymusza pelny przelicz
BACKTEST_MAX_AGE_DAYS = 7
BACKTEST_MIN_NEW_SESSIONS = 10
BACKTEST_RECENT_SESSIONS = 500  # osobna statystyka "ostatnie ~2 lata"
BACKTEST_CI_Z = 1.645           # 90% przedzial ufnosci

# ---------------------------------------------------------------------------
# POWIADOMIENIA (Resend)
# ---------------------------------------------------------------------------
EMAIL_ENABLED = False
EMAIL_FROM = "fx@supercoinsy.pl"
EMAIL_TO = "marketing@supercoinsy.pl"
EMAIL_SUBJECT_PREFIX = "FX Advisor"

ALERT_DECILE = 10.0        # alert (kontekst), gdy kurs wejdzie w skrajny decyl

STATE_FILE = "fx_state.json"
EMAIL_STATE_FILE = "fx_email_state.json"
