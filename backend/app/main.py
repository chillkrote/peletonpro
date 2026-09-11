import logging
import re

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
            flat = " ".join(text.split())  # Zeilenumbrüche entfernen, damit Render-Logs nicht abschneiden
            markers = [
                "UAE Team Emirates", "Visma", "Alpecin", "Ineos", "Lidl-Trek",
                "__NEXT_DATA__", "__NUXT__", "__INITIAL_STATE__",
                "id=\"root\"", "id=\"app\"", "ng-version", "data-reactroot",
                "application/ld+json", "views-view", "field--name", "paragraph--type",
                "enable javascript", "roster",
            ]
            found = [m for m in markers if m.lower() in flat.lower()]
            logger.info(
                "UCI-Probe: %s -> status=%s final_url=%s len=%d markers=%s",
                probe_url,
                resp.status_code,
                resp.url,
                len(text),
                found,
            )
            body_start = flat.find("<body")
            snippet = flat[body_start:body_start + 4000] if body_start != -1 else flat[:4000]
            logger.info("UCI-Probe body snippet: %s", snippet)
            logger.info("UCI-Probe body snippet (4000-9000): %s", flat[body_start + 4000:body_start + 9000])

            ldjson_pos = flat.lower().find("application/ld+json")
            if ldjson_pos != -1:
                logger.info("UCI-Probe ld+json context: %s", flat[max(0, ldjson_pos - 50):ldjson_pos + 2000])

            # API-Endpunkte suchen, die der Frontend-JS-Code fürs Nachladen der
            # Team-Daten aufrufen könnte (Hinweis auf REST/GraphQL statt HTML).
            api_hints = set(re.findall(r'"(/api/[a-zA-Z0-9/_\-{}]*)"', flat))
            api_hints |= set(re.findall(r'"(https?://[a-zA-Z0-9.\-]*uci[a-zA-Z0-9.\-]*/(?:api|graphql)[a-zA-Z0-9/_\-{}]*)"', flat, re.IGNORECASE))
            logger.info("UCI-Probe api hints: %s", sorted(api_hints)[:30])

            # Alle <script src="..."> URLs, um das JS-Framework/Bundle zu identifizieren
            script_srcs = re.findall(r'<script[^>]*\bsrc="([^"]+)"', flat)
            logger.info("UCI-Probe script srcs: %s", script_srcs[:20])
        except Exception as exc:  # noqa: BLE001 - nur Diagnose, darf App nicht crashen
            logger.warning("UCI-Probe fehlgeschlagen für %s: %s", probe_url, exc)

    # Scheduler läuft im Hintergrund-Thread; der erste Lauf jedes Jobs
    # startet sofort (next_run_time=now), blockiert also nicht den
    # FastAPI-Startvorgang selbst.
    app.state.scheduler = start_scheduler()
