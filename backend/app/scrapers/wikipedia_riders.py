"""Scraper für Fahrer-Kader und Team-Wechsel-Historie von Wikipedia.

VERIFIZIERT am 2026-09-12 gegen echte Wikipedia-API-Antworten (per
temporärer Render-Diagnose-Route geprüft, siehe backend/README.md):

- Team-Kader: jede Team-Wikipedia-Seite (z.B. "UAE Team Emirates XRG") hat
  einen Abschnitt "Team roster" mit ein oder zwei nebeneinander stehenden
  Tabellen (Spalten "Rider"/"Date of birth"). Statt uns auf die genaue
  Spalten-/Colspan-Struktur zu verlassen (die von Team zu Team leicht
  variiert), wird pro Zeile einfach der erste Fahrer-Link mit Text sowie
  das Geburtsdatum über die hCard-Microformat-Klasse `span.bday`
  (ISO-Format, z.B. "1998-08-05") herausgesucht - robuster als
  Spaltenzählung.
- Fahrer-Historie: die Infobox jedes Fahrer-Artikels (Lead-Abschnitt,
  `section=0`) hat einen Block "Professional teams" mit einer Zeile pro
  Zeitraum: `<th class="infobox-label">2017–2018</th><td
  class="infobox-data"><a href="...">Rog–Ljubljana</a></td>` - ein
  offener Zeitraum wie "2019–" (kein Ende) markiert das aktuelle Team.
  Zusätzlich gibt es ein separates Feld "Current team" mit Link auf die
  aktuelle Team-Seite.
"""
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from ..models import RiderHistory, RiderStint, RosterRider, Team
from ..gender import GENDER_DEFAULT, gender_prefix
from ..text import normalize_dashes, slugify, vergleichsform
from .wikipedia import fetch_lead_section, fetch_section, wiki_title_from_url

logger = logging.getLogger(__name__)

ROSTER_SECTION = "roster"
TEAM_HISTORY_LABELS = ("professional teams", "teams", "team")
YEAR_RANGE_RE = re.compile(r"^(\d{4})\s*[–-]\s*(\d{4})?$")
YEAR_SINGLE_RE = re.compile(r"^(\d{4})$")

# Im Radsport häufige Namenspartikel, die zum Nachnamen gehören statt zum
# Vornamen (z.B. "Wout van Aert" -> Nachname "van Aert", "Mathieu van der
# Poel" -> Nachname "van der Poel").
NAME_PARTICLES = {
    "van", "der", "den", "von", "de", "la", "le", "du", "di", "da",
    "dos", "das", "del", "els", "ter", "ten",
}


def _wiki_url_from_href(href: str) -> str | None:
    """Baut aus einem '/wiki/...'-href die volle URL - ohne De-/Re-Encoding,
    damit sie 1:1 der von Wikipedia gelieferten Schreibweise entspricht
    (wie auch source_url in wikipedia_teams.py)."""
    if not href.startswith("/wiki/"):
        return None
    return f"https://en.wikipedia.org{href}"


def _parse_roster_row(row) -> RosterRider | None:
    link = next(
        (a for a in row.select('a[href^="/wiki/"]') if a.get_text(strip=True)),
        None,
    )
    if link is None:
        return None
    name = link.get_text(strip=True)
    wiki_url = _wiki_url_from_href(link["href"])
    if not name or not wiki_url:
        return None

    bday_el = row.select_one("span.bday")
    birth_date = bday_el.get_text(strip=True) if bday_el else None

    abbr_el = row.select_one("abbr[title]")
    country = abbr_el.get("title") if abbr_el else None

    return RosterRider(name=name, country=country, birth_date=birth_date, wiki_url=wiki_url)


def parse_team_roster(html: str) -> list[RosterRider]:
    """Eigenständige Parse-Funktion, testbar ohne Netzwerkzugriff gegen
    gespeichertes HTML (siehe backend/README.md)."""
    soup = BeautifulSoup(html, "html.parser")
    riders: list[RosterRider] = []
    seen: set[str] = set()
    for row in soup.select("tr"):
        rider = _parse_roster_row(row)
        if rider is not None and rider.wiki_url not in seen:
            seen.add(rider.wiki_url)
            riders.append(rider)
    return riders


