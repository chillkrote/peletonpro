from fastapi import APIRouter

from .. import cache

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("")
def list_news(limit: int = 30):
    entry = cache.get("news") or {}
    news = entry.get("data") or []
    return {
        "news": news[:limit],
        "last_updated": entry.get("last_updated"),
        "error": entry.get("error"),
    }
