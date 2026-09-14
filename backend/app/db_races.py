"""Persistente Datenbank aller UCI-WorldTour-, ProSeries- und Continental-
Tour-Rennen seit RACE_HISTORY_START_YEAR (Config), inkl. Etappen und
Ergebnislisten (mind. Top 10, sofern die Wikipedia-Quelle das hergibt).

Eigenständiges Modul (statt Erweiterung von app/db.py), weil es fachlich
komplett getrennt ist von der Fahrer/Team-Datenbank dort - teilt sich aber
dieselbe Postgres-Instanz und denselben Verbindungsaufbau (_connect aus
db.py wird hier wiederverwendet).

Architektur in zwei Phasen (siehe scheduler.refresh_race_history):
1. "Seeding": pro (category, circuit, season) wird EINMAL die Wikipedia-
   Saison-Übersichtsseite abgerufen und für jedes gefundene Rennen eine
   Skeleton-Zeile in `races` angelegt (Name, Zeitraum, Wiki-URL) - schnell,
   da nur eine Seite pro Kombination. race_history_seed_log merkt sich,
   welche Kombinationen schon versucht wurden (auch wenn 0 Rennen gefunden
   wurden - manche Jahr/Circuit-Kombinationen haben schlicht keine
   Wikipedia-Seite in einem der beiden versuchten Titel-Formate).
2. "Backfill": pro Rennen ohne `results_fetched_at` wird die EIGENE
   Wikipedia-Seite abgerufen (Distanz, Etappenzahl, Ergebnisliste, bei
   Mehretagenrennen zusätzlich pro Etappe) - das ist der teure Teil (ein
   Abruf pro Rennen, bei Etappenrennen mehrere), daher batchweise über
   viele Scheduler-Läufe verteilt, priorisiert nach Kategorie (World Tour
   zuerst) und Saison (neueste zuerst - eher vollständig dokumentiert).

`elevation_m` (Rennen wie Etappen) ist ein Platzhalter - siehe
backend/README.md, Abschnitt "Bekannte Lücke": auf Wikipedia für kein
Rennen strukturiert erfasst, bleibt NULL bis ein künftiger Import aus
einer anderen Quelle die Werte nachträgt (analog zu riders.uci_points).
"""
import logging
from typing import Optional

from .db import _connect, stream_query
from .models import RaceRecord, RaceResultEntry, RaceStage, RiderRaceResult
from .gender import GENDER_DEFAULT, gender_prefix
from .race_meta import is_grand_tour
from .taxonomy import pruefe_achsen
from .text import slugify

logger = logging.getLogger(__name__)



def race_id_for(
    season: int,
    category: str,
    name: str,
    circuit: Optional[str] = None,
    gender: str = GENDER_DEFAULT,
) -> str:
    """Eindeutige ID über Kategorien, Jahre und Geschlechter hinweg.

    Saison und Kategorie (bei Continental zusätzlich der Circuit) sind Teil
    der ID, damit gleichnamige Rennen in verschiedenen Jahren/Serien nicht
    kollidieren. Seit Befund 7 gilt dasselbe für das Geschlecht: die Ronde
    van Vlaanderen der Frauen und die der Männer sind zwei Rennen, hätten
    aber dieselbe ID bekommen - und das zweite hätte das erste per
    ON CONFLICT (id) DO UPDATE überschrieben.

    `gender="m"` erzeugt weiterhin EXAKT die bisherigen IDs; nur Frauen
    bekommen ein Präfix. Begründung in app/gender.py."""
    parts = [str(season), category]
    if circuit:
        parts.append(circuit)
    parts.append(slugify(name))
    return gender_prefix(gender) + "-".join(parts)


# ---------------------------------------------------------------------------
# Phase 1: Seeding (Saison-Übersichtsseiten -> Skeleton-Zeilen)
# ---------------------------------------------------------------------------


def is_season_seeded(category: str, season: int, circuit: Optional[str] = None) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM race_history_seed_log WHERE category = %s AND circuit = %s AND season = %s",
            (category, circuit or "", season),
        ).fetchone()
    return row is not None


