import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from . import db, db_races
from .config import CORS_ORIGINS, REQUIRE_DATABASE
from .routers import export, news, race_history, races, results, riders, teams
from .ratelimit import limiter
from .routers.messages import INTERNAL_ERROR
from .scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _check_ratelimit_coverage(app: FastAPI) -> None:
    """Prüft, dass SlowAPIMiddleware die Routen überhaupt auflösen kann.

    Die Middleware ermittelt die Route über _find_route_handler(app.routes,
    scope) und schaut dabei nur EINE Ebene tief: findet sie kein Objekt mit
    `.endpoint`, hält sie die Route für ausgenommen und drosselt sie nicht -
    stillschweigend.

    Unter der gepinnten FastAPI 0.115.0 flacht include_router() alle Routen
    zu APIRoute-Objekten ab, die Auflösung funktioniert also. Neuere
    Versionen (nachgemessen mit 0.141.1) legen stattdessen ein opakes
    `_IncludedRouter`-Objekt ohne `.endpoint` ab - damit wäre die
    Default-Grenze wirkungslos, und zwar ohne jede Fehlermeldung. Ein
    FastAPI-Upgrade würde das Rate Limiting also lautlos abschalten.

    Diese Prüfung macht daraus eine sichtbare Warnung beim Start."""
    opaque = [r for r in app.routes if not hasattr(r, "endpoint")]
    if opaque:
        logger.warning(
            "Rate Limiting greift möglicherweise nicht: %d Routen in app.routes "
            "haben kein .endpoint-Attribut (%s). SlowAPIMiddleware kann sie nicht "
            "auflösen und nimmt sie von der Default-Grenze aus. Ursache ist "
            "meist ein FastAPI-Upgrade - dann müssen die Grenzen als "
            "@limiter.limit-Dekorator an die Endpunkte wandern.",
            len(opaque),
            ", ".join(sorted({type(r).__name__ for r in opaque})),
        )
    else:
        logger.info("Rate Limiting: %d Routen auflösbar", len(app.routes))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start- und Herunterfahren der App.

    Ersetzt die früheren Startup-Event-Handler, die in FastAPI 0.115
    deprecated sind - und ist die Stelle, an der der Postgres-Verbindungs-Pool
    (siehe app/db.py) am Ende wieder geschlossen wird.
    """
    _check_ratelimit_coverage(app)

    if REQUIRE_DATABASE and not db.is_configured():
        # Absichtlich harter Abbruch statt einer Warnung: eine Instanz, die
        # leere Fahrer- und Renn-Listen ausliefert, sieht im Betrieb gesund
        # aus und fällt erst auf, wenn jemand die Website anschaut.
        raise RuntimeError(
            "REQUIRE_DATABASE ist gesetzt, aber DATABASE_URL fehlt - "
            "Start abgebrochen, statt leere Daten auszuliefern."
        )

    try:
        db.init_schema()
    except Exception as exc:  # noqa: BLE001 - App darf ohne DB weiterlaufen
        logger.error("Fahrer-Datenbank-Schema konnte nicht initialisiert werden: %s", exc)

    try:
        db_races.init_schema()
    except Exception as exc:  # noqa: BLE001 - App darf ohne DB weiterlaufen
        logger.error("Renn-Historie-Schema konnte nicht initialisiert werden: %s", exc)

    # Scheduler läuft im Hintergrund-Thread; der erste Lauf jedes Jobs
    # startet sofort (next_run_time=now), blockiert also nicht den
    # FastAPI-Startvorgang selbst.
    scheduler = start_scheduler()
    app.state.scheduler = scheduler

    yield

    scheduler.shutdown(wait=False)
    db.close_pool()


# slowapi holt den Limiter aus app.state. SlowAPIMiddleware setzt die
# Default-Grenze für alle Endpunkte durch; die strengeren Grenzen der teuren
# Routen stehen als Dekorator an den Routen selbst (siehe
# routers/race_history.py und routers/export.py).
app = FastAPI(title="PelotonPro API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fängt alles, was kein Router selbst behandelt, loggt es mit Stacktrace
    und antwortet mit einem festen Text.

    Ohne diesen Handler liefert Starlette bei einer unbehandelten Exception
    eine 500 und reicht die Exception an den Server weiter - was je nach
    Konfiguration im Log oder in der Antwort landet. Hier ist beides
    festgelegt: Detail ins Log, nach außen nur INTERNAL_ERROR. Ein
    psycopg-Verbindungsfehler enthält in seinem Text Host, Port, Benutzernamen
    und Datenbanknamen (siehe app/routers/messages.py)."""
    logger.exception("Unbehandelter Fehler bei %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": INTERNAL_ERROR})


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(teams.router)
app.include_router(races.router)
app.include_router(results.router)
app.include_router(riders.router)
app.include_router(race_history.router)
app.include_router(export.router)
app.include_router(news.router)


@app.get("/api/health")
# Ausdrücklich NICHT gedrosselt: Render fragt diesen Pfad als Health Check
# alle ~10 Sekunden ab. Eine Drosselung würde dem Anbieter eine kaputte
# Instanz melden und Deploys scheitern lassen - ein selbstgemachter Ausfall.
# Nachgemessen: ohne diese Ausnahme wurden 30 von 40 Health-Check-Requests
# mit 429 abgewiesen.
@limiter.exempt
def health(request: Request):
    return {"status": "ok"}
