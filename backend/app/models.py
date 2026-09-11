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