def mark_season_seeded(category: str, season: int, race_count: int, circuit: Optional[str] = None) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO race_history_seed_log (category, circuit, season, race_count, seeded_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (category, circuit, season) DO UPDATE SET
                race_count = EXCLUDED.race_count,
                seeded_at = now()
            """,
            (category, circuit or "", season, race_count),
        )


def upsert_race_skeleton(
    *,
    season: int,
    category: str,
    name: str,
    start_date: Optional[str],
    end_date: Optional[str],
    wiki_url: Optional[str],
    circuit: Optional[str] = None,
    gender: str = GENDER_DEFAULT,
) -> str:
    """Legt eine Rennen-Grundzeile an bzw. aktualisiert Name/Zeitraum, falls
    sie schon existiert - rührt `results_fetched_at`/Details NICHT an (siehe
    replace_race_details für die teure zweite Phase).

    `gender` geht in die ID ein und in die Spalte: ohne das hätte ein
    Frauen-Rennen das gleichnamige Männer-Rennen per ON CONFLICT (id)
    überschrieben (Befund 7)."""
    # Vor dem Bilden der ID, nicht danach: Kategorie und Circuit gehen in
    # den Primärschlüssel ein, und eine ID aus einer unmöglichen
    # Kombination (etwa category='wt' MIT circuit) würde von keinem
    # zweiten Lauf reproduziert - der nächste Lauf legte eine zweite Zeile
    # an statt die erste zu aktualisieren.
    pruefe_achsen(category, circuit)
    race_id = race_id_for(season, category, name, circuit, gender)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO races (id, name, season, category, circuit, gender, start_date, end_date, wiki_url, last_updated)
            VALUES (%(id)s, %(name)s, %(season)s, %(category)s, %(circuit)s, %(gender)s, %(start_date)s, %(end_date)s, %(wiki_url)s, now())
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                wiki_url = EXCLUDED.wiki_url,
                last_updated = now()
            """,
            {
                "id": race_id,
                "name": name,
                "season": season,
                "category": category,
                "circuit": circuit,
                "gender": gender,
                "start_date": start_date,
                "end_date": end_date,
                "wiki_url": wiki_url,
            },
        )
    return race_id


# ---------------------------------------------------------------------------
# Phase 2: Backfill (Distanz/Etappen/Ergebnisse pro Rennen)
# ---------------------------------------------------------------------------


