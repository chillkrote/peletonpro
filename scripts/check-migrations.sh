#!/usr/bin/env bash
# Prueft den Migrations-Runner gegen eine echte Postgres-Instanz.
#
#   PGHOST=127.0.0.1 PGPORT=5599 PGUSER=postgres ./scripts/check-migrations.sh
#
# Braucht psql und eine Instanz, auf der Datenbanken angelegt werden duerfen.
# Die Testdatenbanken heissen mig_* und werden jedes Mal neu erzeugt.
#
# Geprueft werden sechs Dinge:
#   1. leeres Schema wird korrekt aufgebaut
#   2. ein zweiter Lauf tut nichts
#   3. eine Datenbank im heutigen Produktionsstand (Tabellen inkl. der per
#      ALTER ergaenzten Spalten, mit Daten) wird migriert, ohne dass sich
#      eine Zeile oder ein Feld aendert
#   4. das Schema aus (1) ist identisch zu dem aus (3) - 0001 erzeugt also
#      wirklich den Produktionsstand
#   5. eine nachtraeglich geaenderte, schon angewendete Migration bricht ab
#   6. eine fehlerhafte Migration laesst nichts halb angewendet zurueck
#
# Der Nebenlaeufigkeits-Test (zwei gleichzeitige Laeufe, Advisory Lock)
# steht in Schritt 7.
set -uo pipefail
cd "$(dirname "$0")/.."

: "${PGHOST:=127.0.0.1}"; : "${PGPORT:=5599}"; : "${PGUSER:=postgres}"
export PGHOST PGPORT PGUSER
BASIS="postgresql://${PGUSER}@${PGHOST}:${PGPORT}"
MIG="backend/migrations"
fehler=0


# Gemeinsamer Wertevergleich (eine Kopie statt drei).
source "$(dirname "$0")/_datenvergleich.sh"

meld()  { printf '  %-62s %s\n' "$1" "$2"; }
pruefe() { if [ "$2" = "$3" ]; then meld "$1" "ok"; else meld "$1" "FEHLER: $2 != $3"; fehler=$((fehler+1)); fi; }

neu() { psql -q -c "DROP DATABASE IF EXISTS $1;" -c "CREATE DATABASE $1;" postgres >/dev/null; }
zaehle() {
  psql -tA -d "$1" -c "SELECT 'teams='||(SELECT count(*) FROM teams)
    ||' riders='||(SELECT count(*) FROM riders)
    ||' stints='||(SELECT count(*) FROM rider_team_stints)
    ||' punkte='||(SELECT count(*) FROM rider_season_points)
    ||' races='||(SELECT count(*) FROM races)
    ||' etappen='||(SELECT count(*) FROM race_stages)
    ||' ergebnisse='||(SELECT count(*) FROM race_results)"
}
# Spaltenliste je Tabelle, wie sie VOR dem Migrieren aussieht. Wird als
# Datei festgehalten und nachher wiederverwendet.
#
# Der Grund: eine Migration darf Spalten HINZUFUEGEN (0002 tut das mit
# gender). Eine Pruefsumme ueber die ganze Zeile (x::text) aendert sich
# dadurch zwangsläufig und meldet einen Fehler, wo keiner ist. Gemeint ist
# aber: keine Zeile verloren, kein BESTEHENDER Wert veraendert. Also wird
# nur ueber die Spalten geprueft, die es vorher schon gab - und die Liste
# kommt aus dem Katalog, damit sie sich nicht mit jeder Migration von Hand
# nachziehen laesst.
spalten_merken() {
  psql -tA -d "$1" -c "
    SELECT table_name||':'||string_agg(column_name, ',' ORDER BY ordinal_position)
    FROM information_schema.columns
    WHERE table_schema='public' AND table_name <> 'schema_migrations'
    GROUP BY table_name ORDER BY table_name"
}
# Der Wertevergleich steht in scripts/_datenvergleich.sh - gemeinsam mit
# check-migration-0002.sh und -0003.sh, siehe dort.
daten_md5() { vergleich_md5 "$1" "$2"; }
schema_abbild() {
  psql -tA -d "$1" -c "
    SELECT 'SPALTE '||table_name||'.'||column_name||' '||data_type||' null='||is_nullable
    FROM information_schema.columns WHERE table_schema='public' AND table_name<>'schema_migrations'
    UNION ALL
    SELECT 'INDEX '||tablename||' '||indexdef FROM pg_indexes
    WHERE schemaname='public' AND tablename<>'schema_migrations'
    UNION ALL
    SELECT 'CONSTRAINT '||rel.relname||' '||pg_get_constraintdef(con.oid)
    FROM pg_constraint con JOIN pg_class rel ON rel.oid=con.conrelid
    JOIN pg_namespace n ON n.oid=rel.relnamespace
    WHERE n.nspname='public' AND rel.relname<>'schema_migrations'
    ORDER BY 1"
}
runner() { ( cd backend && DATABASE_URL="$1" python3 -m app.migrations "$2" 2>&1 ); }

