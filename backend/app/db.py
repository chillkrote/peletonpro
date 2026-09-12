"""Persistente Datenbank (Postgres) für Teams, Fahrer und deren Team-Historie.

Ergänzt (ersetzt nicht) den bestehenden JSON-Cache in app/cache.py: Teams,
Rennen, Ergebnisse und News bleiben im flüchtigen Cache, da sie ohnehin
binnen Sekunden neu gescraped werden können. Die Fahrer-Datenbank braucht
dagegen echte Persistenz über Neustarts hinweg, weil ein vollständiger
Rebuild aller Fahrer-Historien (ein Wikipedia-Abruf pro Fahrer, ca. 500
Fahrer, respektvoll ratenlimitiert) 15-20 Minuten dauert - das soll nicht
nach jedem Render-Neustart (Deploy, Aufwachen aus dem Schlafmodus) erneut
passieren.

DATABASE_URL muss als Umgebungsvariable gesetzt sein (Render Postgres
"Internal Database URL"). Ohne DATABASE_URL bleiben die Fahrer-Endpunkte
leer/deaktiviert, der Rest der App funktioniert unverändert weiter -
siehe is_configured().
"""
import logging
import os
from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg
from psycopg.rows import dict_row

from .models import Rider, RiderStint, Team

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,
    country TEXT,
    code TEXT,
    logo TEXT,
    wiki_url TEXT,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS riders (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT,
    birth_date DATE,
    wiki_url TEXT NOT NULL,
    current_team_id TEXT REFERENCES teams(id) ON DELETE SET NULL,
    history_fetched_at TIMESTAMPTZ,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rider_team_stints (
    id SERIAL PRIMARY KEY,
    rider_id TEXT NOT NULL REFERENCES riders(id) ON DELETE CASCADE,
    team_id TEXT REFERENCES teams(id) ON DELETE SET NULL,
    team_name TEXT NOT NULL,
    start_year INTEGER NOT NULL,
    end_year INTEGER,
    UNIQUE (rider_id, start_year, team_name)
);
CREATE INDEX IF NOT EXISTS idx_stints_rider ON rider_team_stints (rider_id);
CREATE INDEX IF NOT EXISTS idx_riders_current_team ON riders (current_team_id);
"""


def is_configured() -> bool:
    return bool(DATABASE_URL)


@contextmanager
def _connect() -> Iterator[psycopg.Connection]:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL ist nicht gesetzt - Fahrer-Datenbank nicht verfügbar.")
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        yield conn


def init_schema() -> None:
    if not DATABASE_URL:
        logger.warning("DATABASE_URL nicht gesetzt - Fahrer-Datenbank wird übersprungen.")
        return
    with _connect() as conn:
        conn.execute(SCHEMA)
    logger.info("Fahrer-Datenbank-Schema geprüft/erstellt.")


def upsert_team(team: Team) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO teams (id, name, category, country, code, logo, wiki_url, last_updated)
            VALUES (%(id)s, %(name)s, %(category)s, %(country)s, %(code)s, %(logo)s, %(wiki_url)s, now())
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                category = EXCLUDED.category,
                country = EXCLUDED.country,
                code = EXCLUDED.code,
                logo = EXCLUDED.logo,
                wiki_url = EXCLUDED.wiki_url,
                last_updated = now()
            """,
            {
                "id": team.id,
                "name": team.name,
                "category": team.category,
                "country": team.country,
                "code": team.code,
                "logo": team.logo,
                "wiki_url": team.source_url,
            },
        )


