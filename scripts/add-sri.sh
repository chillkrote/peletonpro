#!/usr/bin/env bash
# Trägt Subresource Integrity (SRI) für das Font-Awesome-Stylesheet in alle
# HTML-Seiten ein.
#
# WARUM: Alle Seiten laden
#   https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css
# ohne `integrity` und ohne `crossorigin`. Ein kompromittiertes CDN kann damit
# beliebiges CSS im Kontext der Seite ausführen - CSS reicht für Datenabfluss
# über Attribut-Selektoren und Hintergrundbild-URLs.
#
# WARUM ALS SKRIPT: Der Hash muss aus der ECHTEN Datei gebildet werden. Ein
# geratener oder aus dem Gedächtnis übernommener Wert blockiert das
# Stylesheet komplett (die Seiten verlieren dann alle Icons), und die
# Entwicklungsumgebung, in der dieser Fix entstanden ist, kommt nicht an
# cdnjs.cloudflare.com heran. Deshalb rechnet das Skript den Hash hier und
# jetzt aus, statt einen Wert mitzubringen.
#
# AUFRUF, aus dem Repository-Wurzelverzeichnis:
#   ./scripts/add-sri.sh
#
# Das Skript ist idempotent: ein erneuter Aufruf aktualisiert einen bereits
# vorhandenen integrity-Wert, statt einen zweiten daneben zu setzen.
set -euo pipefail

URL="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"
PAGES=(index.html news.html races.html rider.html team.html teams.html)

for page in "${PAGES[@]}"; do
    [[ -f "$page" ]] || { echo "FEHLER: $page nicht gefunden - im Repo-Wurzelverzeichnis aufrufen." >&2; exit 1; }
done

command -v openssl >/dev/null || { echo "FEHLER: openssl wird gebraucht." >&2; exit 1; }
command -v curl >/dev/null    || { echo "FEHLER: curl wird gebraucht." >&2; exit 1; }

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

echo "Lade $URL"
curl -fsSL --max-time 60 -o "$tmp" "$URL"

size=$(wc -c < "$tmp")
# Font Awesome 6.4.0 all.min.css liegt bei ~100 KB. Eine winzige Antwort ist
# eine Fehlerseite, kein Stylesheet - dann lieber abbrechen als einen Hash
# über Müll eintragen.
if (( size < 20000 )); then
    echo "FEHLER: Antwort ist nur $size Bytes gross - sieht nicht nach dem Stylesheet aus." >&2
    exit 1
fi
if ! grep -q "font-awesome\|Font Awesome\|\.fa-" "$tmp"; then
    echo "FEHLER: Antwort enthaelt kein Font-Awesome-CSS." >&2
    exit 1
fi

HASH="sha384-$(openssl dgst -sha384 -binary "$tmp" | openssl base64 -A)"
echo "Groesse: $size Bytes"
echo "Hash:    $HASH"
echo

for page in "${PAGES[@]}"; do
    python3 - "$page" "$URL" "$HASH" <<'PY'
import re, sys
path, url, digest = sys.argv[1:4]
html = open(path, encoding="utf-8").read()
pattern = re.compile(r'<link rel="stylesheet" href="' + re.escape(url) + r'"[^>]*>')
if not pattern.search(html):
    print(f"  {path}: Font-Awesome-Link nicht gefunden, uebersprungen")
    sys.exit(0)
new_tag = (f'<link rel="stylesheet" href="{url}"\n'
           f'          integrity="{digest}" crossorigin="anonymous" referrerpolicy="no-referrer">')
open(path, "w", encoding="utf-8").write(pattern.sub(new_tag, html, count=1))
print(f"  {path}: integrity gesetzt")
PY
done

echo
echo "Fertig. Bitte eine Seite im Browser oeffnen und pruefen, dass die Icons"
echo "noch erscheinen - erst dann committen. Bleiben sie aus, passt der Hash"
echo "nicht zur ausgelieferten Datei (siehe Konsole: 'Failed to find a valid"
echo "digest'), dann ist der Link ohne integrity wiederherzustellen."
