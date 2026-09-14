-- 0006_ergebnisse_nachholen.sql
--
-- Reparatur: Rennen, die als "Ergebnisse abgerufen" markiert sind, obwohl
-- sie zum Zeitpunkt des Abrufs noch nicht stattgefunden hatten.
--
-- WIE DAS PASSIERT IST
-- --------------------
-- Der Rückstand des Detail-Backfills war "results_fetched_at IS NULL" -
-- ohne Rücksicht darauf, ob das Rennen schon gefahren war. Ein Saisonkalender
-- wird aber komplett auf einmal geseedet, also standen im Januar auch die
-- Rennen vom Oktober in der Tabelle. Deren Wikipedia-Seite existiert zu dem
-- Zeitpunkt oft schon (Streckenverlauf, Teilnehmerliste), eine
-- Ergebnistabelle nicht.
--
-- Der Abruf lieferte deshalb nichts, `replace_race_details` setzte
-- `results_fetched_at = now()` trotzdem - die Funktion markiert unbedingt,
-- nicht abhängig davon, ob Ergebnisse dabei waren - und damit war das Rennen
-- für immer erledigt. Die Ergebnisse waren dauerhaft verloren, ohne dass
-- irgendwo ein Fehler stand. Das Produktionslog meldete zufrieden
-- "noch 0 Rennen ausstehend".
--
-- Sichtbar war es sogar im Frontend, nur falsch herum: js/races.js zeigt bei
-- `results_fetched_at IS NULL` und Startdatum in der Zukunft "bevorstehend".
-- Weil die Spalte gesetzt war, stand dort stattdessen "Ergebnisse ansehen"
-- und beim Aufklappen "Keine Ergebnisliste erfasst." - eine endgültige
-- Aussage über ein Rennen, das noch gar nicht gefahren war. Das Frontend war
-- richtig gebaut; das Backend hat seine Annahme gebrochen.
--
-- WAS DIESE MIGRATION TUT
-- -----------------------
-- Sie setzt `results_fetched_at` auf NULL zurück, und zwar NUR bei Zeilen,
-- bei denen der Abruf BEWEISBAR zu früh war:
--
--     results_fetched_at::date < coalesce(end_date, start_date)
--
-- Also: abgerufen, bevor das Rennen zu Ende war. Das ist keine Schätzung,
-- sondern je Zeile nachrechenbar.
--
-- Bewusst NICHT zurückgesetzt werden Zeilen, die kurz NACH dem Ende
-- abgerufen wurden und trotzdem keine Ergebnisse haben. Die können echt
-- undokumentiert sein (schlecht gepflegte Continental-Rennen), und sie alle
-- erneut abzurufen wäre eine Wikipedia-Last ohne belegten Nutzen. Wer das
-- doch will, setzt sie von Hand zurück:
--
--     UPDATE races SET results_fetched_at = NULL
--     WHERE results_fetched_at IS NOT NULL
--       AND id NOT IN (SELECT DISTINCT race_id FROM race_results);
--
-- KEIN DATENVERLUST
-- -----------------
-- Diese Migration ändert einen Bestandswert - das ist laut README ("Kein
-- Backup, und was das für Migrationen heisst") normalerweise gesperrt. Hier
-- ist es zulässig, weil das Kriterium dort die Wiederherstellbarkeit ist,
-- nicht die Spaltenart: `results_fetched_at` ist ein Merker, kein Inhalt.
-- Was verloren geht, ist der Zeitstempel eines Abrufs, der nichts gefunden
-- hat. Name, Datum, Kategorie, Wiki-URL und die (leeren) Ergebnisse bleiben
-- unangetastet, und der nächste Job-Lauf trägt den Merker neu ein - diesmal
-- nach dem Rennen.

DO $$
DECLARE
    betroffen        bigint;
    davon_zukunft    bigint;
    mit_ergebnissen  bigint;
BEGIN
    -- Zur Kontrolle: wie viele der zu früh abgerufenen Rennen haben trotzdem
    -- Ergebnisse? Das wären Rennen, deren Seite die Ergebnisse vorab hatte -
    -- unerwartet, aber kein Schaden: der erneute Abruf ersetzt sie durch
    -- dieselben oder vollständigere Daten.
    SELECT count(*) INTO mit_ergebnissen
      FROM races r
     WHERE r.results_fetched_at IS NOT NULL
       AND coalesce(r.end_date, r.start_date) IS NOT NULL
       AND r.results_fetched_at::date < coalesce(r.end_date, r.start_date)
       AND EXISTS (SELECT 1 FROM race_results res WHERE res.race_id = r.id);

    SELECT count(*) INTO davon_zukunft
      FROM races
     WHERE results_fetched_at IS NOT NULL
       AND coalesce(end_date, start_date) > current_date;

    UPDATE races
       SET results_fetched_at = NULL
     WHERE results_fetched_at IS NOT NULL
       AND coalesce(end_date, start_date) IS NOT NULL
       AND results_fetched_at::date < coalesce(end_date, start_date);
    GET DIAGNOSTICS betroffen = ROW_COUNT;

    RAISE NOTICE '0006: % Rennen zurueckgesetzt (zu frueh abgerufen)', betroffen;
    RAISE NOTICE '0006: davon % noch nicht gefahren (Enddatum in der Zukunft)', davon_zukunft;
    RAISE NOTICE '0006: % der zurueckgesetzten hatten trotzdem Ergebnisse', mit_ergebnissen;
END $$;
