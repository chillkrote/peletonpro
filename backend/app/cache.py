"""Einfacher In-Memory-Cache mit JSON-Datei-Persistenz.

Jeder Schlüssel (z.B. "teams", "news") wird sowohl im Speicher als auch als
JSON-Datei unter CACHE_DIR gehalten. Persistenz sorgt dafür, dass nach einem
Neustart des Backends nicht sofort wieder gescraped werden muss und dass bei
einem fehlschlagenden Scraping-Lauf der letzte funktionierende Stand
weiterhin ausgeliefert wird, statt die API mit einem Fehler zu beantworten.
"""
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from .config import CACHE_DIR

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_store: dict[str, dict[str, Any]] = {}


def _path_for(key: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{key}.json")


def _load_from_disk(key: str) -> Optional[dict[str, Any]]:
    path = _path_for(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Cache-Datei %s konnte nicht gelesen werden: %s", path, exc)
        return None


def get(key: str) -> Optional[dict[str, Any]]:
    """Liefert {"data": ..., "last_updated": iso-str, "error": str|None} oder None."""
    with _lock:
        if key in _store:
            return _store[key]
        entry = _load_from_disk(key)
        if entry is not None:
            _store[key] = entry
        return entry


def set(key: str, data: Any, error: Optional[str] = None) -> None:
    """Schreibt einen neuen erfolgreichen (oder fehlerhaften) Stand in den Cache.

    Bei error != None und vorhandenem alten Cache-Eintrag wird NUR das
    error-Feld aktualisiert, die alten (weiterhin gültigen) Daten bleiben
    erhalten - damit ein einzelner fehlschlagender Scraping-Lauf nicht die
    zuletzt bekannten guten Daten wegwirft.
    """
    with _lock:
        if key not in _store:
            disk_entry = _load_from_disk(key)
            if disk_entry is not None:
                _store[key] = disk_entry

        now = datetime.now(timezone.utc).isoformat()
        if error is not None and key in _store:
            entry = dict(_store[key])
            entry["error"] = error
            entry["last_attempt"] = now
        else:
            entry = {
                "data": data,
                "last_updated": now,
                "last_attempt": now,
                "error": error,
            }
        _store[key] = entry
        try:
            with open(_path_for(key), "w", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False, default=str)
        except OSError as exc:
            logger.warning("Cache-Datei für %s konnte nicht geschrieben werden: %s", key, exc)


def mark_error(key: str, error: str) -> None:
    """Registriert einen Scraping-Fehler ohne vorhandene Daten zu verwerfen."""
    set(key, data=None, error=error)