def get_races_missing_details(limit: int) -> list[dict]:
    """Rennen ohne Detail-Backfill, priorisiert nach Kategorie (World Tour
    zuerst, dann ProSeries, dann Continental) und Saison (neueste zuerst -
    eher vollständig dokumentiert als sehr alte Rennen)."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, season, category, circuit, wiki_url
            FROM races
            WHERE results_fetched_at IS NULL AND wiki_url IS NOT NULL
            ORDER BY
                CASE category WHEN 'wt' THEN 0 WHEN 'proseries' THEN 1 ELSE 2 END,
                season DESC,
                name
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return rows


def replace_race_details(
    race_id: str,
    *,
    num_stages: Optional[int],
    distance_km: Optional[float],
    organizer_website: Optional[str] = None,
    results: list[RaceResultEntry],
    stages: list[RaceStage],
) -> None:
    """Ersetzt Distanz/Etappenzahl/Veranstalter-Website sowie die komplette
    Ergebnis-/Etappenstruktur eines Rennens (löschen + neu einfügen, analog
    zu db.replace_stints) und setzt results_fetched_at."""
    with _connect() as conn:
        conn.execute(
            """
            UPDATE races SET num_stages = %s, distance_km = %s, organizer_website = %s,
                results_fetched_at = now(), last_updated = now()
            WHERE id = %s
            """,
            (num_stages, distance_km, organizer_website, race_id),
        )
        # Etappen (löscht via ON DELETE CASCADE auch die zugehörigen
        # race_results-Zeilen mit stage_id auf eine alte Etappe).
        conn.execute("DELETE FROM race_stages WHERE race_id = %s", (race_id,))
        # Gesamt-/Eintagesrennen-Ergebnis (stage_id IS NULL) separat löschen -
        # die obige DELETE trifft nur Zeilen MIT stage_id.
        conn.execute("DELETE FROM race_results WHERE race_id = %s AND stage_id IS NULL", (race_id,))

        for result in results:
            conn.execute(
                """
                INSERT INTO race_results (race_id, stage_id, position, rider_name, team_name, time_or_gap)
                VALUES (%s, NULL, %s, %s, %s, %s)
                """,
                (race_id, result.position, result.rider, result.team, result.time_or_gap),
            )

        for stage in stages:
            row = conn.execute(
                """
                INSERT INTO race_stages (race_id, stage_number, stage_date, distance_km, start_location, end_location)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (race_id, stage.stage_number, stage.date, stage.distance_km, stage.start_location, stage.end_location),
            ).fetchone()
            stage_id = row["id"]
            for result in stage.results:
                conn.execute(
                    """
                    INSERT INTO race_results (race_id, stage_id, position, rider_name, team_name, time_or_gap)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (race_id, stage_id, result.position, result.rider, result.team, result.time_or_gap),
                )

        # rider_id/team_id nachtragen - über DIESELBE Datenbankfunktion, die
        # Migration 0004 für den Bestand benutzt (siehe dort für die vier
        # Zuordnungsschritte und warum nichts geraten wird). Stünde die Regel
        # hier ein zweites Mal als Python, liefe sie mit der Migration
        # auseinander, sobald eine der beiden nachgeschärft wird.
        #
        # Der Aufruf ist auf dieses Rennen begrenzt und läuft in derselben
        # Transaktion wie die Ergebniszeilen: entweder stehen Ergebnisse mit
        # Zuordnung da, oder keine.
        #
        # Nebenwirkung, die erwünscht ist: wird ein Rennen erneut gescrapt,
        # bekommen Zeilen eine ID, die beim ersten Mal keine bekamen - etwa
        # weil der Fahrer damals noch nicht in `riders` stand.
        zuordnung = conn.execute(
            "SELECT schritt_a, schritt_b, schritt_c, schritt_d "
            "FROM race_results_ids_nachtragen(%s)",
            (race_id,),
        ).fetchone()
    if zuordnung and any(zuordnung.values()):
        logger.debug(
            "Zuordnung %s: rider_id %d, team_id %d (Teamname %d, Station %d, Altname %d)",
            race_id, zuordnung["schritt_a"],
            zuordnung["schritt_b"] + zuordnung["schritt_c"] + zuordnung["schritt_d"],
            zuordnung["schritt_b"], zuordnung["schritt_c"], zuordnung["schritt_d"],
        )


# ---------------------------------------------------------------------------
# Lesezugriff (API)
# ---------------------------------------------------------------------------


def _race_filter(
    season: Optional[int],
    category: Optional[str],
    circuit: Optional[str],
    gender: str = GENDER_DEFAULT,
) -> tuple[str, list]:
    """Baut die WHERE-Klausel für Liste und Zählung. Eine Stelle statt zwei:
    sonst driften Filter und Gesamtzahl auseinander, sobald eine neue Achse
    dazukommt - genau das ist mit `gender` jetzt passiert, und dank dieser
    Funktion an einer Stelle.

    `gender` hat einen Default, ist aber nicht optional gedacht: ohne den
    Filter mischt der Kalender Männer- und Frauen-Rennen."""
    clause = " AND gender = %s"
    params: list = [gender]
    if season is not None:
        clause += " AND season = %s"
        params.append(season)
    if category:
        clause += " AND category = %s"
        params.append(category)
    if circuit:
        clause += " AND circuit = %s"
        params.append(circuit)
    return clause, params


def get_races(
    season: Optional[int] = None,
    category: Optional[str] = None,
    circuit: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    gender: str = GENDER_DEFAULT,
) -> list[RaceRecord]:
    """Leichtgewichtige Liste (ohne results/stages) - für die Detailansicht
    siehe get_race()."""
    clause, params = _race_filter(season, category, circuit, gender)
    query = f"""
        SELECT id, name, season, category, circuit, start_date, end_date,
               num_stages, distance_km, elevation_m, wiki_url, organizer_website,
               results_fetched_at, gender
        FROM races
        WHERE 1=1{clause}
        ORDER BY start_date NULLS LAST, name LIMIT %s OFFSET %s
    """
    with _connect() as conn:
        rows = conn.execute(query, [*params, limit, offset]).fetchall()
    return [_row_to_race(row) for row in rows]


def count_races(
    season: Optional[int] = None,
    category: Optional[str] = None,
    circuit: Optional[str] = None,
    gender: str = GENDER_DEFAULT,
) -> int:
    """Gesamtzahl für dieselben Filter wie get_races - damit das Frontend
    paginieren kann, ohne alles laden zu müssen."""
    clause, params = _race_filter(season, category, circuit, gender)
    with _connect() as conn:
        row = conn.execute(
            f"SELECT count(*) AS n FROM races WHERE 1=1{clause}", params
        ).fetchone()
    return row["n"] if row else 0


def get_seasons(gender: str = GENDER_DEFAULT) -> list[int]:
    """Alle Saisons, für die Rennen vorliegen - absteigend. Leichter Endpunkt
    für die Saison-Tabs im Frontend, das sie sonst aus der kompletten
    Renn-Liste ableiten müsste (und die dafür komplett laden).

    Nach gender gefiltert: die Frauen-WorldTour hat andere Saisons im
    Bestand als die der Männer, und Tabs für Jahre ohne Rennen wären eine
    Einladung in eine leere Liste."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT season FROM races WHERE gender = %s ORDER BY season DESC",
            (gender,),
        ).fetchall()
    return [r["season"] for r in rows]


