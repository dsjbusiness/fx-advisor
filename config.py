# -*- coding: utf-8 -*-
"""
Konfiguracja doradcy walutowego (FX Advisor).
Wszystkie pokrętła są tutaj. Logika liczbowa siedzi w engine.py.
"""

# ---------------------------------------------------------------------------
# OKNO DECYZYJNE
# ---------------------------------------------------------------------------
# Twój horyzont wymiany. Wszystkie wymiany robisz w oknie 2-tygodniowym,
# więc 14 dni. Wydarzenia (decyzje banków centralnych) wpadające w to okno
# obniżają pewność rekomendacji i są pokazywane jako ostrzeżenie.
WINDOW_DAYS = 14

# ---------------------------------------------------------------------------
# OKNA ANALIZY (w dniach roboczych, bo dane to fixing ECB w dni robocze)
# ---------------------------------------------------------------------------
LEVEL_WINDOW = 60     # baza "pozycjonowania": gdzie jest kurs na tle ~3 miesięcy
TREND_WINDOW = 10     # krótka tendencja: ruch z ostatnich ~2 tygodni
VOL_SHORT = 20        # krótka zmienność
VOL_LONG = 90         # długa zmienność (baza odniesienia)
RSI_PERIOD = 14
SPARK_POINTS = 60     # ile punktów na wykresie sparkline w raporcie

# Ile dni kalendarzowych pobierać wstecz, by mieć zapas dni roboczych.
HISTORY_DAYS = 210

# ---------------------------------------------------------------------------
# PARY I KIERUNKI
# ---------------------------------------------------------------------------
# Dane bazowe pobieramy z ECB (baza EUR): EUR/PLN i EUR/USD.
# USD/PLN wyliczamy jako EUR/PLN / EUR/USD.
#
# "high_good": czy WYSOKI kurs danej pary jest korzystny dla tego kierunku.
#   EUR -> PLN  : sprzedajesz EUR za PLN. Wysoki EUR/PLN = więcej PLN. high_good = True
#   PLN -> EUR  : kupujesz EUR za PLN. Niski EUR/PLN = taniej EUR.   high_good = False
#   EUR -> USD  : sprzedajesz EUR za USD. Wysoki EUR/USD = więcej USD. high_good = True
DIRECTIONS = [
    {
        "id": "eur_pln",
        "label": "EUR \u2192 PLN",
        "desc": "Sprzeda\u017c EUR, zakup PLN",
        "pair": "EURPLN",
        "high_good": True,
        "affected_by": ["EUR", "PLN"],
        "primary": True,
    },
    {
        "id": "pln_eur",
        "label": "PLN \u2192 EUR",
        "desc": "Sprzeda\u017c PLN, zakup EUR",
        "pair": "EURPLN",
        "high_good": False,
        "affected_by": ["EUR", "PLN"],
        "primary": True,
    },
    {
        "id": "eur_usd",
        "label": "EUR \u2192 USD",
        "desc": "Sprzeda\u017c EUR, zakup USD",
        "pair": "EURUSD",
        "high_good": True,
        "affected_by": ["EUR", "USD"],
        "primary": True,
    },
    # Karta kontekstowa (zasilanie konta USD pod akcje). Nie była w pytaniu,
    # ale wynika z EUR/PLN i EUR/USD za darmo. Ustaw "primary": True jeśli
    # chcesz traktować ją na równi z trzema głównymi.
    {
        "id": "usd_pln",
        "label": "USD \u2192 PLN / PLN \u2192 USD",
        "desc": "Kontekst kursu USD/PLN",
        "pair": "USDPLN",
        "high_good": True,   # liczone informacyjnie; karta pokazuje samo położenie
        "affected_by": ["USD", "PLN"],
        "primary": False,
    },
]

# ---------------------------------------------------------------------------
# PROGI OCENY (favorability w skali -100..+100, w kierunku Twojej wymiany)
# ---------------------------------------------------------------------------
THRESHOLDS = {
    "strong_pos": 35,   # Korzystny
    "mild_pos": 15,     # Lekko korzystny
    "mild_neg": -15,    # Lekko niekorzystny
    "strong_neg": -35,  # Niekorzystny
}
# Waga składników oceny.
W_LEVEL = 0.70
W_TREND = 0.30
# Próg uznania zmienności za podwyższoną (krótka / długa).
VOL_ELEVATED_RATIO = 1.25

