#!/usr/bin/env bash
# Prueft Migration 0004 (rider_id/team_id in race_results, Befund 8 + 18).
#
#   PGPORT=5599 ./scripts/check-migration-0004.sh
#
# Geprueft wird:
#   1. der Runner wendet alle vier Migrationen auf einer leeren Datenbank an
#   2. Spalten, Fremdschluessel und Teilindizes sind wie vorgesehen
#   3. der Backfill ordnet jeden der vier Faelle richtig zu - und laesst
#      Mehrdeutiges bewusst NULL
#   4. Geschlechter werden nicht verwechselt (gleicher Name, m und w)
#   5. kein Bestandswert und keine Zeilenzahl aendert sich
#   6. Befund 18: die Team-Statistik findet die Historie eines umbenannten
#      Teams - und faellt fuer nicht zugeordnete Zeilen weiter auf den
#      Namen zurueck
#   7. ON DELETE SET NULL: ein geloeschter Fahrer nimmt die Ergebniszeile
#      NICHT mit
set -uo pipefail
cd "$(dirname "$0")/.."
: "${PGHOST:=127.0.0.1}"; : "${PGPORT:=5599}"; : "${PGUSER:=postgres}"
export PGHOST PGPORT PGUSER
fehler=0
meld()   { printf '  %-58s %s\n' "$1" "$2"; }
pruefe() { if [ "$2" = "$3" ]; then meld "$1" "ok"; else meld "$1" "FEHLER: '$2' != '$3'"; fehler=$((fehler+1)); fi; }
neu()    { psql -q -c "DROP DATABASE IF EXISTS $1;" -c "CREATE DATABASE $1;" postgres >/dev/null 2>&1; }

echo "=== 1. Leere Datenbank: Runner wendet alle vier an ==="
neu b4_leer
( cd backend && DATABASE_URL="postgresql://${PGUSER}@${PGHOST}:${PGPORT}/b4_leer" \
  python3 -m app.migrations upgrade >/dev/null 2>&1 )
pruefe "0004 in schema_migrations" \
  "$(psql -tA -d b4_leer -c "SELECT count(*) FROM schema_migrations WHERE version='0004_ergebnis_ids'")" "1"

echo "=== 2. Spalten, Fremdschluessel, Indizes ==="
pruefe "race_results.rider_id + team_id vorhanden" "$(psql -tA -d b4_leer -c "
  SELECT count(*) FROM information_schema.columns
  WHERE table_name='race_results' AND column_name IN ('rider_id','team_id')")" "2"
pruefe "beide nullable" "$(psql -tA -d b4_leer -c "
  SELECT count(*) FROM information_schema.columns
  WHERE table_name='race_results' AND column_name IN ('rider_id','team_id')
    AND is_nullable='YES'")" "2"
# ON DELETE SET NULL, nicht CASCADE: ein geloeschter Fahrer darf die
# Ergebniszeile nicht mitnehmen - das Ergebnis ist auch ohne ihn ein Fakt.
pruefe "beide Fremdschluessel mit ON DELETE SET NULL" "$(psql -tA -d b4_leer -c "
  SELECT count(*) FROM pg_constraint
  WHERE conrelid='race_results'::regclass AND contype='f' AND confdeltype='n'
    AND conname LIKE '%_id_fkey'")" "2"
pruefe "zwei Teilindizes (WHERE ... IS NOT NULL)" "$(psql -tA -d b4_leer -c "
  SELECT count(*) FROM pg_indexes WHERE tablename='race_results'
    AND indexname IN ('idx_results_rider','idx_results_team')
    AND indexdef LIKE '%IS NOT NULL%'")" "2"

echo "=== 3./4./5. Befuellte Datenbank: Backfill ==="
neu b4_daten
( cd backend
  psql -q -d b4_daten -f migrations/0001_bestand.sql >/dev/null 2>&1
  psql -q -d b4_daten -f migrations/0002_gender.sql   >/dev/null 2>&1
  psql -q -d b4_daten -f migrations/0003_taxonomie.sql >/dev/null 2>&1 )

