import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response

from .. import db, db_races
from ..config import RACE_SEASON_YEAR
from ..ratelimit import RATE_LIMIT_TEAM_STATS, limiter
from .messages import DB_UNAVAILABLE, RIDERS_NOT_CONFIGURED

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("")
def list_teams(category: Optional[Literal["wt"]] = None):
    """Die aktuellen WorldTeams - aus der Datenbank.

    Vorher aus app/cache.py, also aus einer JSON-Datei neben derselben
    Tabelle (siehe db.get_teams für die ganze Begründung). Zwei Folgen davon
    verschwinden damit: die Liste kann nicht mehr von /api/teams/{id}/stats
    abweichen, und sie ist nach einem Deploy auf Renders Free-Plan nicht
    mehr leer.

    `category` akzeptiert nur "wt": die Quelle (Wikipedia-Artikel "UCI World
    Tour") listet ausschließlich WorldTeams, und der Scraper schreibt
    entsprechend fest category="wt". Vorher nahm der Parameter zusätzlich
    "pro" und "cont" an und konnte dafür nie etwas zurückgeben - ein Filter,
    der aussah als funktioniere er. Kommen Frauen-WorldTeams oder ProTeams
    dazu, gehören die Werte hier und im Scraper erweitert, nicht nur hier.
    """
    # Listen-Endpunkte antworten in diesem Projekt mit 200 und error im
    # Rumpf, Detail-Endpunkte mit 503 (siehe routers/riders.py). Der Grund
    # steht in js/home.js: die Startseite holt vier Listen in einem
    # Promise.all, und eine 503 daraus würde alle vier Kacheln leer lassen,
    # nicht nur die betroffene.
    if not db.is_configured():
        return {"teams": [], "last_updated": None, "error": RIDERS_NOT_CONFIGURED}
    try:
        teams = db.get_teams(category)
        last_updated = db.teams_last_updated()
    except Exception:  # noqa: BLE001 - Detail nur ins Log, siehe messages.py
        logger.exception("Team-Liste konnte nicht gelesen werden")
        return {"teams": [], "last_updated": None, "error": DB_UNAVAILABLE}
    return {"teams": teams, "last_updated": last_updated, "error": None}


@router.get("/{team_id}")
def get_team(team_id: str):
    """Ein einzelnes Team.

    Die Team-Detailseite holte sich vorher die komplette Team-Liste und
    suchte darin mit find() den einen Eintrag (js/team.js) - 18 Teams
    übertragen, um eines anzuzeigen, und dieselbe Suche noch einmal im
    Browser. Mit steigender Team-Zahl (Frauen-Teams, ProTeams) wird das
    schlechter, nicht besser.
    """
    if not db.is_configured():
        raise HTTPException(status_code=503, detail=RIDERS_NOT_CONFIGURED)
    try:
        team = db.get_team(team_id)
    except Exception:  # noqa: BLE001
        logger.exception("Team konnte nicht gelesen werden")
        raise HTTPException(status_code=503, detail=DB_UNAVAILABLE)
    if team is None:
        raise HTTPException(status_code=404, detail="Team nicht gefunden")
    return team


@router.get("/{team_id}/stats")
# Strenger als der Default: ein Aufruf löst drei Abfragen aus (Team,
# Aggregation, Siegliste). `request` und `response` braucht slowapi, nicht
# diese Funktion - siehe routers/race_history.py::get_race und
# main.py::_check_ratelimit_headers, dort steht warum.
@limiter.limit(RATE_LIMIT_TEAM_STATS)
def team_season_stats(
    request: Request,
    response: Response,
    team_id: str,
    season: int = Query(RACE_SEASON_YEAR, ge=1900, le=2100),
):
    """Siege, Podestplätze und Top-10-Platzierungen eines Teams in einer
    Saison, plus die Liste der Siege.

    Die Berechnung lief vorher im Browser (js/team.js::computeStats) über
    alle gecachten Ergebnisse und zählte dabei falsch: `findIndex` fand nur
    den besten Fahrer eines Teams pro Rennen, "Top-10-Platzierungen" waren
    also Rennen mit mindestens einer Top-10-Platzierung, und zwei
    Podestplätze desselben Teams im selben Rennen ergaben einen. Hier zählt
    ein GROUP BY über die Ergebniszeilen - also Platzierungen, wie das Label
    sagt. Etappenergebnisse sind enthalten.
    """
    if not db.is_configured():
        raise HTTPException(status_code=503, detail=RIDERS_NOT_CONFIGURED)
    try:
        team = db.get_team(team_id)
        if team is None:
            raise HTTPException(status_code=404, detail="Team nicht gefunden")
        stats = db_races.get_team_season_stats(team["name"], season)
        wins = db_races.get_team_season_wins(team["name"], season)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Team-Statistik fehlgeschlagen")
        return {"season": season, "stats": None, "wins": [], "error": DB_UNAVAILABLE}
    return {
        "season": season,
        "team_name": team["name"],
        "stats": stats,
        "wins": wins,
        "error": None,
    }