def fetch_team_roster(team_wiki_title: str) -> list[RosterRider]:
    html = fetch_section(team_wiki_title, ROSTER_SECTION)
    return parse_team_roster(html)


def _parse_year_range(text: str) -> tuple[int, int | None] | None:
    """Zeitraum aus einem Infobox-Label, z.B. "2017-2018", "2019-" oder
    "2020". Striche und geschützte Leerzeichen werden vorher normalisiert
    (siehe app/text.py): YEAR_RANGE_RE kannte nur Halbgeviert- und
    Bindestrich, ein Geviertstrich liess den Stint still verschwinden."""
    text = normalize_dashes(text).strip()
    match = YEAR_RANGE_RE.match(text)
    if match:
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else None
        return start, end
    match = YEAR_SINGLE_RE.match(text)
    if match:
        year = int(match.group(1))
        return year, year
    return None


def parse_rider_history(html: str) -> RiderHistory:
    """Eigenständige Parse-Funktion, testbar ohne Netzwerkzugriff gegen
    gespeichertes HTML (siehe backend/README.md)."""
    soup = BeautifulSoup(html, "html.parser")

    current_team_wiki_url = None
    for th in soup.select("th.infobox-label"):
        # "Current team" wird von Wikipedia mit &#160; (NBSP) statt einem
        # normalen Leerzeichen gerendert - beim Vergleich normalisieren.
        label_text = th.get_text(strip=True).replace("\xa0", " ").lower()
        if label_text.startswith("current team"):
            data_td = th.find_next_sibling("td")
            link = data_td.select_one("a") if data_td else None
            if link is not None:
                current_team_wiki_url = _wiki_url_from_href(link.get("href", ""))
            break

    header_th = next(
        (
            th
            for th in soup.select("th.infobox-header")
            if th.get_text(strip=True).lower() in TEAM_HISTORY_LABELS
        ),
        None,
    )

    stints: list[RiderStint] = []
    if header_th is not None:
        header_row = header_th.find_parent("tr")
        for row in header_row.find_next_siblings("tr") if header_row else []:
            label_th = row.find("th", class_="infobox-label")
            if label_th is None:
                break  # nächste Infobox-Sektion (z.B. "Major wins") erreicht
            data_td = row.find("td", class_="infobox-data")
            if data_td is None:
                continue
            link = data_td.select_one("a")
            if link is None:
                logger.debug("Infobox-Zeile ohne Team-Link übersprungen: %r",
                             label_th.get_text(strip=True))
                continue
            label_text = label_th.get_text(strip=True)
            years = _parse_year_range(label_text)
            if years is None:
                # Vorher stumm verworfen. Eine unbekannte Format-Variante ist
                # die wahrscheinlichste Ursache dafür, dass eine Station in
                # der Historie fehlt - das soll auffallen können.
                logger.debug("Zeitraum nicht erkannt, Stint übersprungen: %r", label_text)
                continue
            start_year, end_year = years
            stints.append(
                RiderStint(
                    team_name=link.get_text(strip=True),
                    team_wiki_url=_wiki_url_from_href(link.get("href", "")),
                    start_year=start_year,
                    end_year=end_year,
                )
            )

    return RiderHistory(current_team_wiki_url=current_team_wiki_url, stints=stints)


def fetch_rider_history(rider_wiki_title: str) -> RiderHistory:
    html = fetch_lead_section(rider_wiki_title)
    return parse_rider_history(html)


def rider_id_for(name: str, gender: str = GENDER_DEFAULT) -> str:
    """ID eines Fahrers oder einer Fahrerin.

    Der Namens-Slug ist von Natur aus nicht eindeutig - zwei Personen
    gleichen Namens landen in derselben Zeile, und das gilt auch innerhalb
    eines Feldes. Das Geschlecht nimmt einen Teil davon weg (eine Simon
    Yates und ein Simon Yates kollidieren nicht mehr), aber nicht alles.

    Die eigentliche Lösung ist ein Schlüssel aus der Wikidata-QID statt aus
    dem Namen. Die Spalte dafür steht seit Migration 0002 bereit und wird
    gefüllt; der Wechsel des Primärschlüssels ist ein eigener,
    datenverändernder Schritt - siehe backend/README.md, Abschnitt "Stabile
    Fahrer-IDs: der Plan"."""
    return gender_prefix(gender) + slugify(name)


