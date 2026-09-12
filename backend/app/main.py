import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, db_races
from .config import CORS_ORIGINS
from .routers import export, news, race_history, races, results, riders, teams
from .scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PelotonPro API")

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


@app.on_event("startup")
def on_startup() -> None:
    try:
        db.init_schema()
    except Exception as exc:  # noqa: BLE001 - App darf ohne DB weiterlaufen
        logger.error("Fahrer-Datenbank-Schema konnte nicht initialisiert werden: %s", exc)

    try:
        db_races.init_schema()
    except Exception as exc:  # noqa: BLE001 - App darf ohne DB weiterlaufen
        logger.error("Renn-Historie-Schema konnte nicht initialisiert werden: %s", exc)

    # EINMALIGER Fix für den Season-Parser-Bug (siehe db_races.reset_seed_log
    # Docstring) - wird nach dem bestätigten Neu-Seeding wieder entfernt.
    try:
        cleared = db_races.reset_seed_log()
        if cleared:
            logger.info("Renn-Historie-Seed-Log zurückgesetzt (Parser-Fix): %d Einträge, wird neu geseedet", cleared)
    except Exception as exc:  # noqa: BLE001
        logger.error("Renn-Historie-Seed-Log-Reset fehlgeschlagen: %s", exc)

    # Scheduler läuft im Hintergrund-Thread; der erste Lauf jedes Jobs
    # startet sofort (next_run_time=now), blockiert also nicht den
    # FastAPI-Startvorgang selbst.
    app.state.scheduler = start_scheduler()
