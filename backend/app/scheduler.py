"""Hintergrund-Scheduler: aktualisiert die Daten periodisch aus den Quellen.

Ziel ist bei allen Jobs außer News die Postgres-Datenbank (app/db.py,
app/db_races.py); News laufen weiter über app/cache.py, weil es dafür
keine Tabelle gibt (Begründung in app/cache.py).

Jeder refresh_*-Job fängt alle Exceptions ab, statt den Scheduler-Thread
(und damit alle folgenden Jobs) abstürzen zu lassen. Der zuletzt
erfolgreiche Datenstand bleibt dabei erhalten: ein fehlgeschlagener Lauf
schreibt einfach nicht.
"""
import argparse
import functools
import inspect
import logging
import sys
import time
from datetime import datetime, timedelta

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from . import cache, db, db_races
from .config import (
    JOB_START_STAGGER_SECONDS,
    NAME_BATCH_SIZE,
    RACE_HISTORY_CIRCUITS,
    RACE_HISTORY_DETAIL_BATCH_SIZE,
    RACE_HISTORY_RUN_SECONDS,
    RACE_HISTORY_START_YEAR,
    RACE_SEASON_YEAR,
    REFRESH_INTERVAL_NEWS,
    REFRESH_INTERVAL_RACE_HISTORY,
    REFRESH_INTERVAL_RIDER_DETAILS,
    REFRESH_INTERVAL_ROSTERS,
    REFRESH_INTERVAL_TEAMS,
    RIDER_DETAILS_RUN_SECONDS,
    RIDER_HISTORY_BATCH_SIZE,
    STRAVA_BATCH_SIZE,
)
from .models import Team
from .news.rss import fetch_all_news
from .scrapers.wikidata import fetch_family_names, fetch_strava_urls
from .scrapers.wikipedia import fetch_wikidata_ids, wiki_title_from_url
from .scrapers.wikipedia_race_history import fetch_race_details, fetch_season_race_list
from .scrapers.wikipedia_riders import (
    fetch_rider_history,
    nachname_aus_wikidata,
    roster_riders_for_team,
    split_name,
)
from .scrapers.wikipedia_teams import fetch_current_worldteams
from .kadenz import ist_faellig, naechster_lauf_in, takt_tage
from .taxonomy import achsen_kombinationen

logger = logging.getLogger(__name__)