psql -q -d b4_daten -f /dev/stdin >/dev/null <<'SQL'
INSERT INTO teams (id,name,category,country,code,gender,wiki_url) VALUES
 ('uae','UAE Team Emirates XRG','wt','AE','UAE','m','https://en.wikipedia.org/wiki/UAE'),
 ('visma','Team Visma-Lease a Bike','wt','NL','TVL','m','https://en.wikipedia.org/wiki/Visma'),
 ('w--sd-worx','SD Worx-Protime','wt','NL','SDW','w','https://en.wikipedia.org/wiki/SDWorx');
INSERT INTO riders (id,name,country,wiki_url,current_team_id,gender) VALUES
 ('tadej-pogacar','Tadej Pogacar','SI','https://en.wikipedia.org/wiki/Pogacar','uae','m'),
 ('jonas-vingegaard','Jonas Vingegaard','DK','https://en.wikipedia.org/wiki/Vingegaard','visma','m'),
 ('sam-smith','Sam Smith','GB','https://en.wikipedia.org/wiki/SamSmithM','uae','m'),
 ('w--sam-smith','Sam Smith','GB','https://en.wikipedia.org/wiki/SamSmithW','w--sd-worx','w'),
 ('wechsler','Willi Wechsler','DE','https://en.wikipedia.org/wiki/Wechsler','visma','m');
-- Stationen: historische Teamnamen mit aufgeloester team_id (ueber die Wiki-URL)
INSERT INTO rider_team_stints (rider_id,team_id,team_name,start_year,end_year) VALUES
 ('tadej-pogacar','uae','UAE Team Emirates',2019,NULL),
 ('jonas-vingegaard','visma','Jumbo-Visma',2019,2023),
 ('jonas-vingegaard','visma','Team Visma-Lease a Bike',2024,NULL),
 -- derselbe Name auf zwei Teams: fuer Schritt D bewusst mehrdeutig
 ('sam-smith','uae','Doppelname',2020,2020),
 ('w--sam-smith','w--sd-worx','Doppelname',2020,2020),
 -- Wechsel mitten in der Saison: zwei Stationen decken 2022 ab, C muss passen
 ('wechsler','uae','Erstes Team',2022,2022),
 ('wechsler','visma','Zweites Team',2022,NULL);
INSERT INTO races (id,name,season,category,circuit,gender,start_date) VALUES
 ('2026-wt-tdf','Tour de France',2026,'wt',NULL,'m','2026-07-04'),
 ('2021-wt-alt','Altes Rennen',2021,'wt',NULL,'m','2021-05-01'),
 ('w--2026-wt-tdff','Tour de France Femmes',2026,'wt',NULL,'w','2026-08-01'),
 ('2022-wt-wechsel','Rennen im Wechseljahr',2022,'wt',NULL,'m','2022-06-01');
INSERT INTO race_results (race_id,stage_id,position,rider_name,team_name,time_or_gap) VALUES
 -- A trifft, B trifft (heutiger Teamname)
 ('2026-wt-tdf',NULL,1,'Tadej Pogacar','UAE Team Emirates XRG','82h'),
 -- A trifft, B nicht (Name von damals), C soll ueber die Station treffen
 ('2021-wt-alt',NULL,1,'Jonas Vingegaard','Jumbo-Visma','+1'),
 -- Fahrer unbekannt: A und C unmoeglich, D soll ueber den Altnamen treffen
 ('2021-wt-alt',NULL,2,'Unbekannter Fahrer','Jumbo-Visma','+2'),
 -- Altname mehrdeutig: D muss die Finger lassen
 ('2021-wt-alt',NULL,3,'Anderer Fahrer','Doppelname','+3'),
 -- kein Teamname
 ('2021-wt-alt',NULL,4,'Noch Einer',NULL,'+4'),
 -- gleicher Name, Frauenrennen: muss die Fahrerin treffen
 ('w--2026-wt-tdff',NULL,1,'Sam Smith','SD Worx-Protime','25h'),
 -- gleicher Name, Maennerrennen: muss den Fahrer treffen
 ('2026-wt-tdf',NULL,5,'Sam Smith','UAE Team Emirates XRG','+5'),
 -- Schreibvariante: steht weder in teams noch in einer Station, also koennen
 -- B und D nichts finden. NUR C kann das loesen, ueber die Station des
 -- Fahrers in der Saison des Rennens.
 ('2021-wt-alt',NULL,6,'Jonas Vingegaard','Team Jumbo Visma','+6'),
 -- Fahrer mit zwei Stationen in derselben Saison: C ist mehrdeutig und muss
 -- die Finger lassen, B und D finden den Namen nicht.
 ('2022-wt-wechsel',NULL,1,'Willi Wechsler','Name nur hier','1h');
