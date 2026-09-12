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

from .config import RACE_SEASON_YEAR
from .models import Rider, RiderSeason, RiderStint, Team

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

-- Nachträglich ergänzt (Vor-/Nachname-Trennung + Strava-Profil-Abgleich):
-- ALTER statt CREATE, da `riders` in Produktion bereits existiert.
ALTER TABLE riders ADD COLUMN IF NOT EXISTS first_name TEXT;
ALTER TABLE riders ADD COLUMN IF NOT EXISTS last_name TEXT;
ALTER TABLE riders ADD COLUMN IF NOT EXISTS strava_url TEXT;
ALTER TABLE riders ADD COLUMN IF NOT EXISTS strava_checked_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_riders_last_name ON riders (last_name, first_name);
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
    first_name: str,
    last_name: str,
    country: Optional[str],
    birth_date: Optional[str],
    wiki_url: str,
    current_team_id: Optional[str],
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO riders (id, name, first_name, last_name, country, birth_date, wiki_url, current_team_id, last_updated)
            VALUES (%(id)s, %(name)s, %(first_name)s, %(last_name)s, %(country)s, %(birth_date)s, %(wiki_url)s, %(current_team_id)s, now())
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                country = COALESCE(EXCLUDED.country, riders.country),
                birth_date = COALESCE(EXCLUDED.birth_date, riders.birth_date),
                wiki_url = EXCLUDED.wiki_url,
                current_team_id = EXCLUDED.current_team_id,
                last_updated = now()
            """,
            {
                "id": rider_id,
                "name": name,
                "first_name": first_name,
                "last_name": last_name,
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


def _row_to_rider(row: dict) -> Rider:
    return Rider(
        id=row["id"],
        first_name=row["first_name"] or "",
        last_name=row["last_name"] or row["name"],
        name=row["name"],
        country=row["country"],
        birth_date=row["birth_date"].isoformat() if row["birth_date"] else None,
        wiki_url=row["wiki_url"],
        current_team_id=row["current_team_id"],
        current_team_name=row["current_team_name"],
        strava_url=row["strava_url"],
    )


def get_riders(team_id: Optional[str] = None) -> list[Rider]:
    query = """
        SELECT r.id, r.name, r.first_name, r.last_name, r.country, r.birth_date,
               r.wiki_url, r.current_team_id, t.name AS current_team_name, r.strava_url
        FROM riders r
        LEFT JOIN teams t ON t.id = r.current_team_id
    """
    params: tuple = ()
    if team_id:
        query += " WHERE r.current_team_id = %s"
        params = (team_id,)
    # Standard-Sortierung nach Nachname (siehe README) - NULLS LAST betrifft
    # nur das kurze Zeitfenster direkt nach dem Schema-Update, bevor der
    # nächste refresh_riders-Lauf first_name/last_name für alle nachträgt.
    query += " ORDER BY r.last_name NULLS LAST, r.first_name NULLS LAST, r.name"
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_rider(row) for row in rows]


def get_rider(rider_id: str) -> Optional[Rider]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT r.id, r.name, r.first_name, r.last_name, r.country, r.birth_date,
                   r.wiki_url, r.current_team_id, t.name AS current_team_name, r.strava_url
            FROM riders r
            LEFT JOIN teams t ON t.id = r.current_team_id
            WHERE r.id = %s
            """,
            (rider_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_rider(row)


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


def get_riders_missing_strava(limit: int) -> list[dict]:
    """Fahrer, für die noch kein Wikidata-Strava-Abgleich versucht wurde
    (siehe scrapers/wikidata.py). Analog zu get_riders_missing_history:
    einmaliger Check pro Fahrer statt periodischer Neuprüfung, da ein neu
    angelegtes Strava-Profil kein Ereignis ist, auf das zeitnah reagiert
    werden müsste (siehe README, Abschnitt "Bekannte Lücken")."""
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id, wiki_url FROM riders WHERE strava_checked_at IS NULL ORDER BY name LIMIT %s",
            (limit,),
        )
        return cur.fetchall()


def set_strava_url(rider_id: str, strava_url: Optional[str]) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE riders SET strava_url = %s, strava_checked_at = now() WHERE id = %s",
            (strava_url, rider_id),
        )


