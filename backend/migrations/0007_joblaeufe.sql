-- 0007_joblaeufe.sql
--
-- Wann ein Hintergrund-Job das letzte Mal ERFOLGREICH gelaufen ist.
--
-- WOZU
-- ----
-- `REFRESH_INTERVAL_ROSTERS` stand auf 24 Stunden, und die Kader liefen
-- trotzdem 14 Mal an einem Tag (gemessen am 14.09.2026, jedes Mal mit dem
-- Ergebnis "0 von 517 Fahrern geändert"). Ursache ist
-- `next_run_time=datetime.now() + stagger` in start_scheduler(): APScheduler
-- führt jeden Job beim Prozessstart einmal aus, und eine Instanz auf Renders
-- kostenlosem Plan schläft nach 15 Minuten ohne Anfrage ein und startet beim
-- nächsten Besuch neu.
--
-- Ein Intervall, das an die Prozesslaufzeit hängt, greift damit nie. Der
-- Takt war faktisch "bei jedem Aufwachen": rund 500 Wikipedia-Anfragen an
-- einem Tag für null Änderungen.
--
-- Diese Tabelle löst das, indem die Fälligkeit aus der DATENBANK kommt statt
-- aus der Laufzeit. Das ist ausserdem robuster als ein Kalenderplan: ein
-- verpasstes Zeitfenster geht nicht verloren, sondern wird beim nächsten
-- Aufwachen nachgeholt - genau das Verhalten, das ein Dienst braucht, der
-- schläft.
--
-- Bewusst KEIN Verlauf, nur der letzte Erfolg: der Zweck ist die
-- Fälligkeitsprüfung, nicht eine Job-Historie. Wer die will, liest das
-- Anwendungslog.
--
-- `job` ist der Name aus scheduler.JOBS. Kein Fremdschlüssel und keine
-- Aufzählung: ein umbenannter oder entfernter Job soll hier eine verwaiste
-- Zeile hinterlassen, nicht die Migration blockieren. Welche Jobs einen
-- Takt haben, steht in app/kadenz.py::PLAN.

CREATE TABLE job_runs (
    job          TEXT PRIMARY KEY,
    last_success TIMESTAMPTZ NOT NULL
);

COMMENT ON TABLE job_runs IS
    'Letzter erfolgreicher Lauf je Hintergrund-Job. Grundlage der '
    'Faelligkeitspruefung in app/kadenz.py - siehe Migration 0007 fuer den '
    'Grund (Intervalle greifen nicht, weil der Free-Plan staendig neu '
    'startet).';
