import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response

from .. import db, db_races
from ..gender import GENDER_DEFAULT, Gender
from ..ratelimit import RATE_LIMIT_RIDER_RESULTS, limiter
from .messages import DB_UNAVAILABLE, RIDERS_NOT_CONFIGURED

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/riders", tags=["riders"])

# Die Fahrerliste ist heute mit ~517 Einträgen unkritisch, wächst aber mit
# jeder weiteren Datenbank (Frauen-Radsport, mehr Historie). Grenze und
# Gesamtzahl jetzt, damit das Frontend später paginieren kann, ohne dass die
# Antwortstruktur noch einmal bricht.
MAX_LIMIT = 1000
DEFAULT_LIMIT = 1000

# Ergebnisse eines Fahrers: andere Größenordnung als die Fahrerliste. Ein
# Fahrer mit sieben Saisons kommt auf einige hundert Zeilen (Gesamtwertungen
# und Etappen), die Detailseite zeigt davon zunächst eine Seite.
RESULTS_MAX_LIMIT = 200
RESULTS_DEFAULT_LIMIT = 50


@router.get("")
def list_riders(
    team: Optional[str] = None,
    gender: Gender = GENDER_DEFAULT,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Fahrer und Fahrerinnen, nach Nachname sortiert.

    `gender` hat den Default 'm', damit jeder Aufrufer, der den Parameter
    nicht kennt, genau das bekommt, was er vorher bekam - der ganze
    Bestand ist Männer-Radsport (siehe backend/README.md,
    "Geschlechts-Dimension")."""
    if not db.is_configured():
        return {"riders": [], "total": 0, "limit": limit, "offset": offset,
                "gender": gender, "error": RIDERS_NOT_CONFIGURED}
    try:
        riders = db.get_riders(team_id=team, limit=limit, offset=offset, gender=gender)
        return {
            "riders": [r.model_dump() for r in riders],
            "total": db.count_riders(team_id=team, gender=gender),
            "gender": gender,
            "limit": limit,
            "offset": offset,
            "error": None,
        }
    except Exception:  # noqa: BLE001 - DB kann z.B. zeitig ablaufen (Free-Tier)
        logger.exception("Fahrer-Abfrage fehlgeschlagen")
        return {"riders": [], "total": 0, "limit": limit, "offset": offset,
                "error": DB_UNAVAILABLE}


@router.get("/{rider_id}")
def get_rider(rider_id: str):
    if not db.is_configured():
        raise HTTPException(status_code=503, detail=RIDERS_NOT_CONFIGURED)
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


@router.get("/{rider_id}/results")
# Strenger als der Default: zwei Abfragen pro Aufruf. `request` und
# `response` braucht slowapi, nicht diese Funktion - siehe
# main.py::_check_ratelimit_headers, dort steht warum das Fehlen von
# `response` zu einem 500 bei JEDEM Aufruf führt.
@limiter.limit(RATE_LIMIT_RIDER_RESULTS)
def get_rider_results(
    request: Request,
    response: Response,
    rider_id: str,
    limit: int = Query(RESULTS_DEFAULT_LIMIT, ge=1, le=RESULTS_MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Die Platzierungen eines Fahrers, neueste Saison zuerst.

    Eigener Endpunkt statt eines Feldes in /api/riders/{id}: die Liste ist
    unbegrenzt lang (Gesamtwertungen und Etappen über alle Saisons) und
    paginiert, während die Detailantwort eine feste Größe hat. Ein Feld
    hätte die Detailseite mit Daten belastet, die sie erst beim Aufklappen
    braucht.

    Möglich geworden durch `race_results.rider_id` (Migration 0004). Vorher
    stand dort nur der Name als Text.

    `total` ist die Gesamtzahl, damit das Frontend das Ende der Liste
    erkennt, ohne eine leere Seite anzufordern.

    Kein `gender`-Parameter: das Geschlecht steckt in der Fahrer-ID (siehe
    backend/README.md, "Die ID-Regel").
    """
    if not db.is_configured():
        raise HTTPException(status_code=503, detail=RIDERS_NOT_CONFIGURED)
    try:
        # Erst prüfen, ob es den Fahrer überhaupt gibt: sonst wäre eine leere
        # Liste die Antwort auf eine erfundene ID, und ein Tippfehler sähe wie
        # "hat keine Ergebnisse" aus.
        if db.get_rider(rider_id) is None:
            raise HTTPException(status_code=404, detail="Fahrer nicht gefunden")
        results = db_races.get_rider_results(rider_id, limit=limit, offset=offset)
        total = db_races.count_rider_results(rider_id)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - Detail nur ins Log, siehe messages.py
        logger.exception("Ergebnisse eines Fahrers konnten nicht gelesen werden")
        return {"results": [], "total": 0, "limit": limit, "offset": offset,
                "error": DB_UNAVAILABLE}
    return {
        "results": [r.model_dump() for r in results],
        "total": total,
        "limit": limit,
        "offset": offset,
        "error": None,
    }
