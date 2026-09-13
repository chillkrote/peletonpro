from fastapi import APIRouter, Query

from .. import cache

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("")
def list_news(limit: int = Query(30, ge=1, le=200)):
    entry = cache.get("news") or {}
    news = entry.get("data") or []
    return {
        "news": news[:limit],
        "last_updated": entry.get("last_updated"),
        "error": entry.get("error"),
    }
