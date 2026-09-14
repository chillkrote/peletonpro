#!/usr/bin/env bash
# Prueft Migration 0002 (Geschlechts-Dimension) gegen eine echte
# Postgres-Instanz.
#
#   PGPORT=5599 ./scripts/check-migration-0002.sh
#
# Vorgehen: eine Datenbank auf den Stand VOR 0002 bringen (Migration 0001),
# mit Testdaten fuellen, jede Spalte jeder Tabelle als Pruefsumme festhalten,
# dann 0002 fahren und dieselben Pruefsummen erneut bilden. Verglichen wird
# DIESELBE Datenbank vor und nach der Migration - nicht zwei getrennt
# geseedete, denn last_updated/seeded_at stehen auf now() und weichen dann
# ab, ohne dass die Migration daran schuld ist. Genau darauf ist der erste
# Versuch hereingefallen.
#
# Geprueft wird:
#   1. Zeilenzahlen aller acht Tabellen unveraendert
#   2. jede Spalte ausser gender unveraendert (Pruefsumme pro Tabelle ueber
#      eine ausdrueckliche Spaltenliste, gender ausgenommen)
#   3. der Bestand hat ueberall gender='m'
#   4. kein Fremdschluessel zeigt ins Leere (jede Referenz einzeln)
#   5. ein Maenner- und ein Frauen-Rennen gleichen Namens in derselben
#      Saison ergeben ZWEI Zeilen - der Fall aus Befund 7
#   6. der CHECK laesst nur 'm'/'w' zu
set -uo pipefail
cd "$(dirname "$0")/.."

: "${PGHOST:=127.0.0.1}"; : "${PGPORT:=5599}"; : "${PGUSER:=postgres}"
export PGHOST PGPORT PGUSER
DB=mig0002_test
fehler=0

# Gemeinsamer Wertevergleich (eine Kopie statt drei).
source "$(dirname "$0")/_datenvergleich.sh"

meld()   { printf '  %-56s %s\n' "$1" "$2"; }
pruefe() { if [ "$2" = "$3" ]; then meld "$1" "ok"; else meld "$1" "FEHLER: '$2' != '$3'"; fehler=$((fehler+1)); fi; }

# Spaltenlisten OHNE gender - das ist der Punkt der Pruefung.
SPALTEN=(
 "teams:id,name,category,country,code,logo,wiki_url,last_updated"
 "riders:id,name,first_name,last_name,country,birth_date,wiki_url,current_team_id,history_fetched_at,strava_url,strava_checked_at,last_updated"
 "races:id,name,season,category,circuit,start_date,end_date,num_stages,distance_km,elevation_m,wiki_url,organizer_website,results_fetched_at,last_updated"
 "rider_team_stints:id,rider_id,team_id,team_name,start_year,end_year"
 "rider_season_points:rider_id,year,uci_points"
 "race_stages:id,race_id,stage_number,stage_date,distance_km,elevation_m,start_location,end_location"
 "race_results:id,race_id,stage_id,position,rider_name,team_name,time_or_gap"
 "race_history_seed_log:category,circuit,season,race_count,seeded_at"
)
zaehle() {
  psql -tA -d "$DB" -c "SELECT 'teams='||(SELECT count(*) FROM teams)
    ||' riders='||(SELECT count(*) FROM riders)
    ||' stints='||(SELECT count(*) FROM rider_team_stints)
    ||' punkte='||(SELECT count(*) FROM rider_season_points)
    ||' races='||(SELECT count(*) FROM races)
    ||' etappen='||(SELECT count(*) FROM race_stages)
    ||' ergebnisse='||(SELECT count(*) FROM race_results)
    ||' seedlog='||(SELECT count(*) FROM race_history_seed_log)"
}
# Wertevergleich gemeinsam mit check-migrations.sh und -0003.sh, siehe
# scripts/_datenvergleich.sh.
spalten_md5() { vergleich_md5 "$DB" "$(printf '%s\n' "${SPALTEN[@]}")"; }

psql -q -c "DROP DATABASE IF EXISTS $DB;" -c "CREATE DATABASE $DB;" postgres >/dev/null

echo "=== Stand VOR 0002 herstellen (nur Migration 0001) ==="
psql -q -d "$DB" -f backend/migrations/0001_bestand.sql >/dev/null 2>&1
pruefe "0001 angewendet, 8 Tabellen" \
  "$(psql -tA -d "$DB" -c "SELECT count(*) FROM pg_tables WHERE schemaname='public'")" "8"
