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

# Fahrer-Kader (scheduler.refresh_rosters): ein Wikipedia-Abruf pro Team.
# Kader ändern sich ein paar Mal im Jahr (Transferperiode, Nachverpflich-
# tungen), nicht minütlich - ein Tagestakt reicht völlig. Vorher lief das
# im selben Job wie der Rückstands-Abbau und damit alle drei Minuten: 18
# Wikipedia-Seiten und 517 Fahrer-Schreibzugriffe pro Lauf, was den teuren
# Renn-Detail-Backfill ausgehungert hat (siehe README, "Hintergrund-Jobs").
REFRESH_INTERVAL_ROSTERS = int(os.environ.get("REFRESH_INTERVAL_ROSTERS", str(24 * 60 * 60)))

# Fahrer-Details (scheduler.refresh_rider_details): Team-Wechsel-Historie
# und Strava-Abgleich für Fahrer, die noch keine haben. Behält den kurzen
# Takt, weil der Job batchweise durch einen Rückstand arbeitet - ist der
# abgebaut, kostet ein Lauf zwei billige Abfragen und sonst nichts.
REFRESH_INTERVAL_RIDER_DETAILS = int(os.environ.get("REFRESH_INTERVAL_RIDER_DETAILS", str(3 * 60)))
RIDER_HISTORY_BATCH_SIZE = int(os.environ.get("RIDER_HISTORY_BATCH_SIZE", "30"))

# Strava-Profil-Abgleich über Wikidata (siehe scrapers/wikidata.py) - läuft
# im selben Job wie die Historie, aber in größeren Batches, da hier je
# Batch (bis zu 50 Titel) nur 2 Requests nötig sind statt einem pro Fahrer.
STRAVA_BATCH_SIZE = int(os.environ.get("STRAVA_BATCH_SIZE", "50"))

# Renn-Historie (WorldTour/ProSeries/Continental seit RACE_HISTORY_START_YEAR,
# siehe app/db_races.py + scrapers/wikipedia_race_history.py): geschätzt
# 1.000-1.500 Rennen (Stand Startjahr 2020), jedes mit mind. einem eigenen
# Wikipedia-Abruf - das dauert (respektvoll ratenlimitiert) mehrere Stunden
# bis Tage, daher kleine Batches pro Lauf, ähnlich wie bei der Fahrer-
# Historie. Reihenfolge: World Tour + ProSeries zuerst (kleiner,
# wichtiger), Continental Touren laufen danach nach - siehe
# scheduler.refresh_race_history/get_races_missing_details.
#
# RACE_HISTORY_START_YEAR bewusst als Konfigurationswert (nicht hart
# codiert): das Seeding pro Jahr ist idempotent (race_history_seed_log) -
# den Wert später abzusenken (z.B. auf 2010) holt automatisch weitere
# Jahre nach, ohne bereits vorhandene Daten anzurühren.
REFRESH_INTERVAL_RACE_HISTORY = int(os.environ.get("REFRESH_INTERVAL_RACE_HISTORY", str(3 * 60)))
RACE_HISTORY_START_YEAR = int(os.environ.get("RACE_HISTORY_START_YEAR", "2020"))
RACE_HISTORY_DETAIL_BATCH_SIZE = int(os.environ.get("RACE_HISTORY_DETAIL_BATCH_SIZE", "15"))
RACE_HISTORY_CIRCUITS = ("africa", "asia", "europe", "america", "oceania")

CACHE_DIR = os.environ.get(
    "CACHE_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
)