echo "=== 1. Leeres Schema aufbauen ==="
neu mig_leer
a1=$(runner "$BASIS/mig_leer" upgrade)
# Die Abschlusszeile nennt die Zahl; die Log-Zeilen "wird angewendet"/
# "angewendet" pro Migration sind hier nicht gemeint.
pruefe "alle Migrationsdateien angewendet" \
  "$(echo "$a1" | sed -n 's/^\([0-9]*\) Migration(en) angewendet\.$/\1/p')" \
  "$(ls $MIG/[0-9]*.sql | wc -l | tr -d ' ')"
pruefe "schema_migrations existiert" \
  "$(psql -tA -d mig_leer -c "SELECT count(*) FROM pg_tables WHERE tablename='schema_migrations'")" "1"

echo "=== 2. Zweiter Lauf tut nichts ==="
a2=$(runner "$BASIS/mig_leer" upgrade)
pruefe "meldet 0 Migrationen" "$(echo "$a2" | grep -c '^0 Migration')" "1"
pruefe "keine Dubletten in schema_migrations" \
  "$(psql -tA -d mig_leer -c "SELECT count(*) FROM (SELECT version FROM schema_migrations GROUP BY version HAVING count(*)>1) x")" "0"

echo "=== 3. Produktionsstand migrieren, ohne Daten anzufassen ==="
neu mig_prod
# Der Stand, den Produktion vor den Migrationen hatte. Das ist inzwischen
# 0001_bestand.sql aus origin/main und nicht mehr die SCHEMA-String-Literale
# in db.py/db_races.py - die hat genau diese Migration entfernt. Als das
# Skript noch die Strings suchte, fand es nach dem Merge nichts mehr und
# Schritt 3 wurde stillschweigend uebersprungen; die UEBERSPRUNGEN-Meldung
# unten hat das sichtbar gemacht.
git show origin/main:backend/migrations/0001_bestand.sql > /tmp/prod_schema.sql 2>/dev/null
if [ -s /tmp/prod_schema.sql ]; then
  psql -q -d mig_prod -f /tmp/prod_schema.sql >/dev/null 2>&1
  psql -q -d mig_prod -f /dev/stdin >/dev/null <<'SQL'
-- Testdaten. Bewusst im Skript und nicht in einer externen Datei: eine
-- fehlende externe Datei liesse das Seeding still scheitern, und dann
-- verglichen die Pruefungen unten 0 Zeilen mit 0 Zeilen und bestanden
-- scheinbar. Genau das ist beim ersten Lauf passiert.
-- Enthaelt absichtlich Umlaute, Akzente und Halbgeviertstriche, damit ein
-- Kodierungsproblem in einer Migration auffaellt.
INSERT INTO teams (id,name,category,country,code,logo,wiki_url) VALUES
 ('uae-team-emirates-xrg','UAE Team Emirates XRG','wt','United Arab Emirates','UAE','https://upload.wikimedia.org/uae.png','https://en.wikipedia.org/wiki/UAE_Team_Emirates'),
 ('team-visma-lease-a-bike','Team Visma–Lease a Bike','wt','Netherlands','TEA',NULL,'https://en.wikipedia.org/wiki/Team_Visma'),
 ('ineos-grenadiers','INEOS Grenadiers','wt','United Kingdom','INE',NULL,'https://en.wikipedia.org/wiki/Ineos_Grenadiers');
