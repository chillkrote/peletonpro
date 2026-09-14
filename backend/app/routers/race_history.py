import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response

from .. import db, db_races
from ..gender import GENDER_DEFAULT, Gender
from ..ratelimit import RATE_LIMIT_RACE_DETAIL, limiter
from ..taxonomy import Category, Circuit
from .messages import DB_UNAVAILABLE, RACES_NOT_CONFIGURED

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/race-history", tags=["race-history"])

# Obergrenze für `limit`. Ohne sie ging der Wert ungeprüft in SQL: ein
# `?limit=999999999` war damit eine kostenlose Anfrage, die die Free-Instanz
# die volle Tabelle lesen, in Pydantic-Modelle gießen und als JSON
# serialisieren ließ - und das wird mit jedem weiteren Jahrgang schlimmer.
MAX_LIMIT = 500
DEFAULT_LIMIT = 200


@router.get("")
def list_races(
    season: Optional[int] = None,
    category: Optional[Category] = None,
    circuit: Optional[Circuit] = None,
    gender: Gender = GENDER_DEFAULT,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Leichtgewichtige Liste (ohne Ergebnisse/Etappen) - für Details siehe
    GET /api/race-history/{id}.

    `total` nennt die Gesamtzahl für dieselben Filter, damit das Frontend
    paginieren kann, ohne alles laden zu müssen.

    `gender` hat den Default 'm': der ganze Bestand ist Männer-Radsport,
    und ein Aufrufer, der den Parameter nicht kennt, bekommt damit genau
    das, was er vorher bekam (siehe backend/README.md,
    "Geschlechts-Dimension")."""
    if not db.is_configured():
        return {"races": [], "total": 0, "limit": limit, "offset": offset,
                "gender": gender, "error": RACES_NOT_CONFIGURED}
    try:
        races = db_races.get_races(
            season=season, category=category, circuit=circuit,
            limit=limit, offset=offset, gender=gender,
        )
        total = db_races.count_races(
            season=season, category=category, circuit=circuit, gender=gender
        )
        return {
            "races": [r.model_dump() for r in races],
            "total": total,
            "limit": limit,
            "offset": offset,
            "gender": gender,
            "error": None,
        }
    except Exception:  # noqa: BLE001 - DB kann z.B. zeitig ablaufen (Free-Tier)
        logger.exception("Renn-Historie-Abfrage fehlgeschlagen")
        return {"races": [], "total": 0, "limit": limit, "offset": offset,
                "gender": gender, "error": DB_UNAVAILABLE}


# ACHTUNG Reihenfolge: diese Route muss VOR "/{race_id}" stehen. FastAPI
# probiert die Routen in Deklarationsreihenfolge, sonst würde "seasons" als
# race_id durchgehen und ein 404 liefern.
@router.get("/seasons")
def list_seasons(gender: Gender = GENDER_DEFAULT):
    """Nur die Saisons, für die Rennen vorliegen - für die Saison-Tabs.
    Vorher leitete das Frontend sie aus der kompletten Renn-Liste ab und
    musste dafür alle Saisons auf einmal laden."""
    if not db.is_configured():
        return {"seasons": [], "gender": gender, "error": RACES_NOT_CONFIGURED}
    try:
        return {"seasons": db_races.get_seasons(gender=gender), "gender": gender,
                "error": None}
    except Exception:  # noqa: BLE001
        logger.exception("Saison-Abfrage fehlgeschlagen")
        return {"seasons": [], "gender": gender, "error": DB_UNAVAILABLE}


@router.get("/{race_id}")
# Strenger als der Default: ein Aufruf löst mehrere Abfragen aus (Rennen,
# Gesamt-Ergebnis, Etappen, Etappen-Ergebnisse).
#
# Die beiden Parameter `request` und `response` braucht slowapi, nicht diese
# Funktion. `request` ist die Quelle für den Zähler-Schlüssel (die Client-IP,
# siehe app/ratelimit.py). `response` ist die Stelle, an die slowapi die
# X-RateLimit-Header schreibt: Weil ratelimit.py mit headers_enabled=True
# arbeitet, ruft slowapi nach jedem Aufruf _inject_headers() auf, und wenn
# die Funktion keine Response zurückgibt (hier: ein dict) holt es sich das
# Objekt aus dem response-Parameter. Fehlt der, wirft slowapi selbst eine
# Exception und der Endpunkt antwortet mit 500 statt mit dem Rennen - egal
# ob die Grenze erreicht ist oder nicht. Genau das war hier der Fall
# (nachgemessen: 500 auf jeden Aufruf von /api/race-history/{id}).
#
# Endpunkte, die eine Response zurückgeben (die CSV-Exporte mit ihrer
# StreamingResponse), brauchen den Parameter deshalb nicht.
@limiter.limit(RATE_LIMIT_RACE_DETAIL)
def get_race(request: Request, response: Response, race_id: str):
    """Ein Rennen inkl. Gesamt-/Eintagesrennen-Ergebnis (`results`) und bei
    Mehretagenrennen der kompletten Etappenliste inkl. je Etappe eigener
    Ergebnisliste (`stages[].results`)."""
    if not db.is_configured():
        raise HTTPException(status_code=503, detail=RACES_NOT_CONFIGURED)
    race = db_races.get_race(race_id)
    if race is None:
        raise HTTPException(status_code=404, detail="Rennen nicht gefunden")
    return race.model_dump()
