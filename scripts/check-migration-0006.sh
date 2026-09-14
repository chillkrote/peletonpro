#!/usr/bin/env bash
# Prueft Migration 0006 und die Karenzzeit beim Detail-Abruf.
#
#   PGPORT=5599 ./scripts/check-migration-0006.sh
#
# Geprueft wird:
#   1. der Runner wendet alle sechs Migrationen auf einer leeren Datenbank an
#   2. die Migration setzt GENAU die zu frueh abgerufenen Rennen zurueck -
#      und laesst jede andere Zeile in Ruhe
#   3. kein Rennen verliert Name, Datum oder Ergebnisse
#   4. die Karenzzeit: ein Rennen wird erst nach seinem Ende plus Karenz
#      zum Abruf angeboten, und die gemeldete Zahl stimmt mit der Abfrage
#      ueberein
set -uo pipefail
cd "$(dirname "$0")/.."
: "${PGHOST:=127.0.0.1}"; : "${PGPORT:=5599}"; : "${PGUSER:=postgres}"
export PGHOST PGPORT PGUSER
fehler=0
meld()   { printf '  %-60s %s\n' "$1" "$2"; }
pruefe() { if [ "$2" = "$3" ]; then meld "$1" "ok"; else meld "$1" "FEHLER: '$2' != '$3'"; fehler=$((fehler+1)); fi; }
neu()    { psql -q -c "DROP DATABASE IF EXISTS $1;" -c "CREATE DATABASE $1;" postgres >/dev/null 2>&1; }

echo "=== 1. Leere Datenbank ==="
neu r6_leer
( cd backend && DATABASE_URL="postgresql://${PGUSER}@${PGHOST}:${PGPORT}/r6_leer" \
  python3 -m app.migrations upgrade >/dev/null 2>&1 )
pruefe "0006 in schema_migrations" "$(psql -tA -d r6_leer -c \
  "SELECT count(*) FROM schema_migrations WHERE version='0006_ergebnisse_nachholen'")" "1"

echo "=== 2./3. Befuellte Datenbank: nur das Falsche zuruecksetzen ==="
neu r6_daten
( cd backend
  for m in 0001_bestand 0002_gender 0003_taxonomie 0004_ergebnis_ids 0005_namensquelle; do
    psql -q -d r6_daten -f "migrations/$m.sql" >/dev/null 2>&1
  done )

# Sechs Faelle, relativ zum heutigen Datum - damit der Test in jedem Jahr
# laeuft und nicht an einem festen Kalender klebt.
psql -q -d r6_daten -f /dev/stdin >/dev/null <<'SQL'
INSERT INTO races (id,name,season,category,circuit,gender,start_date,end_date,wiki_url,results_fetched_at) VALUES
 -- A: noch nicht gefahren, trotzdem abgerufen -> MUSS zurueckgesetzt werden
 ('a-zukunft','Rennen in der Zukunft',2026,'wt',NULL,'m',
  current_date + 30, current_date + 32, 'https://en.wikipedia.org/wiki/A', now()),
 -- B: abgerufen MITTEN im Rennen -> MUSS zurueckgesetzt werden
 ('b-mittendrin','Rennen mittendrin',2026,'wt',NULL,'m',
  current_date - 1, current_date + 2, 'https://en.wikipedia.org/wiki/B', now()),
 -- C: nach dem Ende abgerufen, ohne Ergebnisse -> bleibt (kann echt
 --    undokumentiert sein, siehe Migrationskommentar)
 ('c-leer-aber-spaet','Rennen ohne Ergebnisliste',2025,'continental','europe','m',
  current_date - 60, current_date - 58, 'https://en.wikipedia.org/wiki/C', now() - interval '50 days'),
 -- D: nach dem Ende abgerufen, mit Ergebnissen -> bleibt
 ('d-fertig','Fertiges Rennen',2025,'wt',NULL,'m',
  current_date - 90, current_date - 88, 'https://en.wikipedia.org/wiki/D', now() - interval '80 days'),
 -- E: nie abgerufen, laengst gefahren -> bleibt NULL, ist faellig
 ('e-offen','Offenes Rennen',2025,'wt',NULL,'m',
  current_date - 20, current_date - 18, 'https://en.wikipedia.org/wiki/E', NULL),
 -- F: kein Datum bekannt -> nicht beurteilbar, bleibt wie es ist
 ('f-ohne-datum','Rennen ohne Datum',2024,'proseries',NULL,'m',
  NULL, NULL, 'https://en.wikipedia.org/wiki/F', now() - interval '100 days');