def _row_to_race(row: dict) -> RaceRecord:
    return RaceRecord(
        id=row["id"],
        name=row["name"],
        season=row["season"],
        category=row["category"],
        circuit=row["circuit"],
        start_date=row["start_date"].isoformat() if row["start_date"] else None,
        end_date=row["end_date"].isoformat() if row["end_date"] else None,
        num_stages=row["num_stages"],
        distance_km=float(row["distance_km"]) if row["distance_km"] is not None else None,
        elevation_m=row["elevation_m"],
        wiki_url=row["wiki_url"],
        is_grand_tour=is_grand_tour(row["name"]),
        organizer_website=row.get("organizer_website"),
        gender=row.get("gender", GENDER_DEFAULT),
        results_fetched_at=row["results_fetched_at"].isoformat() if row.get("results_fetched_at") else None,
    )


def get_race(race_id: str) -> Optional[RaceRecord]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, name, season, category, circuit, start_date, end_date,
                   num_stages, distance_km, elevation_m, wiki_url, organizer_website,
                   results_fetched_at, gender
            FROM races WHERE id = %s
            """,
            (race_id,),
        ).fetchone()
        if row is None:
            return None
        race = _row_to_race(row)

        result_rows = conn.execute(
            """
            SELECT position, rider_name, team_name, time_or_gap
            FROM race_results WHERE race_id = %s AND stage_id IS NULL
            ORDER BY position
            """,
            (race_id,),
        ).fetchall()
        race.results = [
            RaceResultEntry(position=r["position"], rider=r["rider_name"], team=r["team_name"], time_or_gap=r["time_or_gap"])
            for r in result_rows
        ]

        stage_rows = conn.execute(
            """
            SELECT id, stage_number, stage_date, distance_km, elevation_m, start_location, end_location
            FROM race_stages WHERE race_id = %s ORDER BY stage_number
            """,
            (race_id,),
        ).fetchall()
        # Etappen-Ergebnisse für ALLE Etappen in einer Abfrage holen und in
        # Python nach stage_id gruppieren. Vorher eine Abfrage pro Etappe
        # (N+1): eine Grande-Boucle-Detailseite kostete damit 23 Abfragen
        # statt 3.
        stage_ids = [srow["id"] for srow in stage_rows]
        results_by_stage: dict[int, list[RaceResultEntry]] = {}
        if stage_ids:
            result_rows_all = conn.execute(
                """
                SELECT stage_id, position, rider_name, team_name, time_or_gap
                FROM race_results WHERE stage_id = ANY(%s) ORDER BY stage_id, position
                """,
                (stage_ids,),
            ).fetchall()
            for r in result_rows_all:
                results_by_stage.setdefault(r["stage_id"], []).append(
                    RaceResultEntry(
                        position=r["position"],
                        rider=r["rider_name"],
                        team=r["team_name"],
                        time_or_gap=r["time_or_gap"],
                    )
                )

        race.stages = [
            RaceStage(
                stage_number=srow["stage_number"],
                date=srow["stage_date"].isoformat() if srow["stage_date"] else None,
                distance_km=float(srow["distance_km"]) if srow["distance_km"] is not None else None,
                elevation_m=srow["elevation_m"],
                start_location=srow["start_location"],
                end_location=srow["end_location"],
                results=results_by_stage.get(srow["id"], []),
            )
            for srow in stage_rows
        ]
    return race


def get_race_count(category: Optional[str] = None) -> int:
    query = "SELECT count(*) AS n FROM races"
    params: tuple = ()
    if category:
        query += " WHERE category = %s"
        params = (category,)
    with _connect() as conn:
        row = conn.execute(query, params).fetchone()
    return row["n"] if row else 0


def get_races_missing_details_count() -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM races WHERE results_fetched_at IS NULL AND wiki_url IS NOT NULL"
        ).fetchone()
    return row["n"] if row else 0


# ---------------------------------------------------------------------------
# Team-Statistik pro Saison
# ---------------------------------------------------------------------------
#
# ZUORDNUNG: race_results speichert nur den Team-NAMEN als Freitext, keinen
# Fremdschlüssel auf teams. Der Vergleich läuft daher über den Anzeigenamen.
# Beide Seiten stammen aus demselben Parser (dem Link-Text einer
# Wikipedia-Tabelle), die Schreibweisen können aber abweichen - die
# WorldTeams-Übersicht nennt ein Team womöglich "UAE Team Emirates XRG",
# eine Ergebnis-Tabelle "UAE Team Emirates". Wie hoch die Trefferquote in
# Produktion ist, ließ sich hier nicht messen (kein Zugriff auf die
# Produktionsdatenbank und die deployte API).
#
# Der saubere Weg ist ein team_id in race_results - das ist ein eigener
# Befund (siehe README, "Bekannte Lücken"). Danach ändert sich hier nur die
# WHERE-Bedingung, nicht die Struktur: die Aggregation per GROUP BY bleibt.
#
# ZÄHLWEISE: gezählt werden PLATZIERUNGEN, nicht Rennen. Die frühere
# Berechnung im Browser nutzte findIndex und fand damit nur den besten
# Fahrer eines Teams pro Rennen - "Top-10-Platzierungen" zählte also Rennen
# mit mindestens einer Top-10-Platzierung, und zwei Podestplätze desselben
# Teams im selben Rennen ergaben einen.


# Ein Team wird in seinen Ergebniszeilen auf zwei Wegen erkannt:
#
#   res.team_id = %(team_id)s        die Zuordnung aus Migration 0004
#   res.team_id IS NULL AND res.team_name = %(team_name)s
#
# Der zweite Weg ist der alte Vergleich und bleibt als Rückfall für Zeilen,
# die sich nicht zuordnen liessen. Die beiden Bedingungen können sich nicht
# überlappen (die eine verlangt eine gesetzte team_id, die andere keine),
# es wird also nichts doppelt gezählt.
#
# Vorher stand hier NUR der Namensvergleich, und das war Befund 18: ein
# umbenanntes Team - "Jumbo-Visma" wurde "Team Visma-Lease a Bike" - verlor
# damit seine ganze Historie, ohne dass ein Fehler auftauchte. Die Seite
# zeigte einfach null Siege für die Jahre davor.
_TEAM_TREFFER = """(
        res.team_id = %(team_id)s
        OR (res.team_id IS NULL AND res.team_name = %(team_name)s)
    )"""


def get_rider_results(rider_id: str, limit: int, offset: int) -> list[RiderRaceResult]:
    """Die Platzierungen eines Fahrers, neueste Saison zuerst.

    Geht über `race_results.rider_id` (Migration 0004), nicht über den Namen.
    Ein Namensvergleich hätte hier dieselbe stille Lücke wie bei der
    Team-Statistik: eine abweichende Schreibweise in der Ergebnistabelle
    (Akzente, Initialen) ergäbe eine leere Liste, die wie "keine Ergebnisse"
    aussieht statt wie "nicht gefunden".

    Enthalten sind Gesamtwertungen UND Etappenergebnisse; unterscheidbar an
    `stage_number` (NULL = Gesamtwertung oder Eintagesrennen). Der Teamname
    kommt aus der Ergebniszeile, ist also der damalige - nur `team_id` zeigt
    auf das Team von heute.

    Sortiert nach Saison und Startdatum absteigend, innerhalb eines Rennens
    die Gesamtwertung vor den Etappen."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT r.id AS race_id, r.name AS race_name, r.season, r.category,
                   r.circuit, r.start_date, s.stage_number, res.position,
                   res.team_name, res.team_id, res.time_or_gap
            FROM race_results res
            JOIN races r ON r.id = res.race_id
            LEFT JOIN race_stages s ON s.id = res.stage_id
            WHERE res.rider_id = %s
            ORDER BY r.season DESC, r.start_date DESC NULLS LAST, r.id,
                     s.stage_number NULLS FIRST
            LIMIT %s OFFSET %s
            """,
            (rider_id, limit, offset),
        ).fetchall()
    return [
        RiderRaceResult(
            race_id=row["race_id"],
            race_name=row["race_name"],
            season=row["season"],
            category=row["category"],
            circuit=row["circuit"],
            is_grand_tour=is_grand_tour(row["race_name"]),
            start_date=row["start_date"].isoformat() if row["start_date"] else None,
            stage_number=row["stage_number"],
            position=row["position"],
            team_name=row["team_name"],
            team_id=row["team_id"],
            time_or_gap=row["time_or_gap"],
        )
        for row in rows
    ]


def count_rider_results(rider_id: str) -> int:
    """Gesamtzahl für die Paginierung - ohne sie weiss das Frontend nicht,
    ob eine Seite die letzte ist (dieselbe Begründung wie bei
    count_riders)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM race_results WHERE rider_id = %s",
            (rider_id,),
        ).fetchone()
    return row["n"] if row else 0


