"""Zentrale Konfiguration für Backend, Scraper und Scheduler."""
import os

# CORS: welche Origins dürfen die API aufrufen (GitHub Pages + lokale Entwicklung)
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if origin.strip()
]

# Eigener User-Agent mit Kontakt, um beim Scraping als guter Citizen erkennbar
# zu sein (siehe backend/README.md, Abschnitt "Scraping-Ethik"). Wikipedia
# empfiehlt dies ausdrücklich für automatisierte API-Zugriffe.
SCRAPER_USER_AGENT = os.environ.get(
    "SCRAPER_USER_AGENT",
    "PelotonProBot/1.0 (+https://github.com/chillkrote/peletonpro)",
)

# Mindestabstand zwischen aufeinanderfolgenden Requests an dieselbe Quelle (Sekunden)
SCRAPER_REQUEST_DELAY_SECONDS = float(os.environ.get("SCRAPER_REQUEST_DELAY_SECONDS", "2.0"))
SCRAPER_TIMEOUT_SECONDS = float(os.environ.get("SCRAPER_TIMEOUT_SECONDS", "15.0"))

RACE_SEASON_YEAR = int(os.environ.get("RACE_SEASON_YEAR", "2026"))

NEWS_FEEDS = [
    {"name": "Cyclingnews", "url": "https://www.cyclingnews.com/feeds/news/"},
    {
        "name": "Google News: Radsport",
        "url": "https://news.google.com/rss/search?q=Radsport&hl=de&gl=DE&ceid=DE:de",
    },
]

# Aktualisierungsintervalle für den Scheduler (Sekunden). Teams/Kalender/
# Ergebnisse kommen jetzt von Wikipedia statt Live-Scraping - Wikipedia-
# Artikel werden von Freiwilligen bearbeitet, nicht in Echtzeit, daher
# reichen deutlich größere Intervalle als beim ursprünglich geplanten
# Live-Scraping (schont außerdem Wikipedias API).
REFRESH_INTERVAL_TEAMS = int(os.environ.get("REFRESH_INTERVAL_TEAMS", str(24 * 60 * 60)))
REFRESH_INTERVAL_CALENDAR = int(os.environ.get("REFRESH_INTERVAL_CALENDAR", str(24 * 60 * 60)))
REFRESH_INTERVAL_RESULTS = int(os.environ.get("REFRESH_INTERVAL_RESULTS", str(60 * 60)))
REFRESH_INTERVAL_NEWS = int(os.environ.get("REFRESH_INTERVAL_NEWS", str(15 * 60)))

# Fahrer-Datenbank: läuft häufiger als die anderen Jobs, weil sie beim
# ersten Befüllen der (persistenten) Datenbank batchweise durch alle
# Fahrer ohne Historie arbeitet (siehe scheduler.refresh_riders). Ist die
# Datenbank einmal vollständig, wird jeder Lauf sehr billig (kein
# Rückstand mehr abzuarbeiten), daher schadet das kurze Intervall nicht.
REFRESH_INTERVAL_RIDERS = int(os.environ.get("REFRESH_INTERVAL_RIDERS", str(3 * 60)))
RIDER_HISTORY_BATCH_SIZE = int(os.environ.get("RIDER_HISTORY_BATCH_SIZE", "30"))

CACHE_DIR = os.environ.get(
    "CACHE_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
)