# ---------------------------------------------------------------------------
# KALENDARZ WYDARZE\u0143 (decyzje banków centralnych, 2026)
# ---------------------------------------------------------------------------
# To są dni OG\u0141OSZENIA decyzji (drugi dzień posiedzenia). Wydarzenie wpadające
# w Twoje okno 2-tygodniowe podnosi ryzyko gwa\u0142townego ruchu i obniża pewność.
#
# \u017aród\u0142a dat (zweryfikowane przy budowie, czerwiec 2026):
#   ECB:  ecb.europa.eu  (decyzje w czwartki, og\u0142oszenie ~14:15 CET)
#   Fed:  federalreserve.gov  (og\u0142oszenie ~20:00 CET, drugi dzie\u0144)
#   NBP:  nbp.pl  (RPP, og\u0142oszenie ~15:00-16:00, drugi dzie\u0144)
#
# UWAGA: daty RPP na II po\u0142owe 2026 (wrzesie\u0144-grudzie\u0144) NIE są tu wpisane,
# bo \u017aród\u0142a r\u00f3\u017cni\u0142y sie co do dok\u0142adnych dni. Wejd\u017a na
# https://nbp.pl  ->  Polityka pieni\u0119\u017cna -> Kalendarz posiedze\u0144 RPP
# i dopisz brakuj\u0105ce daty (po jednej linii). Pewna data: 8 lipca 2026.
#
# Format: ("YYYY-MM-DD", "Bank", "WALUTA", "opis", impact)  impact: "high"/"medium"
EVENTS = [
    # --- ECB (EUR) ---
    ("2026-03-19", "ECB", "EUR", "Decyzja EBC ws. st\u00f3p", "high"),
    ("2026-04-30", "ECB", "EUR", "Decyzja EBC ws. st\u00f3p", "high"),
    ("2026-06-11", "ECB", "EUR", "Decyzja EBC ws. st\u00f3p", "high"),
    ("2026-07-23", "ECB", "EUR", "Decyzja EBC ws. st\u00f3p", "high"),
    ("2026-09-10", "ECB", "EUR", "Decyzja EBC ws. st\u00f3p", "high"),
    ("2026-10-29", "ECB", "EUR", "Decyzja EBC ws. st\u00f3p", "high"),
    ("2026-12-17", "ECB", "EUR", "Decyzja EBC ws. st\u00f3p", "high"),
    # --- Fed (USD) ---
    ("2026-01-28", "Fed", "USD", "Decyzja FOMC ws. st\u00f3p", "high"),
    ("2026-03-18", "Fed", "USD", "Decyzja FOMC ws. st\u00f3p", "high"),
    ("2026-04-29", "Fed", "USD", "Decyzja FOMC ws. st\u00f3p", "high"),
    ("2026-06-17", "Fed", "USD", "Decyzja FOMC ws. st\u00f3p", "high"),
    ("2026-07-29", "Fed", "USD", "Decyzja FOMC ws. st\u00f3p", "high"),
    ("2026-09-16", "Fed", "USD", "Decyzja FOMC ws. st\u00f3p", "high"),
    ("2026-10-28", "Fed", "USD", "Decyzja FOMC ws. st\u00f3p", "high"),
    ("2026-12-09", "Fed", "USD", "Decyzja FOMC ws. st\u00f3p", "high"),
    # --- NBP / RPP (PLN) --- (II po\u0142owa roku: uzupe\u0142nij z nbp.pl)
    ("2026-01-14", "NBP", "PLN", "Decyzja RPP ws. st\u00f3p", "high"),
    ("2026-02-04", "NBP", "PLN", "Decyzja RPP ws. st\u00f3p", "high"),
    ("2026-03-04", "NBP", "PLN", "Decyzja RPP ws. st\u00f3p", "high"),
    ("2026-06-02", "NBP", "PLN", "Decyzja RPP ws. st\u00f3p", "high"),
    ("2026-07-08", "NBP", "PLN", "Decyzja RPP ws. st\u00f3p (z projekcj\u0105)", "high"),
    # ("2026-09-??", "NBP", "PLN", "Decyzja RPP ws. st\u00f3p", "high"),
    # ("2026-10-??", "NBP", "PLN", "Decyzja RPP ws. st\u00f3p", "high"),
    # ("2026-11-??", "NBP", "PLN", "Decyzja RPP ws. st\u00f3p (z projekcj\u0105)", "high"),
    # ("2026-12-??", "NBP", "PLN", "Decyzja RPP ws. st\u00f3p", "high"),
]

# ---------------------------------------------------------------------------
# POWIADOMIENIA (opcjonalne) - czytane ze zmiennych \u015brodowiskowych
# ---------------------------------------------------------------------------
# E-mail przez Resend (jak w Twoich innych projektach). Ustaw w sekretach.
EMAIL_ENABLED = False          # albo ustaw env FX_EMAIL_ENABLED=1
EMAIL_FROM = "fx@supercoinsy.pl"
EMAIL_TO = "marketing@supercoinsy.pl"
EMAIL_SUBJECT = "FX Advisor - przegl\u0105d wymiany walut"
# Wysyłka maila TYLKO gdy któryś główny kierunek jest KORZYSTNY, tzn. ma
# favorability DODATNIĄ i >= tego progu. Mocny minus ("Niekorzystny") nie wysyła.
# Same wydarzenia banków centralnych też nie wysyłają (są tylko kontekstem w treści).
# 35 = etykieta "Korzystny"; obniż do 15, by łapać też "Lekko korzystny";
# 0 = praktycznie zawsze (gdy którykolwiek kierunek jest nieujemny).
EMAIL_ALERT_MIN_SCORE = 35

# Zapis historii do pliku JSON (stan, do wykres\u00f3w/audytu).
STATE_FILE = "fx_state.json"

# Stan wysylki maila: data ostatniej wysylki (limit raz/dobe) + zestaw par
# korzystnych z poprzedniego uruchomienia (wykrycie przeskoku na korzystna).
EMAIL_STATE_FILE = "fx_email_state.json"
