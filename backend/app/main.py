import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, db_races
from .config import CORS_ORIGINS
from .routers import export, news, race_history, races, results, riders, teams
from .scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start- und Herunterfahren der App.

    Ersetzt die früheren Startup-Event-Handler, die in FastAPI 0.115
    deprecated sind - und ist die Stelle, an der der Postgres-Verbindungs-Pool
    (siehe app/db.py) am Ende wieder geschlossen wird.
    """
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


app = FastAPI(title="PelotonPro API", lifespan=lifespan)

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
def health():
    return {"status": "ok"}
