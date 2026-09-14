#!/usr/bin/env bash
# Prueft Migration 0003 (ein Kategorie-Vokabular) und die Taxonomie.
#
#   PGPORT=5599 ./scripts/check-migration-0003.sh
#
# Geprueft wird:
#   1. 0003 laeuft auf einer leeren Datenbank und setzt die Constraints
#   2. eine befuellte Datenbank wird migriert, ohne dass sich eine Zeile
#      oder ein bestehender Spaltenwert aendert
#   3. die CHECKs lehnen jede unmoegliche Kombination ab und lassen jede
#      moegliche durch
#   4. enthaelt der Bestand Altvokabular, MELDET die Migration alle Befunde
#      auf einmal, schreibt nichts um, und der Stand bleibt auf 0002
#   5. das Vokabular steht nur noch in app/taxonomy.py bzw. app/gender.py
#   6. die Anzeige-Uebersetzungen in js/races.js haben genau die Schluessel
#      des Enums
set -uo pipefail
cd "$(dirname "$0")/.."
: "${PGHOST:=127.0.0.1}"; : "${PGPORT:=5599}"; : "${PGUSER:=postgres}"
export PGHOST PGPORT PGUSER
fehler=0
LOG=$(mktemp); trap 'rm -f "$LOG"' EXIT

# Gemeinsamer Wertevergleich (eine Kopie statt drei).
source "$(dirname "$0")/_datenvergleich.sh"

meld()   { printf '  %-62s %s\n' "$1" "$2"; }
pruefe() { if [ "$2" = "$3" ]; then meld "$1" "ok"; else meld "$1" "FEHLER: '$2' != '$3'"; fehler=$((fehler+1)); fi; }
neu()    { psql -q -c "DROP DATABASE IF EXISTS $1;" -c "CREATE DATABASE $1;" postgres >/dev/null; }
runner() { ( cd backend && DATABASE_URL="postgresql://${PGUSER}@${PGHOST}:${PGPORT}/$1" python3 -m app.migrations "$2" 2>&1 ); }

echo "=== 1. Leere Datenbank ==="
neu tax_leer
runner tax_leer upgrade >/dev/null 2>&1
pruefe "0003 angewendet" \
  "$(psql -tA -d tax_leer -c "SELECT count(*) FROM schema_migrations WHERE version='0003_taxonomie'")" "1"
pruefe "sechs Taxonomie-Constraints gesetzt" "$(psql -tA -d tax_leer -c "
  SELECT count(*) FROM pg_constraint WHERE contype='c' AND conname IN
   ('races_category_check','teams_category_check','races_circuit_check',
    'races_circuit_nur_continental','seed_log_category_check','seed_log_circuit_check')")" "6"

echo "=== 2. Befuellte Datenbank: nichts veraendert ==="
neu tax_daten
( cd backend && psql -q -d tax_daten -f migrations/0001_bestand.sql >/dev/null 2>&1
  psql -q -d tax_daten -f migrations/0002_gender.sql >/dev/null 2>&1 )
psql -q -d tax_daten -f /dev/stdin >/dev/null <<'SQL'
INSERT INTO teams (id,name,category,country,code) VALUES
 ('uae','UAE Team Emirates XRG','wt','United Arab Emirates','UAE'),
 ('visma','Team Visma–Lease a Bike','wt','Netherlands','TEA');
INSERT INTO races (id,name,season,category,circuit,start_date) VALUES
 ('2026-wt-tdf','Tour de France',2026,'wt',NULL,'2026-07-04'),
 ('2026-proseries-tob','Tour of Britain',2026,'proseries',NULL,'2026-09-02'),
 ('2025-continental-europe-toh','Tour of Hellas',2025,'continental','europe','2025-04-10');
INSERT INTO race_history_seed_log (category,circuit,season,race_count) VALUES
 ('wt','',2026,1),('proseries','',2026,1),('continental','europe',2025,1);