pruefe "gender-Spalte gibt es noch NICHT" \
  "$(psql -tA -d "$DB" -c "SELECT count(*) FROM information_schema.columns WHERE table_name='races' AND column_name='gender'")" "0"

psql -q -d "$DB" -f - >/dev/null <<'SQL'
INSERT INTO teams (id,name,category,country,code,logo,wiki_url) VALUES
 ('uae-team-emirates-xrg','UAE Team Emirates XRG','wt','United Arab Emirates','UAE','https://upload.wikimedia.org/uae.png','https://en.wikipedia.org/wiki/UAE_Team_Emirates'),
 ('team-visma-lease-a-bike','Team Visma–Lease a Bike','wt','Netherlands','TEA',NULL,'https://en.wikipedia.org/wiki/Team_Visma'),
 ('ineos-grenadiers','INEOS Grenadiers','wt','United Kingdom','INE',NULL,'https://en.wikipedia.org/wiki/Ineos_Grenadiers');
INSERT INTO riders (id,name,first_name,last_name,country,birth_date,wiki_url,current_team_id,history_fetched_at,strava_url,strava_checked_at) VALUES
 ('tadej-poga-ar','Tadej Pogačar','Tadej','Pogačar','Slovenia','1998-09-21','https://en.wikipedia.org/wiki/Tadej_Poga%C4%8Dar','uae-team-emirates-xrg',now(),'https://strava.com/athletes/1',now()),
 ('simon-yates','Simon Yates','Simon','Yates','United Kingdom','1992-08-07','https://en.wikipedia.org/wiki/Simon_Yates_(cyclist)','team-visma-lease-a-bike',now(),NULL,NULL),
 ('egan-bernal','Egan Bernal','Egan','Bernal','Colombia',NULL,'https://en.wikipedia.org/wiki/Egan_Bernal','ineos-grenadiers',NULL,NULL,NULL);
INSERT INTO rider_team_stints (rider_id,team_id,team_name,start_year,end_year) VALUES
 ('tadej-poga-ar','uae-team-emirates-xrg','UAE Team Emirates XRG',2019,NULL),
 ('simon-yates','team-visma-lease-a-bike','Team Visma–Lease a Bike',2024,NULL),
 ('egan-bernal','ineos-grenadiers','INEOS Grenadiers',2018,2025);
INSERT INTO rider_season_points (rider_id,year,uci_points) VALUES ('tadej-poga-ar',2026,4200),('simon-yates',2026,NULL);
INSERT INTO races (id,name,season,category,circuit,start_date,end_date,num_stages,distance_km,wiki_url,results_fetched_at) VALUES
 ('2026-wt-ronde-van-vlaanderen','Ronde van Vlaanderen',2026,'wt',NULL,'2026-04-05','2026-04-05',NULL,270.0,NULL,now()),
 ('2026-wt-tour-de-france','Tour de France',2026,'wt',NULL,'2026-07-04','2026-07-26',21,3320.0,NULL,now()),
 ('2025-continental-europe-tour-of-hellas','Tour of Hellas',2025,'continental','europe','2025-04-10','2025-04-13',4,600.0,NULL,NULL);
INSERT INTO race_stages (race_id,stage_number,stage_date,start_location,end_location,distance_km) VALUES
 ('2026-wt-tour-de-france',1,'2026-07-04','Lille','Lille',185.0);
INSERT INTO race_results (race_id,stage_id,position,rider_name,team_name,time_or_gap) VALUES
 ('2026-wt-ronde-van-vlaanderen',NULL,1,'Mathieu van der Poel','Alpecin–Deceuninck','6h'),
 ('2026-wt-tour-de-france',NULL,1,'Tadej Pogačar','UAE Team Emirates XRG','80h');
INSERT INTO race_history_seed_log (category,circuit,season,race_count) VALUES ('wt','',2026,2);
SQL
vorher=$(zaehle); vorher_md5=$(spalten_md5)
if echo "$vorher" | grep -q 'teams=0'; then
  meld "Testdaten eingespielt" "FEHLER: keine Zeilen - Vergleiche waeren wertlos"; fehler=$((fehler+1))
else
  meld "Testdaten eingespielt" "ok   $vorher"
fi