class Budget:
    """Zeitbudget für einen Job-Lauf.

    Die beiden Rückstands-Jobs (Renn-Details, Fahrer-Details) arbeiten sich
    durch eine Warteschlange, die Stunden bis Tage umfasst. Vorher holten
    sie eine feste Zahl Einträge pro Lauf und warteten dann auf das nächste
    Intervall - mit dem Ergebnis, dass die Laufzeit vom Inhalt abhing
    (ein Etappenrennen kostet ein Vielfaches eines Eintagesrennens) und
    regelmäßig über dem Intervall lag. APScheduler hat die nächsten Läufe
    dann verworfen ("maximum number of running instances reached").

    Mit einem Budget ist es umgekehrt: der Job arbeitet, solange Zeit übrig
    ist, und hört rechtzeitig auf. Die Laufzeit wird damit vorhersagbar und
    bleibt unter dem Intervall, statt vom Zufall der Datenlage abzuhängen."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._end = time.monotonic() + seconds

    @property
    def remaining(self) -> float:
        return self._end - time.monotonic()

    @property
    def expired(self) -> bool:
        return self.remaining <= 0

    def __str__(self) -> str:
        return f"{self.seconds:.0f}s Budget"


def _timed(func, job_id: str):
    """Misst und loggt die Laufzeit jedes Job-Laufs. An einer Stelle statt in
    jedem Job, und die Grundlage dafür, die Intervalle an die tatsächlichen
    Laufzeiten anzupassen statt an Wunschwerte (siehe README,
    Abschnitt "Hintergrund-Jobs")."""

    def wrapper() -> None:
        start = time.monotonic()
        try:
            func()
        finally:
            logger.info("Job %s beendet nach %.1fs", job_id, time.monotonic() - start)

    wrapper.__name__ = job_id
    return wrapper


def _takt_erlaubt(job: str, force: bool) -> bool:
    """Ob der Job jetzt arbeiten darf - oder ob sein Takt noch läuft.

    `force` kommt von der Kommandozeile (python -m app.scheduler <job>):
    wer den Job von Hand aufruft, will ihn jetzt laufen sehen, nicht hören,
    dass er nicht fällig ist.

    Ist die Tabelle nicht lesbar, wird gearbeitet. Ein unlesbarer Merker
    darf nicht dazu führen, dass die Daten nie wieder aktualisiert werden -
    die Kosten einer unnötigen Aktualisierung sind kleiner als die eines
    Stillstands, den niemand bemerkt."""
    if force:
        return True
    try:
        letzter = db.letzter_joblauf(job)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "%s: Fälligkeit nicht prüfbar (%s) - wird ausgeführt", job, exc
        )
        return True
    if ist_faellig(job, letzter):
        return True
    rest = naechster_lauf_in(job, letzter)
    logger.info(
        "%s nicht fällig: Takt %d Tage, wieder in %d Tagen",
        job, takt_tage(job), rest.days,
    )
    return False


def refresh_teams(force: bool = False) -> None:
    """Die aktuellen WorldTeams von Wikipedia in die teams-Tabelle schreiben.

    Schrieb vorher in den JSON-Cache, und refresh_rosters kopierte den
    Inhalt anschließend zusätzlich in die Tabelle - dieselben Teams an zwei
    Orten, mit dem Cache als Zwischenstation ohne Zweck (siehe
    db.get_teams). Jetzt geht der Weg direkt in die Tabelle.

    Ein fehlgeschlagener Lauf verwirft keine Daten: der Upsert kommt gar
    nicht zustande, die vorhandenen Zeilen bleiben stehen. Das leistete
    vorher cache.mark_error, und die Tabelle tut es von sich aus.
    """
    if not db.is_configured():
        logger.info("Team-Refresh übersprungen: keine Datenbank konfiguriert (DATABASE_URL fehlt)")
        return
    if not _takt_erlaubt("refresh_teams", force):
        return
    try:
        teams = fetch_current_worldteams()
        db.upsert_teams(teams)
        db.joblauf_vermerken("refresh_teams")
        logger.info("Teams aktualisiert: %d Einträge", len(teams))
    except Exception as exc:  # noqa: BLE001 - Job darf niemals crashen
        logger.error("Team-Refresh fehlgeschlagen: %s", exc)




def refresh_rosters(force: bool = False) -> None:
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
    fehlt, siehe app/db.py) oder die teams-Tabelle noch leer ist. Die Teams
    schreibt refresh_teams; vorher las dieser Job sie aus dem JSON-Cache
    und schrieb sie selbst zusätzlich in die Tabelle.
    """
    if not db.is_configured():
        logger.info("Kader-Refresh übersprungen: keine Datenbank konfiguriert (DATABASE_URL fehlt)")
        return
    if not _takt_erlaubt("refresh_rosters", force):
        return

    try:
        team_rows = db.get_teams()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Kader-Refresh übersprungen: Team-Liste nicht lesbar: %s", exc)
        return
    if not team_rows:
        logger.info(
            "Kader-Refresh übersprungen: noch keine Teams in der Datenbank "
            "(refresh_teams läuft alle %ds und füllt sie)", REFRESH_INTERVAL_TEAMS
        )
        return

    teams = [Team(**row) for row in team_rows]

    # Erst alle Kader sammeln, dann EINMAL schreiben. Die Fehlerbehandlung
    # pro Team bleibt: ein Team, dessen Wikipedia-Seite sich geändert hat,
    # darf die übrigen nicht mitreißen.
    rider_rows: list[dict] = []
    seen_rider_ids: set[str] = set()
    duplicates = 0
    gelesen = 0
    for team in teams:
        try:
            roster = roster_riders_for_team(team)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Kader-Scraping für '%s' fehlgeschlagen: %s", team.name, exc)
            continue
        gelesen += 1
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
                # Die Scraper lesen ausschliesslich Maenner-Quellen
                # (WORLDTEAMS_PAGE, season_page_titles), deshalb fest 'm'.
                # Kommt der Frauen-Import, gibt der Aufrufer das Geschlecht
                # der Quelle mit - siehe backend/README.md, "Was der
                # Frauen-Import anzufassen hat".
                "gender": team.gender,
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
        "Kader aktualisiert: %d von %d Fahrern geändert, %d von %d Teams gelesen%s",
        written,
        len(rider_rows),
        gelesen,
        len(teams),
        f", {duplicates} Doppelnennungen übersprungen" if duplicates else "",
    )

    # Nur vermerken, wenn mindestens ein Kader gelesen werden konnte. Sonst
    # wäre ein Lauf, bei dem Wikipedia komplett ausfiel, für den ganzen Takt
    # als erledigt abgehakt - bei 30 Tagen Grundtakt ein Monat ohne Daten.
    # Teilausfälle (ein Team mit geändertem Seitenlayout) vermerken dagegen
    # schon: sie jedes Mal erneut zu versuchen wäre genau die Verschwendung,
    # die dieser Takt beseitigt, und die Warnung oben steht in jedem Lauf.
    if gelesen:
        db.joblauf_vermerken("refresh_rosters")
    else:
        logger.warning(
            "Kader-Refresh nicht vermerkt: kein einziges Team lesbar - "
            "der nächste Lauf versucht es erneut"
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

    budget = Budget(RIDER_DETAILS_RUN_SECONDS)
    fetched = 0
    # Ein fehlgeschlagener Abruf lässt history_fetched_at auf NULL stehen,
    # der Fahrer taucht also in der nächsten Batch-Abfrage DESSELBEN Laufs
    # wieder auf. Ohne diese Menge würde der Job sein Budget auf denselben
    # paar kaputten Seiten verbrennen, statt weiterzukommen. Beim nächsten
    # Lauf werden sie regulär erneut versucht.
    attempted: set[str] = set()
    stopped_early = False
    while not budget.expired:
        # Fenster um die bereits versuchten wachsen lassen - siehe
        # refresh_race_history, gleiche Begründung.
        batch = [
            r for r in db.get_riders_missing_history(
                limit=RIDER_HISTORY_BATCH_SIZE + len(attempted)
            )
            if r["id"] not in attempted
        ]
        if not batch:
            break
        for rider_row in batch:
            if budget.expired:
                stopped_early = True
                break
            attempted.add(rider_row["id"])
            try:
                wiki_title = wiki_title_from_url(rider_row["wiki_url"])
                history = fetch_rider_history(wiki_title)
                db.replace_stints(rider_row["id"], history.stints)
                fetched += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Historie-Scraping für '%s' fehlgeschlagen: %s", rider_row["name"], exc)
    if attempted:
        remaining = db.get_riders_missing_history_count()
        logger.info(
            "Fahrer-Historie geladen: %d/%d in diesem Lauf (%s), noch %d Fahrer ausstehend",
            fetched,
            len(attempted),
            "Budget aufgebraucht" if stopped_early else "nichts mehr zu versuchen",
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

    _namen_abgleichen()


def _namen_abgleichen() -> None:
    """Familiennamen über Wikidata prüfen (Befund 16).

    Die Heuristik `split_name` liegt bei spanischen und portugiesischen
    Doppelnachnamen falsch ("Juan Ayuso Pesquera" -> Nachname "Pesquera"
    statt "Ayuso Pesquera"). Wikidata führt die Namensteile als eigene
    P734-Aussagen; `nachname_aus_wikidata` übernimmt sie nur, wenn sie als
    Suffix des vollen Namens aufgehen (Begründung dort).

    Eigene Funktion, nicht in refresh_rider_details hineingeschrieben: der
    Abgleich hat seinen eigenen Rückstand, seine eigene Batchgröße und seine
    eigene Fehlerbehandlung. Er läuft im selben Job, weil er dieselbe
    Wikidata-Maschinerie benutzt und ebenfalls einmal pro Fahrer stattfindet.

    Ein Batch pro Lauf, ausserhalb des Zeitbudgets - genau wie der
    Strava-Abgleich darüber, und aus demselben Grund: drei Requests für bis
    zu 50 Fahrer fallen neben dem Budget von RIDER_DETAILS_RUN_SECONDS nicht
    ins Gewicht. Zwei solche Phasen hintereinander sind jetzt allerdings der
    Grund, das Verhältnis von Budget zu Intervall im Blick zu behalten
    (120 s Budget gegen 180 s Intervall).

    Berichtet, was herauskam - die Zahlen sind nur an echten Daten messbar,
    und Wikidata ist aus der Entwicklungsumgebung nicht erreichbar. Bleibt
    "korrigiert" dauerhaft bei 0, während "geprüft" hochläuft, stimmt die
    Annahme über die Antwortform nicht (siehe wikidata._claim_ziel)."""
    offen = db.get_riders_missing_name_source(NAME_BATCH_SIZE)
    if not offen:
        return

    titel = [wiki_title_from_url(r["wiki_url"]) for r in offen]
    try:
        qid_je_titel = fetch_wikidata_ids(titel)
        namen_je_qid = fetch_family_names(sorted(set(qid_je_titel.values())))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Familiennamen-Abgleich (Wikidata) fehlgeschlagen: %s", exc)
        return

    korrigiert = bestaetigt = ohne_treffer = qids_gesetzt = 0
    for zeile, t in zip(offen, titel):
        qid = qid_je_titel.get(t)
        if qid and db.set_rider_qid(zeile["id"], qid):
            qids_gesetzt += 1

        treffer = nachname_aus_wikidata(zeile["name"], namen_je_qid.get(qid, []) if qid else [])
        if treffer is None:
            # Nichts Passendes - die Heuristik bleibt stehen, und der Fahrer
            # wird nicht erneut gefragt.
            db.set_rider_name(zeile["id"], *split_name(zeile["name"]), "heuristik")
            ohne_treffer += 1
            continue
        vorname, nachname = treffer
        db.set_rider_name(zeile["id"], vorname, nachname, "wikidata")
        if treffer == split_name(zeile["name"]):
            bestaetigt += 1
        else:
            korrigiert += 1
            logger.info(
                "Namenstrennung korrigiert: %r -> Vorname %r / Nachname %r "
                "(Heuristik: %r / %r)",
                zeile["name"], vorname, nachname, *split_name(zeile["name"]),
            )

    logger.info(
        "Familiennamen-Abgleich: %d Fahrer geprüft, %d korrigiert, %d bestätigt, "
        "%d ohne Wikidata-Treffer, %d QIDs nachgetragen",
        len(offen), korrigiert, bestaetigt, ohne_treffer, qids_gesetzt,
    )


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

    budget = Budget(RACE_HISTORY_RUN_SECONDS)

    seeded_now = 0
    # Die (Kategorie, Circuit)-Paare stehen in app/taxonomy.py, nicht hier:
    # sie ergeben sich aus den Achsen selbst (siehe achsen_kombinationen).
    for category, circuit in achsen_kombinationen(RACE_HISTORY_CIRCUITS):
        for year in range(RACE_HISTORY_START_YEAR, RACE_SEASON_YEAR + 1):
            if budget.expired:
                break
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

    # Phase 2 arbeitet, solange Budget übrig ist, statt eine feste Zahl
    # Rennen zu holen und dann bis zum nächsten Intervall zu warten. Die
    # Batch-Größe ist damit nur noch das Abfrage-Fenster; wie lange der Lauf
    # dauert, bestimmt das Budget - und dadurch bleibt die Laufzeit unter
    # dem Intervall, egal ob gerade Eintages- oder Etappenrennen anstehen
    # (ein Etappenrennen kostet ein Vielfaches an Abrufen).
    fetched = 0
    # Wie bei den Fahrer-Details: ein fehlgeschlagenes Rennen behält
    # results_fetched_at NULL und käme sonst im selben Lauf endlos wieder.
    attempted: set[str] = set()
    stopped_early = False
    while not budget.expired:
        # Fenster um die bereits versuchten wachsen lassen: sonst liefert
        # die Abfrage immer wieder dieselben (gescheiterten) Einträge und
        # der Lauf käme nie an ihnen vorbei.
        batch = [
            r for r in db_races.get_races_missing_details(
                limit=RACE_HISTORY_DETAIL_BATCH_SIZE + len(attempted)
            )
            if r["id"] not in attempted
        ]
        if not batch:
            break
        for race_row in batch:
            if budget.expired:
                stopped_early = True
                break
            attempted.add(race_row["id"])
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
    if attempted:
        remaining = db_races.get_races_missing_details_count()
        logger.info(
            "Renn-Historie-Details geladen: %d/%d in diesem Lauf (%s), noch %d Rennen ausstehend",
            fetched,
            len(attempted),
            "Budget aufgebraucht" if stopped_early else "nichts mehr zu versuchen",
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


# (Funktion, Intervall in Sekunden, Job-ID, Executor-Pool).
# Alles, was Wikipedia abfragt, gehört in den "scrape"-Pool mit einem
# Worker - siehe start_scheduler().
JOBS = [
    (refresh_teams, REFRESH_INTERVAL_TEAMS, "refresh_teams", "scrape"),
    (refresh_rosters, REFRESH_INTERVAL_ROSTERS, "refresh_rosters", "scrape"),
    (refresh_rider_details, REFRESH_INTERVAL_RIDER_DETAILS, "refresh_rider_details", "scrape"),
    (refresh_race_history, REFRESH_INTERVAL_RACE_HISTORY, "refresh_race_history", "scrape"),
    (refresh_news, REFRESH_INTERVAL_NEWS, "refresh_news", "default"),
]


def start_scheduler() -> BackgroundScheduler:
    """Startet alle Jobs im Hintergrund.

    Zwei Executor-Pools statt des Standard-Pools mit zehn Threads:

    - "scrape" mit EINEM Worker für alle Jobs, die Wikipedia abfragen.
      Parallelität bringt dort nichts: `scrapers/http.py` lässt ohnehin nur
      einen Request alle SCRAPER_REQUEST_DELAY_SECONDS pro Host durch. Zwei
      gleichzeitige Wikipedia-Jobs haben sich deshalb nur gegenseitig
      ausgebremst - jeder lief doppelt so lange, beide überschritten ihr
      Intervall, und APScheduler verwarf die nächsten Läufe.
    - "default" für alles Übrige (aktuell nur der RSS-Newsfeed, der andere
      Hosts anspricht und nicht hinter den Wikipedia-Jobs warten soll).
    """
    scheduler = BackgroundScheduler(
        executors={
            "default": ThreadPoolExecutor(max_workers=2),
            "scrape": ThreadPoolExecutor(max_workers=1),
        }
    )
    # Startversatz, damit nicht alle Jobs gleichzeitig loslaufen und sich vor
    # dem einen "scrape"-Worker stauen.
    stagger = 0
    for func, interval_seconds, job_id, executor in JOBS:
        scheduler.add_job(
            _timed(func, job_id),
            "interval",
            seconds=interval_seconds,
            id=job_id,
            executor=executor,
            next_run_time=datetime.now() + timedelta(seconds=stagger),
            max_instances=1,
            coalesce=True,
            # Ein Job, der hinter einem anderen auf den einzigen
            # "scrape"-Worker wartet, startet später als geplant. APSchedulers
            # Default (misfire_grace_time=1s) verwirft ihn dann komplett -
            # der Rückstands-Abbau kam dadurch überhaupt nicht mehr zum Zug.
            # Eine Verspätung von bis zu einem vollen Intervall ist hier
            # unkritisch: besser spät als gar nicht.
            misfire_grace_time=interval_seconds,
        )
        stagger += JOB_START_STAGGER_SECONDS
    scheduler.start()
    logger.info("Scheduler gestartet mit %d Jobs", len(JOBS))
    return scheduler


def main(argv: list[str] | None = None) -> int:
    """Einen einzelnen Job einmal ausführen und beenden.

        python -m app.scheduler refresh_race_history

    Gedacht für einen Render Cron Job oder Background Worker: der
    Renn-Backfill braucht durchgängige Laufzeit, die eine kostenlose
    Web-Instanz nicht liefert (sie schläft nach 15 Minuten ohne Requests
    ein, siehe README). Greift bewusst auf dieselbe JOBS-Liste zu wie der
    Scheduler, damit es keine zweite Registrierung gibt, die auseinander
    laufen kann."""
    by_id = {job_id: func for func, _interval, job_id, _executor in JOBS}
    parser = argparse.ArgumentParser(
        prog="python -m app.scheduler",
        description="Einen einzelnen Hintergrund-Job einmal ausführen.",
    )
    parser.add_argument("job", choices=sorted(by_id), help="Name des Jobs")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # force=True, wo der Job es kennt: ein Aufruf von Hand soll arbeiten,
    # nicht melden, dass sein Takt noch läuft (siehe _takt_erlaubt).
    func = by_id[args.job]
    if "force" in inspect.signature(func).parameters:
        func = functools.partial(func, force=True)
    _timed(func, args.job)()
    return 0


if __name__ == "__main__":
    sys.exit(main())
