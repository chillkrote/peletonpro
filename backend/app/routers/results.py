from fastapi import APIRouter
from typing import Literal

from .. import cache

router = APIRouter(prefix="/api/results", tags=["results"])


@router.get("")
def list_results(status: Literal["live", "finished", "upcoming"] | None = None):
    entry = cache.get("results") or {}
    results = entry.get("data") or []
    if status:
        results = [r for r in results if r.get("status") == status]
    return {
        "results": results,
        "last_updated": entry.get("last_updated"),
        "error": entry.get("error"),
    }
