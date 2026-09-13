"""Scraper für Rennkalender + Ergebnisse von Wikipedia.

VERIFIZIERT am 2026-09-11 gegen echte Wikipedia-API-Antworten (per
temporärer Render-Diagnose-Route geprüft, siehe backend/README.md):

- Kalender: Saison-Artikel "{year} UCI World Tour", Abschnitt "Events" -
  eine `<table class="wikitable plainrowheaders">` mit einer Zeile pro
  Rennen: Race (Zeilenüberschrift `<th>` mit Länderflagge + Link auf die
  eigene Rennseite), Date ("20–25 January" bzw. "30 March – 5 April" bei
  Monatswechsel), Winner/Second/Third (je ein Fahrer-Link).
- Ergebnisse Etappenrennen: eigener Rennartikel (z.B. "2026 Tour de
  France"), Abschnitt "General classification" - `<table class="wikitable
  ...">` mit Rank (`<th scope="row">`) / Rider / Team / Time, von Wikipedia
  selbst bereits auf die Top 10 begrenzt ("Final general classification
  (1-10)").
- Ergebnisse Eintagesrennen: eigener Rennartikel (z.B. "2026 Milan–San
  Remo"), Abschnitt "Result" - gleiche Spalten, aber Rank als normale
  `<td>`-Zelle statt `<th scope="row">`.

Alle Rennen auf der Saison-Kalenderseite sind per Definition World-Tour-
Rennen (category="wt") - anders als bei procyclingstats.com gibt es hier
keine gemischte Pro/Continental-Klassifizierung in derselben Tabelle.
"""
import logging
import re
import urllib.parse
from datetime import date, datetime

from bs4 import BeautifulSoup

from ..config import RACE_SEASON_YEAR
from ..text import normalize_dashes
from ..models import LiveResult, Race, RiderResult
from .wikipedia import fetch_section

logger = logging.getLogger(__name__)

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

MONUMENTS = {"milan-san-remo", "tour-of-flanders", "paris-roubaix", "liege-bastogne-liege", "il-lombardia"}
GRAND_TOURS = {"tour-de-france", "giro-d-italia", "vuelta-a-espana"}

RESULT_SECTION_CANDIDATES = ("General classification", "Final classification", "Result")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "unknown"


def _classify_type(slug: str, is_multi_day: bool) -> str:
    if slug in GRAND_TOURS:
        return "gt"
    if slug in MONUMENTS:
        return "monument"
    return "stage_race" if is_multi_day else "one_day"


def _parse_date_range(text: str, year: int) -> tuple[str, str] | None:
    text = normalize_dashes(text).strip()

    match = re.match(r"^(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Za-z]+)$", text)
    if match:
        d1, d2, month_name = match.groups()
        month = MONTHS.get(month_name.lower())
        if not month:
            return None
        start = date(year, month, int(d1)).isoformat()
        end = date(year, month, int(d2)).isoformat()
        return start, end

    match = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s*-\s*(\d{1,2})\s+([A-Za-z]+)$", text)
    if match:
        d1, mo1, d2, mo2 = match.groups()
        month1, month2 = MONTHS.get(mo1.lower()), MONTHS.get(mo2.lower())
        if not month1 or not month2:
            return None
        start = date(year, month1, int(d1)).isoformat()
        end = date(year, month2, int(d2)).isoformat()
        return start, end

    match = re.match(r"^(\d{1,2})\s+([A-Za-z]+)$", text)
    if match:
        d1, month_name = match.groups()
        month = MONTHS.get(month_name.lower())
        if not month:
            return None
        start = date(year, month, int(d1)).isoformat()
        return start, start

    return None


