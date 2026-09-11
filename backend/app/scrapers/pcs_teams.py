"""Scraper für UCI World Tour / ProTeam / Continental Teams von ProCyclingStats.

VERIFIZIERT am 2026-09-11 gegen echtes HTML der Seite `teams/worldtour`
(vom Nutzer per Browser-Devtools bereitgestellt, da diese Umgebung keinen
Netzwerkzugriff auf procyclingstats.com hat). Struktur zum Zeitpunkt der
Verifizierung:

    <h4>UCI WorldTeams</h4>
    <ul class="list lh18 fs14 columns2 mob_columns1">
        <li><div><span class="flag be"></span> <a href="team/SLUG">Name</a></div>
            <div> (30)</div>              <!-- Fahrer-Anzahl in Klammern -->
            <div class="fs10"></div></li>
        ...
    </ul>
    <h4>UCI ProTeams</h4>
    <ul class="list ...">...</ul>

Beide Kategorien (WorldTeams + ProTeams) liegen auf DERSELBEN Seite
`/teams/worldtour`. Continental Teams liegen unter `/teams/continental`
(analoge Struktur angenommen, aber NICHT gegen echtes HTML verifiziert -
siehe backend/README.md, Abschnitt "Scraping-Ethik/Verifizierung").

Die Kategorie wird über den Text der jeweils vorausgehenden <h4>
bestimmt, nicht über einen Query-Parameter - das war in der ersten
(unverifizierten) Fassung dieses Moduls falsch angenommen.
"""
import logging
import re

from bs4 import BeautifulSoup

from ..config import PCS_BASE_URL
from ..models import Team
from .http import get

logger = logging.getLogger(__name__)

# Eine Seite pro Eintrag; "worldtour" liefert sowohl wt- als auch
# pro-Teams, die per Überschrift auseinandergehalten werden.
TEAM_PAGES = {
    "worldtour": f"{PCS_BASE_URL}/teams/worldtour",
    "continental": f"{PCS_BASE_URL}/teams/continental",  # Struktur unverifiziert, siehe Docstring
}

SECTION_HEADING_SELECTOR = "h4"
TEAM_LINK_SELECTOR = 'a[href^="team/"]'
FLAG_SELECTOR = "span.flag"
RIDER_COUNT_RE = re.compile(r"\((\d+)\)")


def _category_from_heading(text: str) -> str | None:
    text_lower = text.lower()
    if "worldteam" in text_lower:
        return "wt"
    if "proteam" in text_lower:
        return "pro"
    if "continental" in text_lower:
        return "cont"
    return None


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "unknown"


def _country_from_flag_class(flag_el) -> str:
    if flag_el is None:
        return ""
    classes = flag_el.get("class", [])
    codes = [c for c in classes if c != "flag"]
    return codes[0] if codes else ""


def _parse_team_item(li, category: str) -> Team | None:
    link = li.select_one(TEAM_LINK_SELECTOR)
    if link is None:
        return None
    name = link.get_text(strip=True)
    if not name:
        return None
    href = link.get("href", "").strip("/")
    if not href:
        return None
    slug = href.rsplit("/", maxsplit=1)[-1]

    flag_el = li.select_one(FLAG_SELECTOR)
    country_code = _country_from_flag_class(flag_el)

    riders = None
    match = RIDER_COUNT_RE.search(li.get_text())
    if match:
        riders = int(match.group(1))

    return Team(
        id=slug,
        name=name,
        category=category,
        country=country_code.upper() or "?",
        code=_slugify(name)[:3].upper(),
        riders=riders,
        website=None,
        source_url=f"{PCS_BASE_URL}/{href}",
    )


def parse_teams_page(html: str) -> list[Team]:
    """Extrahiert alle Team-Einträge aus einer teams/*-Seite.

    Eigenständige Funktion (statt in fetch_teams_from_page verschachtelt),
    damit sie sich ohne Netzwerkzugriff gegen gespeichertes HTML testen
    lässt (siehe backend/README.md).
    """
    soup = BeautifulSoup(html, "html.parser")
    teams: list[Team] = []
    for heading in soup.select(SECTION_HEADING_SELECTOR):
        category = _category_from_heading(heading.get_text())
        if category is None:
            continue
        list_el = heading.find_next_sibling("ul")
        if list_el is None:
            continue
        for li in list_el.select("li"):
            team = _parse_team_item(li, category)
            if team is not None:
                teams.append(team)
    return teams


def fetch_teams_from_page(url: str) -> list[Team]:
    response = get(url)
    return parse_teams_page(response.text)


def fetch_all_teams() -> list[Team]:
    all_teams: list[Team] = []
    errors: list[str] = []
    for name, url in TEAM_PAGES.items():
        try:
            teams = fetch_teams_from_page(url)
            if not teams:
                raise ValueError(
                    f"Keine Teams auf Seite '{name}' gefunden - Struktur hat sich "
                    "vermutlich geändert."
                )
            all_teams.extend(teams)
        except Exception as exc:  # noqa: BLE001 - bewusst breit, siehe Modul-Docstring
            logger.warning("Team-Scraping für Seite '%s' fehlgeschlagen: %s", name, exc)
            errors.append(f"{name}: {exc}")
    if not all_teams and errors:
        raise RuntimeError("; ".join(errors))
    return all_teams


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for t in fetch_all_teams():
        print(t.model_dump())
