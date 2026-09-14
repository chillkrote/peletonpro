-- 0005_namensquelle.sql
--
-- Befund 16: `riders.first_name`/`last_name` entstehen aus einer Heuristik
-- (scrapers/wikipedia_riders.py::split_name): Nachname = letztes Wort plus
-- vorangehende bekannte Partikel (van/de/von/...). Der Standardfall und die
-- niederländisch/deutschen Partikel-Namen stimmen damit. Falsch liegt sie
-- bei spanischen und portugiesischen Doppelnachnamen:
--
--     "Juan Ayuso Pesquera"  ->  Vorname "Juan Ayuso" / Nachname "Pesquera"
--
-- Richtig wäre Vorname "Juan" / Nachname "Ayuso Pesquera". Das betrifft die
-- Standardsortierung (ORDER BY last_name, first_name) und jede Anzeige, die
-- den Nachnamen hervorhebt - auf der Fahrer-Detailseite ist das die
-- Überschrift.
--
-- Wikidata führt Familiennamen als Property P734, bei Doppelnachnamen als
-- zwei Aussagen in Reihenfolge. Damit ist der Fall entscheidbar statt
-- geraten.
--
-- WAS DIESE MIGRATION TUT
-- -----------------------
-- Nur eine Spalte anlegen, die festhält, WOHER die Trennung kommt:
--
--     NULL          noch nicht bei Wikidata nachgefragt
--     'heuristik'   nachgefragt, Wikidata hat nichts Passendes geliefert
--     'wikidata'    Wikidata hat den Familiennamen bestätigt oder korrigiert
--
-- Sie schreibt KEINEN Namen um. Das Nachfragen erledigt der Job
-- `refresh_rider_details` gebatcht über die Wikidata-API - eine Migration
-- kann nicht ins Netz, und sie soll es auch nicht.
--
-- Die Spalte ist nicht Zierrat, sondern der Rückweg: ohne sie wäre eine
-- falsche Wikidata-Korrektur nicht von einem Heuristik-Ergebnis zu
-- unterscheiden. Mit ihr lässt sich jede Zeile gezielt auf die Heuristik
-- zurückrechnen (`name` bleibt unverändert die Quelle), und ein erneuter
-- Durchlauf ist ein `UPDATE riders SET name_source = NULL`.
--
-- Additiv, wie 0002 bis 0004: kein Bestandswert wird angefasst. Der Grund
-- steht im README unter "Kein Backup, und was das für Migrationen heisst".

ALTER TABLE riders ADD COLUMN name_source TEXT;

ALTER TABLE riders ADD CONSTRAINT riders_name_source_check
    CHECK (name_source IS NULL OR name_source IN ('heuristik', 'wikidata'));

-- Rückstands-Abfrage des Jobs ("wer wurde noch nicht gefragt", sortiert
-- nach Namen) - derselbe Teilindex-Trick wie bei idx_riders_missing_strava
-- und idx_riders_missing_qid. Ohne ihn ein Seq Scan plus Sortierung über
-- die ganze Tabelle bei jedem Lauf, und der Job läuft alle drei Minuten.
CREATE INDEX idx_riders_missing_name_source ON riders (name)
    WHERE name_source IS NULL;
