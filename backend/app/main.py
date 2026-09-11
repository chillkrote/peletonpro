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


@app.on_event("startup")
def on_startup() -> None:
    # TEMPORÄR - wird in einem Folge-Commit wieder entfernt: einmalige
    # Erreichbarkeits-Probe für uci.org, um per Render-Logs zu prüfen, ob
    # die UCI-Seite Cloud-Hosting-IPs blockiert (wie procyclingstats.com)
    # oder als alternative Datenquelle nutzbar wäre.
    for probe_url in ("https://www.uci.org/road/teams",):
        try:
            resp = httpx.get(
                probe_url,
                headers={"User-Agent": SCRAPER_USER_AGENT},
                timeout=15,
                follow_redirects=True,
            )
            text = resp.text
            markers = ["UAE Team Emirates", "Visma", "Alpecin", "__NEXT_DATA__", "id=\"root\"", "id=\"__next\""]
            found = [m for m in markers if m in text]
            logger.info(
                "UCI-Probe: %s -> status=%s final_url=%s len=%d markers=%s",
                probe_url,
                resp.status_code,
                resp.url,
                len(text),
                found,
            )
            # Body-Anfang loggen, um SPA-Shell vs. serverseitig gerendertes HTML zu unterscheiden
            body_start = text.find("<body")
            snippet = text[body_start:body_start + 1500] if body_start != -1 else text[:1500]
            logger.info("UCI-Probe body snippet: %s", snippet)
        except Exception as exc:  # noqa: BLE001 - nur Diagnose, darf App nicht crashen
            logger.warning("UCI-Probe fehlgeschlagen für %s: %s", probe_url, exc)

    # Scheduler läuft im Hintergrund-Thread; der erste Lauf jedes Jobs
    # startet sofort (next_run_time=now), blockiert also nicht den
    # FastAPI-Startvorgang selbst.
    app.state.scheduler = start_scheduler()
