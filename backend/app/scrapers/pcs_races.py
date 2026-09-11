"""Scraper für Rennkalender + Ergebnisse von ProCyclingStats.

VERIFIZIERT am 2026-09-11 gegen echtes HTML von:
- `races.php?year=2026&circuit=1&filter=Filter` (Kalender, canonical:
  `/calendar/uci/year-calendar`): eine echte `<table class="basic">` mit
  5 Spalten (Datum, Datum (mobile-Duplikat), Rennen+Flagge, Sieger,
  Klassifizierungscode wie "2.UWT"/"1.UWT"). Die ursprüngliche Annahme
  einer Tabellenstruktur war hier also richtig.
- `race/tour-de-france/2026` (Renn-Übersichtsseite): enthält eine
  einfache Top-10-Tabelle unter der Überschrift "Result {year}"
  (Rang, Fahrer+Flagge, Team, Zeit) - das ist die verwendete Quelle für
  fetch_race_result. Die komplexere, tab-basierte Etappen-Ergebnisseite
  (`race/{slug}/{year}/stage-{n}/result/result`) wäre für Live-Ergebnisse
  präziser, ist aber ungleich komplexer (mehrere Klassifikations-Tabs,
  Team-Zeitfahr-Sonderfall) und wird hier bewusst nicht verwendet.
"""
import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..config import PCS_BASE_URL, RACE_SEASON_YEAR
from ..models import LiveResult, Race, RiderResult
from .http import get

logger = logging.getLogger(__name__)

RACE_ROW_SELECTOR = "table.basic tbody tr"
RACE_LINK_SELECTOR = 'a[href^="race/"]'
FLAG_SELECTOR = "span.flag"
RESULT_HEADING_SELECTOR = "h4"
DATE_RE = re.compile(r"(\d{2})\.(\d{2})(?:\s*-\s*(\d{2})\.(\d{2}))?")

MONUMENTS = {
    "milano-sanremo",
    "ronde-van-vlaanderen",
    "paris-roubaix",
    "liege-bastogne-liege",
    "il-lombardia",
}
GRAND_TOURS = {"tour-de-france", "giro-d-italia", "vuelta-a-espana"}


def _country_from_flag_class(flag_el) -> str:
    if flag_el is None:
        return ""
    classes = flag_el.get("class", [])
    codes = [c for c in classes if c not in ("flag", "flags")]
    return codes[0] if codes else ""


def _classify_type(slug: str, is_multi_day: bool) -> str:
    if slug in GRAND_TOURS:
        return "gt"
    if slug in MONUMENTS:
        return "monument"
    return "stage_race" if is_multi_day else "one_day"


def _category_from_class_code(code: str) -> str:
    if "UWT" in code or "WWT" in code:
        return "wt"
    if "Pro" in code:
        return "pro"
    return "cont"


def _parse_date_cell(text: str, year: int) -> tuple[str, str] | None:
    match = DATE_RE.search(text)
    if not match:
        return None
    d1, m1, d2, m2 = match.groups()
    try:
        start = datetime(year, int(m1), int(d1)).date().isoformat()
    except ValueError:
        return None
    if d2 and m2:
        try:
            end = datetime(year, int(m2), int(d2)).date().isoformat()
        except ValueError:
            end = start
    else:
        end = start
    return start, end


def _parse_race_row(row, year: int) -> Race | None:
    cells = row.find_all("td")
    if len(cells) < 5:
        return None

    dates = _parse_date_cell(cells[0].get_text(strip=True), year)
    if dates is None:
        return None
    start_date, end_date = dates

    link = cells[2].select_one(RACE_LINK_SELECTOR)
    if link is None:
        return None
    name = link.get_text(strip=True)
    href = link.get("href", "").strip("/")
    parts = href.split("/")
    if len(parts) < 2:
        return None
    slug = parts[1]

    flag_el = cells[2].select_one(FLAG_SELECTOR)
    country_code = _country_from_flag_class(flag_el)

    class_code = cells[4].get_text(strip=True)
    category = _category_from_class_code(class_code)
    race_type = _classify_type(slug, start_date != end_date)

    winner_link = cells[3].select_one("a")
    winner = winner_link.get_text(strip=True) if winner_link else None

    return Race(
        id=slug,
        name=name,
        category=category,
        type=race_type,
        start_date=start_date,
        end_date=end_date,
        country=country_code.upper() or "?",
        winner_previous_year=winner or None,
        source_url=f"{PCS_BASE_URL}/{href}" if href else None,
    )


def parse_calendar_page(html: str, year: int) -> list[Race]:
    """Eigenständige Parse-Funktion, testbar ohne Netzwerkzugriff gegen
    gespeichertes HTML (siehe backend/README.md)."""
    soup = BeautifulSoup(html, "html.parser")
    races: list[Race] = []
    for row in soup.select(RACE_ROW_SELECTOR):
        race = _parse_race_row(row, year)
        if race is not None:
            races.append(race)
    return races


def fetch_race_calendar(year: int = RACE_SEASON_YEAR, circuit: int = 1) -> list[Race]:
    url = f"{PCS_BASE_URL}/races.php?year={year}&circuit={circuit}&filter=Filter"
    response = get(url)
    races = parse_calendar_page(response.text, year)

    if not races:
        raise ValueError(
            "Keine Rennen im Kalender gefunden - Selektoren stimmen vermutlich "
            "nicht mehr mit der PCS-Seite überein."
        )
    return races


def parse_race_result_page(html: str, race_slug: str, year: int) -> LiveResult | None:
    """Liest die Top-10-Tabelle ('Result {year}') von der Renn-Übersichtsseite.

    Liefert None, wenn (noch) keine Ergebnistabelle vorhanden ist (z.B. Rennen
    hat noch nicht begonnen).
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[RiderResult] = []

    for heading in soup.select(RESULT_HEADING_SELECTOR):
        if not heading.get_text(strip=True).lower().startswith("result"):
            continue
        table = heading.find_next_sibling("table")
        if table is None:
            continue
        for position, row in enumerate(table.select("tbody tr"), start=1):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            rider_link = cells[1].select_one("a")
            team_link = cells[2].select_one("a")
            if rider_link is None:
                continue
            time_text = cells[3].get_text(strip=True)
            results.append(
                RiderResult(
                    position=position,
                    rider=rider_link.get_text(strip=True),
                    team=team_link.get_text(strip=True) if team_link else "",
                    # Nur Rang 1 zeigt die absolute Zeit, alle anderen den
                    # Rückstand ohne "+"-Prefix - roh übernommen.
                    time=time_text or None,
                    gap=None if position == 1 else time_text,
                )
            )
        break

    if not results:
        return None

    return LiveResult(
        id=f"{race_slug}-{year}-result",
        race_id=race_slug,
        race_name=race_slug.replace("-", " ").title(),
        # Wird ausschließlich für aktuell laufende Rennen aufgerufen
        # (siehe scheduler.refresh_results), daher hier fest "live".
        status="live",
        results=results,
        source_url=f"{PCS_BASE_URL}/race/{race_slug}/{year}",
    )


def fetch_race_result(race_slug: str, year: int = RACE_SEASON_YEAR) -> LiveResult:
    url = f"{PCS_BASE_URL}/race/{race_slug}/{year}"
    response = get(url)
    result = parse_race_result_page(response.text, race_slug, year)

    if result is None:
        raise ValueError(
            f"Keine Ergebnisse für '{race_slug}' ({year}) gefunden - "
            "Selektoren stimmen vermutlich nicht mehr mit der PCS-Seite überein."
        )
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for r in fetch_race_calendar():
        print(r.model_dump())
