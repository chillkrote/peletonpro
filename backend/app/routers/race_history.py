import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException

from .. import db, db_races

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/race-history", tags=["race-history"])

NOT_CONFIGURED_ERROR = "Renn-Historie-Datenbank nicht konfiguriert (DATABASE_URL fehlt)"


@router.get("")
def list_races(
    season: Optional[int] = None,
    category: Optional[Literal["wt", "proseries", "continental"]] = None,
    circuit: Optional[Literal["africa", "asia", "europe", "america", "oceania"]] = None,
    limit: int = 500,
    offset: int = 0,
):
    """Leichtgewichtige Liste (ohne Ergebnisse/Etappen) - für Details siehe
    GET /api/race-history/{id}. `limit`/`offset` für Pagination, da die
    Gesamtzahl (World Tour + ProSeries + 5 Continental Touren seit
    RACE_HISTORY_START_YEAR) mehrere hundert bis tausend Rennen umfasst."""
    if not db.is_configured():
        return {"races": [], "error": NOT_CONFIGURED_ERROR}
    try:
        races = db_races.get_races(season=season, category=category, circuit=circuit, limit=limit, offset=offset)
        return {"races": [r.model_dump() for r in races], "error": None}
    except Exception as exc:  # noqa: BLE001 - DB kann z.B. zeitig ablaufen (Free-Tier)
        logger.error("Renn-Historie-Abfrage fehlgeschlagen: %s", exc)
        return {"races": [], "error": str(exc)}


@router.get("/{race_id}")
def get_race(race_id: str):
    """Ein Rennen inkl. Gesamt-/Eintagesrennen-Ergebnis (`results`) und bei
    Mehretagenrennen der kompletten Etappenliste inkl. je Etappe eigener
    Ergebnisliste (`stages[].results`)."""
    if not db.is_configured():
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED_ERROR)
    race = db_races.get_race(race_id)
    if race is None:
        raise HTTPException(status_code=404, detail="Rennen nicht gefunden")
    return race.model_dump()