INSERT INTO riders (id,name,first_name,last_name,country,birth_date,wiki_url,current_team_id,history_fetched_at,strava_url,strava_checked_at) VALUES
 ('tadej-poga-ar','Tadej Pogačar','Tadej','Pogačar','Slovenia','1998-09-21','https://en.wikipedia.org/wiki/Tadej_Poga%C4%8Dar','uae-team-emirates-xrg',now(),'https://strava.com/athletes/1',now()),
 ('jonas-vingegaard','Jonas Vingegaard','Jonas','Vingegaard','Denmark','1996-12-10','https://en.wikipedia.org/wiki/Jonas_Vingegaard','team-visma-lease-a-bike',NULL,NULL,NULL),
 ('egan-bernal','Egan Bernal','Egan','Bernal','Colombia',NULL,'https://en.wikipedia.org/wiki/Egan_Bernal','ineos-grenadiers',now(),NULL,NULL);
INSERT INTO rider_team_stints (rider_id,team_id,team_name,start_year,end_year) VALUES
 ('tadej-poga-ar','uae-team-emirates-xrg','UAE Team Emirates XRG',2019,NULL),
 ('jonas-vingegaard','team-visma-lease-a-bike','Team Visma–Lease a Bike',2019,NULL),
 ('egan-bernal','ineos-grenadiers','INEOS Grenadiers',2018,2025);
INSERT INTO rider_season_points (rider_id,year,uci_points) VALUES
 ('tadej-poga-ar',2026,4200),('jonas-vingegaard',2026,NULL);
INSERT INTO races (id,name,season,category,circuit,start_date,end_date,num_stages,distance_km,wiki_url,results_fetched_at) VALUES
 ('2026-wt-tour-de-france','Tour de France',2026,'wt',NULL,'2026-07-04','2026-07-26',21,3320.0,'https://en.wikipedia.org/wiki/2026_Tour_de_France',now()),
 ('2026-wt-milan-san-remo','Milan–San Remo',2026,'wt',NULL,'2026-03-21','2026-03-21',NULL,294.0,NULL,now()),
 ('2025-continental-europe-tour-of-hellas','Tour of Hellas',2025,'continental','europe','2025-04-10','2025-04-13',4,600.0,NULL,NULL);
INSERT INTO race_stages (race_id,stage_number,stage_date,start_location,end_location,distance_km) VALUES
 ('2026-wt-tour-de-france',1,'2026-07-04','Lille','Lille',185.0),
 ('2026-wt-tour-de-france',2,'2026-07-05','Lille','Boulogne',209.0);
INSERT INTO race_results (race_id,stage_id,position,rider_name,team_name,time_or_gap) VALUES
 ('2026-wt-tour-de-france',NULL,1,'Tadej Pogačar','UAE Team Emirates XRG','80h 12'' 30"'),
 ('2026-wt-tour-de-france',NULL,2,'Jonas Vingegaard','Team Visma–Lease a Bike','+ 3'' 20"'),
 ('2026-wt-milan-san-remo',NULL,1,'Mathieu van der Poel','Alpecin–Deceuninck','6h 30'' 00"');
