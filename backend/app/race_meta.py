"""Einordnung von Rennen: Grand Tours und Monumente.

Diese Einordnung gab es zweimal, und beide Kopien waren je anders falsch:

- `wikipedia_races.GRAND_TOURS` (Backend, mit dem alten Kalender-Pfad
  entfallen) verglich Slugs: {"tour-de-france", "giro-d-italia",
  "vuelta-a-espana"}. Der Slug von "Vuelta a España" ist aber
  "vuelta-a-espa-a" - slugify() transliteriert Akzente nicht, sondern
  ersetzt sie wie jedes Sonderzeichen durch "-" (siehe text.slugify). Die
  Vuelta fiel damit durch, sobald Wikipedia den Namen mit Akzent schrieb.
- `js/races.js::GRAND_TOUR_NAMES` verglich Anzeigenamen und führte beide
  Vuelta-Schreibweisen auf - war also an dieser Stelle richtig, dafür aber
  im Frontend, wo es beim Erweitern der Datenbank niemand sucht.

Jetzt eine Stelle, im Backend, und der Vergleich läuft über den Slug: der
macht aus Halbgeviertstrich und Bindestrich, aus Apostroph-Varianten und
aus doppelten Leerzeichen dasselbe Zeichen und ist damit gegen die
Schreibweisen-Vielfalt der Wikipedia-Autoren unempfindlich. Was er NICHT
einfängt, sind Akzente - deshalb stehen akzentbehaftete Namen mit beiden
Slugs in der Liste, und das ist der Grund, warum hier Slugs und nicht
Namen stehen: den Slug kann man ausrechnen, ohne zu wissen, wie der Autor
den Bindestrich getippt hat.

Warum im Backend und nicht im Frontend: es ist eine Aussage über das
Rennen, keine über seine Darstellung. Jeder API-Client bekommt sie jetzt
mit (RaceRecord.is_grand_tour), nicht nur unsere eigene Kalenderseite.

Der CSV-Export (/api/export/races) führt sie NICHT: der spiegelt die
Tabellenspalten 1:1, und is_grand_tour ist keine Spalte. Das ist Absicht -
sie in den Export zu bekommen hieße, die Liste als CASE-Ausdruck ein
zweites Mal in SQL zu schreiben, also genau die Doppelstruktur, die hier
gerade verschwindet.

Warum keine Spalte in der races-Tabelle: nichts scraped diese Angabe, sie
ändert sich nur wenn diese Datei sich ändert, und eine Spalte müsste bei
jeder Erweiterung per Migration nachgezogen werden (die es noch nicht gibt,
siehe Befund 10). Hier wird sie beim Lesen aus dem Namen bestimmt
(db_races._row_to_race) - eine neue Zeile wirkt damit sofort für alle
Saisons, auch die längst gescrapten.

NICHT geprüft: gegen welche Namen die races-Tabelle tatsächlich gefüllt
ist. Die Render-Datenbank ist aus der Entwicklungsumgebung nicht
erreichbar. Die Liste deckt die Schreibweisen ab, die auf den
Wikipedia-Saison-Übersichtsseiten stehen (das ist die Quelle, aus der
races.name gefüllt wird, siehe scrapers/wikipedia_race_history.py) - ein
Abgleich gegen die echten Zeilen bleibt offen und ist eine Zeile SQL:
    SELECT DISTINCT name FROM races ORDER BY name;
"""
from .text import slugify

# Die drei großen Rundfahrten und ihre Frauen-Pendants. Frauen-Rennen sind
# aufgenommen, obwohl noch keine in der Datenbank stehen: das Ziel ist,
# den Frauen-Radsport einzubinden, und dann soll diese Datei nicht der
# Grund sein, warum die Tour de France Femmes im Kalender unter "Rennen"
# statt unter "Grand Tours" landet.
GRAND_TOUR_SLUGS = frozenset({
    "tour-de-france",
    "giro-d-italia",
    "vuelta-a-espana",
    "vuelta-a-espa-a",          # "Vuelta a España" - Akzent wird zu "-"
    "tour-de-france-femmes",
    "tour-de-france-femmes-avec-zwift",
    "giro-d-italia-women",
    "giro-d-italia-donne",
    "giro-donne",
    "la-vuelta-femenina",
    "vuelta-a-espana-femenina",
    "vuelta-a-espa-a-femenina",
    "ceratizit-challenge-by-la-vuelta",   # Vorgängername der Vuelta Femenina
})

# Die fünf Monumente. Noch von keinem Endpunkt ausgewertet - hier
# aufgeschrieben, weil die Liste vorher in wikipedia_races.py stand und mit
# jener Datei sonst verloren gegangen wäre. Anschließen geht analog zu
# is_grand_tour. Die Frauen-Pendants (Ronde van Vlaanderen voor Vrouwen,
# Paris-Roubaix Femmes, Liège-Bastogne-Liège Femmes) sind mit aufgeführt.
MONUMENT_SLUGS = frozenset({
    "milan-san-remo",
    "milano-sanremo",
    "sanremo-women",
    "ronde-van-vlaanderen",
    "tour-of-flanders",
    "ronde-van-vlaanderen-voor-vrouwen",
    "paris-roubaix",
    "paris-roubaix-femmes",
    "liege-bastogne-liege",
    "li-ge-bastogne-li-ge",     # "Liège-Bastogne-Liège" - Akzente werden zu "-"
    "liege-bastogne-liege-femmes",
    "li-ge-bastogne-li-ge-femmes",
    "il-lombardia",
})


def is_grand_tour(name: str) -> bool:
    """Ob ein Rennen eine Grand Tour ist - entschieden über den Slug seines
    Namens, wie er in races.name steht."""
    return slugify(name) in GRAND_TOUR_SLUGS


def is_monument(name: str) -> bool:
    """Ob ein Rennen ein Monument ist. Siehe MONUMENT_SLUGS."""
    return slugify(name) in MONUMENT_SLUGS
