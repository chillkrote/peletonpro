"""Scraper für UCI World Tour / ProTeam / Continental Teams von ProCyclingStats.

VERIFIZIERT am 2026-09-11 gegen echtes HTML von zwei Seiten (vom Nutzer per
Browser-Devtools bereitgestellt, da diese Umgebung keinen Netzwerkzugriff auf
procyclingstats.com hat):

1. `/teams/worldtour` (WorldTeams + ProTeams zusammen auf einer Seite):

    <h4>UCI WorldTeams</h4>
    <ul class="list lh18 fs14 columns2 mob_columns1">
        <li><div><span class="flag be"></span> <a href="team/SLUG">Name</a></div>
            <div> (30)</div>              <!-- Fahrer-Anzahl in Klammern -->
            <div class="fs10"></div></li>
        ...
    </ul>
    <h4>UCI ProTeams</h4>
    <ul class="list ...">...</ul>

2. `/teams/continental` - VÖLLIG ANDERE Struktur, keine <ul>/<li>-Liste,
   sondern nach Land gruppiert über <h3>-Überschriften mit Fließtext:

    <h3><span class="flags cn"></span> China</h3>
    <div style="overflow: hidden; ...">
        <div style="float: left; width: 260px; ">
            1. <a class="black" href="team/SLUG">Name (18)</a><br />
            2. <a class="black" href="team/SLUG2">Name2 (10)</a><br />
            ...
        </div>
        <div style="float: left; width: 500px; ">...Trikot-Bilder...</div>
    </div>
    <h3>...nächstes Land...</h3>
    ...

   Achtung: hier heißt die Flag-Klasse "flags" (Plural), nicht "flag" wie
   auf der worldtour-Seite - beide werden über `[class*="flag"]` erfasst.
   Fahrer-Anzahl steckt hier direkt im Link-Text als "(N)"-Suffix statt in
   einem eigenen <div>.
"""
import logging
import re

from bs4 import BeautifulSoup

from ..config import PCS_BASE_URL
from ..models import Team
from .http import get

logger = logging.getLogger(__name__)

WORLDTOUR_URL = f"{PCS_BASE_URL}/teams/worldtour"
CONTINENTAL_URL = f"{PCS_BASE_URL}/teams/continental"

SECTION_HEADING_SELECTOR = "h4"
TEAM_LINK_SELECTOR = 'a[href^="team/"]'
FLAG_SELECTOR = '[class*="flag"]'
RIDER_COUNT_RE = re.compile(r"\((\d+)\)")
NAME_WITH_RIDER_COUNT_RE = re.compile(r"^(.*?)\s*\((\d+)\)\s*$")


def _category_from_heading(text: str) -> str | None:
    text_lower = text.lower()
    if "worldteam" in text_lower:
        return "wt"
    if "proteam" in text_lower:
        return "pro"
    return None


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "unknown"


def _country_from_flag_class(flag_el) -> str:
    if flag_el is None:
        return ""
    classes = flag_el.get("class", [])
    codes = [c for c in classes if c not in ("flag", "flags")]
    return codes[0] if codes else ""


def _slug_from_href(href: str) -> str | None:
    href = href.strip("/")
    if not href:
        return None
    return href.rsplit("/", maxsplit=1)[-1]


def _parse_team_item(li, category: str) -> Team | None:
    """Für die worldtour-Seite: ein <li> pro Team in einer <ul class="list">."""
    link = li.select_one(TEAM_LINK_SELECTOR)
    if link is None:
        return None
    name = link.get_text(strip=True)
    if not name:
        return None
    href = link.get("href", "")
    slug = _slug_from_href(href)
    if not slug:
        return None

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
        source_url=f"{PCS_BASE_URL}/{href.strip('/')}",
    )


def parse_teams_page(html: str) -> list[Team]:
    """Für /teams/worldtour: <h4>-Überschrift + <ul class="list"> pro Kategorie."""
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


def _parse_continental_link(link, country_code: str) -> Team | None:
    href = link.get("href", "")
    slug = _slug_from_href(href)
    if not slug:
        return None

    text = link.get_text(strip=True)
    match = NAME_WITH_RIDER_COUNT_RE.match(text)
    name, riders = (match.group(1), int(match.group(2))) if match else (text, None)
    if not name:
        return None

    return Team(
        id=slug,
        name=name,
        category="cont",
        country=country_code.upper() or "?",
        code=_slugify(name)[:3].upper(),
        riders=riders,
        website=None,
        source_url=f"{PCS_BASE_URL}/{href.strip('/')}",
    )


def parse_continental_teams_page(html: str) -> list[Team]:
    """Für /teams/continental: <h3>Land</h3> + <div> mit Fließtext-Liste."""
    soup = BeautifulSoup(html, "html.parser")
    teams: list[Team] = []
    for heading in soup.select("h3"):
        flag_el = heading.select_one(FLAG_SELECTOR)
        country_code = _country_from_flag_class(flag_el)
        wrapper = heading.find_next_sibling("div")
        if wrapper is None:
            continue
        for link in wrapper.select(TEAM_LINK_SELECTOR):
            team = _parse_continental_link(link, country_code)
            if team is not None:
                teams.append(team)
    return teams


def fetch_all_teams() -> list[Team]:
    all_teams: list[Team] = []
    errors: list[str] = []

    for name, url, parser in (
        ("worldtour", WORLDTOUR_URL, parse_teams_page),
        ("continental", CONTINENTAL_URL, parse_continental_teams_page),
    ):
        try:
            response = get(url)
            teams = parser(response.text)
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
