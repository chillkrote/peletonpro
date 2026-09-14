-- 0003_taxonomie.sql
--
-- Ein Kategorie-Vokabular statt zwei (Befund 9), plus die Circuit-Regel als
-- CHECK.
--
-- KEINE WERT-MIGRATION. Der Bestand enthält bereits genau das gewählte
-- Vokabular ('wt'/'proseries'/'continental'), belegt über den Schreibpfad:
-- races.category schreibt ausschliesslich db_races.upsert_race_skeleton,
-- aufgerufen aus der einen Schleife in scheduler._race_history_series();
-- teams.category schreibt nur scrapers/wikipedia_teams.py, fest auf 'wt'.
-- Das zweite Vokabular ('pro'/'cont') stand nur im Typ von Team.category
-- und konnte keine Zeile erreichen.
--
-- Diese Migration setzt die Regeln deshalb nur DURCH, statt Daten
-- anzufassen. Damit ist sie gleichzeitig die Prüfung, die von der
-- Entwicklungsumgebung aus nicht möglich war: die Render-Datenbank ist von
-- dort nicht per SQL erreichbar (kein TLS im Abfragepfad). Enthält
-- Produktion wider Erwarten einen anderen Wert, schlägt die Migration fehl
-- und NENNT ihn - statt ihn stillschweigend umzuschreiben oder
-- wegzuwerfen. Der Runner protokolliert den Fehler, die App läuft weiter,
-- und der Stand bleibt auf 0002 (siehe app/migrations.py).

-- ---------------------------------------------------------------------------
-- Erst melden, dann erzwingen.
--
-- EIN Block, der ALLE Probleme sammelt und einmal meldet. Vorher waren es
-- vier Blöcke, von denen der erste abbrach - man hätte ein Problem behoben,
-- die Migration erneut laufen lassen, das nächste gefunden, und nie den
-- Umfang gesehen. Eine nackte Constraint-Verletzung sagt ausserdem nur
-- "violates check constraint races_category_check" und nicht, WELCHER Wert
-- schuld ist.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    befunde text[] := ARRAY[]::text[];
    fremd   text;
    anzahl  bigint;
BEGIN
    SELECT string_agg(DISTINCT quote_literal(category), ', ') INTO fremd
      FROM races WHERE category NOT IN ('wt', 'proseries', 'continental');
    IF fremd IS NOT NULL THEN
        befunde := befunde || format('races.category enthält %s', fremd);
    END IF;

    SELECT string_agg(DISTINCT quote_literal(category), ', ') INTO fremd
      FROM teams WHERE category NOT IN ('wt', 'proseries', 'continental');
    IF fremd IS NOT NULL THEN
        befunde := befunde || format('teams.category enthält %s', fremd);
    END IF;

    SELECT string_agg(DISTINCT quote_literal(category), ', ') INTO fremd
      FROM race_history_seed_log
     WHERE category NOT IN ('wt', 'proseries', 'continental');
    IF fremd IS NOT NULL THEN
        befunde := befunde || format('race_history_seed_log.category enthält %s', fremd);
    END IF;

    SELECT string_agg(DISTINCT quote_literal(circuit), ', ') INTO fremd
      FROM races WHERE circuit IS NOT NULL
       AND circuit NOT IN ('africa', 'asia', 'europe', 'america', 'oceania');
    IF fremd IS NOT NULL THEN
        befunde := befunde || format('races.circuit enthält %s', fremd);
    END IF;

    SELECT count(*) INTO anzahl FROM races
     WHERE (category = 'continental') <> (circuit IS NOT NULL);
    IF anzahl > 0 THEN
        befunde := befunde || format(
            '%s Zeilen in races verletzen die Circuit-Regel (circuit ist genau '
            'dann gesetzt, wenn category = ''continental'')', anzahl);
    END IF;

    SELECT count(*) INTO anzahl FROM race_history_seed_log
     WHERE (category = 'continental')
        <> (circuit IN ('africa', 'asia', 'europe', 'america', 'oceania'));
    IF anzahl > 0 THEN
        befunde := befunde || format(
            '%s Zeilen in race_history_seed_log verletzen die Circuit-Regel', anzahl);
    END IF;

    IF array_length(befunde, 1) > 0 THEN
        RAISE EXCEPTION E'Der Bestand passt nicht zum Vokabular aus app/taxonomy.py:\n  - %\n'
            'Diese Migration schreibt NICHTS um - entscheide erst, was mit diesen '
            'Zeilen passieren soll, und leg dafür eine eigene Migration an. '
            'Zum Ansehen:\n'
            '  SELECT DISTINCT category, circuit FROM races ORDER BY 1, 2;\n'
            '  SELECT DISTINCT category FROM teams;\n'
            '  SELECT id, category, circuit FROM races '
            'WHERE (category = ''continental'') <> (circuit IS NOT NULL);',
            array_to_string(befunde, E'\n  - ');
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Jetzt die Regeln festschreiben.
-- ---------------------------------------------------------------------------
ALTER TABLE races DROP CONSTRAINT IF EXISTS races_category_check;
ALTER TABLE races ADD CONSTRAINT races_category_check
    CHECK (category IN ('wt', 'proseries', 'continental'));

ALTER TABLE teams DROP CONSTRAINT IF EXISTS teams_category_check;
ALTER TABLE teams ADD CONSTRAINT teams_category_check
    CHECK (category IN ('wt', 'proseries', 'continental'));

ALTER TABLE races DROP CONSTRAINT IF EXISTS races_circuit_check;
ALTER TABLE races ADD CONSTRAINT races_circuit_check
    CHECK (circuit IS NULL
           OR circuit IN ('africa', 'asia', 'europe', 'america', 'oceania'));

-- Die Circuit-Achse selbst: gesetzt genau dann, wenn die Kategorie
-- geografisch gegliedert ist. Vorher war das eine Zusicherung in
-- season_page_titles, und nur in eine Richtung - ein Circuit bei
-- category='wt' lief stillschweigend durch und wäre über race_id_for in
-- den Primärschlüssel gewandert.
ALTER TABLE races DROP CONSTRAINT IF EXISTS races_circuit_nur_continental;
ALTER TABLE races ADD CONSTRAINT races_circuit_nur_continental
    CHECK ((category = 'continental') = (circuit IS NOT NULL));

-- race_history_seed_log führt den Circuit als '' statt NULL, weil er Teil
-- des Primärschlüssels ist (PKs dürfen kein NULL enthalten, siehe 0001).
-- Deshalb dort eine eigene Fassung derselben Regel.
ALTER TABLE race_history_seed_log DROP CONSTRAINT IF EXISTS seed_log_category_check;
ALTER TABLE race_history_seed_log ADD CONSTRAINT seed_log_category_check
    CHECK (category IN ('wt', 'proseries', 'continental'));

ALTER TABLE race_history_seed_log DROP CONSTRAINT IF EXISTS seed_log_circuit_check;
ALTER TABLE race_history_seed_log ADD CONSTRAINT seed_log_circuit_check
    CHECK ((category = 'continental')
           = (circuit IN ('africa', 'asia', 'europe', 'america', 'oceania')));