INSERT INTO race_history_seed_log (category,circuit,season,race_count) VALUES ('wt','',2026,2);
SQL
  vorher=$(zaehle mig_prod)
  spalten_vorher=$(spalten_merken mig_prod)
  vorher_md5=$(daten_md5 mig_prod "$spalten_vorher")
  # Ein leeres Seeding wuerde alle Vergleiche unten trivial bestehen lassen.
  if echo "$vorher" | grep -q 'teams=0'; then
    meld "Testdaten eingespielt" "FEHLER: keine Zeilen - Vergleiche waeren wertlos"
    fehler=$((fehler+1))
  else
    meld "Testdaten eingespielt" "ok"
  fi
  runner "$BASIS/mig_prod" upgrade >/dev/null
  nachher=$(zaehle mig_prod)
  nachher_md5=$(daten_md5 mig_prod "$spalten_vorher")
  pruefe "Zeilenzahlen unveraendert" "$vorher" "$nachher"
  if [ "$vorher_md5" = "$nachher_md5" ]; then
    meld "kein bestehender Spaltenwert veraendert" "ok"
  else
    meld "Spaltenvergleich" "FEHLER:"; diff <(echo "$vorher_md5") <(echo "$nachher_md5")
    fehler=$((fehler+1))
  fi
  echo "    vorher:  $vorher"

  echo "=== 4. 0001 erzeugt genau den Produktionsstand ==="
  pruefe "Schema (Spalten/Indizes/Constraints) identisch" \
    "$(schema_abbild mig_leer | md5sum)" "$(schema_abbild mig_prod | md5sum)"
else
  meld "Produktionsstand aus origin/main lesbar" "FEHLER: 0001_bestand.sql nicht abrufbar"
  fehler=$((fehler+1))
fi

echo "=== 5. Geaenderte, schon angewendete Migration bricht ab ==="
erste=$(ls $MIG/[0-9]*.sql | head -1)
cp "$erste" /tmp/erste.bak
echo "-- nachtraeglich angehaengt" >> "$erste"
a5=$(runner "$BASIS/mig_leer" upgrade)
pruefe "Abbruch mit Hinweis auf die Datei" "$(echo "$a5" | grep -c 'nachträglich geändert')" "1"
pruefe "status meldet GEAENDERT" "$(runner "$BASIS/mig_leer" status | grep -c 'GEÄNDERT')" "1"
cp /tmp/erste.bak "$erste"
pruefe "nach dem Zuruecksetzen wieder angewendet" \
  "$(runner "$BASIS/mig_leer" status | grep -c 'GEÄNDERT')" "0"

echo "=== 6. Fehlerhafte Migration laesst nichts halb angewendet ==="
cat > "$MIG/9999_kaputt.sql" <<'SQL'
CREATE TABLE erste_haelfte (id INTEGER);
DIES IST KEIN SQL;
SQL
runner "$BASIS/mig_leer" upgrade >/dev/null 2>&1
pruefe "Tabelle aus der ersten Zeile nicht angelegt" \
  "$(psql -tA -d mig_leer -c "SELECT count(*) FROM pg_tables WHERE tablename='erste_haelfte'")" "0"
pruefe "kein Eintrag in schema_migrations" \
  "$(psql -tA -d mig_leer -c "SELECT count(*) FROM schema_migrations WHERE version LIKE '9999%'")" "0"
rm -f "$MIG/9999_kaputt.sql"

echo "=== 7. Zwei gleichzeitige Laeufe (Advisory Lock) ==="
neu mig_lock
cat > "$MIG/9998_langsam.sql" <<'SQL'
SELECT pg_sleep(4);
CREATE TABLE lock_test (id INTEGER PRIMARY KEY);
SQL
( runner "$BASIS/mig_lock" upgrade > /tmp/lauf_a.log 2>&1 ) &
( runner "$BASIS/mig_lock" upgrade > /tmp/lauf_b.log 2>&1 ) &
wait
pruefe "die langsame Migration genau einmal angewendet" \
  "$(psql -tA -d mig_lock -c "SELECT count(*) FROM schema_migrations WHERE version='9998_langsam'")" "1"
pruefe "ihre Tabelle genau einmal angelegt" \
  "$(psql -tA -d mig_lock -c "SELECT count(*) FROM pg_tables WHERE tablename='lock_test'")" "1"
pruefe "kein Lauf mit Traceback" \
  "$(grep -l Traceback /tmp/lauf_a.log /tmp/lauf_b.log 2>/dev/null | wc -l | tr -d ' ')" "0"
rm -f "$MIG/9998_langsam.sql"

echo
if [ "$fehler" -eq 0 ]; then echo "Alle Pruefungen bestanden."; else echo "$fehler Pruefung(en) fehlgeschlagen."; fi
exit $((fehler > 0 ? 1 : 0))
