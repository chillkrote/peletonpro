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


def _debug_season_tables(title: str) -> dict:
    """TEMPORÄR: Diagnose-Helfer zur Verifikation der Renn-Historie-Scraper-
    Struktur gegen echte Wikipedia-Seiten (dieses Sandbox-Environment hat
    keinen Netzwerkzugriff auf Wikipedia UND keinen auf die deployte
    Render-URL - Ergebnisse laufen daher über logger.info, ausgelesen per
    Render-Log-API statt per HTTP-Response). Wird nach der Verifikation
    wieder entfernt - siehe backend/README.md, Abschnitt "Renn-Historie"."""
    from bs4 import BeautifulSoup

    from .scrapers.wikipedia import fetch_full_page

    html = fetch_full_page(title)
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.select("table.wikitable")
    result = []
    for i, table in enumerate(tables):
        rows = table.select("tr")
        header_cells = rows[0].find_all(["th", "td"]) if rows else []
        headers = [c.get_text(strip=True) for c in header_cells]
        sample_row_html = str(rows[1])[:600] if len(rows) > 1 else None
        result.append({"index": i, "headers": headers, "row_count": max(0, len(rows) - 1), "sample_row_html": sample_row_html})
    return {"title": title, "table_count": len(tables), "tables": result}


@app.get("/api/_debug/season-tables")
def debug_season_tables(title: str):
    return _debug_season_tables(title)


def _run_startup_diagnostics() -> None:
    """TEMPORÄR: läuft einmal beim Start, loggt die Tabellenstruktur der
    Seiten, die beim ersten Produktivlauf 0 Rennen lieferten."""
    for title in ("2020 UCI Europe Tour", "2021 UCI Europe Tour", "2020 UCI ProSeries"):
        try:
            info = _debug_season_tables(title)
            logger.info("DIAGNOSE %s: %d Tabellen", title, info["table_count"])
            for t in info["tables"]:
                logger.info("DIAGNOSE %s table[%d] headers=%s rows=%d", title, t["index"], t["headers"], t["row_count"])
                logger.info("DIAGNOSE %s table[%d] sample=%s", title, t["index"], t["sample_row_html"])
        except Exception as exc:  # noqa: BLE001
            logger.error("DIAGNOSE %s fehlgeschlagen: %s", title, exc)


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

    # Scheduler läuft im Hintergrund-Thread; der erste Lauf jedes Jobs
    # startet sofort (next_run_time=now), blockiert also nicht den
    # FastAPI-Startvorgang selbst.
    app.state.scheduler = start_scheduler()

    import threading

    threading.Thread(target=_run_startup_diagnostics, daemon=True).start()
