import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from .. import db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/riders", tags=["riders"])

NOT_CONFIGURED_ERROR = "Fahrer-Datenbank nicht konfiguriert (DATABASE_URL fehlt)"


@router.get("")
def list_riders(team: Optional[str] = None):
    if not db.is_configured():
        return {"riders": [], "error": NOT_CONFIGURED_ERROR}
    try:
        riders = db.get_riders(team_id=team)
        return {"riders": [r.model_dump() for r in riders], "error": None}
    except Exception as exc:  # noqa: BLE001 - DB kann z.B. wegzeitig ablaufen (Free-Tier)
        logger.error("Fahrer-Abfrage fehlgeschlagen: %s", exc)
        return {"riders": [], "error": str(exc)}


@router.get("/{rider_id}")
def get_rider(rider_id: str):
    if not db.is_configured():
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED_ERROR)
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
