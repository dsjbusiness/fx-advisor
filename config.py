# -*- coding: utf-8 -*-
"""
Konfiguracja FX Advisor. Wszystkie pokretla sa tutaj, logika w pozostalych
modulach:
  data_layer.py  - pobieranie i cache historii, kalendarz wydarzen (YAML)
  indicators.py  - czysta matematyka wskaznikow
  signals.py     - silnik sygnalow (raz na PARE, nie na kierunek)
  planner.py     - warstwa decyzyjna: konkretne plany transz + symulator
  backtest.py    - walk-forward backtest z cache
  report.py      - generator HTML
  notify.py      - alerty e-mail (Resend) + zapis stanu
"""

# ---------------------------------------------------------------------------
# OKNO DECYZYJNE
# ---------------------------------------------------------------------------
WINDOW_DAYS = 14          # kroczace okno decyzyjne (dni kalendarzowe)
WINDOW_SESSIONS = 10      # ~10 dni roboczych w oknie 14-dniowym

# ---------------------------------------------------------------------------
# HISTORIA DANYCH
# ---------------------------------------------------------------------------
TARGET_SESSIONS = 420     # ile sesji chcemy miec w cache
MAX_SESSIONS = 520        # twardy limit rozmiaru cache
MIN_HISTORY = 250         # minimum sesji potrzebne do policzenia sygnalu

DATA_DIR = "data"
HISTORY_FILE = "data/history.json"
BACKTEST_FILE = "data/backtest.json"
EVENTS_GLOB = "data/events_*.yaml"   # events_2026.yaml, events_2027.yaml, ...

# ---------------------------------------------------------------------------
# SILNIK SYGNALOW
# ---------------------------------------------------------------------------
# Percentyle poziomu: 0.2*p30 + 0.3*p90 + 0.5*p250
LEVEL_WINDOWS = (30, 90, 250)
LEVEL_WEIGHTS = (0.20, 0.30, 0.50)

TREND_RET_SESSIONS = 10   # zwrot z 10 sesji...
TREND_VOL_SESSIONS = 20   # ...normalizowany zmiennoscia z 20 sesji
TREND_TANH_SCALE = 2.0    # trend = 100*tanh(t/SCALE)

RSI_PERIOD = 14
BOLL_N = 20
BOLL_K = 2.0

VOL_SESSIONS = 20         # zmiennosc zrealizowana (20 sesji)
VOL_REGIME_LOOKBACK = 250 # rozklad wlasnej zmiennosci z ~1 roku
VOL_LOW_PCT = 25.0        # ponizej -> rezim "niska"
VOL_HIGH_PCT = 75.0       # powyzej -> rezim "wysoka"

RANGE_Z = 1.28            # 80% przedzial: kurs +/- 1.28*sigma*sqrt(10)

# Wagi score zlozonego S (perspektywa SPRZEDAZY waluty bazowej)
W_LEVEL = 0.55
W_TREND = 0.25
W_MR = 0.20

# Progi decyzyjne na S (-100..+100)
S_STRONG = 60
S_MILD = 20

# ---------------------------------------------------------------------------
# PARY (score liczony raz na pare; kierunek kupna = -S)
# ---------------------------------------------------------------------------
# base/quote: sprzedaz bazy = korzystny WYSOKI kurs pary.
PAIRS = [
    {
        "pair": "EURPLN", "base": "EUR", "quote": "PLN",
        "label": "EUR/PLN",
        "affected_by": ["EUR", "PLN"],
        "unit_amount": 10000,   # "na kazde 10 000 EUR"
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
ENGINE_VERSION = "2.1"        # zmiana wersji wymusza pelny przelicz backtestu
BACKTEST_MAX_AGE_DAYS = 7     # pelny przelicz co najwyzej raz na tydzien
BACKTEST_MIN_NEW_SESSIONS = 10  # ...albo gdy przybylo tyle nowych sesji

# ---------------------------------------------------------------------------
# POWIADOMIENIA (Resend) - czytane ze zmiennych srodowiskowych
# ---------------------------------------------------------------------------
EMAIL_ENABLED = False              # albo env FX_EMAIL_ENABLED=1
EMAIL_FROM = "fx@supercoinsy.pl"
EMAIL_TO = "marketing@supercoinsy.pl"
EMAIL_SUBJECT_PREFIX = "FX Advisor"

ALERT_SCORE_CROSS = 60     # alert gdy S ktoregos kierunku przekroczy +/-60
ALERT_DECILE = 10.0        # alert gdy kurs wejdzie w skrajny decyl 250 sesji

STATE_FILE = "fx_state.json"
EMAIL_STATE_FILE = "fx_email_state.json"
