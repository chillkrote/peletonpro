"""Hintergrund-Scheduler: aktualisiert den Cache periodisch aus den Quellen.

Jeder refresh_*-Job fängt alle Exceptions ab und schreibt sie über
cache.mark_error weg, statt den Scheduler-Thread (und damit alle
folgenden Jobs) abstürzen zu lassen. Der zuletzt erfolgreiche Datenstand
bleibt dabei erhalten (siehe app/cache.py).
"""
import logging
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler

from . import cache, db, db_races
from .config import (
    RACE_HISTORY_CIRCUITS,
    RACE_HISTORY_DETAIL_BATCH_SIZE,
    RACE_HISTORY_START_YEAR,
    RACE_SEASON_YEAR,
    REFRESH_INTERVAL_CALENDAR,
    REFRESH_INTERVAL_NEWS,
    REFRESH_INTERVAL_RACE_HISTORY,
    REFRESH_INTERVAL_RESULTS,
    REFRESH_INTERVAL_RIDER_DETAILS,
    REFRESH_INTERVAL_ROSTERS,
    REFRESH_INTERVAL_TEAMS,
    RIDER_HISTORY_BATCH_SIZE,
    STRAVA_BATCH_SIZE,
)
from .models import Race, Team
from .news.rss import fetch_all_news
from .scrapers.wikidata import fetch_strava_urls
from .scrapers.wikipedia import wiki_title_from_url
from .scrapers.wikipedia_race_history import fetch_race_details, fetch_season_race_list
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


def refresh_rosters() -> None:
    """Aktuelle Kader aller WorldTeams (ein Wikipedia-Abruf pro Team) in die
    Datenbank schreiben, plus die UCI-Punkte-Platzhalter.

    Läuft auf einem eigenen, langsamen Takt (REFRESH_INTERVAL_ROSTERS,
    Default 24 h). Vorher steckte das im selben Job wie der Rückstands-
    Abbau und lief damit alle drei Minuten: 18 Wikipedia-Seiten und 517
    Fahrer-Schreibzugriffe pro Lauf, für Daten, die sich ein paar Mal im
    Jahr ändern. Das hat den Großteil der Job-Laufzeit und der
    Wikipedia-Requests verbraucht und den teuren Renn-Detail-Backfill
    ausgehungert (siehe backend/README.md, Abschnitt "Hintergrund-Jobs").

    Übersprungen, wenn keine Datenbank konfiguriert ist (DATABASE_URL
    fehlt, siehe app/db.py) oder noch keine Teams im Cache sind.
    """
    if not db.is_configured():
        logger.info("Kader-Refresh übersprungen: keine Datenbank konfiguriert (DATABASE_URL fehlt)")
        return

    teams_entry = cache.get("teams")
    teams_data = teams_entry.get("data") if teams_entry else None
    if not teams_data:
        logger.info("Kader-Refresh übersprungen: noch keine Teams im Cache")
        return

    teams = [Team(**t) for t in teams_data]
    try:
        db.upsert_teams(teams)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Team-Upsert fehlgeschlagen (%d Teams): %s", len(teams), exc)

    # Erst alle Kader sammeln, dann EINMAL schreiben. Die Fehlerbehandlung
    # pro Team bleibt: ein Team, dessen Wikipedia-Seite sich geändert hat,
    # darf die übrigen nicht mitreißen.
    rider_rows: list[dict] = []
    seen_rider_ids: set[str] = set()
    duplicates = 0
    for team in teams:
        try:
            roster = roster_riders_for_team(team)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Kader-Scraping für '%s' fehlgeschlagen: %s", team.name, exc)
            continue
        for rider_id, rider in roster:
            # Ein Fahrer kann auf zwei Kadern stehen (bei Wechseln listen ihn
            # beide Team-Artikel). Innerhalb eines Batches muss jede ID genau
            # einmal vorkommen; der erste Treffer gewinnt. Die saubere Lösung
            # ist eine Zuordnung pro Saison, siehe README ("Bekannte Lücken").
            if rider_id in seen_rider_ids:
                duplicates += 1
                continue
            seen_rider_ids.add(rider_id)
            first_name, last_name = split_name(rider.name)
            rider_rows.append({
                "id": rider_id,
                "name": rider.name,
                "first_name": first_name,
                "last_name": last_name,
                "country": rider.country,
                "birth_date": rider.birth_date,
                "wiki_url": rider.wiki_url,
                "current_team_id": team.id,
            })

    # Nur schreiben, was sich tatsächlich geändert hat. Ohne diesen Vergleich
    # schreibt jeder Lauf alle ~517 Fahrer neu, auch wenn kein einziges Feld
    # anders ist - das setzt last_updated neu und erzeugt Schreiblast ohne
    # jeden Informationsgewinn.
    try:
        known = db.get_rider_fingerprints()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fahrer-Vergleichsstand nicht lesbar, schreibe alle: %s", exc)
        known = {}
    changed = [r for r in rider_rows if known.get(r["id"]) != db.rider_fingerprint(r)]

    try:
        written = db.upsert_riders(changed)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fahrer-Upsert fehlgeschlagen (%d Fahrer): %s", len(changed), exc)
        written = 0
    logger.info(
        "Kader aktualisiert: %d von %d Fahrern geändert, %d Teams%s",
        written,
        len(rider_rows),
        len(teams),
        f", {duplicates} Doppelnennungen übersprungen" if duplicates else "",
    )

    try:
        new_placeholders = db.ensure_season_point_placeholders()
        if new_placeholders:
            logger.info("UCI-Punkte-Platzhalter angelegt: %d neue Saison-Einträge", new_placeholders)
    except Exception as exc:  # noqa: BLE001
        logger.warning("UCI-Punkte-Platzhalter-Anlage fehlgeschlagen: %s", exc)


