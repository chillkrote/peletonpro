"""Gemeinsame Bausteine zum Lesen von Wikipedia-Tabellen.

Hier liegen die Teile, die vorher in `wikipedia_races.py` standen und von
`wikipedia_race_history.py` importiert wurden. Beim Abbau des alten
Kalender-/Ergebnis-Pfades (siehe backend/README.md, Abschnitt "Renn-Daten:
ein Pfad statt zwei") wäre `wikipedia_races.py` komplett entfallen - die
beiden Helfer werden aber weiter gebraucht. Sie hierher zu verschieben war
die Alternative dazu, sie in die Renn-Historie zu kopieren.

VERIFIZIERT am 2026-09-11 gegen echte Wikipedia-API-Antworten (siehe
Historie in backend/README.md): Ergebnis-Tabellen haben durchgehend die
Spalten Rank/Rider/Team/Time, wobei der Rang bei Etappenrennen-Klassements
als Zeilenüberschrift (`<th scope="row">`) und bei Eintagesrennen als
normale `<td>`-Zelle steht.
"""
from ..models import RaceResultEntry

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def parse_result_row(row) -> RaceResultEntry | None:
    """Eine Zeile einer Wikipedia-Ergebnis-Tabelle.

    Liefert None, wenn die Zeile keine Platzierung ist (Kopfzeile, Zeile
    ohne Rang, Zeile ohne Fahrer-Link) - der Aufrufer überspringt sie dann.

    Liefert direkt ein RaceResultEntry. Vorher gab die Funktion ein
    RiderResult zurück, das der einzige Aufrufer anschließend Feld für Feld
    in ein RaceResultEntry umkopierte - zwei Modelle für dieselbe Sache.
    """
    header = row.find("th")
    cells = row.find_all("td")

    if header is not None:
        # Etappenrennen-Klassement: Rang steht als Zeilenüberschrift <th>.
        position_text = header.get_text(strip=True)
        if len(cells) < 3:
            return None
        rider_cell, team_cell, time_cell = cells[0], cells[1], cells[2]
    elif len(cells) >= 4:
        # Eintagesrennen-Ergebnis: Rang ist eine normale <td>-Zelle.
        position_text = cells[0].get_text(strip=True)
        rider_cell, team_cell, time_cell = cells[1], cells[2], cells[3]
    else:
        return None

    try:
        position = int(position_text)
    except ValueError:
        return None

    rider_link = rider_cell.select_one("a")
    if rider_link is None:
        return None
    team_link = team_cell.select_one("a")
    time_text = time_cell.get_text(strip=True) or None

    team_name = team_link.get_text(strip=True) if team_link else None
    return RaceResultEntry(
        position=position,
        rider=rider_link.get_text(strip=True),
        team=team_name or None,
        time_or_gap=time_text,
    )
