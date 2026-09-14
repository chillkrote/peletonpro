# Gemeinsamer Wertevergleich fuer die Migrations-Pruefskripte.
# Wird per `source` eingebunden, ist selbst kein ausfuehrbares Skript.
#
# WARUM GEMEINSAM
# ---------------
# Diese Funktion lag in DREI Kopien unter drei Namen: `daten_md5` in
# check-migrations.sh, `spalten_md5` in check-migration-0002.sh und `md5s`
# in check-migration-0003.sh. Migration 0008 hat gezeigt, was das kostet:
# die verlustfreie Typerweiterung INTEGER -> NUMERIC(8,2) liess zwei der
# drei Kopien scheitern, und jede Korrektur waere einzeln nachzuziehen
# gewesen - bei der dritten faellt das Vergessen erst auf, wenn sie einmal
# anschlaegt.
#
#   vergleich_md5 <datenbank> <specs>
#     specs: je Zeile "tabelle:spalte,spalte,..."
#     Ausgabe: je Zeile "tabelle <md5>"
#
# WARUM trim_scale
# ----------------
# Verglichen werden soll der WERT, nicht seine Textdarstellung. Nach einer
# Typerweiterung rendert Postgres dieselbe Zahl als "5.00" statt "5" - der
# Vergleich haette angeschlagen, obwohl sich kein Wert geaendert hat.
# trim_scale normalisiert beide Seiten. Eine echte Aenderung (5 -> 6,
# 5 -> NULL, 5.5 -> 5) bleibt sichtbar; gegengeprueft mit einer
# Testmigration, die uci_points auf 999 setzt.
#
# Braucht Postgres 13+ (Render laeuft auf 16).
#
# Spalten, deren Typ nicht ermittelbar ist (etwa weil eine Migration sie
# entfernt hat), bleiben unveraendert stehen statt still zu verschwinden -
# der Vergleich soll dann scheitern, nicht schoenrechnen.
vergleich_md5() {
  local db=$1 specs=$2 t cols ausdruck
  while IFS= read -r spec; do
    [ -n "$spec" ] || continue
    t=${spec%%:*}; cols=${spec#*:}
    ausdruck=$(psql -tA -d "$db" -c "
      SELECT string_agg(
               CASE WHEN c.data_type IN ('numeric','integer','bigint','smallint',
                                         'real','double precision')
                    THEN 'trim_scale('||quote_ident(s.spalte)||'::numeric)'
                    ELSE quote_ident(s.spalte) END,
               ',' ORDER BY s.nr)
        FROM unnest(string_to_array('${cols}', ',')) WITH ORDINALITY AS s(spalte, nr)
        LEFT JOIN information_schema.columns c
               ON c.table_schema = 'public' AND c.table_name = '${t}'
              AND c.column_name = s.spalte")
    echo "$t $(psql -tA -d "$db" -c "SELECT md5(coalesce(string_agg(x::text,'|' ORDER BY x::text),'')) FROM (SELECT $ausdruck FROM $t) x")"
  done <<< "$specs"
}