SQL
spalten() {
  psql -tA -d tax_daten -c "
    SELECT table_name||':'||string_agg(column_name,',' ORDER BY ordinal_position)
    FROM information_schema.columns WHERE table_schema='public'
      AND table_name <> 'schema_migrations' GROUP BY table_name ORDER BY table_name"
}
# Wertevergleich gemeinsam mit check-migrations.sh und -0002.sh, siehe
# scripts/_datenvergleich.sh.
md5s() { vergleich_md5 tax_daten "$1"; }
zaehle() { psql -tA -d tax_daten -c "SELECT (SELECT count(*) FROM teams)||'/'||(SELECT count(*) FROM races)||'/'||(SELECT count(*) FROM race_history_seed_log)"; }
sp=$(spalten); vorher=$(zaehle); vorher_md5=$(md5s "$sp")
pruefe "Testdaten eingespielt (teams/races/seedlog)" "$vorher" "2/3/3"
runner tax_daten upgrade >/dev/null 2>&1
pruefe "0003 angewendet" \
  "$(psql -tA -d tax_daten -c "SELECT count(*) FROM schema_migrations WHERE version='0003_taxonomie'")" "1"
pruefe "Zeilenzahlen unveraendert" "$vorher" "$(zaehle)"
if [ "$vorher_md5" = "$(md5s "$sp")" ]; then meld "kein Spaltenwert veraendert" "ok"
else meld "Spaltenvergleich" "FEHLER"; diff <(echo "$vorher_md5") <(md5s "$sp"); fehler=$((fehler+1)); fi

echo "=== 3. CHECKs: unmoegliche Kombinationen ==="
verstoss() {
  local erwartet=$1 sql=$2
  local con
  con=$(psql -d tax_leer -c "$sql" 2>&1 | grep -oP 'violates check constraint "\K[^"]+' | head -1)
  pruefe "$3" "${con:-DURCHGELASSEN}" "$erwartet"
}
verstoss races_category_check "INSERT INTO races (id,name,season,category) VALUES ('x','X',2026,'pro')" \
  "races.category='pro' abgelehnt"
verstoss teams_category_check "INSERT INTO teams (id,name,category,country,code) VALUES ('t','T','cont','X','T')" \
  "teams.category='cont' abgelehnt"
verstoss races_circuit_check "INSERT INTO races (id,name,season,category,circuit) VALUES ('q','Q',2026,'continental','mars')" \
  "unbekannter circuit abgelehnt"
verstoss races_circuit_nur_continental "INSERT INTO races (id,name,season,category,circuit) VALUES ('y','Y',2026,'wt','europe')" \
  "circuit bei category='wt' abgelehnt"
verstoss races_circuit_nur_continental "INSERT INTO races (id,name,season,category) VALUES ('z','Z',2026,'continental')" \
  "continental ohne circuit abgelehnt"
verstoss seed_log_circuit_check "INSERT INTO race_history_seed_log (category,circuit,season) VALUES ('wt','europe',2026)" \
  "seed_log: circuit bei 'wt' abgelehnt"

echo "=== 3b. CHECKs: moegliche Kombinationen ==="
gueltig() {
  local n
  n=$(psql -d tax_leer -c "$1" 2>&1 | grep -c "INSERT 0 1")
  pruefe "$2" "$n" "1"
}
gueltig "INSERT INTO races (id,name,season,category) VALUES ('a','A',2026,'wt')" "category='wt' ohne circuit"
gueltig "INSERT INTO races (id,name,season,category) VALUES ('b','B',2026,'proseries')" "category='proseries'"
gueltig "INSERT INTO races (id,name,season,category,circuit) VALUES ('c','C',2026,'continental','europe')" "continental mit circuit"
gueltig "INSERT INTO race_history_seed_log (category,circuit,season) VALUES ('wt','',2026)" "seed_log: 'wt' mit leerem circuit"
gueltig "INSERT INTO race_history_seed_log (category,circuit,season) VALUES ('continental','asia',2026)" "seed_log: continental mit circuit"