def get_rider_seasons(rider_id: str) -> list[RiderSeason]:
    """Leitet Saison-für-Saison-Zuordnungen (Jahr -> Team) aus den
    gespeicherten Team-Stints ab. Nur Stints bei einem aktuell bekannten
    WorldTour-Team (team_id gesetzt, also in der teams-Tabelle vorhanden)
    zählen als "World Tour"-Saison - die Infobox-Historie eines Fahrers
    listet auch niedrigere Kategorien (Continental/ProConti) auf, die
    nicht Teil der World Tour sind und hier bewusst ausgeschlossen werden.
    Ein offener Zeitraum (end_year IS NULL, aktuelles Team) läuft bis zur
    laufenden Saison (RACE_SEASON_YEAR)."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT s.start_year, s.end_year, t.name AS team_name, t.wiki_url AS team_wiki_url
            FROM rider_team_stints s
            JOIN teams t ON t.id = s.team_id
            WHERE s.rider_id = %s
            ORDER BY s.start_year
            """,
            (rider_id,),
        ).fetchall()
    seasons: list[RiderSeason] = []
    for row in rows:
        end_year = row["end_year"] if row["end_year"] is not None else RACE_SEASON_YEAR
        for year in range(row["start_year"], end_year + 1):
            seasons.append(
                RiderSeason(year=year, team_name=row["team_name"], team_wiki_url=row["team_wiki_url"])
            )
    seasons.sort(key=lambda s: s.year, reverse=True)
    return seasons


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


# ---------------------------------------------------------------------------
# CSV-Export: liefert die Rohdaten je Tabelle (mit ein paar lesbaren
# Zusatzspalten aus Joins) für app/routers/export.py. Bewusst getrennt von
# den obigen Funktionen, die auf die API-Modelle (Rider/RiderStint) zugeschnitten
# sind - der Export soll die Datenbank 1:1 nachvollziehbar machen.
# ---------------------------------------------------------------------------


def export_teams() -> list[dict]:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT id, name, category, country, code, logo, wiki_url, last_updated
            FROM teams ORDER BY name
            """
        ).fetchall()


def export_riders() -> list[dict]:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT r.id, r.first_name, r.last_name, r.name, r.country, r.birth_date,
                   r.wiki_url, r.current_team_id, t.name AS current_team_name,
                   r.strava_url, r.history_fetched_at, r.last_updated
            FROM riders r
            LEFT JOIN teams t ON t.id = r.current_team_id
            ORDER BY r.last_name NULLS LAST, r.first_name NULLS LAST, r.name
            """
        ).fetchall()


def export_stints() -> list[dict]:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT s.rider_id, r.name AS rider_name, s.team_id, s.team_name,
                   t.wiki_url AS team_wiki_url, s.start_year, s.end_year
            FROM rider_team_stints s
            JOIN riders r ON r.id = s.rider_id
            LEFT JOIN teams t ON t.id = s.team_id
            ORDER BY r.last_name NULLS LAST, r.first_name NULLS LAST, s.start_year
            """
        ).fetchall()


def export_seasons() -> list[dict]:
    """Eine Zeile pro Fahrer und Saison (Jahr) bei einem WorldTour-Team -
    dieselbe Ableitung wie get_rider_seasons, aber für alle Fahrer auf
    einmal (für den CSV-Export). UCI-Ranking-Punkte fehlen bewusst, siehe
    README, Abschnitt "Bekannte Lücken"."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT s.rider_id, r.name AS rider_name, s.team_id, t.name AS team_name,
                   t.wiki_url AS team_wiki_url, s.start_year, s.end_year
            FROM rider_team_stints s
            JOIN riders r ON r.id = s.rider_id
            JOIN teams t ON t.id = s.team_id
            ORDER BY r.last_name NULLS LAST, r.first_name NULLS LAST, s.start_year
            """
        ).fetchall()
    seasons: list[dict] = []
    for row in rows:
        end_year = row["end_year"] if row["end_year"] is not None else RACE_SEASON_YEAR
        for year in range(row["start_year"], end_year + 1):
            seasons.append(
                {
                    "rider_id": row["rider_id"],
                    "rider_name": row["rider_name"],
                    "year": year,
                    "team_id": row["team_id"],
                    "team_name": row["team_name"],
                    "team_wiki_url": row["team_wiki_url"],
                }
            )
    return seasons
