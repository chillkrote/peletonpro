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


def _log_section(page: str, section_line_substr: str) -> None:
    result = _wiki_get({"action": "parse", "page": page, "prop": "sections"})
    sections = result["json"].get("parse", {}).get("sections", [])
    for sec in sections:
        line = sec.get("line", "")
        if section_line_substr.lower() in line.lower():
            idx = sec.get("index")
            text_result = _wiki_get({"action": "parse", "page": page, "prop": "text", "section": idx})
            html = text_result["json"].get("parse", {}).get("text", {}).get("*", "")
            flat = " ".join(html.split())
            logger.info("Wiki-Probe '%s' section '%s' (idx=%s) len=%d snippet=%s", page, line, idx, len(flat), flat[:4000])


def _wiki_probe() -> None:
    """TEMPORÄR - wird wieder entfernt: prüft die Struktur von Team-Kader-
    Abschnitten und Fahrer-Infoboxen (Team-Historie) auf Wikipedia, um
    Machbarkeit einer Fahrer/Team-Datenbank mit Wechsel-Historie zu klären."""
    try:
        result = _wiki_get({"action": "parse", "page": "UAE Team Emirates XRG", "prop": "sections"})
        sections = result["json"].get("parse", {}).get("sections", [])
        logger.info("Wiki-Probe 'UAE Team Emirates XRG' sections=%s", [s.get("line") for s in sections])
        for candidate in ("Roster", "Team roster", "Current roster", "Riders"):
            try:
                _log_section("UAE Team Emirates XRG", candidate)
            except Exception:
                pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("Wiki-Probe Team-Roster fehlgeschlagen: %s", exc)

    try:
        html_result = _wiki_get({"action": "parse", "page": "Tadej Pogačar", "prop": "text", "section": 0})
        html = html_result["json"].get("parse", {}).get("text", {}).get("*", "")
        flat = " ".join(html.split())
        logger.info("Wiki-Probe 'Tadej Pogačar' infobox (section 0) len=%d snippet=%s", len(flat), flat[:6000])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Wiki-Probe Fahrer-Infobox fehlgeschlagen: %s", exc)


@app.on_event("startup")
def on_startup() -> None:
    _wiki_probe()

    # Scheduler läuft im Hintergrund-Thread; der erste Lauf jedes Jobs
    # startet sofort (next_run_time=now), blockiert also nicht den
    # FastAPI-Startvorgang selbst.
    app.state.scheduler = start_scheduler()