echo "=== 4. Altvokabular im Bestand: melden, nichts umschreiben ==="
neu tax_alt
( cd backend && psql -q -d tax_alt -f migrations/0001_bestand.sql >/dev/null 2>&1
  psql -q -d tax_alt -f migrations/0002_gender.sql >/dev/null 2>&1 )
psql -q -d tax_alt -c "
 INSERT INTO teams (id,name,category,country,code) VALUES ('alt','Alt','cont','X','ALT');
 INSERT INTO races (id,name,season,category) VALUES ('r1','R1',2026,'pro');
 INSERT INTO races (id,name,season,category,circuit) VALUES ('r2','R2',2026,'wt','europe');
 INSERT INTO race_history_seed_log (category,circuit,season) VALUES ('cont','',2026);" >/dev/null 2>&1
meldung=$(runner tax_alt upgrade 2>&1)
for erwartet in "races.category enthält 'pro'" "teams.category enthält 'cont'" \
                "race_history_seed_log.category enthält 'cont'" "verletzen die Circuit-Regel"; do
  pruefe "Meldung nennt: $erwartet" "$(echo "$meldung" | grep -c -- "$erwartet")" "1"
done
pruefe "Stand bleibt auf 0002" \
  "$(psql -tA -d tax_alt -c "SELECT count(*) FROM schema_migrations WHERE version='0003_taxonomie'")" "0"
pruefe "kein Constraint gesetzt" "$(psql -tA -d tax_alt -c "
  SELECT count(*) FROM pg_constraint WHERE contype='c' AND conname LIKE '%category_check%'")" "0"
pruefe "Zeilen unberuehrt" "$(psql -tA -d tax_alt -c "SELECT (SELECT count(*) FROM races)||'/'||(SELECT count(*) FROM teams)")" "2/1"

echo "=== 5. Vokabular nur noch an einer Stelle ==="
# Keine Textsuche: scripts/check-vokabular.py parst die Dateien und findet
# Literal-Typen und fest getippte Aufzaehlungen, ohne Kommentare und
# Docstrings mitzuzaehlen (Begruendung im Docstring des Skripts).
if python3 scripts/check-vokabular.py > "$LOG" 2>&1; then
  vokabular=ok
else
  vokabular=$(cat "$LOG")
fi
pruefe "kein Vokabular doppelt (category/circuit/gender)" "$vokabular" "ok"
pruefe "Werte-Tupel aus den Literalen abgeleitet" "$( cd backend && python3 -c "
import sys; sys.path.insert(0,'.')
from typing import get_args
from app.gender import GENDERS, Gender
from app.taxonomy import CATEGORIES, CIRCUITS, TEAM_CATEGORIES
from app.taxonomy import Category, Circuit, TeamCategory
print(CATEGORIES == get_args(Category) and CIRCUITS == get_args(Circuit)
      and TEAM_CATEGORIES == get_args(TeamCategory) and GENDERS == get_args(Gender))")" "True"

echo "=== 6. Anzeige-Uebersetzungen im Frontend ==="
pruefe "js/races.js-Schluessel == Enum" "$( cd backend && python3 -c "
import re, sys, pathlib
sys.path.insert(0,'.')
from app.taxonomy import CATEGORIES, CIRCUITS
js = pathlib.Path('../js/races.js').read_text(encoding='utf-8')
def k(name):
    m = re.search(rf'const {name} = \{{(.*?)\}};', js, re.S)
    return tuple(x.strip() for x in re.findall(r'(\w+):', m.group(1)))
print(k('CATEGORY_LABEL') == CATEGORIES and k('CIRCUIT_LABEL') == CIRCUITS)")" "True"

echo
if [ "$fehler" -eq 0 ]; then echo "Alle Pruefungen bestanden."; else echo "$fehler Pruefung(en) fehlgeschlagen."; fi
exit $((fehler > 0 ? 1 : 0))
