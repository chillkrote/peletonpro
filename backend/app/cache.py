"""Einfacher In-Memory-Cache mit JSON-Datei-Persistenz. Nur noch für News.

Jeder Schlüssel wird sowohl im Speicher als auch als JSON-Datei unter
CACHE_DIR gehalten. Bei einem fehlschlagenden Scraping-Lauf wird der letzte
funktionierende Stand weiter ausgeliefert, statt die API mit einem Fehler zu
beantworten (siehe set()).

WARUM NUR NOCH NEWS
-------------------
Der Cache hatte zwei Schlüssel: "teams" und "news". Die Teams lagen damit
doppelt - einmal hier als JSON-Datei, einmal in der Postgres-Tabelle
`teams`, in die derselbe Scraper-Lauf sie ebenfalls schrieb. Die Tabelle
ist die richtige Quelle (sie hat Fremdschlüssel von riders und
rider_stints, sie übersteht Deploys, und sie wächst mit weiteren Teams),
also liest /api/teams jetzt von dort. Siehe db.get_teams.

News bleiben hier, und das ist eine Entscheidung, keine Auslassung:

- News sind ein flacher RSS-Auszug von ~20 Einträgen, auf den nichts
  verweist und den nichts joint. Eine Tabelle dafür bräuchte Schema,
  Migration und eine Aufräumregel für alte Einträge - Aufwand ohne
  Gegenwert.
- Sie sind das Einzige, was die Seite noch ohne Datenbank anzeigen kann.
  Das ist beim Debuggen nützlich.
- Verlorene News sind kein Datenverlust. Der RSS-Feed ist die Quelle und
  liefert sie beim nächsten Lauf (REFRESH_INTERVAL_NEWS, Default 30 min)
  wieder.

GRENZE DER PERSISTENZ
---------------------
Auf Renders Free-Plan ist das Dateisystem flüchtig: die JSON-Datei ist
nach jedem Deploy und nach jedem Aufwachen aus dem Schlafmodus (nach 15
Minuten ohne Request) weg. Wirksam ist dort also nur der
In-Memory-Anteil. Praktisch heißt das: der erste Request nach einem Deploy
sieht eine leere News-Liste, bis der erste Scheduler-Lauf durch ist (er
startet sofort beim Hochfahren). Wer sich auf die Datei verlässt, verlässt
sich auf nichts - deshalb steht das hier und nicht im Verborgenen.
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
