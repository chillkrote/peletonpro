-- 0008_uci_punkte.sql
--
-- Das UCI-Punktereglement in die Datenbank, als Grundlage fuer die eigene
-- Berechnung.
--
-- WOZU
-- ----
-- Die Punkte sollen selbst berechnet werden, nicht importiert. Dafuer
-- muessen die Skalen abfragbar sein - ein CSV im Repository reicht fuer die
-- Dokumentation, aber nicht fuer ein JOIN gegen Ergebniszeilen.
--
-- Quelle ist docs/uci-punkte-2026.csv (Werte) und
-- docs/uci-punkte-2026-wt-stufen.csv (Rennzuordnung), beide aus den UCI
-- Cycling Regulations Teil 2, Kapitel X, Ausgabe 01.09.2026. Diese
-- Migration legt nur die Tabellen an; gefuellt werden sie von
-- app/uci_punkte.py aus der CSV. Die Zahlen stehen damit genau EINMAL im
-- Repository, nicht zusaetzlich als INSERT-Block hier drin - sonst waere
-- beim naechsten Reglement-Jahrgang nicht mehr erkennbar, welche der
-- beiden Kopien gilt.
--
-- WARUM DIE SAISON IM SCHLUESSEL STEHT
-- -----------------------------------
-- Das Reglement erscheint jaehrlich, und die Skalen aendern sich dabei.
-- Ein spaeterer Jahrgang ERGAENZT, er ueberschreibt nicht - sonst liesse
-- sich eine historische Rangliste nie mehr nachrechnen. Genau dieselbe
-- Ueberlegung wie bei rider_season_points: ein Wert gilt fuer eine Saison,
-- nicht fuer immer.
--
-- WARUM DREI TABELLEN UND NICHT EINE
-- ----------------------------------
-- uci_stufe ist der Schluessel, auf den die beiden anderen per
-- Fremdschluessel zeigen. Ohne sie waere eine Rennzuordnung auf eine
-- Stufe ohne Skala moeglich, und die faellt beim Rechnen nicht als Fehler
-- auf, sondern als stilles Null-Ergebnis - die schlimmste Art von
-- Datenfehler, weil sie wie ein legitimes "keine Punkte" aussieht.

-- Welche Stufen es je Saison, Geschlecht und Anlass gibt.
CREATE TABLE uci_stufe (
    saison  INTEGER NOT NULL,
    gender  TEXT    NOT NULL,
    anlass  TEXT    NOT NULL,
    stufe   TEXT    NOT NULL,
    PRIMARY KEY (saison, gender, anlass, stufe)
);

COMMENT ON TABLE uci_stufe IS
    'Vorhandene Punkte-Stufen je Saison/Geschlecht/Anlass. Schluesseltabelle '
    'fuer uci_punkte und uci_rennstufe - siehe Migration 0008.';

-- Die Skala selbst. Ganzzahlig: im Reglement stehen nur ganze Zahlen.
-- Geteilt wird erst bei der Zuteilung (Mannschaftszeitfahren, auf ein
-- Hundertstel), und das Ergebnis landet nicht hier.
CREATE TABLE uci_punkte (
    saison  INTEGER NOT NULL,
    gender  TEXT    NOT NULL,
    anlass  TEXT    NOT NULL,
    stufe   TEXT    NOT NULL,
    platz   INTEGER NOT NULL CHECK (platz >= 1),
    punkte  INTEGER NOT NULL CHECK (punkte > 0),
    PRIMARY KEY (saison, gender, anlass, stufe, platz),
    FOREIGN KEY (saison, gender, anlass, stufe)
        REFERENCES uci_stufe (saison, gender, anlass, stufe) ON DELETE CASCADE
);

COMMENT ON TABLE uci_punkte IS
    'Punkte je Platz. Quelle: docs/uci-punkte-<saison>.csv, geladen von '
    'app/uci_punkte.py. Nicht von Hand aendern.';

-- Welches Rennen in welcher WorldTour-Stufe laeuft.
--
-- `rennen_reglement` ist der Name, wie er im Reglement steht -
-- UNVERAENDERT, samt Tippfehlern ("Oomlop Nieuwsblad" fuer Omloop
-- Nieuwsblad im Frauen-Gesamtklassement). Er ist die Quelle, nicht der
-- Fehler, und er ist der Grund, warum `race_id` nicht aus dem Namen
-- abgeleitet werden darf.
--
-- `race_id` ist deshalb NULL, solange die Zuordnung nicht von Hand oder
-- halbautomatisch gesetzt wurde. Eine offene Zuordnung ist damit
-- ABFRAGBAR (WHERE race_id IS NULL) statt unsichtbar - der Unterschied
-- zwischen "wir wissen, dass 15 Rennen fehlen" und "die Punkte sind
-- irgendwie zu niedrig".
CREATE TABLE uci_rennstufe (
    saison           INTEGER NOT NULL,
    gender           TEXT    NOT NULL,
    anlass           TEXT    NOT NULL,
    stufe            TEXT    NOT NULL,
    rennen_reglement TEXT    NOT NULL,
    race_id          TEXT        NULL REFERENCES races(id) ON DELETE SET NULL,
    PRIMARY KEY (saison, gender, anlass, rennen_reglement),
    FOREIGN KEY (saison, gender, anlass, stufe)
        REFERENCES uci_stufe (saison, gender, anlass, stufe) ON DELETE CASCADE
);

COMMENT ON TABLE uci_rennstufe IS
    'Zuordnung Reglement-Rennname -> Stufe, und (wenn bekannt) -> races.id. '
    'race_id IS NULL heisst: noch nicht zugeordnet, siehe Migration 0008.';

CREATE INDEX idx_uci_rennstufe_race ON uci_rennstufe (race_id)
    WHERE race_id IS NOT NULL;

-- Merker, damit der Loader bei jedem Prozessstart NICHT 1564 Zeilen
-- schreibt. Auf dem kostenlosen Plan startet die Instanz mehrmals pro
-- Stunde neu (siehe Migration 0007) - dieselbe Falle, nur an anderer
-- Stelle.
CREATE TABLE uci_quelle (
    datei      TEXT PRIMARY KEY,
    sha256     TEXT NOT NULL,
    geladen_am TIMESTAMPTZ NOT NULL
);

COMMENT ON TABLE uci_quelle IS
    'SHA-256 der geladenen CSV-Dateien. Gleicher Hash -> Loader tut nichts.';

-- Mannschaftszeitfahren-Punkte werden auf ein Hundertstel geteilt
-- (Art. 2.10.008: "divided equally between the riders finishing the event
-- ... rounded to a hundredth of a point"). Ein Fahrer kann also 12,86
-- Punkte haben, und INTEGER wuerde das stillschweigend runden.
--
-- Die Aenderung ist nach der Regel in backend/README.md ("Kein Backup, und
-- was das fuer Migrationen heisst") auch ohne Backup zulaessig: INTEGER ->
-- NUMERIC ist verlustfrei, kein Wert kann dabei kaputtgehen. Die Meldung
-- unten belegt zusaetzlich, wie viele Zeilen ueberhaupt einen Wert hatten -
-- geschrieben hat die Spalte bisher nichts.
DO $$
DECLARE
    belegt INTEGER;
BEGIN
    SELECT count(*) INTO belegt
      FROM rider_season_points WHERE uci_points IS NOT NULL;
    RAISE NOTICE '0008: % Zeilen in rider_season_points hatten einen uci_points-Wert', belegt;
END $$;

ALTER TABLE rider_season_points
    ALTER COLUMN uci_points TYPE NUMERIC(8,2);
