"""Gemeinsamer HTTP-Helfer für alle Scraper.

Zentralisiert User-Agent, Timeout und einen Mindestabstand zwischen
Requests, damit sich die Scraper gegenüber der Zielseite fair verhalten
(siehe backend/README.md, Abschnitt "Scraping-Ethik").
"""
import threading
import time

import httpx

from ..config import (
    SCRAPER_REQUEST_DELAY_SECONDS,
    SCRAPER_TIMEOUT_SECONDS,
    SCRAPER_USER_AGENT,
)

_last_request_at: dict[str, float] = {}
_lock = threading.Lock()


def get(url: str) -> httpx.Response:
    """GET mit Rate-Limiting pro Host und definiertem User-Agent.

    Wirft httpx.HTTPStatusError / httpx.RequestError bei Problemen - der
    Aufrufer (Scraper) ist dafür verantwortlich, das abzufangen und über
    cache.mark_error zu protokollieren, statt die App abstürzen zu lassen.
    """
    host = httpx.URL(url).host
    with _lock:
        last = _last_request_at.get(host, 0.0)
        wait = SCRAPER_REQUEST_DELAY_SECONDS - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        _last_request_at[host] = time.monotonic()

    response = httpx.get(
        url,
        headers={"User-Agent": SCRAPER_USER_AGENT},
        timeout=SCRAPER_TIMEOUT_SECONDS,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response
