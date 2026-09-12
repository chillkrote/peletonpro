"""Hintergrund-Scheduler: aktualisiert den Cache periodisch aus den Quellen.

Jeder refresh_*-Job fängt alle Exceptions ab und schreibt sie über
cache.mark_error weg, statt den Scheduler-Thread (und damit alle
folgenden Jobs) abstürzen zu lassen. Der zuletzt erfolgreiche Datenstand
bleibt dabei erhalten (siehe app/cache.py).
"""
import logging
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler

from . import cache, db
from .config import (
    REFRESH_INTERVAL_CALENDAR,
    REFRESH_INTERVAL_NEWS,
    REFRESH_INTERVAL_RESULTS,
    REFRESH_INTERVAL_RIDERS,
    REFRESH_INTERVAL_TEAMS,
    RIDER_HISTORY_BATCH_SIZE,
    STRAVA_BATCH_SIZE,
)
from .models import Race, Team
from .news.rss import fetch_all_news
from .scrapers.wikidata import fetch_strava_urls
from .scrapers.wikipedia import wiki_title_from_url
from .scrapers.wikipedia_races import fetch_race_calendar, fetch_race_result
from .scrapers.wikipedia_riders import fetch_rider_history, roster_riders_for_team, split_name
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


def refresh_riders() -> None:
    """Baut die (persistente) Fahrer-Datenbank auf: aktuelle Kader aller
    WorldTeams (schnell, ein Abruf pro Team) sowie Team-Wechsel-Historie für
    Fahrer, die noch keine haben (langsam, ein Abruf pro Fahrer - daher
    batchweise über mehrere Job-Läufe verteilt, siehe RIDER_HISTORY_BATCH_SIZE).

    Übersprungen, wenn keine Fahrer-Datenbank konfiguriert ist (DATABASE_URL
    fehlt, siehe app/db.py) oder noch keine Teams im Cache sind.
    """
    if not db.is_configured():
        logger.info("Fahrer-Refresh übersprungen: keine Fahrer-Datenbank konfiguriert (DATABASE_URL fehlt)")
        return

    teams_entry = cache.get("teams")
    teams_data = teams_entry.get("data") if teams_entry else None
    if not teams_data:
        logger.info("Fahrer-Refresh übersprungen: noch keine Teams im Cache")
        return

    teams = [Team(**t) for t in teams_data]
    for team in teams:
        try:
            db.upsert_team(team)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Team-Upsert für '%s' fehlgeschlagen: %s", team.name, exc)

    total_riders = 0
    for team in teams:
        try:
            for rider_id, rider in roster_riders_for_team(team):
                first_name, last_name = split_name(rider.name)
                db.upsert_rider(
                    rider_id=rider_id,
                    name=rider.name,
                    first_name=first_name,
                    last_name=last_name,
                    country=rider.country,
                    birth_date=rider.birth_date,
                    wiki_url=rider.wiki_url,
                    current_team_id=team.id,
                )
                total_riders += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Kader-Scraping für '%s' fehlgeschlagen: %s", team.name, exc)
    logger.info("Fahrer-Kader aktualisiert: %d Zuordnungen über %d Teams", total_riders, len(teams))

    pending = db.get_riders_missing_history(limit=RIDER_HISTORY_BATCH_SIZE)
    fetched = 0
    for rider_row in pending:
        try:
            wiki_title = wiki_title_from_url(rider_row["wiki_url"])
            history = fetch_rider_history(wiki_title)
            db.replace_stints(rider_row["id"], history.stints)
            fetched += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Historie-Scraping für '%s' fehlgeschlagen: %s", rider_row["name"], exc)
    if pending:
        remaining = db.get_riders_missing_history_count()
        logger.info(
            "Fahrer-Historie geladen: %d/%d in diesem Lauf, noch %d Fahrer ausstehend",
            fetched,
            len(pending),
            remaining,
        )

    try:
        new_placeholders = db.ensure_season_point_placeholders()
        if new_placeholders:
            logger.info("UCI-Punkte-Platzhalter angelegt: %d neue Saison-Einträge", new_placeholders)
    except Exception as exc:  # noqa: BLE001
        logger.warning("UCI-Punkte-Platzhalter-Anlage fehlgeschlagen: %s", exc)

    pending_strava = db.get_riders_missing_strava(limit=STRAVA_BATCH_SIZE)
    if pending_strava:
        titles = [wiki_title_from_url(r["wiki_url"]) for r in pending_strava]
        try:
            urls_by_title = fetch_strava_urls(titles)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Strava-Abgleich (Wikidata) fehlgeschlagen: %s", exc)
            urls_by_title = {}
        found = 0
        for rider_row, title in zip(pending_strava, titles):
            url = urls_by_title.get(title)
            db.set_strava_url(rider_row["id"], url)
            found += bool(url)
        logger.info(
            "Strava-Abgleich: %d Fahrer geprüft, %d mit Profil gefunden", len(pending_strava), found
        )


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
    (refresh_riders, REFRESH_INTERVAL_RIDERS, "refresh_riders"),
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
