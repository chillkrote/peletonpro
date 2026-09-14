import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from .. import db
from ..gender import GENDER_DEFAULT
from .messages import DB_UNAVAILABLE, RIDERS_NOT_CONFIGURED

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/riders", tags=["riders"])

# Die Fahrerliste ist heute mit ~517 Einträgen unkritisch, wächst aber mit
# jeder weiteren Datenbank (Frauen-Radsport, mehr Historie). Grenze und
# Gesamtzahl jetzt, damit das Frontend später paginieren kann, ohne dass die
# Antwortstruktur noch einmal bricht.
MAX_LIMIT = 1000
DEFAULT_LIMIT = 1000


@router.get("")
def list_riders(
    team: Optional[str] = None,
    gender: Literal["m", "w"] = GENDER_DEFAULT,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Fahrer und Fahrerinnen, nach Nachname sortiert.

    `gender` hat den Default 'm', damit jeder Aufrufer, der den Parameter
    nicht kennt, genau das bekommt, was er vorher bekam - der ganze
    Bestand ist Männer-Radsport (siehe backend/README.md,
    "Geschlechts-Dimension")."""
    if not db.is_configured():
        return {"riders": [], "total": 0, "limit": limit, "offset": offset,
                "gender": gender, "error": RIDERS_NOT_CONFIGURED}
    try:
        riders = db.get_riders(team_id=team, limit=limit, offset=offset, gender=gender)
        return {
            "riders": [r.model_dump() for r in riders],
            "total": db.count_riders(team_id=team, gender=gender),
            "gender": gender,
            "limit": limit,
            "offset": offset,
            "error": None,
        }
    except Exception:  # noqa: BLE001 - DB kann z.B. zeitig ablaufen (Free-Tier)
        logger.exception("Fahrer-Abfrage fehlgeschlagen")
        return {"riders": [], "total": 0, "limit": limit, "offset": offset,
                "error": DB_UNAVAILABLE}


@router.get("/{rider_id}")
def get_rider(rider_id: str):
    if not db.is_configured():
        raise HTTPException(status_code=503, detail=RIDERS_NOT_CONFIGURED)
    rider = db.get_rider(rider_id)
    if rider is None:
        raise HTTPException(status_code=404, detail="Fahrer nicht gefunden")
    history = db.get_rider_stints(rider_id)
    seasons = db.get_rider_seasons(rider_id)
    return {
        **rider.model_dump(),
        "history": [s.model_dump() for s in history],
        "seasons": [s.model_dump() for s in seasons],
    }
