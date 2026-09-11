"""Gemeinsamer Helfer für alle Wikipedia-basierten Scraper.

VERIFIZIERT am 2026-09-11 gegen die echte MediaWiki-API (per temporärer
Render-Diagnose-Route geprüft, da diese Entwicklungsumgebung keinen
Netzwerkzugriff auf en.wikipedia.org hat, siehe backend/README.md):

`action=parse` mit `prop=sections` liefert die Abschnitts-Liste einer Seite
(inkl. `index` pro Überschrift). `action=parse` mit `prop=text&section=<index>`
liefert das gerenderte HTML genau dieses Abschnitts (Tabellen als
`<table class="wikitable">`), ohne verschachtelte Unterabschnitte. Ein
ungültiger Seitentitel liefert HTTP 200 mit einem `error`-Feld im JSON
(kein 4xx-Statuscode) - das wird hier explizit geprüft.
"""
import urllib.parse

from .http import get

API_URL = "https://en.wikipedia.org/w/api.php"


def _api_get(params: dict) -> dict:
    query = urllib.parse.urlencode({**params, "format": "json"})
    response = get(f"{API_URL}?{query}")
    data = response.json()
    if "error" in data:
        raise ValueError(f"Wikipedia-API-Fehler für {params}: {data['error']}")
    return data


def fetch_section(page: str, section_line_substr: str) -> str:
    """Liefert das gerenderte HTML des ersten Abschnitts, dessen Überschrift
    `section_line_substr` enthält (case-insensitiv)."""
    sections_data = _api_get({"action": "parse", "page": page, "prop": "sections"})
    for sec in sections_data["parse"]["sections"]:
        if section_line_substr.lower() in sec.get("line", "").lower():
            text_data = _api_get(
                {"action": "parse", "page": page, "prop": "text", "section": sec["index"]}
            )
            return text_data["parse"]["text"]["*"]
    raise ValueError(f"Abschnitt mit '{section_line_substr}' nicht gefunden auf Seite '{page}'")


def wiki_title_from_url(url: str) -> str:
    """Extrahiert den Wikipedia-Seitentitel aus einer '/wiki/...'-URL, z.B.
    'https://en.wikipedia.org/wiki/2026_Tour_de_France' -> '2026 Tour de France'."""
    tail = url.rsplit("/wiki/", maxsplit=1)[-1]
    return urllib.parse.unquote(tail).replace("_", " ")
