-- 0002_gender.sql
--
-- Geschlechts-Dimension für Rennen, Fahrer und Teams (Befund 7).
--
-- Weder races noch riders noch teams hatten eine Spalte für Geschlecht. Die
-- Primärschlüssel entstehen allein aus Name, Saison und Kategorie und
-- kollidieren deshalb, sobald Frauen-Radsport dazukommt: ein Frauen-Rennen
-- hätte das gleichnamige Männer-Rennen per ON CONFLICT (id) DO UPDATE
-- stillschweigend überschrieben statt daneben zu existieren.
--
-- Diese Migration ist REIN ADDITIV. Sie legt Spalten und Indizes an und
-- rührt keine bestehende Zeile an ausser durch den Default. Kein UPDATE,
-- kein Umschreiben von Schlüsseln, kein DROP. Grund: es gibt (Stand
-- 2026-09-13) kein automatisches Backup dieser Datenbank, und ein
-- Umschreiben von Primärschlüsseln über fünf Tabellen ohne Netz ist genau
-- die Migration, die man nicht fährt. Warum keine nötig ist, steht in
-- backend/README.md, Abschnitt "Geschlechts-Dimension".

-- 'm'/'w'. Default 'm' für den Bestand: alles aktuell Gespeicherte ist
-- Männer-Radsport (die Scraper lesen ausschliesslich Männer-Quellen, siehe
-- scrapers/wikipedia_teams.WORLDTEAMS_PAGE und
-- scrapers/wikipedia_race_history.season_page_titles).
--
-- CHAR(1) mit CHECK statt eines Enum-Typs: ein Enum zu erweitern
-- (ALTER TYPE ... ADD VALUE) ist in Postgres nicht transaktional
-- zurücknehmbar, und mehr als zwei Werte sind hier nicht zu erwarten. Ein
-- CHECK lässt sich in einer gewöhnlichen Migration ändern.
ALTER TABLE races ADD COLUMN IF NOT EXISTS gender CHAR(1) NOT NULL DEFAULT 'm';
ALTER TABLE riders ADD COLUMN IF NOT EXISTS gender CHAR(1) NOT NULL DEFAULT 'm';
ALTER TABLE teams  ADD COLUMN IF NOT EXISTS gender CHAR(1) NOT NULL DEFAULT 'm';

ALTER TABLE races  DROP CONSTRAINT IF EXISTS races_gender_check;
ALTER TABLE riders DROP CONSTRAINT IF EXISTS riders_gender_check;
ALTER TABLE teams  DROP CONSTRAINT IF EXISTS teams_gender_check;
ALTER TABLE races  ADD CONSTRAINT races_gender_check  CHECK (gender IN ('m', 'w'));
ALTER TABLE riders ADD CONSTRAINT riders_gender_check CHECK (gender IN ('m', 'w'));
ALTER TABLE teams  ADD CONSTRAINT teams_gender_check  CHECK (gender IN ('m', 'w'));

-- Indizes dort, wo nach gender gefiltert wird. Die API filtert immer nach
-- gender (Default 'm'), meist zusammen mit einem zweiten Feld - deshalb
-- zusammengesetzte Indizes in der Spaltenreihenfolge der Abfragen und nicht
-- ein Index nur auf gender, der bei zwei Werten ohnehin wenig aussortiert.
--
-- races: /api/race-history filtert gender + season + category
CREATE INDEX IF NOT EXISTS idx_races_gender_season_category
    ON races (gender, season, category);
-- riders: /api/riders filtert gender, optional nach Team, sortiert nach Nachname
CREATE INDEX IF NOT EXISTS idx_riders_gender_last_name
    ON riders (gender, last_name, first_name);
CREATE INDEX IF NOT EXISTS idx_riders_gender_team
    ON riders (gender, current_team_id);
-- teams: /api/teams filtert gender, sortiert nach Namen
CREATE INDEX IF NOT EXISTS idx_teams_gender_name
    ON teams (gender, name);

-- Vorbereitung für stabile Fahrer-IDs (Befund 7, Schritt 3): der Namens-Slug
-- ist von Natur aus nicht eindeutig, die Wikidata-QID ist es. Die Spalte
-- wird hier angelegt und von scheduler.refresh_rider_details gefüllt; der
-- Wechsel des Primärschlüssels ist ein eigener, datenverändernder Schritt
-- und passiert NICHT hier (siehe README, "Stabile Fahrer-IDs: der Plan").
--
-- Kein UNIQUE-Constraint, sondern ein partieller UNIQUE-Index: NULL zählt in
-- Postgres nicht als Dublette, aber der partielle Index macht sichtbar, dass
-- nur gefüllte QIDs eindeutig sein müssen - und er ist kleiner.
ALTER TABLE riders ADD COLUMN IF NOT EXISTS wikidata_qid TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_riders_wikidata_qid
    ON riders (wikidata_qid) WHERE wikidata_qid IS NOT NULL;
-- Rückstands-Abfrage für den Job, der die QIDs nachträgt: derselbe
-- Teilindex-Trick wie bei idx_riders_missing_history.
CREATE INDEX IF NOT EXISTS idx_riders_missing_qid ON riders (name)
    WHERE wikidata_qid IS NULL;
