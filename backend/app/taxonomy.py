"""Die drei Achsen, nach denen Rennen, Teams und Fahrer eingeordnet sind.

Für dieselbe Sache gab es zwei Vokabulare:

    Team.category        Literal["wt", "pro", "cont"]
    RaceRecord.category  Literal["wt", "proseries", "continental"]

und dazu die Circuits als dritte Achse, verstreut über config.py, den
Router, den Scraper und js/races.js. Bei jeder weiteren Datenbank hätte
man alle Kopien mitpflegen müssen - und beim ersten Vergessen wäre ein
Filter entstanden, der aussieht als funktioniere er. Genau das war
/api/teams?category=pro: der Scraper schreibt fest "wt", die Antwort war
immer leer.

DREI UNABHÄNGIGE ACHSEN
-----------------------
    gender    m | w                       (app/gender.py, Befund 7)
    category  wt | proseries | continental
    circuit   africa | asia | europe | america | oceania

Sie sind unabhängig in dem Sinne, dass jede für sich gefiltert werden kann.
Eine Abhängigkeit gibt es: `circuit` ist ausschliesslich bei
`category = 'continental'` gesetzt - die UCI gliedert nur die dritte Stufe
geografisch. Das ist keine Ausnahme in der Kategorie, sondern die
Definition der Circuit-Achse, und sie steht hier einmal als
`kategorie_braucht_circuit()`; die Datenbank setzt dieselbe Regel als CHECK
durch (Migration 0003).

WELCHES VOKABULAR UND WARUM
---------------------------
"wt"/"proseries"/"continental" - nicht "wt"/"pro"/"cont".

Der Grund ist nicht Geschmack: es ist das, was in der Datenbank steht.
Belegt über den Schreibpfad, der ALLE Zeilen abdeckt statt einer
Stichprobe - `races.category` wird ausschliesslich von
`db_races.upsert_race_skeleton` geschrieben, aufgerufen aus der einen
Schleife in `scheduler.refresh_race_history()`, und die geht genau über
diese drei Werte (`achsen_kombinationen()` unten). `teams.category` schreibt nur
`scrapers/wikipedia_teams.py`, fest auf "wt".

"pro"/"cont" war damit totes Vokabular: keine Zeile konnte die Werte
enthalten. Diese Wahl braucht deshalb keine Datenmigration - und das ist
wichtig, weil es für diese Datenbank kein automatisches Backup gibt (siehe
README, "Geschlechts-Dimension").
"""
from typing import Literal, Optional, get_args

Category = Literal["wt", "proseries", "continental"]
Circuit = Literal["africa", "asia", "europe", "america", "oceania"]

# Aus dem Literal abgeleitet, nicht daneben geschrieben. FastAPI und Pydantic
# brauchen den Literal-Typ, Schleifen und Fehlermeldungen brauchen die Werte
# zur Laufzeit - beides aus einer Quelle, sonst stünde das Vokabular auch in
# dieser Datei zweimal und könnte auseinanderlaufen. Genau der Fehler, den
# dieses Modul beheben soll.
CATEGORIES: tuple[str, ...] = get_args(Category)
CIRCUITS: tuple[str, ...] = get_args(Circuit)

# Nur die dritte Stufe ist geografisch gegliedert.
KATEGORIEN_MIT_CIRCUIT: frozenset[str] = frozenset({"continental"})


def kategorie_braucht_circuit(category: str) -> bool:
    """Ob für diese Kategorie ein Circuit gesetzt sein MUSS - und bei allen
    anderen nicht gesetzt sein darf."""
    return category in KATEGORIEN_MIT_CIRCUIT


def pruefe_achsen(category: str, circuit: Optional[str]) -> None:
    """Wirft ValueError, wenn Kategorie und Circuit nicht zusammenpassen.

    Vorher prüfte das nur `season_page_titles`, und nur in eine Richtung
    (fehlender Circuit bei continental). Ein Circuit bei category='wt' lief
    stillschweigend durch und wäre als Teil der Renn-ID in der Datenbank
    gelandet - eine ID, die kein zweiter Lauf reproduziert."""
    if category not in CATEGORIES:
        raise ValueError(
            f"Unbekannte Kategorie: {category!r} (erlaubt: {', '.join(CATEGORIES)})"
        )
    if circuit is not None and circuit not in CIRCUITS:
        raise ValueError(
            f"Unbekannter Circuit: {circuit!r} (erlaubt: {', '.join(CIRCUITS)})"
        )
    if kategorie_braucht_circuit(category) and circuit is None:
        raise ValueError(f"circuit ist für category={category!r} erforderlich")
    if not kategorie_braucht_circuit(category) and circuit is not None:
        raise ValueError(
            f"circuit darf für category={category!r} nicht gesetzt sein "
            f"(bekommen: {circuit!r})"
        )


# Welche Kategorien in der teams-Tabelle vorkommen KÖNNEN - nicht dasselbe wie
# CATEGORIES. `races.category` deckt alle drei Stufen ab, `teams.category`
# schreibt nur scrapers/wikipedia_teams.py und dort fest "wt", weil die Quelle
# (Wikipedia-Artikel "UCI World Tour") ausschliesslich WorldTeams listet.
# Getrennt aufgeführt, damit der Filter in routers/teams.py nicht mehr
# verspricht, als die Daten hergeben - vorher nahm er "pro" und "cont" an und
# antwortete darauf zwangsläufig leer. Kommen ProTeams oder Continental-Teams
# hinzu, gehört der Wert hier UND im Scraper erweitert; steht er nur hier,
# entsteht derselbe Filter wieder.
TeamCategory = Literal["wt"]
TEAM_CATEGORIES: tuple[str, ...] = get_args(TeamCategory)


def achsen_kombinationen(
    circuits: tuple[str, ...] = CIRCUITS,
) -> list[tuple[str, Optional[str]]]:
    """Alle gültigen (category, circuit)-Paare - je Kategorie genau die
    Circuits, die `kategorie_braucht_circuit` für sie vorsieht.

    Steht hier statt im Scheduler, weil die Liste dort fest getippt war
    (zwei Paare wt/proseries plus eine Schleife über die Circuits): eine
    vierte Kategorie hätte man an zwei Stellen nachtragen
    müssen, und beim Vergessen der zweiten wäre sie stillschweigend nie
    geseedet worden.

    Die Reihenfolge ist die von CATEGORIES und damit die Seeding-Priorität
    (World Tour zuerst) - dieselbe Ordnung, die auch
    db_races.get_races_missing_details für den Backfill benutzt.

    `circuits` ist einschränkbar (config.RACE_HISTORY_CIRCUITS), damit der
    Scheduler eine Teilmenge abdecken kann, ohne dass die Achse selbst
    kleiner wird.
    """
    unbekannt = [c for c in circuits if c not in CIRCUITS]
    if unbekannt:
        raise ValueError(
            f"Unbekannte Circuits: {', '.join(map(repr, unbekannt))} "
            f"(erlaubt: {', '.join(CIRCUITS)})"
        )
    kombinationen: list[tuple[str, Optional[str]]] = []
    for category in CATEGORIES:
        if kategorie_braucht_circuit(category):
            kombinationen += [(category, circuit) for circuit in circuits]
        else:
            kombinationen.append((category, None))
    return kombinationen
