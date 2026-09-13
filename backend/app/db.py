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
import threading
from contextlib import contextmanager
from typing import Iterator, Optional, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import RACE_SEASON_YEAR
from .models import Rider, RiderSeason, RiderStint, Team

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

# Verbindungs-Pool statt einer neuen Verbindung pro Funktionsaufruf. Vorher
# öffnete jeder Aufruf von _connect() eine frische Postgres-Verbindung; ein
# einzelner Kader-Lauf (18 Teams + ~517 Fahrer) kam so auf über 500
# Verbindungsaufbauten, jeweils mit TCP- und TLS-Handshake zu Renders
# Postgres. Der kostenlose Plan erlaubt nur wenige gleichzeitige
# Verbindungen - das war die harte Grenze vor jeder Vergrößerung des
# Bestands.
#
# Bewusst klein dimensioniert: die Anwendung hat einen Web-Prozess und
# einen Scheduler mit wenigen Threads, mehr Verbindungen bringen nichts und
# verbrauchen auf dem Free-Plan nur das knappe Kontingent.
DB_POOL_MIN_SIZE = int(os.environ.get("DB_POOL_MIN_SIZE", "1"))
DB_POOL_MAX_SIZE = int(os.environ.get("DB_POOL_MAX_SIZE", "5"))
DB_POOL_TIMEOUT_SECONDS = float(os.environ.get("DB_POOL_TIMEOUT_SECONDS", "30"))

_pool: Optional[ConnectionPool] = None
_pool_lock = threading.Lock()


def _get_pool() -> ConnectionPool:
    """Erzeugt den Pool beim ersten Zugriff (nicht beim Import), damit das
    Modul auch ohne DATABASE_URL importierbar bleibt - die App soll ohne
    Datenbank weiterlaufen, siehe is_configured()."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            if not DATABASE_URL:
                raise RuntimeError(
                    "DATABASE_URL ist nicht gesetzt - Fahrer-Datenbank nicht verfügbar."
                )
            _pool = ConnectionPool(
                DATABASE_URL,
                min_size=DB_POOL_MIN_SIZE,
                max_size=DB_POOL_MAX_SIZE,
                timeout=DB_POOL_TIMEOUT_SECONDS,
                kwargs={"row_factory": dict_row},
                open=True,
            )
            logger.info(
                "Postgres-Pool geöffnet (min %d, max %d)", DB_POOL_MIN_SIZE, DB_POOL_MAX_SIZE
            )
    return _pool


def close_pool() -> None:
    """Beim Shutdown aufgerufen (siehe app/main.py). Idempotent."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None
            logger.info("Postgres-Pool geschlossen.")

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

-- Teilindizes für die beiden Rückstands-Abfragen des Schedulers
-- (get_riders_missing_history / get_riders_missing_strava, jeweils
-- "WHERE ... IS NULL ORDER BY name LIMIT n"). Für `races` gab es das
-- Gegenstück idx_races_missing_details schon, hier fehlte es: ohne Index
-- ein Seq Scan plus Sortierung über die ganze Tabelle bei jedem Lauf, und
-- der Job läuft alle drei Minuten.
CREATE INDEX IF NOT EXISTS idx_riders_missing_history ON riders (name)
    WHERE history_fetched_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_riders_missing_strava ON riders (name)
    WHERE strava_checked_at IS NULL;

