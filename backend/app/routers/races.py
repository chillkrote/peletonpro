from fastapi import APIRouter

from .. import cache

router = APIRouter(prefix="/api", tags=["races"])


@router.get("/races")
def list_races():
    entry = cache.get("races") or {}
    return {
        "races": entry.get("data") or [],
        "last_updated": entry.get("last_updated"),
        "error": entry.get("error"),
    }


@router.get("/calendar")
def list_calendar():
    """Kalenderansicht wird aus dem Renn-Cache abgeleitet (ein Eintrag pro Rennstart)."""
    entry = cache.get("races") or {}
    races = entry.get("data") or []
    events = [
        {
            "id": r["id"],
            "date": r["start_date"],
            "race_id": r["id"],
            "race_name": r["name"],
        }
        for r in races
    ]
    return {
        "events": events,
        "last_updated": entry.get("last_updated"),
        "error": entry.get("error"),
    }
