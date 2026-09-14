-- 0004_ergebnis_ids.sql
--
-- Befund 8: race_results kennt Fahrer und Team nur als Text.
--
--     rider_name TEXT NOT NULL
--     team_name  TEXT
--
-- Das ist der Rohwert aus der Wikipedia-Ergebnistabelle, und er ist nicht
-- verknüpft: die Fahrer-Detailseite kann daraus nicht "seine Ergebnisse"
-- zeigen, und die Team-Statistik vergleicht Zeichenketten
-- (`res.team_name = teams.name`). Letzteres ist Befund 18 und die Stelle, wo
-- es wirklich weh tut: ein Team wird umbenannt - "Jumbo-Visma" wurde "Team
-- Visma-Lease a Bike" - und verliert damit seine gesamte Historie, ohne dass
-- irgendwo ein Fehler auftaucht. Die Seite zeigt einfach null Siege.
--
-- ADDITIV, ABSICHTLICH
-- --------------------
-- Diese Migration legt zwei NEUE Spalten an und füllt NUR diese. Sie
-- verändert keinen bestehenden Wert, löscht keine Spalte und rührt keinen
-- Primärschlüssel an. `rider_name` und `team_name` bleiben stehen: sie sind
-- der unverfälschte Quellwert und der Rückfall für jede Zeile, die sich
-- nicht zuordnen lässt.
--
-- Der Grund ist nicht Vorsicht um ihrer selbst willen. Für diese Datenbank
-- gibt es kein Backup: der Free-Plan bietet keines, und die
-- `ipAllowList` ist leer - die Datenbank nimmt überhaupt keine externen
-- Verbindungen an, ein `pg_dump` von ausserhalb ist also nicht möglich
-- (siehe README, "Kein Backup, und was das für Migrationen heisst"). Eine
-- Migration ohne Rückweg darf nur Dinge tun, die sich neu berechnen lassen.
-- Ein falscher Wert in einer neuen Spalte erfüllt das; ein überschriebener
-- Bestandswert nicht.
--
-- NICHTS GERATEN
-- --------------
-- Jeder der vier Zuordnungsschritte setzt eine ID nur dann, wenn sie
-- EINDEUTIG ist (`HAVING count(...) = 1`). Bei zwei möglichen Treffern
-- bleibt die Spalte NULL. Eine falsche Zuordnung wäre schlimmer als keine:
-- sie sieht wie ein Ergebnis aus.
--
-- EINE STELLE, ZWEI AUFRUFER
-- ---------------------------
-- Die Zuordnungsregel gilt für zwei Dinge: den Bestand (einmal, hier) und
-- jedes künftig gescrapte Ergebnis (bei jedem Schreiben). Stünde sie zweimal
-- - hier als Backfill und in db_races.py als Python -, liefen die beiden
-- auseinander, sobald eine Regel nachgeschärft wird. Genau die Doppelung,
-- die dieses Projekt vermeiden will.
--
-- Sie steht deshalb als Datenbankfunktion `race_results_ids_nachtragen`:
-- ohne Argument für alle Zeilen, mit race_id für eine. Die Migration ruft
-- sie für den Bestand, `db_races.replace_race_details` für das Rennen, das es
-- gerade geschrieben hat. Eine Änderung der Regel ist damit eine neue
-- Migration, die die Funktion ersetzt - und gilt sofort für beide.
--
-- ERWARTUNG AN DIE ABDECKUNG
-- --------------------------
-- `riders` enthält nur die Kader der aktuellen 18 WorldTeams (517 Fahrer).
-- `race_results` reicht über alle Saisons und enthält ProSeries und
-- Continental - also tausende Namen von Fahrern, die nie in einem WorldTeam
-- waren oder längst aufgehört haben. `rider_id` bleibt deshalb für die
-- MEHRHEIT der Zeilen NULL, und das ist die Datenlage, kein Fehler des
-- Backfills. Die Zahlen berichtet die Migration am Ende per RAISE NOTICE;
-- app/migrations.py schreibt sie ins Anwendungslog.

ALTER TABLE race_results
    ADD COLUMN rider_id TEXT REFERENCES riders(id) ON DELETE SET NULL;
ALTER TABLE race_results
    ADD COLUMN team_id  TEXT REFERENCES teams(id)  ON DELETE SET NULL;

