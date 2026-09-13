"""Nutzerlesbare Fehlermeldungen der API - an einer Stelle.

Grundsatz: nach außen gehen ausschließlich feste Texte. Ein
psycopg-Verbindungsfehler enthält in `str(exc)` Host, Port, Benutzernamen und
Datenbanknamen; das wäre die Postgres-Topologie für jeden Besucher, zumal das
Frontend das `error`-Feld sichtbar anzeigt (siehe js/riders.js und
js/races.js). Das Detail gehört ins Log, nicht in die Antwort.

Die "nicht konfiguriert"-Texte sind dagegen unkritisch und bewusst konkret:
sie verraten nichts über die Infrastruktur, sondern sagen der Entwicklerin,
dass DATABASE_URL fehlt.
"""

DB_UNAVAILABLE = "Datenbank derzeit nicht erreichbar"
RIDERS_NOT_CONFIGURED = "Fahrer-Datenbank nicht konfiguriert (DATABASE_URL fehlt)"
RACES_NOT_CONFIGURED = "Renn-Historie-Datenbank nicht konfiguriert (DATABASE_URL fehlt)"
INTERNAL_ERROR = "Interner Fehler"