INSERT INTO race_results (race_id,position,rider_name,team_name) VALUES
 ('d-fertig',1,'Sieger Eins','Team X'),
 ('a-zukunft',1,'Vorab Erfasst','Team Y');
SQL
pruefe "sechs Rennen eingespielt" "$(psql -tA -d r6_daten -c 'SELECT count(*) FROM races')" "6"
pruefe "zwei Ergebniszeilen eingespielt" "$(psql -tA -d r6_daten -c 'SELECT count(*) FROM race_results')" "2"

stand_vorher=$(psql -tA -d r6_daten -c "
  SELECT md5(string_agg(id||'|'||name||'|'||coalesce(start_date::text,'')||'|'||
                        coalesce(end_date::text,'')||'|'||season||'|'||category,
                        E'\n' ORDER BY id)) FROM races")

( cd backend && psql -q -d r6_daten -f migrations/0006_ergebnisse_nachholen.sql >/dev/null 2>&1 )

markiert() { psql -tA -d r6_daten -c \
  "SELECT CASE WHEN results_fetched_at IS NULL THEN 'NULL' ELSE 'gesetzt' END FROM races WHERE id='$1'"; }

pruefe "A Zukunft         -> zurueckgesetzt" "$(markiert a-zukunft)" "NULL"
pruefe "B mittendrin      -> zurueckgesetzt" "$(markiert b-mittendrin)" "NULL"
pruefe "C spaet, leer     -> bleibt"         "$(markiert c-leer-aber-spaet)" "gesetzt"
pruefe "D fertig          -> bleibt"         "$(markiert d-fertig)" "gesetzt"
pruefe "E nie abgerufen   -> bleibt NULL"    "$(markiert e-offen)" "NULL"
pruefe "F ohne Datum      -> bleibt"         "$(markiert f-ohne-datum)" "gesetzt"

pruefe "kein Rennen-Stammdatum veraendert" "$(psql -tA -d r6_daten -c "
  SELECT md5(string_agg(id||'|'||name||'|'||coalesce(start_date::text,'')||'|'||
                        coalesce(end_date::text,'')||'|'||season||'|'||category,
                        E'\n' ORDER BY id)) FROM races")" "$stand_vorher"
pruefe "Ergebniszeilen unangetastet" "$(psql -tA -d r6_daten -c 'SELECT count(*) FROM race_results')" "2"
pruefe "Zeilenzahl unveraendert" "$(psql -tA -d r6_daten -c 'SELECT count(*) FROM races')" "6"

echo "=== 4. Karenzzeit: was wird zum Abruf angeboten ==="
faellig() { ( cd backend && DATABASE_URL="postgresql://${PGUSER}@${PGHOST}:${PGPORT}/r6_daten" \
  RACE_DETAIL_GRACE_DAYS="$1" python3 -c "
from app import db_races
zeilen = db_races.get_races_missing_details(50)
print(','.join(sorted(z['id'] for z in zeilen)))" 2>/dev/null ); }
anzahl() { ( cd backend && DATABASE_URL="postgresql://${PGUSER}@${PGHOST}:${PGPORT}/r6_daten" \
  RACE_DETAIL_GRACE_DAYS="$1" python3 -c "
from app import db_races
print(db_races.get_races_missing_details_count())" 2>/dev/null ); }

# Karenz 3: A und B sind noch nicht faellig (Enddatum in der Zukunft), E ist
# es (vor 18 Tagen zu Ende).
pruefe "Karenz 3: nur das gefahrene offene Rennen" "$(faellig 3)" "e-offen"
pruefe "Karenz 3: Zaehlung stimmt mit der Abfrage" "$(anzahl 3)" "1"
# Karenz 0 aendert daran nichts: A und B enden erst in der Zukunft.
pruefe "Karenz 0: Zukunft bleibt trotzdem aussen" "$(faellig 0)" "e-offen"
# Karenz 30: E ist erst 18 Tage her, faellt also heraus - nichts mehr faellig.
pruefe "Karenz 30: nichts mehr faellig" "$(faellig 30)" ""
pruefe "Karenz 30: Zaehlung stimmt" "$(anzahl 30)" "0"

echo
if [ "$fehler" -eq 0 ]; then echo "Alle Pruefungen bestanden."; else echo "$fehler Pruefung(en) fehlgeschlagen."; fi
exit "$fehler"
