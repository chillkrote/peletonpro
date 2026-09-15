-- 0009_punkte_je_ergebnis.sql
--
-- Die berechneten UCI-Punkte, eine Zeile je Ergebniszeile.
--
-- WARUM JE ERGEBNIS UND NICHT JE SAISON
-- -------------------------------------
-- rider_season_points haelt eine Zahl je (Fahrer, Jahr). Das reicht fuer
-- eine Anzeige, aber nicht fuer diese drei Dinge:
--
--   1. NACHRECHNEN. Eine Saisonsumme, die von 1300 abweicht, sagt nicht,
--      welches Rennen schuld ist. Eine Zeile je Ergebnis schon.
--   2. Die 52-WOCHEN-RANGLISTEN. Die UCI-Einzelwertung ist rollierend
--      (Art. 2.10.002); sie braucht das DATUM jedes Punktgewinns, nicht die
--      Jahressumme. Aus Zeilen je Ergebnis laesst sich beides bilden, aus
--      der Jahressumme nur eines.
--   3. NEUBERECHNEN. Aendert sich eine Skala oder eine Zuordnung, muss die
--      alte Rechnung verschwinden koennen, ohne dass jemand raet, welcher
--      Anteil der Summe von wo kam.
--
-- rider_season_points.uci_points bleibt deshalb ABSICHTLICH unberuehrt.
-- Diese Rechnung deckt nur Gesamtklassement und Etappen der WorldTour ab -
-- sechs der dreizehn Anlaesse haben ueberhaupt keine Datenquelle (siehe
-- docs/uci-punkte.md). Eine Teilsumme in eine Spalte zu schreiben, die
-- "UCI-Punkte" heisst, waere genau die stille Falschaussage, die dieses
-- Projekt an anderen Stellen beseitigt hat.

CREATE TABLE uci_punkte_fahrer (
    id        SERIAL PRIMARY KEY,
    race_id   TEXT    NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    -- NULL = Gesamtklassement oder Eintagesrennen, wie in race_results.
    stage_id  INTEGER          REFERENCES race_stages(id) ON DELETE CASCADE,
    rider_id  TEXT    NOT NULL REFERENCES riders(id) ON DELETE CASCADE,
    anlass    TEXT    NOT NULL,
    position  INTEGER NOT NULL CHECK (position >= 1),
    punkte    NUMERIC(8,2) NOT NULL CHECK (punkte > 0),
    -- Fuer die rollierende Rangliste: das Datum, an dem die Punkte fielen.
    -- Aus der Etappe bzw. dem Renn-Enddatum abgeleitet und mitgeschrieben,
    -- damit eine 52-Wochen-Abfrage nicht ueber drei Tabellen joinen muss.
    punkt_datum DATE
);

-- Ein Fahrer kann in einem Anlass eines Rennens nur einmal punkten. Ueber
-- coalesce, weil stage_id NULL sein darf und NULL in einem UNIQUE nicht
-- mit sich selbst kollidiert - ohne das waere die Gesamtklassement-Zeile
-- beliebig oft einfuegbar.
CREATE UNIQUE INDEX idx_punkte_fahrer_eindeutig
    ON uci_punkte_fahrer (race_id, anlass, rider_id, coalesce(stage_id, -1));

CREATE INDEX idx_punkte_fahrer_rider ON uci_punkte_fahrer (rider_id);
CREATE INDEX idx_punkte_fahrer_datum ON uci_punkte_fahrer (punkt_datum);

COMMENT ON TABLE uci_punkte_fahrer IS
    'Berechnete UCI-Punkte je Ergebniszeile. Quelle: race_results x '
    'uci_punkte, siehe app/uci_berechnung.py. Deckt bisher nur '
    'Gesamtklassement und Etappen der WorldTour ab.';

-- Wann ein Rennen zuletzt gerechnet wurde. Damit ist die Berechnung beim
-- Prozessstart ein No-Op, solange sich nichts geaendert hat - dieselbe
-- Ueberlegung wie beim Hash-Merker des Reglement-Loaders (Migration 0008)
-- und beim Saison-Takt (0007): diese Instanz startet mehrmals pro Stunde
-- neu.
ALTER TABLE races ADD COLUMN punkte_berechnet_at TIMESTAMPTZ;
