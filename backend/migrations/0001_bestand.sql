-- 0001_bestand.sql
--
-- Der Schemastand, wie er beim Einführen der Migrationen in Produktion lief.
-- Wörtlich aus den früheren String-Literalen SCHEMA (app/db.py) und
-- SCHEMA_RACES (app/db_races.py) übernommen, die bei jedem App-Start
-- ausgeführt wurden.
--
-- WICHTIG: diese Migration läuft auch gegen die bestehende
-- Produktionsdatenbank, in der alle Tabellen und Spalten schon existieren -
-- denn dort gibt es die Tabelle schema_migrations noch nicht, 0001 gilt also
-- als nicht angewendet. Sie ist deshalb durchgehend idempotent formuliert
-- (CREATE TABLE IF NOT EXISTS, ADD COLUMN IF NOT EXISTS,
-- CREATE INDEX IF NOT EXISTS) und rührt vorhandene Daten nicht an. Genau so
-- lief sie vorher bei jedem Start.
--
-- Künftige Migrationen brauchen diese Rücksicht NICHT: ab 0002 ist bekannt,
-- welcher Stand angewendet wurde, und sie dürfen gewöhnliches ALTER TABLE
-- schreiben.
--
-- Inhalt nicht mehr ändern: der Runner prüft die Prüfsumme jeder
-- angewendeten Migration (siehe app/migrations.py).

-- ===========================================================================
-- Fahrer und Teams (vorher app/db.py::SCHEMA)
-- ===========================================================================
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

-- ===========================================================================
-- Renn-Historie (vorher app/db_races.py::SCHEMA_RACES)
-- ===========================================================================
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