def get_team_season_stats(team_id: str, team_name: str, season: int) -> dict:
    """Siege, Podestplätze und Top-10-Platzierungen eines Teams in einer
    Saison, gezählt über alle Ergebniszeilen (Gesamtwertungen UND Etappen).

    `races` nennt zusätzlich die Zahl der Rennen, in denen das Team
    überhaupt platziert war - das ist die Zahl, die die frühere
    Browser-Berechnung faelschlich als "Top-10-Platzierungen" auswies.

    Braucht beides: `team_id` für die zugeordneten Zeilen, `team_name` für
    den Rückfall (siehe _TEAM_TREFFER)."""
    with _connect() as conn:
        row = conn.execute(
            f"""
            SELECT
                count(*) FILTER (WHERE res.position = 1)  AS wins,
                count(*) FILTER (WHERE res.position <= 3) AS podiums,
                count(*) FILTER (WHERE res.position <= 10) AS top_ten,
                count(DISTINCT res.race_id)               AS races
            FROM race_results res
            JOIN races r ON r.id = res.race_id
            WHERE r.season = %(season)s AND {_TEAM_TREFFER}
            """,
            {"season": season, "team_id": team_id, "team_name": team_name},
        ).fetchone()
    return dict(row) if row else {"wins": 0, "podiums": 0, "top_ten": 0, "races": 0}


