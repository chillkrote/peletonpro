"""Scraper für die Renn-Historie (WorldTour/ProSeries/Continental Touren
seit RACE_HISTORY_START_YEAR) von Wikipedia.

NICHT einzeln gegen echte Wikipedia-Antworten verifiziert wie die übrigen
Scraper in diesem Projekt (siehe backend/README.md) - bei geschätzt 3.000+
verschiedenen Renn-Artikeln über 16 Jahre und 7 Kategorien/Circuits ist das
händische Vorab-Verifizieren jeder Struktur-Variante nicht praktikabel.
Stattdessen bewusst DEFENSIV gebaut (mehrere Titel-/Abschnitts-Kandidaten
probieren, fehlende Felder bleiben None statt einen Fehler zu werfen) und
vor dem produktiven Rollout per temporärer Render-Diagnose-Route gegen eine
Stichprobe echter historischer Seiten geprüft, siehe README.

Zwei bekannte historische Formatbrüche, für die Kandidaten-Titel probiert
werden:
- Die UCI World Tour heißt erst ab 2011 so; 2010 war das letzte Jahr der
  vorherigen "UCI ProTour" (2005-2010).
- UCI ProSeries gibt es erst seit 2020 (zweite Stufe unterhalb der World
  Tour) - frühere Jahre liefern hier planmäßig 0 Rennen.
- Continental-Tour-Saisons liefen in früheren Jahren über den Winter
  (z.B. "2010–11 UCI Africa Tour"), neuere über das Kalenderjahr
  (z.B. "2020 UCI Africa Tour") - beide Titel-Formate werden versucht.

Etappen-Details (Datum/Distanz/Start-Ziel) werden best-effort aus einer
Etappen-Übersichtstabelle irgendwo auf der Rennseite gelesen (Spalten-
namen variieren: "Stage"/"Date"/"Distance"/"Course" o.ä.) - fehlt eine
solche Tabelle oder eine Spalte, bleibt das jeweilige Feld None statt die
ganze Etappe zu verwerfen. Etappen-ERGEBNISSE (Top 10) stammen aus
eigenen "Stage N"-Abschnitten, sofern die Rennseite solche hat (bei
kleineren/älteren Rennen oft nicht vorhanden).
"""
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from ..models import RaceResultEntry, RaceStage
from ..text import normalize_dashes
from .wikipedia import (
    fetch_full_page,
    fetch_lead_section,
    fetch_section_by_index,
    fetch_sections,
)
from .wikipedia_tables import MONTHS, parse_result_row

logger = logging.getLogger(__name__)

CIRCUIT_NAMES = {
    "africa": "Africa",
    "asia": "Asia",
    "europe": "Europe",
    "america": "America",
    "oceania": "Oceania",
}

RESULT_SECTION_CANDIDATES = (
    "general classification",
    "final classification",
    "final general classification",
    "overall classification",
    "result",
    "results",
)

STAGE_SECTION_RE = re.compile(r"^stage\s*(\d+)\b", re.IGNORECASE)
DISTANCE_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*km")
STAGE_NUMBER_RE = re.compile(r"^(\d+)")



def season_page_titles(year: int, category: str, circuit: Optional[str] = None) -> list[str]:
    """Kandidaten-Seitentitel für die Saison-Übersichtsseite, probiert in
    dieser Reihenfolge - siehe Modul-Docstring für die historischen
    Formatbrüche, die das nötig machen."""
    if category == "wt":
        titles = [f"{year} UCI World Tour"]
        if year <= 2010:
            titles.append(f"{year} UCI ProTour")
        return titles
    if category == "proseries":
        return [f"{year} UCI ProSeries"]
    if category == "continental":
        if not circuit:
            raise ValueError("circuit ist für category='continental' erforderlich")
        name = CIRCUIT_NAMES[circuit]
        next_suffix = f"{(year + 1) % 100:02d}"
        return [f"{year} UCI {name} Tour", f"{year}–{next_suffix} UCI {name} Tour"]
    raise ValueError(f"Unbekannte Kategorie: {category}")


