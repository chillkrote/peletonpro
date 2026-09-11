"""Scraper für UCI World Tour / ProTeam / Continental Teams von ProCyclingStats.

ACHTUNG - UNVERIFIZIERT: Diese Session hatte keinen Netzwerkzugriff auf
procyclingstats.com (vom Sandbox-Proxy blockiert). Die folgenden CSS-
Selektoren basieren auf der seit Jahren bekannten, tabellenbasierten
PCS-Struktur, sind aber NICHT gegen die aktuell live Seite getestet.

Vor dem produktiven Einsatz bitte einmal mit echtem Netzwerkzugriff
gegenprüfen (z.B. lokal: `python -m backend.app.scrapers.pcs_teams`) und
die Selektoren unten (TEAM_ROW_SELECTOR, TEAM_LINK_SELECTOR, ...) bei
Bedarf anpassen. Ein Fehlschlag hier crasht die App NICHT - der
Aufrufer (Scheduler) fängt Exceptions ab und behält die letzten
funktionierenden Daten im Cache (siehe app/cache.py).
"""
import logging
import re

from bs4 import BeautifulSoup

from ..config import PCS_BASE_URL, RACE_SEASON_YEAR
from ..models import Team
from .http import get

logger = logging.getLogger(__name__)

# PCS-Kategorie-Filter -> unser internes category-Kürzel
CATEGORY_FILTERS = {
    "wt": "worldteams",
    "pro": "proteams",
    "cont": "continental",
}

# --- Unverifizierte Selektoren (siehe Modul-Docstring) ---
TEAM_ROW_SELECTOR = "table.basic tbody tr"
TEAM_LINK_SELECTOR = 'a[href^="team/"]'
FLAG_SELECTOR = "span.flag"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "unknown"


def _country_from_flag_class(flag_el) -> str:
    if flag_el is None:
        return ""
    classes = flag_el.get("class", [])
    # z.B. class="flag ge" -> "ge" ist der Ländercode; wir geben den
    # Rohcode zurück, das Frontend kann ihn ggf. später in Klartext mappen.
    codes = [c for c in classes if c != "flag"]
    return codes[0] if codes else ""


def _parse_team_row(row, category: str, year: int) -> Team | None:
    link = row.select_one(TEAM_LINK_SELECTOR)
    if link is None:
        return None
    name = link.get_text(strip=True)
    if not name:
        return None
    href = link.get("href", "")
    slug = href.split("/")[-1] if href else _slugify(f"{name}-{year}")

    flag_el = row.select_one(FLAG_SELECTOR)
    country_code = _country_from_flag_class(flag_el)

    return Team(
        id=slug,
        name=name,
        category=category,
        country=country_code.upper() or "?",
        code=_slugify(name)[:3].upper(),
        website=None,
        source_url=f"{PCS_BASE_URL}/{href}" if href else None,
    )


def fetch_teams_for_category(category: str, year: int = RACE_SEASON_YEAR) -> list[Team]:
    pcs_filter = CATEGORY_FILTERS[category]
    url = f"{PCS_BASE_URL}/teams.php?year={year}&filter=Filter&s={pcs_filter}"
    response = get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    teams: list[Team] = []
    for row in soup.select(TEAM_ROW_SELECTOR):
        team = _parse_team_row(row, category, year)
        if team is not None:
            teams.append(team)

    if not teams:
        raise ValueError(
            f"Keine Teams für Kategorie '{category}' gefunden - "
            "Selektoren stimmen vermutlich nicht mehr mit der PCS-Seite überein."
        )
    return teams


def fetch_all_teams(year: int = RACE_SEASON_YEAR) -> list[Team]:
    all_teams: list[Team] = []
    errors: list[str] = []
    for category in CATEGORY_FILTERS:
        try:
            all_teams.extend(fetch_teams_for_category(category, year))
        except Exception as exc:  # noqa: BLE001 - bewusst breit, siehe Docstring
            logger.warning("Team-Scraping für Kategorie '%s' fehlgeschlagen: %s", category, exc)
            errors.append(f"{category}: {exc}")
    if not all_teams and errors:
        raise RuntimeError("; ".join(errors))
    return all_teams


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for t in fetch_all_teams():
        print(t.model_dump())
