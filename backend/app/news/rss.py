"""RSS-News-Aggregator (Cyclingnews + Google News 'Radsport').

Nutzt feedparser, das RSS/Atom generisch normalisiert - dadurch deutlich
robuster gegenüber Struktur-Details der jeweiligen Quelle als klassisches
HTML-Scraping. Trotzdem unverifiziert in dieser Session (kein Netzwerk-
zugriff auf die Feed-URLs möglich), daher mit Fehlerbehandlung pro Feed:
ein einzelner nicht erreichbarer Feed verhindert nicht, dass die anderen
Feeds trotzdem ausgeliefert werden.
"""
import hashlib
import logging
from datetime import datetime, timezone

import feedparser

from ..config import NEWS_FEEDS
from ..models import NewsItem

logger = logging.getLogger(__name__)


def _entry_id(entry, source: str) -> str:
    raw = entry.get("id") or entry.get("link") or f"{source}-{entry.get('title', '')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _entry_published(entry) -> str | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def fetch_feed(name: str, url: str) -> list[NewsItem]:
    parsed = feedparser.parse(url)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Feed '{name}' konnte nicht geparst werden: {parsed.bozo_exception}")

    items: list[NewsItem] = []
    for entry in parsed.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue
        items.append(
            NewsItem(
                id=_entry_id(entry, name),
                title=title,
                link=link,
                source=name,
                published=_entry_published(entry),
                summary=(entry.get("summary") or "")[:500] or None,
            )
        )
    return items


def fetch_all_news() -> list[NewsItem]:
    all_items: list[NewsItem] = []
    errors: list[str] = []
    seen_titles: set[str] = set()

    for feed in NEWS_FEEDS:
        try:
            items = fetch_feed(feed["name"], feed["url"])
        except Exception as exc:  # noqa: BLE001 - siehe Modul-Docstring
            logger.warning("News-Feed '%s' fehlgeschlagen: %s", feed["name"], exc)
            errors.append(f"{feed['name']}: {exc}")
            continue
        for item in items:
            key = item.title.lower().strip()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            all_items.append(item)

    all_items.sort(key=lambda i: i.published or "", reverse=True)

    if not all_items and errors:
        raise RuntimeError("; ".join(errors))
    return all_items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for n in fetch_all_news():
        print(n.model_dump())
