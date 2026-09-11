"""Hintergrund-Scheduler: aktualisiert den Cache periodisch aus den Quellen.

Jeder refresh_*-Job fängt alle Exceptions ab und schreibt sie über
cache.mark_error weg, statt den Scheduler-Thread (und damit alle
folgenden Jobs) abstürzen zu lassen. Der zuletzt erfolgreiche Datenstand
bleibt dabei erhalten (siehe app/cache.py).
"""
import logging
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler

from . import cache
from .config import (
    REFRESH_INTERVAL_CALENDAR,
    REFRESH_INTERVAL_NEWS,
    REFRESH_INTERVAL_RESULTS,
    REFRESH_INTERVAL_TEAMS,
)
from .models import Race
from .news.rss import fetch_all_news
from .scrapers.wikipedia_races import fetch_race_calendar, fetch_race_result
from .scrapers.wikipedia_teams import fetch_current_worldteams

logger = logging.getLogger(__name__)


def refresh_teams() -> None:
    try:
        teams = fetch_current_worldteams()
        cache.set("teams", [t.model_dump() for t in teams])
        logger.info("Teams aktualisiert: %d Einträge", len(teams))
    except Exception as exc:  # noqa: BLE001 - Job darf niemals crashen
        logger.error("Team-Refresh fehlgeschlagen: %s", exc)
        cache.mark_error("teams", str(exc))


def refresh_calendar() -> None:
    try:
        races = fetch_race_calendar()
        cache.set("races", [r.model_dump() for r in races])
        logger.info("Rennkalender aktualisiert: %d Einträge", len(races))
    except Exception as exc:  # noqa: BLE001
        logger.error("Kalender-Refresh fehlgeschlagen: %s", exc)
        cache.mark_error("races", str(exc))


def refresh_results() -> None:
    """Holt Ergebnisse für alle bereits gestarteten Rennen der Saison.

    Anders als bei Live-Scraping (procyclingstats.com) gibt es hier keinen
    Sinn in einem engen "aktuell laufend"-Fenster: Wikipedia-Artikel werden
    von Freiwilligen bearbeitet, nicht in Echtzeit, und das Endergebnis
    bleibt nach Rennende dauerhaft im Artikel stehen. Daher werden alle
    Rennen berücksichtigt, deren Startdatum in der Vergangenheit liegt -
    Rennen, für die noch kein Ergebnis-Abschnitt existiert (laufend oder
    Artikel noch nicht aktualisiert), liefern einfach kein Ergebnis (siehe
    fetch_race_result) und werden übersprungen.

    Best-effort: basiert auf dem zuletzt gecachten Kalender. Ohne Kalender-
    Daten (z.B. beim allerersten Start) wird der Lauf übersprungen.
    """
    calendar_entry = cache.get("races")
    if not calendar_entry or not calendar_entry.get("data"):
        logger.info("Ergebnis-Refresh übersprungen: noch kein Kalender im Cache")
        return

    today = date.today().isoformat()
    started_races = [r for r in calendar_entry["data"] if r["start_date"] <= today]

    results = []
    errors = []
    for race_dict in started_races:
        try:
            race = Race(**race_dict)
            result = fetch_race_result(race)
            if result is not None:
                results.append(result.model_dump())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ergebnis-Scraping für '%s' fehlgeschlagen: %s", race_dict["id"], exc)
            errors.append(f"{race_dict['id']}: {exc}")

    if results:
        cache.set("results", results)
        logger.info("Ergebnisse aktualisiert: %d Rennen mit Ergebnis", len(results))
    elif errors:
        cache.mark_error("results", "; ".join(errors))


def refresh_news() -> None:
    try:
        news = fetch_all_news()
        cache.set("news", [n.model_dump() for n in news])
        logger.info("News aktualisiert: %d Einträge", len(news))
    except Exception as exc:  # noqa: BLE001
        logger.error("News-Refresh fehlgeschlagen: %s", exc)
        cache.mark_error("news", str(exc))


JOBS = [
    (refresh_teams, REFRESH_INTERVAL_TEAMS, "refresh_teams"),
    (refresh_calendar, REFRESH_INTERVAL_CALENDAR, "refresh_calendar"),
    (refresh_results, REFRESH_INTERVAL_RESULTS, "refresh_results"),
    (refresh_news, REFRESH_INTERVAL_NEWS, "refresh_news"),
]


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    for func, interval_seconds, job_id in JOBS:
        scheduler.add_job(
            func,
            "interval",
            seconds=interval_seconds,
            id=job_id,
            next_run_time=datetime.now(),  # sofort einmal ausführen, dann im Intervall
            max_instances=1,
            coalesce=True,
        )
    scheduler.start()
    logger.info("Scheduler gestartet mit %d Jobs", len(JOBS))
    return scheduler