def split_name(full_name: str) -> tuple[str, str]:
    """Trennt einen vollen Namen (wie er auf Wikipedia-Kaderlisten steht) in
    Vor- und Nachname. Der Nachname ist das letzte Wort plus alle direkt
    davorstehenden bekannten Namenspartikel (siehe NAME_PARTICLES) - der
    Standardfall (ein Vor-, ein Nachname) ist damit korrekt, Sonderfälle
    mit mehrteiligen Nachnamen (van/de/von/...) ebenfalls. Ein einzelnes
    Wort (kein Leerzeichen, in der Praxis kaum vorkommend) wird komplett
    als Nachname behandelt, damit die Standard-Sortierung nach Nachname
    ihn nicht verliert."""
    parts = full_name.split()
    if len(parts) <= 1:
        return "", full_name
    split_index = len(parts) - 1
    while split_index > 0 and parts[split_index - 1].lower() in NAME_PARTICLES:
        split_index -= 1
    first_name = " ".join(parts[:split_index])
    last_name = " ".join(parts[split_index:])
    return first_name, last_name


def nachname_aus_wikidata(
    full_name: str, family_labels: list[str]
) -> Optional[tuple[str, str]]:
    """(Vorname, Nachname) aus Wikidatas Familiennamen (P734) - oder None.

    WOZU: `split_name` nimmt das letzte Wort plus bekannte Partikel. Bei
    spanischen und portugiesischen Doppelnachnamen ist das falsch:

        "Juan Ayuso Pesquera"  ->  Vorname "Juan Ayuso" / Nachname "Pesquera"

    Richtig wäre Vorname "Juan" / Nachname "Ayuso Pesquera". Wikidata führt
    beide Namensteile als eigene P734-Aussagen, in der richtigen Reihenfolge
    - damit ist der Fall entscheidbar, statt geraten.

    KONSERVATIV, ABSICHTLICH: übernommen wird nur, was als Suffix des vollen
    Namens auf Wortgrenzen aufgeht. Wikidata enthält auch Geburtsnamen,
    Namen in anderen Schriften und schlicht Fehler; keine davon darf einen
    Namen in der Datenbank überschreiben. Passt nichts, gibt die Funktion
    None zurück und der Aufrufer behält das Ergebnis von `split_name`.

    Zurückgegeben wird die Schreibweise aus `full_name`, nicht die von
    Wikidata: die Datenbank soll `name == first_name + " " + last_name`
    erfüllen, und der volle Name ist die Quelle mit den richtigen Akzenten.
    """
    worte = full_name.split()
    if not worte or not family_labels:
        return None

    # Kandidaten: erst alle Teile zusammen (der Doppelnachname-Fall), dann
    # die einzelnen. Längster Treffer gewinnt, damit "Ayuso Pesquera" nicht
    # von "Pesquera" verdrängt wird.
    kandidaten = [" ".join(family_labels)] + list(family_labels)
    kandidaten.sort(key=lambda k: len(k.split()), reverse=True)

    for kandidat in kandidaten:
        teile = kandidat.split()
        if not teile or len(teile) >= len(worte):
            # Ein Nachname, der den ganzen Namen einnimmt, lässt keinen
            # Vornamen übrig - das ist kein Treffer, sondern ein Hinweis,
            # dass Wikidata etwas anderes meint.
            continue
        if vergleichsform(" ".join(worte[-len(teile):])) == vergleichsform(kandidat):
            return " ".join(worte[:-len(teile)]), " ".join(worte[-len(teile):])
    return None


def roster_riders_for_team(team: Team) -> list[tuple[str, RosterRider]]:
    """Holt den Kader eines Teams und liefert (rider_id, RosterRider)-Paare."""
    if not team.source_url:
        return []
    riders = fetch_team_roster(wiki_title_from_url(team.source_url))
    return [(rider_id_for(r.name), r) for r in riders]
