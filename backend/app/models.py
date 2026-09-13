"""Pydantic-Schemas für alle API-Antworten."""
from typing import Literal, Optional

from pydantic import BaseModel


class Team(BaseModel):
    id: str
    name: str
    category: Literal["wt", "pro", "cont"]
    country: str
    code: str
    logo: Optional[str] = None
    source_url: Optional[str] = None
    # Hier standen zusätzlich riders, wins_season und website. Alle drei
    # wurden vom Scraper fest auf None gesetzt, von keiner Abfrage gelesen
    # und hatten keine Spalte in der teams-Tabelle - Felder, die in der
    # API-Antwort aussahen als kämen da Daten. Die Fahrerzahl liefert
    # db.count_riders(team_id), die Siege /api/teams/{id}/stats.


class NewsItem(BaseModel):
    id: str
    title: str
    link: str
    source: str
    published: Optional[str] = None
    summary: Optional[str] = None


class RosterRider(BaseModel):
    """Ein Fahrer wie er im 'Team roster'-Abschnitt einer Team-Wikipedia-Seite steht."""

    name: str
    country: Optional[str] = None
    birth_date: Optional[str] = None
    wiki_url: str


class RiderStint(BaseModel):
    """Eine Team-Zugehörigkeit eines Fahrers für einen Zeitraum (Jahr(e))."""

    team_name: str
    team_wiki_url: Optional[str] = None
    start_year: int
    end_year: Optional[int] = None


class RiderHistory(BaseModel):
    """Die 'Professional teams'-Historie aus der Infobox eines Fahrer-Wikipedia-Artikels."""

    current_team_wiki_url: Optional[str] = None
    stints: list[RiderStint] = []


class Rider(BaseModel):
    id: str
    first_name: str
    last_name: str
    name: str
    country: Optional[str] = None
    birth_date: Optional[str] = None
    wiki_url: str
    current_team_id: Optional[str] = None
    current_team_name: Optional[str] = None
    strava_url: Optional[str] = None


class RiderSeason(BaseModel):
    """Eine Saison (Kalenderjahr), in der ein Fahrer laut Wikipedia-Team-
    Historie bei einem aktuell bekannten WorldTour-Team war - abgeleitet aus
    den RiderStint-Zeiträumen (siehe db.get_rider_seasons). `uci_points` ist
    ein Platzhalter (rider_season_points-Tabelle): es gibt aktuell keine
    zuverlässige, in großem Umfang abrufbare Scraping-Quelle dafür (siehe
    README, Abschnitt "Bekannte Lücke") - das Feld ist bewusst vorbereitet,
    damit ein künftiger Import aus einer anderen UCI-Punkte-Datenbank die
    Werte nachtragen kann, ohne das Schema erneut ändern zu müssen."""

    year: int
    team_name: str
    team_wiki_url: Optional[str] = None
    uci_points: Optional[int] = None


class RiderDetail(Rider):
    history: list[RiderStint] = []
    seasons: list[RiderSeason] = []


# ---------------------------------------------------------------------------
# Renn-Historie (app/db_races.py): die persistente Datenbank aller
# UCI-WorldTour-, ProSeries- und Continental-Tour-Rennen seit 2010 und die
# einzige Quelle für Renn-Daten.
#
# Daneben standen hier früher Race, CalendarEvent, RiderResult und
# LiveResult: dieselben Rennen, nur für die aktuelle Saison und aus dem
# flüchtigen JSON-Cache. Zwei Modellsätze und zwei Scraper für eine Sache,
# von denen der Cache-Pfad nach jedem Deploy leer war. Er ist entfallen,
# siehe backend/README.md, Abschnitt "Renn-Daten: ein Pfad statt zwei".
# ---------------------------------------------------------------------------


class RaceResultEntry(BaseModel):
    """Eine Platzierung in einem Gesamt-/Eintagesrennen-Ergebnis oder einer
    einzelnen Etappe - mindestens die Top 10, sofern die Wikipedia-Quelle
    das hergibt (manche wenig dokumentierten Rennen/Etappen haben weniger)."""

    position: int
    rider: str
    team: Optional[str] = None
    time_or_gap: Optional[str] = None


class RaceStage(BaseModel):
    """Eine einzelne Etappe eines Mehretagenrennens."""

    stage_number: int
    date: Optional[str] = None
    distance_km: Optional[float] = None
    elevation_m: Optional[int] = None  # Platzhalter - siehe RaceRecord.elevation_m
    start_location: Optional[str] = None
    end_location: Optional[str] = None
    results: list[RaceResultEntry] = []


class RaceRecord(BaseModel):
    """Ein einzelnes Rennen (Eintagesrennen oder komplettes Mehretagenrennen
    mit allen Etappen) aus der Renn-Historien-Datenbank."""

    id: str
    name: str
    season: int
    category: Literal["wt", "proseries", "continental"]
    circuit: Optional[str] = None  # nur bei category == "continental": africa/asia/europe/america/oceania
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    num_stages: Optional[int] = None
    distance_km: Optional[float] = None
    elevation_m: Optional[int] = None
    """Platzhalter: auf Wikipedia für kein Rennen strukturiert erfasst (siehe
    backend/README.md, Abschnitt "Bekannte Lücke") - bleibt NULL, bis ein
    künftiger Import aus einer anderen Quelle die Werte nachträgt."""
    wiki_url: Optional[str] = None
    is_grand_tour: bool = False
    """Ob das Rennen eine Grand Tour ist. Nicht gescraped und keine
    Tabellenspalte, sondern beim Lesen aus dem Namen bestimmt - siehe
    app/race_meta.py, dort steht auch, warum. Die Einordnung lag vorher
    im Frontend (js/races.js)."""
    organizer_website: Optional[str] = None
    """Offizielle Veranstalter-Website (z.B. amstelgoldrace.nl), sofern in
    der Wikipedia-Infobox als 'Website' gepflegt - NICHT selbst gescraped
    (siehe backend/README.md, Abschnitt "Bekannte Lücke": jede Veranstalter-
    Seite hat ihre eigene, oft JS-basierte Struktur ohne gemeinsames
    Muster, anders als Wikipedias einheitliches Infobox-Template)."""
    results_fetched_at: Optional[str] = None
    results: list[RaceResultEntry] = []
    stages: list[RaceStage] = []
