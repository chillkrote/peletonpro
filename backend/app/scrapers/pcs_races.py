"""Scraper für Rennkalender + Ergebnisse von ProCyclingStats.

ACHTUNG - UNVERIFIZIERT: siehe Hinweis in pcs_teams.py. Auch hier basieren
alle Selektoren auf der allgemein bekannten PCS-Struktur und müssen einmal
mit echtem Netzwerkzugriff gegen die aktuell live Seite geprüft werden.
"""
import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..config import PCS_BASE_URL, RACE_SEASON_YEAR
from ..models import LiveResult, Race, RiderResult
from .http import get

logger = logging.getLogger(__name__)

# --- Unverifizierte Selektoren (siehe Modul-Docstring) ---
RACE_ROW_SELECTOR = "table.basic tbody tr"
RACE_LINK_SELECTOR = 'a[href^="race/"]'
RESULT_ROW_SELECTOR = "table.results tbody tr"

MONUMENTS = {
    "milano-sanremo",
    "ronde-van-vlaanderen",
    "paris-roubaix",
    "liege-bastogne-liege",
    "il-lombardia",
}
GRAND_TOURS = {"tour-de-france", "giro-d-italia", "vuelta-a-espana"}


def _classify_type(slug: str, stages: int | None) -> str:
    if slug in GRAND_TOURS:
        return "gt"
    if slug in MONUMENTS:
        return "monument"
    if stages and stages > 1:
        return "stage_race"
    return "one_day"


def _parse_race_row(row, year: int) -> Race | None:
    link = row.select_one(RACE_LINK_SELECTOR)
    if link is None:
        return None
    name = link.get_text(strip=True)
    href = link.get("href", "")
    slug = href.split("/")[1] if href.count("/") >= 1 else name.lower().replace(" ", "-")

    date_cell = row.find(string=re.compile(r"\d{1,2}\.\d{1,2}"))
    date_str = date_cell.strip() if date_cell else ""
    start_date = _parse_pcs_date(date_str, year) or f"{year}-01-01"

    return Race(
        id=slug,
        name=name,
        category="wt",
        type=_classify_type(slug, None),
        start_date=start_date,
        end_date=start_date,
        country="?",
        source_url=f"{PCS_BASE_URL}/{href}" if href else None,
    )


def _parse_pcs_date(date_str: str, year: int) -> str | None:
    """PCS zeigt Datumsangaben typischerweise als 'DD.MM' an."""
    match = re.match(r"(\d{1,2})\.(\d{1,2})", date_str)
    if not match:
        return None
    day, month = int(match.group(1)), int(match.group(2))
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def fetch_race_calendar(year: int = RACE_SEASON_YEAR, circuit: int = 1) -> list[Race]:
    url = f"{PCS_BASE_URL}/races.php?year={year}&circuit={circuit}&filter=Filter"
    response = get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    races: list[Race] = []
    for row in soup.select(RACE_ROW_SELECTOR):
        race = _parse_race_row(row, year)
        if race is not None:
            races.append(race)

    if not races:
        raise ValueError(
            "Keine Rennen im Kalender gefunden - Selektoren stimmen vermutlich "
            "nicht mehr mit der PCS-Seite überein."
        )
    return races


def fetch_race_result(race_slug: str, year: int = RACE_SEASON_YEAR, stage: str = "result") -> LiveResult:
    url = f"{PCS_BASE_URL}/race/{race_slug}/{year}/{stage}"
    response = get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    results: list[RiderResult] = []
    for row in soup.select(RESULT_ROW_SELECTOR):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        try:
            position = int(re.sub(r"\D", "", cells[0].get_text(strip=True)) or "0")
        except ValueError:
            continue
        rider = cells[1].get_text(strip=True)
        team = cells[2].get_text(strip=True) if len(cells) > 2 else ""
        time_text = cells[3].get_text(strip=True) if len(cells) > 3 else ""
        if position and rider:
            results.append(RiderResult(position=position, rider=rider, team=team, time=time_text or None))

    if not results:
        raise ValueError(
            f"Keine Ergebnisse für '{race_slug}' ({year}/{stage}) gefunden - "
            "Selektoren stimmen vermutlich nicht mehr mit der PCS-Seite überein."
        )

    return LiveResult(
        id=f"{race_slug}-{year}-{stage}",
        race_id=race_slug,
        race_name=race_slug.replace("-", " ").title(),
        status="finished",
        results=results,
        source_url=url,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for r in fetch_race_calendar():
        print(r.model_dump())
