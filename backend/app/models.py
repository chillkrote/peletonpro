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
    riders: Optional[int] = None
    wins_season: Optional[int] = None
    website: Optional[str] = None
    source_url: Optional[str] = None


class Race(BaseModel):
    id: str
    name: str
    category: Literal["wt", "pro", "cont"]
    type: Literal["gt", "monument", "one_day", "stage_race"]
    start_date: str
    end_date: str
    country: str
    distance: Optional[str] = None
    stages: Optional[int] = None
    winner_previous_year: Optional[str] = None
    winner_team_previous_year: Optional[str] = None
    website: Optional[str] = None
    source_url: Optional[str] = None


class CalendarEvent(BaseModel):
    id: str
    date: str
    race_id: str
    race_name: str


class RiderResult(BaseModel):
    position: int
    rider: str
    team: str
    time: Optional[str] = None
    gap: Optional[str] = None


class LiveResult(BaseModel):
    id: str
    race_id: str
    race_name: str
    stage: Optional[int] = None
    status: Literal["live", "finished", "upcoming"]
    current_km: Optional[float] = None
    total_km: Optional[float] = None
    start_time: Optional[str] = None
    estimated_finish: Optional[str] = None
    category: Optional[str] = None
    results: list[RiderResult] = []
    source_url: Optional[str] = None


class NewsItem(BaseModel):
    id: str
    title: str
    link: str
    source: str
    published: Optional[str] = None
    summary: Optional[str] = None


class RefreshMeta(BaseModel):
    last_updated: Optional[str] = None
    stale: bool = False
    error: Optional[str] = None


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
# Renn-Historie (app/db_races.py): eigenständige, persistente Datenbank aller
# UCI-WorldTour-, ProSeries- und Continental-Tour-Rennen seit 2010 - getrennt
# von Race/LiveResult oben, die die AKTUELLE Saison aus dem flüchtigen
# JSON-Cache bedienen (app/cache.py, für Kalender/Live-Ticker auf der
# Startseite). Siehe backend/README.md, Abschnitt "Renn-Historie".
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
    organizer_website: Optional[str] = None
    """Offizielle Veranstalter-Website (z.B. amstelgoldrace.nl), sofern in
    der Wikipedia-Infobox als 'Website' gepflegt - NICHT selbst gescraped
    (siehe backend/README.md, Abschnitt "Bekannte Lücke": jede Veranstalter-
    Seite hat ihre eigene, oft JS-basierte Struktur ohne gemeinsames
    Muster, anders als Wikipedias einheitliches Infobox-Template)."""
    results_fetched_at: Optional[str] = None
    results: list[RaceResultEntry] = []
    stages: list[RaceStage] = []