def _parse_date_range_flexible(text: str, default_year: int) -> Optional[tuple[str, str]]:
    """Wie wikipedia_races._parse_date_range, aber toleriert einen
    optionalen expliziten 4-stelligen Jahres-Suffix (nötig für Continental-
    Saison-Tabellen, die über einen Jahreswechsel laufen) und einen
    Jahreswechsel innerhalb eines Zeitraums (z.B. "29 December - 3
    January")."""
    from datetime import date

    text = normalize_dashes(text).strip()
    year_suffix = r"(?:\s+(\d{4}))?"

    m = re.match(rf"^(\d{{1,2}})\s*-\s*(\d{{1,2}})\s+([A-Za-z]+){year_suffix}$", text)
    if m:
        d1, d2, month_name, year_str = m.groups()
        month = MONTHS.get(month_name.lower())
        if not month:
            return None
        y = int(year_str) if year_str else default_year
        try:
            return date(y, month, int(d1)).isoformat(), date(y, month, int(d2)).isoformat()
        except ValueError:
            return None

    m = re.match(rf"^(\d{{1,2}})\s+([A-Za-z]+)\s*-\s*(\d{{1,2}})\s+([A-Za-z]+){year_suffix}$", text)
    if m:
        d1, mo1, d2, mo2, year_str = m.groups()
        month1, month2 = MONTHS.get(mo1.lower()), MONTHS.get(mo2.lower())
        if not month1 or not month2:
            return None
        y1 = int(year_str) if year_str else default_year
        y2 = y1 + 1 if month2 < month1 else y1
        try:
            return date(y1, month1, int(d1)).isoformat(), date(y2, month2, int(d2)).isoformat()
        except ValueError:
            return None

    m = re.match(rf"^(\d{{1,2}})\s+([A-Za-z]+){year_suffix}$", text)
    if m:
        d1, month_name, year_str = m.groups()
        month = MONTHS.get(month_name.lower())
        if not month:
            return None
        y = int(year_str) if year_str else default_year
        try:
            d = date(y, month, int(d1)).isoformat()
            return d, d
        except ValueError:
            return None

    return None


def _find_col(headers: list[str], *keywords: str) -> Optional[int]:
    return next((i for i, h in enumerate(headers) if any(k in h for k in keywords)), None)


def _parse_season_table(table, default_year: int) -> list[dict]:
    """Parst EINE Tabelle spaltennamen-basiert statt positionsbasiert - die
    Spaltenreihenfolge variiert erheblich zwischen Seitentypen (World-Tour-
    Tabellen: Race zuerst, dann Date; Continental-Tour-Tabellen z.B. "2020
    UCI Europe Tour": Date zuerst, dann "Race name"; ProSeries-Tabellen:
    Ranking-Spalten zuerst, "Race" erst an Position 5). Liefert [], wenn
    die Kopfzeile keine als Renn-Name erkennbare Spalte hat (z.B. eine
    unrelated Wikitable auf derselben Seite)."""
    rows = table.select("tr")
    if not rows:
        return []
    header_cells = rows[0].find_all(["th", "td"])
    headers = [c.get_text(strip=True).lower() for c in header_cells]
    name_col = _find_col(headers, "race", "event")
    if name_col is None:
        return []
    date_col = _find_col(headers, "date")

    races: list[dict] = []
    seen: set[str] = set()
    for row in rows[1:]:
        cells = row.find_all(["th", "td"])
        if name_col >= len(cells):
            continue
        link = next((a for a in cells[name_col].select('a[href^="/wiki/"]') if a.get_text(strip=True)), None)
        if link is None:
            continue
        wiki_title = link["href"][len("/wiki/"):]
        if wiki_title in seen:
            continue
        seen.add(wiki_title)

        start_date = end_date = None
        if date_col is not None and date_col < len(cells):
            dates = _parse_date_range_flexible(cells[date_col].get_text(strip=True), default_year)
            if dates:
                start_date, end_date = dates

        races.append(
            {"name": link.get_text(strip=True), "wiki_title": wiki_title, "start_date": start_date, "end_date": end_date}
        )
    return races


