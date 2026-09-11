from fastapi import APIRouter
from typing import Literal

from .. import cache

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("")
def list_teams(category: Literal["wt", "pro", "cont"] | None = None):
    entry = cache.get("teams") or {}
    teams = entry.get("data") or []
    if category:
        teams = [t for t in teams if t.get("category") == category]
    return {
        "teams": teams,
        "last_updated": entry.get("last_updated"),
        "error": entry.get("error"),
    }