echo "=== 0002 fahren ==="
( cd backend && DATABASE_URL="postgresql://${PGUSER}@${PGHOST}:${PGPORT}/${DB}" \
  python3 -m app.migrations upgrade >/dev/null 2>&1 )
pruefe "0002 steht in schema_migrations" \
  "$(psql -tA -d "$DB" -c "SELECT count(*) FROM schema_migrations WHERE version='0002_gender'")" "1"

echo "=== 1. Zeilenzahlen ==="
pruefe "unveraendert" "$vorher" "$(zaehle)"

echo "=== 2. Jede Spalte ausser gender unveraendert ==="
nachher_md5=$(spalten_md5)
if [ "$vorher_md5" = "$nachher_md5" ]; then
  meld "alle 8 Tabellen, alle Spalten ausser gender" "ok"
else
  meld "Spaltenvergleich" "FEHLER:"; diff <(echo "$vorher_md5") <(echo "$nachher_md5"); fehler=$((fehler+1))
fi

echo "=== 3. Bestand hat ueberall gender='m' ==="
for t in races riders teams; do
  pruefe "$t: alle Zeilen 'm'" \
    "$(psql -tA -d "$DB" -c "SELECT count(*) FROM $t WHERE gender <> 'm'")" "0"
done

echo "=== 4. Fremdschluessel ==="
pruefe "keine verwaiste Referenz (7 Beziehungen)" "$(psql -tA -d "$DB" -c "
 SELECT (SELECT count(*) FROM riders r WHERE r.current_team_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM teams t WHERE t.id=r.current_team_id))
      + (SELECT count(*) FROM rider_team_stints s WHERE NOT EXISTS (SELECT 1 FROM riders r WHERE r.id=s.rider_id))
      + (SELECT count(*) FROM rider_team_stints s WHERE s.team_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM teams t WHERE t.id=s.team_id))
      + (SELECT count(*) FROM rider_season_points p WHERE NOT EXISTS (SELECT 1 FROM riders r WHERE r.id=p.rider_id))
      + (SELECT count(*) FROM race_stages g WHERE NOT EXISTS (SELECT 1 FROM races x WHERE x.id=g.race_id))
      + (SELECT count(*) FROM race_results e WHERE NOT EXISTS (SELECT 1 FROM races x WHERE x.id=e.race_id))
      + (SELECT count(*) FROM race_results e WHERE e.stage_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM race_stages g WHERE g.id=e.stage_id))")" "0"

echo "=== 5. Der Fall aus Befund 7: gleicher Name, gleiche Saison, zwei Zeilen ==="
neue_id=$( cd backend && DATABASE_URL="postgresql://${PGUSER}@${PGHOST}:${PGPORT}/${DB}" python3 -c "
import sys; sys.path.insert(0,'.')
import logging; logging.disable(logging.CRITICAL)
from app.db_races import upsert_race_skeleton
print(upsert_race_skeleton(season=2026, category='wt', name='Ronde van Vlaanderen',
                start_date='2026-04-05', end_date='2026-04-05',
                wiki_url=None, gender='w'))" )
pruefe "Frauen-Rennen bekommt eigene ID" "$neue_id" "w--2026-wt-ronde-van-vlaanderen"
pruefe "jetzt ZWEI Zeilen mit diesem Namen in 2026" \
  "$(psql -tA -d "$DB" -c "SELECT count(*) FROM races WHERE name='Ronde van Vlaanderen' AND season=2026")" "2"
pruefe "eine 'm', eine 'w'" \
  "$(psql -tA -d "$DB" -c "SELECT string_agg(gender,',' ORDER BY gender) FROM races WHERE name='Ronde van Vlaanderen' AND season=2026")" "m,w"
pruefe "das Maenner-Rennen ist unveraendert da" \
  "$(psql -tA -d "$DB" -c "SELECT count(*) FROM races WHERE id='2026-wt-ronde-van-vlaanderen' AND gender='m'")" "1"

echo "=== 6. CHECK laesst nur 'm'/'w' zu ==="
abgelehnt=$(psql -tA -d "$DB" -c "UPDATE races SET gender='x' WHERE id='2026-wt-tour-de-france'" 2>&1 | grep -c "races_gender_check")
pruefe "gender='x' wird abgelehnt" "$abgelehnt" "1"

echo
if [ "$fehler" -eq 0 ]; then echo "Alle Pruefungen bestanden."; else echo "$fehler Pruefung(en) fehlgeschlagen."; fi
exit $((fehler > 0 ? 1 : 0))