def upsert_rider(
    rider_id: str,
    name: str,
    country: Optional[str],
    birth_date: Optional[str],
    wiki_url: str,
    current_team_id: Optional[str],
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO riders (id, name, country, birth_date, wiki_url, current_team_id, last_updated)
            VALUES (%(id)s, %(name)s, %(country)s, %(birth_date)s, %(wiki_url)s, %(current_team_id)s, now())
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                country = COALESCE(EXCLUDED.country, riders.country),
                birth_date = COALESCE(EXCLUDED.birth_date, riders.birth_date),
                wiki_url = EXCLUDED.wiki_url,
                current_team_id = EXCLUDED.current_team_id,
                last_updated = now()
            """,
            {
                "id": rider_id,
                "name": name,
                "country": country,
                "birth_date": birth_date,
                "wiki_url": wiki_url,
                "current_team_id": current_team_id,
            },
        )


def get_riders_missing_history(limit: int) -> list[dict]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id, name, wiki_url FROM riders WHERE history_fetched_at IS NULL ORDER BY name LIMIT %s",
            (limit,),
        )
        return cur.fetchall()


def replace_stints(rider_id: str, stints: list[RiderStint]) -> None:
    """Ersetzt die komplette Historie eines Fahrers (löschen + neu einfügen) -
    einfacher als ein Diff, und die Historie ändert sich ohnehin nur selten
    (neuer Wechsel = neue Zeile, alte Zeilen bleiben unverändert)."""
    with _connect() as conn:
        conn.execute("DELETE FROM rider_team_stints WHERE rider_id = %s", (rider_id,))
        for stint in stints:
            team_id = None
            if stint.team_wiki_url:
                row = conn.execute(
                    "SELECT id FROM teams WHERE wiki_url = %s", (stint.team_wiki_url,)
                ).fetchone()
                team_id = row["id"] if row else None
            conn.execute(
                """
                INSERT INTO rider_team_stints (rider_id, team_id, team_name, start_year, end_year)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (rider_id, start_year, team_name) DO UPDATE SET
                    team_id = EXCLUDED.team_id,
                    end_year = EXCLUDED.end_year
                """,
                (rider_id, team_id, stint.team_name, stint.start_year, stint.end_year),
            )
        conn.execute(
            "UPDATE riders SET history_fetched_at = now() WHERE id = %s", (rider_id,)
        )


def get_riders(team_id: Optional[str] = None) -> list[Rider]:
    query = """
        SELECT r.id, r.name, r.country, r.birth_date, r.wiki_url,
               r.current_team_id, t.name AS current_team_name
        FROM riders r
        LEFT JOIN teams t ON t.id = r.current_team_id
    """
    params: tuple = ()
    if team_id:
        query += " WHERE r.current_team_id = %s"
        params = (team_id,)
    query += " ORDER BY r.name"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        Rider(
            id=row["id"],
            name=row["name"],
            country=row["country"],
            birth_date=row["birth_date"].isoformat() if row["birth_date"] else None,
            wiki_url=row["wiki_url"],
            current_team_id=row["current_team_id"],
            current_team_name=row["current_team_name"],
        )
        for row in rows
    ]


def get_rider(rider_id: str) -> Optional[Rider]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT r.id, r.name, r.country, r.birth_date, r.wiki_url,
                   r.current_team_id, t.name AS current_team_name
            FROM riders r
            LEFT JOIN teams t ON t.id = r.current_team_id
            WHERE r.id = %s
            """,
            (rider_id,),
        ).fetchone()
    if row is None:
        return None
    return Rider(
        id=row["id"],
        name=row["name"],
        country=row["country"],
        birth_date=row["birth_date"].isoformat() if row["birth_date"] else None,
        wiki_url=row["wiki_url"],
        current_team_id=row["current_team_id"],
        current_team_name=row["current_team_name"],
    )


def get_rider_stints(rider_id: str) -> list[RiderStint]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT team_name, start_year, end_year, t.wiki_url AS team_wiki_url
            FROM rider_team_stints s
            LEFT JOIN teams t ON t.id = s.team_id
            WHERE s.rider_id = %s
            ORDER BY start_year DESC
            """,
            (rider_id,),
        ).fetchall()
    return [
        RiderStint(
            team_name=row["team_name"],
            team_wiki_url=row["team_wiki_url"],
            start_year=row["start_year"],
            end_year=row["end_year"],
        )
        for row in rows
    ]


def get_rider_count() -> int:
    with _connect() as conn:
        row = conn.execute("SELECT count(*) AS n FROM riders").fetchone()
    return row["n"] if row else 0


def get_riders_missing_history_count() -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM riders WHERE history_fetched_at IS NULL"
        ).fetchone()
    return row["n"] if row else 0