-- Platzhalter für UCI-Ranking-Punkte pro Fahrer und Saison: aktuell noch
-- keine erreichbare Quelle zum automatischen Befüllen (siehe README,
-- Abschnitt "Bekannte Lücke"), aber eine feste Zeile pro (rider_id, year)
-- gibt einem künftigen Import aus einer anderen UCI-Punkte-Datenbank ein
-- verlässliches Ziel für ein UPDATE, ohne raten zu müssen, welche
-- Kombinationen es gibt. Siehe ensure_season_point_placeholders().
CREATE TABLE IF NOT EXISTS rider_season_points (
    rider_id TEXT NOT NULL REFERENCES riders(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    uci_points INTEGER,
    PRIMARY KEY (rider_id, year)
);
"""


def is_configured() -> bool:
    return bool(DATABASE_URL)


@contextmanager
def _connect() -> Iterator[psycopg.Connection]:
    """Leiht eine Verbindung aus dem Pool. Signatur und Semantik sind
    absichtlich unverändert gegenüber der früheren Fassung mit
    psycopg.connect(): auch pool.connection() committet beim regulären
    Verlassen des Blocks und rollt bei einer Exception zurück, gibt die
    Verbindung danach aber zurück in den Pool statt sie zu schließen.
    Dadurch musste kein einziger der vielen Aufrufer in db.py und
    db_races.py angepasst werden."""
    with _get_pool().connection() as conn:
        yield conn


def init_schema() -> None:
    if not DATABASE_URL:
        logger.warning("DATABASE_URL nicht gesetzt - Fahrer-Datenbank wird übersprungen.")
        return
    with _connect() as conn:
        conn.execute(SCHEMA)
    logger.info("Fahrer-Datenbank-Schema geprüft/erstellt.")


_UPSERT_TEAM_SQL = """
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
"""


def _team_params(team: Team) -> dict:
    return {
        "id": team.id,
        "name": team.name,
        "category": team.category,
        "country": team.country,
        "code": team.code,
        "logo": team.logo,
        "wiki_url": team.source_url,
    }


def upsert_teams(teams: list[Team]) -> int:
    """Schreibt mehrere Teams in EINER Verbindung und Transaktion
    (executemany) statt eine Verbindung pro Team. Gibt die Zahl der
    übergebenen Zeilen zurück."""
    if not teams:
        return 0
    with _connect() as conn:
        conn.cursor().executemany(_UPSERT_TEAM_SQL, [_team_params(t) for t in teams])
    return len(teams)


def upsert_team(team: Team) -> None:
    """Einzel-Variante - delegiert an upsert_teams, damit das SQL nur an
    einer Stelle steht."""
    upsert_teams([team])


_UPSERT_RIDER_SQL = """
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
"""

RIDER_FIELDS = (
    "id", "name", "first_name", "last_name", "country", "birth_date",
    "wiki_url", "current_team_id",
)


def upsert_riders(riders: list[dict]) -> int:
    """Schreibt mehrere Fahrer in EINER Verbindung und Transaktion
    (executemany). Jedes dict braucht die Schlüssel aus RIDER_FIELDS.

    Wichtig: derselbe Fahrer darf innerhalb eines Aufrufs nur EINMAL
    vorkommen. Postgres kann eine Zeile pro Statement nicht zweimal per
    ON CONFLICT aktualisieren ("ON CONFLICT DO UPDATE command cannot affect
    row a second time"); bei executemany ist jede Zeile ein eigenes
    Statement, sodass es hier technisch durchläuft - fachlich wäre es aber
    ein stiller Last-Write-Wins wie bisher. Der Aufrufer entdoppelt daher
    vorher (siehe scheduler.refresh_rosters)."""
    if not riders:
        return 0
    missing = [k for k in RIDER_FIELDS if k not in riders[0]]
    if missing:
        raise ValueError(f"Fahrer-Datensatz fehlen Felder: {', '.join(missing)}")
    with _connect() as conn:
        conn.cursor().executemany(
            _UPSERT_RIDER_SQL, [{k: r[k] for k in RIDER_FIELDS} for r in riders]
        )
    return len(riders)


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
    """Einzel-Variante - delegiert an upsert_riders, damit das SQL nur an
    einer Stelle steht."""
    upsert_riders([{
        "id": rider_id,
        "name": name,
        "first_name": first_name,
        "last_name": last_name,
        "country": country,
        "birth_date": birth_date,
        "wiki_url": wiki_url,
        "current_team_id": current_team_id,
    }])


RIDER_FINGERPRINT_FIELDS = (
    "name", "first_name", "last_name", "country", "birth_date",
    "wiki_url", "current_team_id",
)


def get_rider_fingerprints() -> dict[str, tuple]:
    """Liefert je Fahrer-ID ein Tupel der Felder, die ein Kader-Scrape
    schreibt - damit der Scheduler unveränderte Fahrer überspringen kann,
    statt sie bei jedem Lauf neu zu schreiben (siehe
    scheduler.refresh_rosters).

    Bewusst NICHT über last_updated entschieden: dieser Zeitstempel wird von
    jedem Upsert neu gesetzt und sagt deshalb nur, wann zuletzt geschrieben
    wurde, nicht ob sich etwas geändert hat. `birth_date` kommt aus Postgres
    als date-Objekt, vom Scraper dagegen als ISO-String - hier auf ISO
    normalisiert, damit der Vergleich nicht an der Darstellung scheitert."""
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id, {', '.join(RIDER_FINGERPRINT_FIELDS)} FROM riders"
        ).fetchall()
    return {
        row["id"]: tuple(
            row[f].isoformat() if f == "birth_date" and row[f] is not None else row[f]
            for f in RIDER_FINGERPRINT_FIELDS
        )
        for row in rows
    }


def rider_fingerprint(rider_row: dict) -> tuple:
    """Gegenstück zu get_rider_fingerprints für einen frisch gescrapten
    Datensatz (siehe upsert_riders für das Format)."""
    return tuple(rider_row.get(f) for f in RIDER_FINGERPRINT_FIELDS)


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

        # Alle Team-Wiki-URLs der Stints in EINER Abfrage auflösen statt
        # einer Abfrage pro Stint (vorher N+1 - bei ~500 Fahrern mit je
        # 3-8 Stationen mehrere tausend Einzelabfragen beim Erstaufbau).
        urls = [s.team_wiki_url for s in stints if s.team_wiki_url]
        team_id_by_url: dict[str, str] = {}
        if urls:
            rows = conn.execute(
                "SELECT id, wiki_url FROM teams WHERE wiki_url = ANY(%s)", (urls,)
            ).fetchall()
            team_id_by_url = {r["wiki_url"]: r["id"] for r in rows}

        if stints:
            conn.cursor().executemany(
                """
                INSERT INTO rider_team_stints (rider_id, team_id, team_name, start_year, end_year)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (rider_id, start_year, team_name) DO UPDATE SET
                    team_id = EXCLUDED.team_id,
                    end_year = EXCLUDED.end_year
                """,
                [
                    (
                        rider_id,
                        team_id_by_url.get(s.team_wiki_url) if s.team_wiki_url else None,
                        s.team_name,
                        s.start_year,
                        s.end_year,
                    )
                    for s in stints
                ],
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


def _rider_filter(team_id: Optional[str]) -> tuple[str, list]:
    """WHERE-Klausel für Liste und Zählung an einer Stelle - siehe
    db_races._race_filter, gleiche Begründung."""
    if team_id:
        return " WHERE r.current_team_id = %s", [team_id]
    return "", []


def get_riders(
    team_id: Optional[str] = None, limit: int = 1000, offset: int = 0
) -> list[Rider]:
    clause, params = _rider_filter(team_id)
    # Standard-Sortierung nach Nachname (siehe README) - NULLS LAST betrifft
    # nur das kurze Zeitfenster direkt nach dem Schema-Update, bevor der
    # nächste refresh_rosters-Lauf first_name/last_name für alle nachträgt.
    query = f"""
        SELECT r.id, r.name, r.first_name, r.last_name, r.country, r.birth_date,
               r.wiki_url, r.current_team_id, t.name AS current_team_name, r.strava_url
        FROM riders r
        LEFT JOIN teams t ON t.id = r.current_team_id{clause}
        ORDER BY r.last_name NULLS LAST, r.first_name NULLS LAST, r.name
        LIMIT %s OFFSET %s
    """
    with _connect() as conn:
        rows = conn.execute(query, [*params, limit, offset]).fetchall()
    return [_row_to_rider(row) for row in rows]


def count_riders(team_id: Optional[str] = None) -> int:
    clause, params = _rider_filter(team_id)
    with _connect() as conn:
        row = conn.execute(
            f"SELECT count(*) AS n FROM riders r{clause}", params
        ).fetchone()
    return row["n"] if row else 0


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


def ensure_season_point_placeholders() -> int:
    """Legt für jede WorldTour-Saison aus rider_team_stints eine leere
    Platzhalter-Zeile in rider_season_points an (uci_points bleibt NULL),
    falls noch keine existiert - damit hat jeder Fahrer/jede Saison einen
    festen Datensatz, den ein künftiger Import aus einer anderen
    UCI-Punkte-Datenbank per UPDATE befüllen kann, ohne selbst ermitteln
    zu müssen, welche (rider_id, year)-Kombinationen es gibt. Bereits
    befüllte Zeilen werden nie überschrieben (ON CONFLICT DO NOTHING); ein
    offener Zeitraum (end_year IS NULL) läuft bis RACE_SEASON_YEAR, legt
    also mit fortschreitender Saison automatisch neue Platzhalter an, wenn
    dieser Job erneut läuft. Gibt die Zahl neu angelegter Zeilen zurück."""
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO rider_season_points (rider_id, year)
            SELECT s.rider_id, gs.year
            FROM rider_team_stints s
            CROSS JOIN LATERAL generate_series(s.start_year, COALESCE(s.end_year, %s)) AS gs(year)
            WHERE s.team_id IS NOT NULL
            ON CONFLICT (rider_id, year) DO NOTHING
            """,
            (RACE_SEASON_YEAR,),
        )
        return cur.rowcount


# Ein Fahrer kann in EINEM Jahr in zwei Stints auftauchen: auf Wikipedia
# überlappt das Startjahr eines neuen Stints regelmäßig mit dem Endjahr des
# alten (Wechsel zum Saisonwechsel). Die frühere Python-Expansion erzeugte
# dafür zwei Zeilen für dasselbe Jahr - auf rider.html stand die Saison
# doppelt in der Tabelle, und rider_seasons.csv enthielt sie zweimal.
#
# DISTINCT ON (rider_id, year) mit ORDER BY ... start_year DESC behält die
# Zeile des SPÄTEREN Stints. Das passt zu rider_season_points, das mit
# PRIMARY KEY (rider_id, year) ohnehin genau eine Zeile pro Jahr vorsieht -
# eine Darstellung mit zwei Teams pro Übergangsjahr hätte dort kein Ziel.
#
# Ein SQL-Ausdruck für beide Aufrufer (Detailansicht und CSV-Export), damit
# die Ableitung nicht zweimal existiert und wieder auseinanderläuft.
_SEASONS_SQL = """
    SELECT DISTINCT ON (s.rider_id, gs.year)
           s.rider_id, gs.year, s.team_id,
           r.name AS rider_name, r.last_name, r.first_name,
           t.name AS team_name, t.wiki_url AS team_wiki_url, p.uci_points
    FROM rider_team_stints s
    JOIN riders r ON r.id = s.rider_id
    JOIN teams t ON t.id = s.team_id
    CROSS JOIN LATERAL generate_series(s.start_year, COALESCE(s.end_year, %(season)s)) AS gs(year)
    LEFT JOIN rider_season_points p
           ON p.rider_id = s.rider_id AND p.year = gs.year
    {where}
    ORDER BY s.rider_id, gs.year, s.start_year DESC
"""


def get_rider_seasons(rider_id: str) -> list[RiderSeason]:
    """Saison-für-Saison-Zuordnungen (Jahr -> Team) aus den gespeicherten
    Team-Stints, ergänzt um die (noch meist leeren) UCI-Punkte aus
    rider_season_points.

    Nur Stints bei einem aktuell bekannten WorldTour-Team (team_id gesetzt,
    also in der teams-Tabelle vorhanden) zählen als "World Tour"-Saison - die
    Infobox-Historie eines Fahrers listet auch niedrigere Kategorien
    (Continental/ProConti) auf, die nicht Teil der World Tour sind. Ein
    offener Zeitraum (end_year IS NULL, aktuelles Team) läuft bis zur
    laufenden Saison (RACE_SEASON_YEAR). Pro Jahr genau eine Zeile, siehe
    _SEASONS_SQL."""
    inner = _SEASONS_SQL.format(where="WHERE s.rider_id = %(rider_id)s")
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM ({inner}) q ORDER BY q.year DESC",
            {"season": RACE_SEASON_YEAR, "rider_id": rider_id},
        ).fetchall()
    return [
        RiderSeason(
            year=row["year"],
            team_name=row["team_name"],
            team_wiki_url=row["team_wiki_url"],
            uci_points=row["uci_points"],
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


# ---------------------------------------------------------------------------
# CSV-Export: liefert die Rohdaten je Tabelle (mit ein paar lesbaren
# Zusatzspalten aus Joins) für app/routers/export.py. Bewusst getrennt von
# den obigen Funktionen, die auf die API-Modelle (Rider/RiderStint)
# zugeschnitten sind - der Export soll die Datenbank 1:1 nachvollziehbar
# machen.
#
# Alle Export-Funktionen streamen über einen SERVER-SIDE CURSOR statt
# fetchall(): die Ergebnistabellen wachsen mit jedem Jahrgang, und ein
# race_results-Export über alle Rennen lag sonst komplett im Speicher der
# 512-MB-Instanz (siehe stream_query).
# ---------------------------------------------------------------------------

EXPORT_ITERSIZE = int(os.environ.get("EXPORT_ITERSIZE", "1000"))


@contextmanager
def stream_query(query: str, params: Sequence = ()) -> Iterator[tuple[list[str], Iterator[dict]]]:
    """Liefert (Spaltennamen, Zeilen-Iterator) für eine Abfrage, gelesen über
    einen benannten (server-side) Cursor.

    Der Cursor hält das Ergebnis in der Datenbank und liefert es in Blöcken
    von EXPORT_ITERSIZE Zeilen - der Speicherverbrauch bleibt damit flach,
    unabhängig davon, wie groß das Ergebnis ist. Die Verbindung bleibt bis
    zum Ende des with-Blocks geliehen, der Aufrufer muss den Iterator also
    innerhalb des Blocks verbrauchen.

    Spaltennamen kommen aus cur.description, nicht aus der ersten Zeile -
    so stimmt der CSV-Kopf auch bei einem leeren Ergebnis."""
    with _connect() as conn:
        with conn.cursor(name="export") as cur:
            cur.itersize = EXPORT_ITERSIZE
            cur.execute(query, params)
            fields = [d.name for d in cur.description]
            yield fields, cur


def export_teams():
    return stream_query(
        """
        SELECT id, name, category, country, code, logo, wiki_url, last_updated
        FROM teams ORDER BY name
        """
    )


def export_riders():
    return stream_query(
        """
        SELECT r.id, r.first_name, r.last_name, r.name, r.country, r.birth_date,
               r.wiki_url, r.current_team_id, t.name AS current_team_name,
               r.strava_url, r.history_fetched_at, r.last_updated
        FROM riders r
        LEFT JOIN teams t ON t.id = r.current_team_id
        ORDER BY r.last_name NULLS LAST, r.first_name NULLS LAST, r.name
        """
    )


def export_stints():
    return stream_query(
        """
        SELECT s.rider_id, r.name AS rider_name, s.team_id, s.team_name,
               t.wiki_url AS team_wiki_url, s.start_year, s.end_year
        FROM rider_team_stints s
        JOIN riders r ON r.id = s.rider_id
        LEFT JOIN teams t ON t.id = s.team_id
        ORDER BY r.last_name NULLS LAST, r.first_name NULLS LAST, s.start_year
        """
    )


def export_seasons():
    """Eine Zeile pro Fahrer und Saison (Jahr) bei einem WorldTour-Team.

    Nutzt denselben SQL-Ausdruck wie get_rider_seasons (_SEASONS_SQL) -
    inklusive der Entdopplung pro Jahr, die vorher in beiden Pfaden fehlte
    (siehe dort). `uci_points` ist der Platzhalter aus rider_season_points
    (siehe ensure_season_point_placeholders) - i.d.R. noch NULL."""
    inner = _SEASONS_SQL.format(where="")
    return stream_query(
        f"""
        SELECT q.rider_id, q.rider_name, q.year, q.team_id, q.team_name,
               q.team_wiki_url, q.uci_points
        FROM ({inner}) q
        ORDER BY q.last_name NULLS LAST, q.first_name NULLS LAST, q.year
        """,
        {"season": RACE_SEASON_YEAR},
    )