def parse_season_page(html: str, default_year: int) -> list[dict]:
    """Eigenständige Parse-Funktion, testbar ohne Netzwerkzugriff. Scannt
    ALLE Wikitables der Seite statt eine bestimmte Abschnittsüberschrift
    vorauszusetzen (die Kapitelstruktur variiert stark zwischen World-Tour-/
    ProSeries-/den fünf Continental-Tour-Seitentypen über mehrere Jahre) und
    SUMMIERT über alle Tabellen mit einer erkennbaren Renn-Namen-Spalte -
    stark frequentierte Circuits (z.B. UCI Europe Tour) verteilen ihren
    Kalender auf mehrere Tabellen (eine pro Monat/Quartal statt einer
    einzigen Gesamttabelle)."""
    soup = BeautifulSoup(html, "html.parser")
    all_races: list[dict] = []
    seen_titles: set[str] = set()
    for table in soup.select("table.wikitable"):
        for race in _parse_season_table(table, default_year):
            if race["wiki_title"] not in seen_titles:
                seen_titles.add(race["wiki_title"])
                all_races.append(race)
    return all_races


def fetch_season_race_list(year: int, category: str, circuit: Optional[str] = None) -> list[dict]:
    """Holt die Renn-Liste einer Saison/Kategorie/(Circuit) - probiert alle
    Kandidaten-Titel (season_page_titles) der Reihe nach, bis einer eine
    gültige Seite mit erkennbarer Renn-Tabelle liefert. Liefert eine leere
    Liste (kein Fehler), wenn keiner der Kandidaten existiert oder keine
    Tabelle erkannt wurde - das ist für manche Jahr/Kategorie-Kombinationen
    erwartet (z.B. ProSeries vor 2020)."""
    for title in season_page_titles(year, category, circuit):
        try:
            html = fetch_full_page(title)
        except ValueError:
            continue
        races = parse_season_page(html, year)
        if races:
            for race in races:
                race["wiki_url"] = f"https://en.wikipedia.org/wiki/{race['wiki_title']}"
            return races
    return []


def parse_race_infobox(html: str) -> dict:
    """Eigenständige Parse-Funktion, testbar ohne Netzwerkzugriff. Liest
    'Stages', 'Distance' und 'Website' (offizielle Veranstalter-Seite, falls
    von Wikipedia gepflegt) aus der Infobox (Lead-Abschnitt) eines
    Renn-Artikels - alle Felder bleiben None, wenn nicht vorhanden (z.B.
    bei sehr kurzen Stub-Artikeln kleinerer Continental-Rennen)."""
    soup = BeautifulSoup(html, "html.parser")
    num_stages = None
    distance_km = None
    website = None
    for th in soup.select("th.infobox-label"):
        label = th.get_text(strip=True).replace("\xa0", " ").lower()
        td = th.find_next_sibling("td")
        if td is None:
            continue
        if label.startswith("stages") and num_stages is None:
            m = re.search(r"\d+", td.get_text(" ", strip=True))
            if m:
                num_stages = int(m.group())
        elif label.startswith("distance") and distance_km is None:
            m = DISTANCE_RE.search(td.get_text(" ", strip=True))
            if m:
                distance_km = float(m.group(1).replace(",", ""))
        elif label.startswith("website") and website is None:
            link = td.select_one("a")
            if link is not None and link.get("href"):
                href = link["href"]
                website = f"https:{href}" if href.startswith("//") else href
    return {"num_stages": num_stages, "distance_km": distance_km, "website": website}


def _parse_results_table(html: str) -> list[RaceResultEntry]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.wikitable")
    if table is None:
        return []
    entries: list[RaceResultEntry] = []
    for row in table.select("tbody tr"):
        entry = parse_result_row(row)
        if entry is not None:
            entries.append(entry)
    return entries


