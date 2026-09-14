"""Scraper für die UCI-WorldTeams-Übersicht von Wikipedia.

VERIFIZIERT am 2026-09-11 gegen echte Wikipedia-API-Antworten (per
temporärer Render-Diagnose-Route geprüft, siehe backend/README.md):

Artikel "UCI World Tour", Abschnitt "Current UCI WorldTeams (2026 season)":
eine `<table class="wikitable sortable">` mit den Spalten Team (Link auf die
eigene Wikipedia-Seite des Teams), Country (Flagge + Ländername als Text),
Seasons in World Tour, No. of seasons, Previous team names.

Wikipedia deckt hier nur die WorldTeams (oberste Stufe, aktuell 18 Teams)
ab - keine ProTeams oder Continental Teams, anders als procyclingstats.com.
Auf ausdrücklichen Wunsch verwendet, da procyclingstats.com Render's
Cloud-IPs blockiert (siehe README) und Teams ohnehin nicht häufig
aktualisiert werden müssen.

Team-Logos werden zusätzlich per `action=query&prop=pageimages` (Infobox-
Bild der jeweiligen Team-Seite) in einem einzigen Batch-Request für alle
Teams nachgeladen - best-effort, ein Team ohne Infobox-Bild bleibt einfach
ohne Logo statt den ganzen Abruf fehlschlagen zu lassen.
"""
import logging
import re

from bs4 import BeautifulSoup

from ..models import Team
from ..gender import GENDER_DEFAULT, gender_prefix
from ..text import slugify
from .wikipedia import fetch_page_images, fetch_section, wiki_title_from_url

logger = logging.getLogger(__name__)

WORLDTEAMS_PAGE = "UCI World Tour"
WORLDTEAMS_SECTION = "current uci worldteams"


def _country_from_cell(cell) -> str:
    """Bei Länderwechsel stehen mehrere Flagge+Land-Zeilen per <br/> getrennt
    im selben Feld - wir nehmen die letzte (aktuellste) Zeile."""
    lines = [line.strip() for line in cell.get_text(separator="\n").split("\n") if line.strip()]
    if not lines:
        return ""
    text = lines[-1]
    return re.sub(r"\s*\(\d{4}.*?\)\s*$", "", text).strip()


def team_id_for(name: str, gender: str = GENDER_DEFAULT) -> str:
    """ID eines Teams. Wie bei den Fahrern trennt das Geschlecht die
    gleichnamigen Männer- und Frauen-Ableger eines Teams - "Team
    Visma-Lease a Bike" gibt es zweimal, und Wikipedia unterscheidet die
    Artikel entsprechend ("(men's team)" / "(women's team)"). Ohne das
    Präfix hätte das Frauen-Team das Männer-Team überschrieben.

    Männer-IDs bleiben unverändert, siehe app/gender.py."""
    return gender_prefix(gender) + slugify(name)


def _parse_team_row(row) -> Team | None:
    cells = row.find_all("td")
    if len(cells) < 2:
        return None  # Header-Zeile (nur <th>) oder unerwartete Struktur

    link = cells[0].select_one('a[href^="/wiki/"]')
    if link is None:
        return None
    name = link.get_text(strip=True)
    if not name:
        return None
    wiki_title = link["href"][len("/wiki/"):]

    country = _country_from_cell(cells[1])

    return Team(
        id=team_id_for(name),
        name=name,
        category="wt",
        country=country or "?",
        # Kürzel aus dem Namens-Slug, NICHT aus der ID: das Präfix einer
        # Frauen-ID würde sonst jedes Kürzel zu "W--" machen.
        code=slugify(name)[:3].upper(),
        gender=GENDER_DEFAULT,
        source_url=f"https://en.wikipedia.org/wiki/{wiki_title}",
    )


def parse_worldteams_section(html: str) -> list[Team]:
    """Eigenständige Parse-Funktion, testbar ohne Netzwerkzugriff gegen
    gespeichertes HTML (siehe backend/README.md)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.wikitable")
    if table is None:
        return []
    teams: list[Team] = []
    for row in table.select("tbody tr"):
        team = _parse_team_row(row)
        if team is not None:
            teams.append(team)
    return teams


def fetch_current_worldteams() -> list[Team]:
    html = fetch_section(WORLDTEAMS_PAGE, WORLDTEAMS_SECTION)
    teams = parse_worldteams_section(html)
    if not teams:
        raise ValueError(
            "Keine WorldTeams auf der Wikipedia-Seite gefunden - Struktur hat "
            "sich vermutlich geändert."
        )

    # Team-Logos (Infobox-Bild der jeweiligen Team-Wikipedia-Seite) in einem
    # einzigen Batch-Request nachladen - best-effort, ein Fehler hier darf
    # die Teams selbst nicht verwerfen.
    try:
        logos = fetch_page_images([wiki_title_from_url(t.source_url) for t in teams if t.source_url])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Team-Logo-Abruf fehlgeschlagen, Teams bleiben ohne Logo: %s", exc)
        logos = {}
    for team in teams:
        if team.source_url:
            team.logo = logos.get(wiki_title_from_url(team.source_url))
    logger.info("Team-Logos: %d/%d Teams mit Bild", sum(1 for t in teams if t.logo), len(teams))

    return teams


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for t in fetch_current_worldteams():
        print(t.model_dump())
