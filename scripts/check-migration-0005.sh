#!/usr/bin/env bash
# Prueft Migration 0005 (name_source, Befund 16).
#
#   PGPORT=5599 ./scripts/check-migration-0005.sh
#
# Geprueft wird:
#   1. der Runner wendet alle fuenf Migrationen auf einer leeren Datenbank an
#   2. Spalte, CHECK und Teilindex sind wie vorgesehen
#   3. eine befuellte Datenbank wird migriert, ohne dass sich eine Zeilenzahl
#      oder ein bestehender Spaltenwert aendert - insbesondere kein Name
#   4. der CHECK laesst genau die drei vorgesehenen Zustaende zu
#   5. alle Bestandszeilen starten als NULL, stehen also im Rueckstand des
#      Jobs (haetten sie 'heuristik', wuerde nie jemand nachfragen)
set -uo pipefail
cd "$(dirname "$0")/.."
: "${PGHOST:=127.0.0.1}"; : "${PGPORT:=5599}"; : "${PGUSER:=postgres}"
export PGHOST PGPORT PGUSER
fehler=0
meld()   { printf '  %-58s %s\n' "$1" "$2"; }
pruefe() { if [ "$2" = "$3" ]; then meld "$1" "ok"; else meld "$1" "FEHLER: '$2' != '$3'"; fehler=$((fehler+1)); fi; }
neu()    { psql -q -c "DROP DATABASE IF EXISTS $1;" -c "CREATE DATABASE $1;" postgres >/dev/null 2>&1; }

echo "=== 1. Leere Datenbank ==="
neu n5_leer
( cd backend && DATABASE_URL="postgresql://${PGUSER}@${PGHOST}:${PGPORT}/n5_leer" \
  python3 -m app.migrations upgrade >/dev/null 2>&1 )
pruefe "0005 in schema_migrations" "$(psql -tA -d n5_leer -c \
  "SELECT count(*) FROM schema_migrations WHERE version='0005_namensquelle'")" "1"

echo "=== 2. Spalte, CHECK, Teilindex ==="
pruefe "riders.name_source vorhanden und nullable" "$(psql -tA -d n5_leer -c "
  SELECT is_nullable FROM information_schema.columns
  WHERE table_name='riders' AND column_name='name_source'")" "YES"
pruefe "CHECK-Constraint gesetzt" "$(psql -tA -d n5_leer -c "
  SELECT count(*) FROM pg_constraint
  WHERE conname='riders_name_source_check' AND contype='c'")" "1"
pruefe "Teilindex (WHERE name_source IS NULL)" "$(psql -tA -d n5_leer -c "
  SELECT count(*) FROM pg_indexes WHERE indexname='idx_riders_missing_name_source'
    AND indexdef LIKE '%name_source IS NULL%'")" "1"

echo "=== 3. Befuellte Datenbank: nichts veraendert ==="
neu n5_daten
( cd backend
  for m in 0001_bestand 0002_gender 0003_taxonomie 0004_ergebnis_ids; do
    psql -q -d n5_daten -f "migrations/$m.sql" >/dev/null 2>&1
  done )
psql -q -d n5_daten -f /dev/stdin >/dev/null <<'SQL'
INSERT INTO teams (id,name,category,country,code,gender,wiki_url) VALUES
 ('uae','UAE Team Emirates XRG','wt','AE','UAE','m','https://en.wikipedia.org/wiki/UAE');
INSERT INTO riders (id,name,first_name,last_name,country,wiki_url,current_team_id,gender) VALUES
 ('juan-ayuso-pesquera','Juan Ayuso Pesquera','Juan Ayuso','Pesquera','ES','https://en.wikipedia.org/wiki/A','uae','m'),
 ('tadej-pogacar','Tadej Pogacar','Tadej','Pogacar','SI','https://en.wikipedia.org/wiki/P','uae','m');
SQL
pruefe "Testdaten eingespielt" "$(psql -tA -d n5_daten -c 'SELECT count(*) FROM riders')" "2"

namen_vorher=$(psql -tA -d n5_daten -c "
  SELECT md5(string_agg(id||'|'||name||'|'||coalesce(first_name,'')||'|'||coalesce(last_name,''),
                        E'\n' ORDER BY id)) FROM riders")
zeilen_vorher=$(psql -tA -d n5_daten -c "SELECT count(*) FROM riders")

( cd backend && psql -q -d n5_daten -f migrations/0005_namensquelle.sql >/dev/null 2>&1 )

pruefe "Zeilenzahl unveraendert" "$(psql -tA -d n5_daten -c 'SELECT count(*) FROM riders')" "$zeilen_vorher"
pruefe "kein Name veraendert" "$(psql -tA -d n5_daten -c "
  SELECT md5(string_agg(id||'|'||name||'|'||coalesce(first_name,'')||'|'||coalesce(last_name,''),
                        E'\n' ORDER BY id)) FROM riders")" "$namen_vorher"

echo "=== 4. CHECK laesst genau drei Zustaende zu ==="
for wert in heuristik wikidata; do
  psql -q -d n5_daten -c "UPDATE riders SET name_source='$wert' WHERE id='tadej-pogacar'" >/dev/null 2>&1
  pruefe "'$wert' angenommen" "$(psql -tA -d n5_daten -c \
    "SELECT name_source FROM riders WHERE id='tadej-pogacar'")" "$wert"
done
psql -q -d n5_daten -c "UPDATE riders SET name_source=NULL WHERE id='tadej-pogacar'" >/dev/null 2>&1
pruefe "NULL angenommen (= noch nicht gefragt)" "$(psql -tA -d n5_daten -c \
  "SELECT coalesce(name_source,'NULL') FROM riders WHERE id='tadej-pogacar'")" "NULL"
psql -d n5_daten -c "UPDATE riders SET name_source='erfunden' WHERE id='tadej-pogacar'" >/dev/null 2>&1
pruefe "'erfunden' abgelehnt" "$(psql -tA -d n5_daten -c \
  "SELECT coalesce(name_source,'NULL') FROM riders WHERE id='tadej-pogacar'")" "NULL"

echo "=== 5. Bestand steht im Rueckstand ==="
# Waere der Default 'heuristik', wuerde der Job NIE nachfragen - der ganze
# Befund haette dann keine Wirkung auf die vorhandenen Fahrer.
pruefe "alle Bestandszeilen name_source IS NULL" "$(psql -tA -d n5_daten -c \
  'SELECT count(*) FROM riders WHERE name_source IS NULL')" "2"

echo
if [ "$fehler" -eq 0 ]; then echo "Alle Pruefungen bestanden."; else echo "$fehler Pruefung(en) fehlgeschlagen."; fi
exit "$fehler"