def _parse_stage_overview_table(html: str) -> dict[int, dict]:
    """Sucht eine Etappen-Übersichtstabelle (Kopfzeile enthält eine Spalte,
    die mit 'Stage' beginnt) irgendwo auf der Seite. Liefert
    stage_number -> {date_text, distance_km, start_location, end_location}.
    Best-effort: Spaltennamen/-reihenfolge variieren zwischen Rennen und
    Jahren, fehlende Spalten liefern einfach None für dieses Feld."""
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.select("table.wikitable"):
        header_row = table.select_one("tr")
        if header_row is None:
            continue
        header_cells = [c.get_text(strip=True).lower() for c in header_row.find_all(["th", "td"])]
        if not any(h.startswith("stage") for h in header_cells):
            continue

        def _col(*keywords: str) -> Optional[int]:
            return next((i for i, h in enumerate(header_cells) if any(k in h for k in keywords)), None)

        stage_col = _col("stage")
        date_col = _col("date")
        distance_col = _col("distance", "length")
        course_col = _col("course", "route")

        overview: dict[int, dict] = {}
        for row in table.select("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if stage_col is None or stage_col >= len(cells):
                continue
            m = STAGE_NUMBER_RE.match(cells[stage_col].get_text(strip=True))
            if not m:
                continue
            stage_number = int(m.group(1))
            entry: dict = {"date_text": None, "distance_km": None, "start_location": None, "end_location": None}
            if date_col is not None and date_col < len(cells):
                entry["date_text"] = cells[date_col].get_text(strip=True)
            if distance_col is not None and distance_col < len(cells):
                dm = DISTANCE_RE.search(cells[distance_col].get_text(" ", strip=True))
                if dm:
                    entry["distance_km"] = float(dm.group(1).replace(",", ""))
            if course_col is not None and course_col < len(cells):
                course_text = cells[course_col].get_text(" ", strip=True)
                parts = re.split(r"\s+(?:to|–|—|-)\s+", course_text, maxsplit=1)
                if len(parts) == 2:
                    entry["start_location"], entry["end_location"] = parts[0].strip(), parts[1].strip()
                elif course_text:
                    entry["start_location"] = course_text
            overview[stage_number] = entry
        if overview:
            return overview
    return {}


def fetch_race_details(wiki_title: str, race_season: int) -> dict:
    """Holt Distanz/Etappenzahl (Infobox), das Gesamt-/Eintagesrennen-
    Ergebnis sowie - bei Mehretagenrennen - pro Etappe Datum/Distanz/
    Start-Ziel (Übersichtstabelle) und Ergebnisliste (eigener 'Stage N'-
    Abschnitt, falls vorhanden). Alle Teilschritte sind best-effort:
    fehlt eine Quelle für ein Feld, bleibt es leer statt den ganzen
    Rennabruf fehlschlagen zu lassen."""
    infobox = parse_race_infobox(fetch_lead_section(wiki_title))

    try:
        sections = fetch_sections(wiki_title)
    except ValueError:
        sections = []

    results: list[RaceResultEntry] = []
    result_section = next(
        (s for s in sections if any(cand in s.get("line", "").lower() for cand in RESULT_SECTION_CANDIDATES)),
        None,
    )
    if result_section is not None:
        try:
            results = _parse_results_table(fetch_section_by_index(wiki_title, result_section["index"]))
        except ValueError:
            pass

    stages: list[RaceStage] = []
    if infobox["num_stages"] and infobox["num_stages"] > 1:
        stage_sections = {
            int(m.group(1)): s
            for s in sections
            if (m := STAGE_SECTION_RE.match(s.get("line", "").strip()))
        }
        stage_results: dict[int, list[RaceResultEntry]] = {}
        for stage_number, sec in stage_sections.items():
            try:
                entries = _parse_results_table(fetch_section_by_index(wiki_title, sec["index"]))
            except ValueError:
                continue
            if entries:
                stage_results[stage_number] = entries

        try:
            overview = _parse_stage_overview_table(fetch_full_page(wiki_title))
        except ValueError:
            overview = {}

        stage_numbers = sorted(set(overview) | set(stage_results)) or list(range(1, infobox["num_stages"] + 1))
        for n in stage_numbers:
            ov = overview.get(n, {})
            stage_date = None
            if ov.get("date_text"):
                parsed = _parse_date_range_flexible(ov["date_text"], race_season)
                if parsed:
                    stage_date = parsed[0]
            stages.append(
                RaceStage(
                    stage_number=n,
                    date=stage_date,
                    distance_km=ov.get("distance_km"),
                    start_location=ov.get("start_location"),
                    end_location=ov.get("end_location"),
                    results=stage_results.get(n, []),
                )
            )

    return {
        "num_stages": infobox["num_stages"],
        "distance_km": infobox["distance_km"],
        "organizer_website": infobox["website"],
        "results": results,
        "stages": stages,
    }