def _parse_race_row(row, year: int) -> Race | None:
    header = row.find("th")
    cells = row.find_all("td")
    if header is None or len(cells) < 2:
        return None  # Header-Zeile oder unerwartete Struktur

    # Der Zeilenkopf enthaelt zwei Links: die Laenderflagge (verlinkt aufs
    # Land, ohne Text) und den Rennnamen - wir brauchen den mit Text.
    link = next(
        (a for a in header.select('a[href^="/wiki/"]') if a.get_text(strip=True)),
        None,
    )
    if link is None:
        return None
    name = link.get_text(strip=True)
    wiki_title = link["href"][len("/wiki/"):]

    flag_img = header.select_one("img")
    country = (flag_img.get("alt") or "").strip() if flag_img is not None else ""

    dates = _parse_date_range(cells[0].get_text(strip=True), year)
    if dates is None:
        return None
    start_date, end_date = dates

    winner_link = cells[1].select_one("a") if len(cells) > 1 else None
    winner = winner_link.get_text(strip=True) if winner_link else None

    slug = _slugify(name)
    race_type = _classify_type(slug, start_date != end_date)

    return Race(
        id=slug,
        name=name,
        category="wt",
        type=race_type,
        start_date=start_date,
        end_date=end_date,
        country=country or "?",
        winner_previous_year=winner,
        source_url=f"https://en.wikipedia.org/wiki/{wiki_title}",
    )


def parse_calendar_section(html: str, year: int) -> list[Race]:
    """Eigenständige Parse-Funktion, testbar ohne Netzwerkzugriff gegen
    gespeichertes HTML (siehe backend/README.md)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.wikitable")
    if table is None:
        return []
    races: list[Race] = []
    for row in table.select("tbody tr"):
        race = _parse_race_row(row, year)
        if race is not None:
            races.append(race)
    return races


def fetch_race_calendar(year: int = RACE_SEASON_YEAR) -> list[Race]:
    html = fetch_section(f"{year} UCI World Tour", "Events")
    races = parse_calendar_section(html, year)
    if not races:
        raise ValueError(
            "Keine Rennen im Wikipedia-Kalender gefunden - Struktur hat sich "
            "vermutlich geändert."
        )
    return races


def _parse_result_row(row) -> RiderResult | None:
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

    return RiderResult(
        position=position,
        rider=rider_link.get_text(strip=True),
        team=team_link.get_text(strip=True) if team_link else "",
        time=time_text,
        gap=None if position == 1 else time_text,
    )


def parse_result_section(html: str, race_id: str, race_name: str) -> LiveResult | None:
    """Eigenständige Parse-Funktion, testbar ohne Netzwerkzugriff gegen
    gespeichertes HTML (siehe backend/README.md)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.wikitable")
    if table is None:
        return None

    results: list[RiderResult] = []
    for row in table.select("tbody tr"):
        result = _parse_result_row(row)
        if result is not None:
            results.append(result)

    if not results:
        return None

    return LiveResult(
        id=f"{race_id}-result",
        race_id=race_id,
        race_name=race_name,
        status="finished",
        results=results,
    )


def fetch_race_result(race: Race) -> LiveResult | None:
    """Holt das Ergebnis für ein Rennen aus dessen eigenem Wikipedia-Artikel.

    Liefert None, wenn (noch) kein Ergebnis-Abschnitt vorhanden ist (z.B.
    Rennen hat noch nicht begonnen oder der Artikel wurde noch nicht
    aktualisiert).
    """
    if not race.source_url:
        return None
    wiki_title = urllib.parse.unquote(race.source_url.rsplit("/", maxsplit=1)[-1]).replace("_", " ")

    html = None
    for section_name in RESULT_SECTION_CANDIDATES:
        try:
            html = fetch_section(wiki_title, section_name)
            break
        except ValueError:
            continue
    if html is None:
        return None

    result = parse_result_section(html, race.id, race.name)
    if result is not None:
        result.source_url = race.source_url
        result.status = "finished" if race.end_date < datetime.now().date().isoformat() else "live"
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for r in fetch_race_calendar():
        print(r.model_dump())