SQL
pruefe "Testdaten eingespielt" "$(psql -tA -d b4_daten -c 'SELECT count(*) FROM race_results')" "9"

# Zustand VOR 0004 festhalten: Zeilenzahlen und alle Bestandsspalten.
vorher_zeilen=$(psql -tA -d b4_daten -c "
  SELECT string_agg(t||':'||n, ' ' ORDER BY t) FROM (
    SELECT 'races' t,(SELECT count(*) FROM races) n
    UNION ALL SELECT 'riders',(SELECT count(*) FROM riders)
    UNION ALL SELECT 'teams',(SELECT count(*) FROM teams)
    UNION ALL SELECT 'results',(SELECT count(*) FROM race_results)
    UNION ALL SELECT 'stints',(SELECT count(*) FROM rider_team_stints)) x")
bestand() {
  psql -tA -d b4_daten -c "
    SELECT md5(string_agg(race_id||'|'||coalesce(stage_id::text,'')||'|'||position||'|'||
                          rider_name||'|'||coalesce(team_name,'')||'|'||coalesce(time_or_gap,''),
                          E'\n' ORDER BY race_id, position))
    FROM race_results"
}
vorher_bestand=$(bestand)

( cd backend && psql -q -d b4_daten -f migrations/0004_ergebnis_ids.sql 2>&1 | grep -c "NOTICE" >/dev/null )

nachher_zeilen=$(psql -tA -d b4_daten -c "
  SELECT string_agg(t||':'||n, ' ' ORDER BY t) FROM (
    SELECT 'races' t,(SELECT count(*) FROM races) n
    UNION ALL SELECT 'riders',(SELECT count(*) FROM riders)
    UNION ALL SELECT 'teams',(SELECT count(*) FROM teams)
    UNION ALL SELECT 'results',(SELECT count(*) FROM race_results)
    UNION ALL SELECT 'stints',(SELECT count(*) FROM rider_team_stints)) x")
pruefe "Zeilenzahlen unveraendert" "$nachher_zeilen" "$vorher_zeilen"
pruefe "kein Bestandswert in race_results veraendert" "$(bestand)" "$vorher_bestand"

id_von() { psql -tA -d b4_daten -c "
  SELECT coalesce($3,'NULL') FROM race_results res
  WHERE res.race_id='$1' AND res.position=$2"; }

echo "--- Schritt A: rider_id ueber den Namen"
pruefe "Pogacar zugeordnet"            "$(id_von 2026-wt-tdf 1 rider_id)" "tadej-pogacar"
pruefe "unbekannter Fahrer bleibt NULL" "$(id_von 2021-wt-alt 2 rider_id)" "NULL"
echo "--- Schritt 4: Geschlecht nicht verwechselt"
pruefe "Frauenrennen -> Fahrerin"      "$(id_von w--2026-wt-tdff 1 rider_id)" "w--sam-smith"
pruefe "Maennerrennen -> Fahrer"       "$(id_von 2026-wt-tdf 5 rider_id)" "sam-smith"
echo "--- Schritt B: team_id ueber den heutigen Teamnamen"
pruefe "UAE zugeordnet"                "$(id_von 2026-wt-tdf 1 team_id)" "uae"
pruefe "SD Worx (Frauen) zugeordnet"   "$(id_von w--2026-wt-tdff 1 team_id)" "w--sd-worx"
echo "--- Schritt C: team_id ueber die Station in der Saison"
# Diese Zeile ist der eigentliche C-Test: die Schreibvariante "Team Jumbo
# Visma" steht in keiner teams-Zeile und in keiner Station, B und D koennen
# sie also nicht finden. Die erste Gegenprobe zu C bestand noch, weil D
# denselben Fall mitgeloest hat - der Test behauptete damit etwas, das er
# nicht prueft.
pruefe "Schreibvariante, nur ueber die Station"  "$(id_von 2021-wt-alt 6 team_id)" "visma"
pruefe "zwei Stationen in der Saison -> NULL"    "$(id_von 2022-wt-wechsel 1 team_id)" "NULL"
echo "--- Schritt D: team_id ueber den Altnamen allein"
pruefe "Altname + unbekannter Fahrer"  "$(id_von 2021-wt-alt 2 team_id)" "visma"
pruefe "mehrdeutiger Altname -> NULL"  "$(id_von 2021-wt-alt 3 team_id)" "NULL"
pruefe "kein Teamname -> NULL"         "$(id_von 2021-wt-alt 4 team_id)" "NULL"

echo "=== 6. Befund 18: die Statistik findet die umbenannte Historie ==="
# Das Team heisst heute "Team Visma-Lease a Bike"; die Ergebnisse von 2021
# stehen unter "Jumbo-Visma" und "Team Jumbo Visma". Der frühere Vergleich
# res.team_name = teams.name findet davon NICHTS.
alt_zaehlung=$(psql -tA -d b4_daten -c "
  SELECT count(*) FILTER (WHERE res.position = 1)
  FROM race_results res JOIN races r ON r.id = res.race_id
  WHERE r.season = 2021 AND res.team_name = 'Team Visma-Lease a Bike'")
pruefe "alter Namensvergleich findet 0 Siege" "$alt_zaehlung" "0"

neue_zaehlung=$( cd backend && DATABASE_URL="postgresql://${PGUSER}@${PGHOST}:${PGPORT}/b4_daten" python3 -c "
from app import db_races
s = db_races.get_team_season_stats('visma', 'Team Visma-Lease a Bike', 2021)
w = db_races.get_team_season_wins('visma', 'Team Visma-Lease a Bike', 2021)
print(f\"{s['wins']}/{s['podiums']}/{s['top_ten']}/{s['races']}/{len(w)}\")" 2>/dev/null )
# Erwartet: Platz 1 (Sieg), Platz 2, Platz 6 - alle drei ueber team_id
# zugeordnet. 1 Sieg, 2 Podestplaetze, 3 Top-10, 1 Rennen, 1 Siegeintrag.
pruefe "ueber team_id: Siege/Podeste/Top10/Rennen/Siegliste" "$neue_zaehlung" "1/2/3/1/1"

# Der Rueckfall auf den Namen muss weiter greifen: fuer eine Zeile OHNE
# team_id zaehlt der Name wie vorher.
psql -q -d b4_daten -c "
  INSERT INTO races (id,name,season,category,gender,start_date)
    VALUES ('2019-wt-ohne','Rennen ohne Zuordnung',2019,'wt','m','2019-05-01');
  INSERT INTO race_results (race_id,position,rider_name,team_name)
    VALUES ('2019-wt-ohne',1,'Niemand','Team Visma-Lease a Bike');" >/dev/null
pruefe "Rueckfall auf den Namen bei team_id IS NULL" "$( cd backend &&   DATABASE_URL="postgresql://${PGUSER}@${PGHOST}:${PGPORT}/b4_daten" python3 -c "
from app import db_races
print(db_races.get_team_season_stats('visma','Team Visma-Lease a Bike',2019)['wins'])" 2>/dev/null )" "1"

echo "=== 7. ON DELETE SET NULL: Ergebnis ueberlebt den Fahrer ==="
psql -q -d b4_daten -c "DELETE FROM riders WHERE id='tadej-pogacar'" >/dev/null
pruefe "Ergebniszeile noch da"  "$(psql -tA -d b4_daten -c "
  SELECT count(*) FROM race_results WHERE race_id='2026-wt-tdf' AND position=1")" "1"
pruefe "rider_id jetzt NULL"    "$(id_von 2026-wt-tdf 1 rider_id)" "NULL"
pruefe "rider_name unveraendert" "$(psql -tA -d b4_daten -c "
  SELECT rider_name FROM race_results WHERE race_id='2026-wt-tdf' AND position=1")" "Tadej Pogacar"

echo
if [ "$fehler" -eq 0 ]; then echo "Alle Pruefungen bestanden."; else echo "$fehler Pruefung(en) fehlgeschlagen."; fi
exit "$fehler"