-- Teilindizes: gefragt wird immer nach gesetzten IDs ("die Ergebnisse dieses
-- Fahrers", "die Siege dieses Teams"), nie nach den NULLs. Bei der erwarteten
-- Verteilung - Mehrheit NULL - ist der Teilindex deutlich kleiner als ein
-- vollständiger und beantwortet dieselben Abfragen.
CREATE INDEX idx_results_rider ON race_results (rider_id) WHERE rider_id IS NOT NULL;
CREATE INDEX idx_results_team  ON race_results (team_id)  WHERE team_id  IS NOT NULL;

CREATE OR REPLACE FUNCTION race_results_ids_nachtragen(p_race_id TEXT DEFAULT NULL)
RETURNS TABLE (schritt_a bigint, schritt_b bigint, schritt_c bigint, schritt_d bigint)
LANGUAGE plpgsql AS $$
BEGIN
    schritt_a := 0; schritt_b := 0; schritt_c := 0; schritt_d := 0;

    -- A) rider_id über den Namen, innerhalb desselben Geschlechts.
    -- riders.id ist der slugifizierte Name (bei Frauen mit Präfix), zwei
    -- Fahrer gleichen Namens könnten dort also gar nicht beide stehen. Die
    -- Eindeutigkeitsprüfung bleibt trotzdem: sie kostet nichts und hält die
    -- Regel "nichts raten" auch dann, wenn sich die ID-Bildung einmal ändert.
    WITH zuordnung AS (
        SELECT res.id AS result_id, min(ri.id) AS rider_id
        FROM race_results res
        JOIN races  r  ON r.id = res.race_id
        JOIN riders ri ON ri.name = res.rider_name AND ri.gender = r.gender
        WHERE res.rider_id IS NULL
          AND (p_race_id IS NULL OR res.race_id = p_race_id)
        GROUP BY res.id
        HAVING count(*) = 1
    )
    UPDATE race_results res SET rider_id = z.rider_id
    FROM zuordnung z WHERE res.id = z.result_id;
    GET DIAGNOSTICS schritt_a = ROW_COUNT;

    -- B) team_id über den heutigen Teamnamen. Greift nur bei Teams, die HEUTE
    -- so heissen - für ältere Saisons steht in der Ergebnistabelle der
    -- damalige Name. Genau deshalb folgen C und D.
    WITH zuordnung AS (
        SELECT res.id AS result_id, min(t.id) AS team_id
        FROM race_results res
        JOIN races r ON r.id = res.race_id
        JOIN teams t ON t.name = res.team_name AND t.gender = r.gender
        WHERE res.team_id IS NULL AND res.team_name IS NOT NULL
          AND (p_race_id IS NULL OR res.race_id = p_race_id)
        GROUP BY res.id
        HAVING count(*) = 1
    )
    UPDATE race_results res SET team_id = z.team_id
    FROM zuordnung z WHERE res.id = z.result_id;
    GET DIAGNOSTICS schritt_b = ROW_COUNT;

    -- C) team_id über die Team-Station des Fahrers in der Saison des Rennens.
    -- rider_team_stints hat team_id bereits aufgelöst, und zwar über die
    -- WIKI-URL des Teams statt über den Namen - der stabile Schlüssel, der
    -- race_results fehlt. Das löst auch Schreibvarianten ("Team Jumbo Visma"
    -- gegen "Jumbo-Visma"), die weder B noch D finden. Braucht rider_id,
    -- läuft daher nach A. Deckt mehr als eine Station die Saison ab
    -- (Wechsel mitten im Jahr), bleibt die Spalte NULL.
    WITH zuordnung AS (
        SELECT res.id AS result_id, min(s.team_id) AS team_id
        FROM race_results res
        JOIN races r ON r.id = res.race_id
        JOIN rider_team_stints s
              ON s.rider_id = res.rider_id
             AND s.team_id IS NOT NULL
             AND r.season >= s.start_year
             AND r.season <= coalesce(s.end_year, 9999)
        WHERE res.team_id IS NULL AND res.rider_id IS NOT NULL
          AND (p_race_id IS NULL OR res.race_id = p_race_id)
        GROUP BY res.id
        HAVING count(DISTINCT s.team_id) = 1
    )
    UPDATE race_results res SET team_id = z.team_id
    FROM zuordnung z WHERE res.id = z.result_id;
    GET DIAGNOSTICS schritt_c = ROW_COUNT;

    -- D) team_id über historische Teamnamen allein. rider_team_stints enthält
    -- die Namen, unter denen ein Team damals lief, jeweils mit aufgelöster
    -- team_id. Das ergibt eine Abbildung "alter Name -> team_id", die auch
    -- für Zeilen greift, deren Fahrer wir nicht kennen. Nur Namen, die auf
    -- GENAU EIN Team zeigen; mehrdeutige bleiben aussen vor.
    WITH namen AS (
        SELECT team_name, min(team_id) AS team_id
        FROM rider_team_stints
        WHERE team_id IS NOT NULL
        GROUP BY team_name
        HAVING count(DISTINCT team_id) = 1
    )
    UPDATE race_results res SET team_id = n.team_id
    FROM namen n
    WHERE res.team_id IS NULL AND res.team_name = n.team_name
      AND (p_race_id IS NULL OR res.race_id = p_race_id);
    GET DIAGNOSTICS schritt_d = ROW_COUNT;

    RETURN NEXT;
END $$;

COMMENT ON FUNCTION race_results_ids_nachtragen(TEXT) IS
    'Traegt rider_id/team_id in race_results nach - ohne Argument fuer alle '
    'Zeilen, mit race_id fuer eines. Setzt eine ID nur bei eindeutigem '
    'Treffer. Aufrufer: Migration 0004 (Bestand) und '
    'db_races.replace_race_details (neu gescrapte Ergebnisse).';

-- Bestand einmal durchlaufen und berichten.
DO $$
DECLARE
    a bigint; b bigint; c bigint; d bigint;
    zeilen_gesamt  bigint;
    fahrer_gesetzt bigint;
    team_gesetzt   bigint;
BEGIN
    SELECT count(*) INTO zeilen_gesamt FROM race_results;
    SELECT schritt_a, schritt_b, schritt_c, schritt_d
      INTO a, b, c, d
      FROM race_results_ids_nachtragen();

    SELECT count(*) FILTER (WHERE rider_id IS NOT NULL),
           count(*) FILTER (WHERE team_id  IS NOT NULL)
      INTO fahrer_gesetzt, team_gesetzt
      FROM race_results;

    RAISE NOTICE '0004: % Ergebniszeilen insgesamt', zeilen_gesamt;
    RAISE NOTICE '0004: rider_id gesetzt bei % Zeilen (Schritt A: %)',
        fahrer_gesetzt, a;
    RAISE NOTICE '0004: team_id gesetzt bei % Zeilen (B Teamname: %, C Station: %, D Altname: %)',
        team_gesetzt, b, c, d;
END $$;
