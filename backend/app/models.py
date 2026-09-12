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
    den RiderStint-Zeiträumen (siehe db.get_rider_seasons). UCI-Ranking-
    Punkte pro Saison sind hier bewusst NICHT enthalten: es gibt dafür keine
    zuverlässige, in großem Umfang abrufbare Quelle (siehe README, Abschnitt
    "Bekannte Lücken")."""

    year: int
    team_name: str
    team_wiki_url: Optional[str] = None


class RiderDetail(Rider):
    history: list[RiderStint] = []
    seasons: list[RiderSeason] = []