def get_team_season_wins(team_id: str, team_name: str, season: int, limit: int = 50) -> list[dict]:
    """Die Siege eines Teams in einer Saison, für die Liste unter den
    Kennzahlen. Etappensiege sind enthalten und über `stage_number`
    unterscheidbar - bei einem Etappenrennen ist das der Unterschied
    zwischen einem Etappensieg und dem Gesamtsieg (stage_number IS NULL)."""
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT r.id AS race_id, r.name AS race_name, r.start_date,
                   s.stage_number, res.rider_name
            FROM race_results res
            JOIN races r ON r.id = res.race_id
            LEFT JOIN race_stages s ON s.id = res.stage_id
            WHERE r.season = %(season)s AND res.position = 1 AND {_TEAM_TREFFER}
            ORDER BY r.start_date DESC NULLS LAST, s.stage_number NULLS FIRST
            LIMIT %(limit)s
            """,
            {"season": season, "team_id": team_id, "team_name": team_name,
             "limit": limit},
        ).fetchall()
    return [
        {
            "race_id": r["race_id"],
            "race_name": r["race_name"],
            "start_date": r["start_date"].isoformat() if r["start_date"] else None,
            "stage_number": r["stage_number"],
            "rider": r["rider_name"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# CSV-Export (siehe app/routers/race_history.py)
# ---------------------------------------------------------------------------


def export_races():
    return stream_query(
        """
        SELECT id, name, season, category, circuit, gender, start_date, end_date,
               num_stages, distance_km, elevation_m, wiki_url, organizer_website,
               results_fetched_at, last_updated
        FROM races
        ORDER BY gender, season, category, circuit NULLS FIRST, name
        """
    )


def export_race_results():
    """Die mit Abstand größte Export-Tabelle: jede Platzierung über alle
    Rennen und Etappen. Streamt über einen server-side Cursor (siehe
    db.stream_query) - mit fetchall() lag das komplette Ergebnis im Speicher
    der 512-MB-Instanz."""
    return stream_query(
        """
        SELECT r.id AS race_id, r.name AS race_name, r.season, r.category,
               s.stage_number, res.position, res.rider_name, res.rider_id,
               res.team_name, res.team_id, res.time_or_gap
        FROM race_results res
        JOIN races r ON r.id = res.race_id
        LEFT JOIN race_stages s ON s.id = res.stage_id
        ORDER BY r.season, r.category, r.name, s.stage_number NULLS FIRST, res.position
        """
    )


def export_race_stages():
    return stream_query(
        """
        SELECT r.id AS race_id, r.name AS race_name, r.season, r.category,
               s.stage_number, s.stage_date, s.distance_km, s.elevation_m,
               s.start_location, s.end_location
        FROM race_stages s
        JOIN races r ON r.id = s.race_id
        ORDER BY r.season, r.category, r.name, s.stage_number
        """
    )