def refresh_rider_details() -> None:
    """Arbeitet den Rückstand ab: Team-Wechsel-Historie für Fahrer ohne
    history_fetched_at (ein Wikipedia-Abruf pro Fahrer) und den
    Wikidata-Strava-Abgleich für Fahrer ohne strava_checked_at (gebatcht,
    zwei Requests je bis zu 50 Fahrer).

    Behält das kurze Intervall (REFRESH_INTERVAL_RIDER_DETAILS): solange ein
    Rückstand besteht, soll er zügig abgebaut werden; ist er leer, kostet ein
    Lauf zwei billige Abfragen und nichts weiter.
    """
    if not db.is_configured():
        logger.info("Fahrer-Detail-Refresh übersprungen: keine Datenbank konfiguriert (DATABASE_URL fehlt)")
        return

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


def _race_history_series() -> list[tuple[str, str | None]]:
    """Alle (Kategorie, Circuit)-Kombinationen, die abgedeckt werden -
    Circuit ist nur bei category == 'continental' gesetzt."""
    series: list[tuple[str, str | None]] = [("wt", None), ("proseries", None)]
    series += [("continental", circuit) for circuit in RACE_HISTORY_CIRCUITS]
    return series


def refresh_race_history() -> None:
    """Baut die (persistente) Renn-Historie-Datenbank auf: World Tour +
    ProSeries + alle Continental Touren seit RACE_HISTORY_START_YEAR (siehe
    app/db_races.py + scrapers/wikipedia_race_history.py).

    Phase 1 (Seeding): für jede (Kategorie, Circuit, Saison)-Kombination,
    die noch nicht versucht wurde (race_history_seed_log), wird EINMAL die
    Wikipedia-Saison-Übersichtsseite abgerufen und jedes gefundene Rennen
    als Skeleton-Zeile (Name, Zeitraum, Wiki-URL) angelegt - günstig (ein
    Abruf pro Kombination), läuft daher komplett in einem Durchgang statt
    gebatcht. RACE_HISTORY_START_YEAR lässt sich später absenken (z.B. auf
    2010), um weitere Jahre nachzuholen - bereits geseedete Kombinationen
    werden dabei nicht erneut angefasst.

    Phase 2 (Backfill): für bis zu RACE_HISTORY_DETAIL_BATCH_SIZE Rennen
    ohne Detail-Daten wird die eigene Wikipedia-Seite abgerufen (Distanz,
    Etappenzahl, Ergebnisliste, bei Mehretagenrennen zusätzlich pro
    Etappe) - das ist der teure Teil, daher batchweise über viele Läufe
    verteilt, priorisiert nach Kategorie (World Tour zuerst) und Saison
    (siehe db_races.get_races_missing_details).
    """
    if not db.is_configured():
        logger.info("Renn-Historie-Refresh übersprungen: keine Datenbank konfiguriert (DATABASE_URL fehlt)")
        return

    seeded_now = 0
    for category, circuit in _race_history_series():
        for year in range(RACE_HISTORY_START_YEAR, RACE_SEASON_YEAR + 1):
            if db_races.is_season_seeded(category, year, circuit):
                continue
            label = f"{category}{f'/{circuit}' if circuit else ''} {year}"
            try:
                races = fetch_season_race_list(year, category, circuit)
                for race in races:
                    db_races.upsert_race_skeleton(
                        season=year,
                        category=category,
                        circuit=circuit,
                        name=race["name"],
                        start_date=race["start_date"],
                        end_date=race["end_date"],
                        wiki_url=race["wiki_url"],
                    )
                db_races.mark_season_seeded(category, year, len(races), circuit)
                seeded_now += 1
                if races:
                    logger.info("Renn-Historie geseedet: %s - %d Rennen", label, len(races))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Saison-Seeding fehlgeschlagen für %s: %s", label, exc)
    if seeded_now:
        logger.info("Renn-Historie-Seeding: %d neue Saison/Kategorie-Kombinationen verarbeitet", seeded_now)

    pending = db_races.get_races_missing_details(limit=RACE_HISTORY_DETAIL_BATCH_SIZE)
    fetched = 0
    for race_row in pending:
        try:
            wiki_title = wiki_title_from_url(race_row["wiki_url"])
            details = fetch_race_details(wiki_title, race_row["season"])
            db_races.replace_race_details(
                race_row["id"],
                num_stages=details["num_stages"],
                distance_km=details["distance_km"],
                organizer_website=details["organizer_website"],
                results=details["results"],
                stages=details["stages"],
            )
            fetched += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Detail-Scraping für '%s' fehlgeschlagen: %s", race_row["name"], exc)
    if pending:
        remaining = db_races.get_races_missing_details_count()
        logger.info(
            "Renn-Historie-Details geladen: %d/%d in diesem Lauf, noch %d Rennen ausstehend",
            fetched,
            len(pending),
            remaining,
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
    (refresh_rosters, REFRESH_INTERVAL_ROSTERS, "refresh_rosters"),
    (refresh_rider_details, REFRESH_INTERVAL_RIDER_DETAILS, "refresh_rider_details"),
    (refresh_race_history, REFRESH_INTERVAL_RACE_HISTORY, "refresh_race_history"),
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
