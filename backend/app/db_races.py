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
import re
from typing import Optional

from .db import _connect
from .models import RaceRecord, RaceResultEntry, RaceStage

logger = logging.getLogger(__name__)

SCHEMA_RACES = """
CREATE TABLE IF NOT EXISTS races (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    season INTEGER NOT NULL,
    category TEXT NOT NULL,
    circuit TEXT,
    start_date DATE,
    end_date DATE,
    num_stages INTEGER,
    distance_km NUMERIC,
    elevation_m INTEGER,
    wiki_url TEXT,
    organizer_website TEXT,
    results_fetched_at TIMESTAMPTZ,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_races_season_category ON races (season, category);
CREATE INDEX IF NOT EXISTS idx_races_missing_details ON races (results_fetched_at) WHERE results_fetched_at IS NULL;

CREATE TABLE IF NOT EXISTS race_stages (
    id SERIAL PRIMARY KEY,
    race_id TEXT NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    stage_number INTEGER NOT NULL,
    stage_date DATE,
    distance_km NUMERIC,
    elevation_m INTEGER,
    start_location TEXT,
    end_location TEXT,
    UNIQUE (race_id, stage_number)
);

CREATE TABLE IF NOT EXISTS race_results (
    id SERIAL PRIMARY KEY,
    race_id TEXT NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    stage_id INTEGER REFERENCES race_stages(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    rider_name TEXT NOT NULL,
    team_name TEXT,
    time_or_gap TEXT
);
CREATE INDEX IF NOT EXISTS idx_results_race ON race_results (race_id);
CREATE INDEX IF NOT EXISTS idx_results_stage ON race_results (stage_id);

-- circuit ist Teil des Primärschlüssels, daher '' statt NULL für wt/proseries
-- (PKs duerfen kein NULL enthalten).
CREATE TABLE IF NOT EXISTS race_history_seed_log (
    category TEXT NOT NULL,
    circuit TEXT NOT NULL DEFAULT '',
    season INTEGER NOT NULL,
    race_count INTEGER NOT NULL DEFAULT 0,
    seeded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (category, circuit, season)
);
"""


def init_schema() -> None:
    from .db import DATABASE_URL  # gleiche Verfügbarkeitsprüfung wie db.init_schema

    if not DATABASE_URL:
        logger.warning("DATABASE_URL nicht gesetzt - Renn-Historie wird übersprungen.")
        return
    with _connect() as conn:
        conn.execute(SCHEMA_RACES)
    logger.info("Renn-Historie-Schema geprüft/erstellt.")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "unknown"


def race_id_for(season: int, category: str, name: str, circuit: Optional[str] = None) -> str:
    """Eindeutige ID über alle Kategorien/Jahre hinweg - Saison und Kategorie
    (bei Continental zusätzlich der Circuit) sind Teil der ID, damit
    gleichnamige Rennen in verschiedenen Jahren/Serien nicht kollidieren."""
    parts = [str(season), category]
    if circuit:
        parts.append(circuit)
    parts.append(_slugify(name))
    return "-".join(parts)


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
) -> str:
    """Legt eine Rennen-Grundzeile an bzw. aktualisiert Name/Zeitraum, falls
    sie schon existiert - rührt `results_fetched_at`/Details NICHT an (siehe
    replace_race_details für die teure zweite Phase)."""
    race_id = race_id_for(season, category, name, circuit)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO races (id, name, season, category, circuit, start_date, end_date, wiki_url, last_updated)
            VALUES (%(id)s, %(name)s, %(season)s, %(category)s, %(circuit)s, %(start_date)s, %(end_date)s, %(wiki_url)s, now())
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


# ---------------------------------------------------------------------------
# Lesezugriff (API)
# ---------------------------------------------------------------------------


def get_races(
    season: Optional[int] = None,
    category: Optional[str] = None,
    circuit: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
) -> list[RaceRecord]:
    """Leichtgewichtige Liste (ohne results/stages) - für die Detailansicht
    siehe get_race()."""
    query = """
        SELECT id, name, season, category, circuit, start_date, end_date,
               num_stages, distance_km, elevation_m, wiki_url, organizer_website, results_fetched_at
        FROM races
        WHERE 1=1
    """
    params: list = []
    if season is not None:
        query += " AND season = %s"
        params.append(season)
    if category:
        query += " AND category = %s"
        params.append(category)
    if circuit:
        query += " AND circuit = %s"
        params.append(circuit)
    query += " ORDER BY start_date NULLS LAST, name LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_race(row) for row in rows]


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
        organizer_website=row.get("organizer_website"),
        results_fetched_at=row["results_fetched_at"].isoformat() if row.get("results_fetched_at") else None,
    )


def get_race(race_id: str) -> Optional[RaceRecord]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, name, season, category, circuit, start_date, end_date,
                   num_stages, distance_km, elevation_m, wiki_url, organizer_website, results_fetched_at
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
# CSV-Export (siehe app/routers/race_history.py)
# ---------------------------------------------------------------------------


def export_races() -> list[dict]:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT id, name, season, category, circuit, start_date, end_date,
                   num_stages, distance_km, elevation_m, wiki_url, organizer_website,
                   results_fetched_at, last_updated
            FROM races
            ORDER BY season, category, circuit NULLS FIRST, name
            """
        ).fetchall()


def export_race_results() -> list[dict]:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT r.id AS race_id, r.name AS race_name, r.season, r.category,
                   s.stage_number, res.position, res.rider_name, res.team_name, res.time_or_gap
            FROM race_results res
            JOIN races r ON r.id = res.race_id
            LEFT JOIN race_stages s ON s.id = res.stage_id
            ORDER BY r.season, r.category, r.name, s.stage_number NULLS FIRST, res.position
            """
        ).fetchall()


def export_race_stages() -> list[dict]:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT r.id AS race_id, r.name AS race_name, r.season, r.category,
                   s.stage_number, s.stage_date, s.distance_km, s.elevation_m,
                   s.start_location, s.end_location
            FROM race_stages s
            JOIN races r ON r.id = s.race_id
            ORDER BY r.season, r.category, r.name, s.stage_number
            """
        ).fetchall()
