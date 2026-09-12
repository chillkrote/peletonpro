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


def fetch_full_page(page: str) -> str:
    """Liefert das gerenderte HTML der KOMPLETTEN Seite (kein section=-
    Parameter) - für Fälle, in denen die relevante Tabelle nicht
    zuverlässig unter einer bestimmten Abschnittsüberschrift zu finden ist
    (z.B. stark variierende Kapitelstruktur über viele verschiedene
    Renn-Saison-Artikel hinweg, siehe scrapers/wikipedia_race_history.py)."""
    data = _api_get({"action": "parse", "page": page, "prop": "text"})
    return data["parse"]["text"]["*"]


def fetch_sections(page: str) -> list[dict]:
    """Liefert die rohe Abschnitts-Liste einer Seite (je Eintrag u.a. `line`
    = Überschrift, `index` = Abschnitts-Index für fetch_section-artige
    Folgeabrufe) - für Fälle, in denen alle Abschnitte durchsucht werden
    müssen (z.B. "Stage 1", "Stage 2", ... auf Etappenrennen-Seiten)."""
    data = _api_get({"action": "parse", "page": page, "prop": "sections"})
    return data["parse"]["sections"]


def fetch_section_by_index(page: str, index: str) -> str:
    """Wie fetch_section, aber mit bereits bekanntem Abschnitts-Index (aus
    fetch_sections) statt erneuter Suche nach der Überschrift."""
    data = _api_get({"action": "parse", "page": page, "prop": "text", "section": index})
    return data["parse"]["text"]["*"]


def fetch_lead_section(page: str) -> str:
    """Liefert das gerenderte HTML des Lead-Abschnitts (vor der ersten
    Überschrift) einer Seite - bei Personen-Artikeln enthält dieser die
    Infobox. MediaWiki zählt den Lead nicht in der `prop=sections`-Liste
    (der erste `line`-Eintrag dort ist bereits Abschnitt 1), daher hier
    direkt `section=0` anfragen statt über fetch_section() zu suchen."""
    data = _api_get({"action": "parse", "page": page, "prop": "text", "section": 0})
    return data["parse"]["text"]["*"]


def wiki_title_from_url(url: str) -> str:
    """Extrahiert den Wikipedia-Seitentitel aus einer '/wiki/...'-URL, z.B.
    'https://en.wikipedia.org/wiki/2026_Tour_de_France' -> '2026 Tour de France'."""
    tail = url.rsplit("/wiki/", maxsplit=1)[-1]
    return urllib.parse.unquote(tail).replace("_", " ")


def _resolve_titles(batch: list[str], query: dict) -> dict[str, str]:
    """Bildet jeden Titel aus `batch` (unser Input) auf den von MediaWiki
    aufgelösten End-Titel ab - normalized dann redirects, in dieser
    Reihenfolge verkettet, da ein Titel erst normalisiert und danach ggf.
    weitergeleitet wird. Gemeinsam genutzt von fetch_page_images und
    fetch_wikidata_ids, damit deren Aufrufer nicht selbst durch
    `normalized`/`redirects` navigieren müssen."""
    resolved: dict[str, str] = {t: t for t in batch}
    for entry in query.get("normalized", []):
        resolved = {k: (entry["to"] if v == entry["from"] else v) for k, v in resolved.items()}
    for entry in query.get("redirects", []):
        resolved = {k: (entry["to"] if v == entry["from"] else v) for k, v in resolved.items()}
    return resolved


def fetch_page_images(titles: list[str], thumb_size: int = 200) -> dict[str, str]:
    """Liefert Thumbnail-Bild-URLs (i.d.R. Infobox-Logo/Trikot) für mehrere
    Wikipedia-Seiten in einem einzigen Request (`action=query&prop=pageimages`,
    bis zu 50 Titel pro Aufruf - für unsere ~18 Teams reicht ein Request).
    Das Ergebnis-Dict ist nach dem JEWEILS ÜBERGEBENEN Titel geschlüsselt
    (nicht nach dem von MediaWiki normalisierten/aufgelösten Titel), damit
    der Aufrufer nicht selbst durch `normalized`/`redirects` navigieren muss.
    Seiten ohne Bild fehlen einfach im Ergebnis-Dict."""
    if not titles:
        return {}
    result: dict[str, str] = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        data = _api_get(
            {
                "action": "query",
                "titles": "|".join(batch),
                "prop": "pageimages",
                "piprop": "thumbnail",
                "pithumbsize": thumb_size,
            }
        )
        query = data.get("query", {})
        pages = query.get("pages", {})

        thumb_by_final_title: dict[str, str] = {}
        for page in pages.values():
            title = page.get("title")
            thumb = page.get("thumbnail", {}).get("source")
            if title and thumb:
                thumb_by_final_title[title] = thumb

        for original_title, final_title in _resolve_titles(batch, query).items():
            thumb = thumb_by_final_title.get(final_title)
            if thumb:
                result[original_title] = thumb
    return result


def fetch_wikidata_ids(titles: list[str]) -> dict[str, str]:
    """Liefert die Wikidata-Q-Nummer (z.B. 'Q1630132') für mehrere
    Wikipedia-Seiten in einem Request (`action=query&prop=pageprops`, bis
    zu 50 Titel pro Aufruf) - Grundlage für den Wikidata-Abgleich in
    scrapers/wikidata.py (z.B. Strava-Profile über Property P5283). Seiten
    ohne verknüpftes Wikidata-Item fehlen einfach im Ergebnis-Dict."""
    if not titles:
        return {}
    result: dict[str, str] = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        data = _api_get(
            {
                "action": "query",
                "titles": "|".join(batch),
                "prop": "pageprops",
                "ppprop": "wikibase_item",
            }
        )
        query = data.get("query", {})
        pages = query.get("pages", {})

        qid_by_final_title: dict[str, str] = {}
        for page in pages.values():
            title = page.get("title")
            qid = page.get("pageprops", {}).get("wikibase_item")
            if title and qid:
                qid_by_final_title[title] = qid

        for original_title, final_title in _resolve_titles(batch, query).items():
            qid = qid_by_final_title.get(final_title)
            if qid:
                result[original_title] = qid
    return result
