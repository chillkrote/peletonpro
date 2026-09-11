import logging

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS, SCRAPER_USER_AGENT
from .routers import news, races, results, teams
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
app.include_router(news.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


WIKI_API = "https://en.wikipedia.org/w/api.php"


def _wiki_get(params: dict) -> dict:
    resp = httpx.get(
        WIKI_API,
        params={**params, "format": "json"},
        headers={"User-Agent": SCRAPER_USER_AGENT},
        timeout=15,
    )
    return {"status_code": resp.status_code, "json": resp.json()}


def _wiki_probe() -> None:
    """TEMPORÄR - wird wieder entfernt: prüft per Render-Logs, ob Wikipedia von
    Render aus erreichbar ist und wie die Team-/Kalender-Seiten strukturiert sind."""
    try:
        result = _wiki_get({"action": "parse", "page": "UCI World Tour", "prop": "sections"})
        sections = result["json"].get("parse", {}).get("sections", [])
        logger.info(
            "Wiki-Probe sections status=%s count=%d lines=%s",
            result["status_code"],
            len(sections),
            [s.get("line") for s in sections],
        )
        for sec in sections:
            line = sec.get("line", "")
            if "worldteam" in line.lower() or "proteam" in line.lower():
                idx = sec.get("index")
                text_result = _wiki_get({"action": "parse", "page": "UCI World Tour", "prop": "text", "section": idx})
                html = text_result["json"].get("parse", {}).get("text", {}).get("*", "")
                flat = " ".join(html.split())
                logger.info("Wiki-Probe section '%s' (idx=%s) len=%d snippet=%s", line, idx, len(flat), flat[:4000])
    except Exception as exc:  # noqa: BLE001 - nur Diagnose, darf App nicht crashen
        logger.warning("Wiki-Probe (Teams-Sektion) fehlgeschlagen: %s", exc)

    for candidate in ("2026 UCI World Tour", "2026 UCI WorldTour", "2026 Tour de France"):
        try:
            result = _wiki_get({"action": "parse", "page": candidate, "prop": "sections"})
            data = result["json"]
            if "error" in data:
                logger.info("Wiki-Probe candidate '%s' -> error: %s", candidate, data["error"])
            else:
                lines = [s.get("line") for s in data.get("parse", {}).get("sections", [])]
                logger.info("Wiki-Probe candidate '%s' exists, status=%s sections=%s", candidate, result["status_code"], lines)
        except Exception as exc:  # noqa: BLE001 - nur Diagnose, darf App nicht crashen
            logger.warning("Wiki-Probe candidate '%s' fehlgeschlagen: %s", candidate, exc)


@app.on_event("startup")
def on_startup() -> None:
    _wiki_probe()

    # Scheduler läuft im Hintergrund-Thread; der erste Lauf jedes Jobs
    # startet sofort (next_run_time=now), blockiert also nicht den
    # FastAPI-Startvorgang selbst.
    app.state.scheduler = start_scheduler()
