"""Wikidata-Anbindung: löst Strava-Profile für Fahrer auf.

Nutzt die öffentliche Wikidata-Property P5283 ("Strava ID of a
professional sport person", https://www.wikidata.org/wiki/Property:P5283)
statt einer Ad-hoc-Websuche pro Fahrer: das ist strukturiert, in Batches
abfragbar (bis zu 50 Fahrer pro Request) und zuverlässig - eine echte
Volltextsuche pro Name ist weder Teil dieser Scraping-Architektur noch
skaliert sie sinnvoll für ~500 Fahrer. Nicht jeder Profi hat ein aktives
Strava-Profil bzw. eine gepflegte Wikidata-Property dafür; fehlende
Einträge werden einfach ausgelassen (kein Fehler).
"""
import urllib.parse

from .http import get
from .wikipedia import fetch_wikidata_ids

WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
STRAVA_PROPERTY = "P5283"
STRAVA_PROFILE_URL = "https://www.strava.com/pros/{}"


def _api_get(params: dict) -> dict:
    query = urllib.parse.urlencode({**params, "format": "json"})
    response = get(f"{WIKIDATA_API_URL}?{query}")
    return response.json()


def fetch_strava_ids(qids: list[str]) -> dict[str, str]:
    """Wikidata-QID -> Strava-Athleten-ID (Property P5283), gebatcht (bis
    zu 50 Entitäten pro Request via `wbgetentities`). QIDs ohne gepflegte
    Property fehlen einfach im Ergebnis-Dict."""
    if not qids:
        return {}
    result: dict[str, str] = {}
    for i in range(0, len(qids), 50):
        batch = qids[i:i + 50]
        data = _api_get({"action": "wbgetentities", "ids": "|".join(batch), "props": "claims"})
        for qid, entity in data.get("entities", {}).items():
            claims = entity.get("claims", {}).get(STRAVA_PROPERTY)
            if not claims:
                continue
            value = claims[0].get("mainsnak", {}).get("datavalue", {}).get("value")
            if value:
                result[qid] = value
    return result


def fetch_strava_urls(wiki_titles: list[str]) -> dict[str, str]:
    """Wikipedia-Titel -> Strava-Profil-URL, für alle Fahrer mit gepflegter
    Wikidata-Property. Titel ohne Treffer (kein Wikidata-Item verlinkt,
    oder Item ohne Strava-Property) fehlen einfach im Ergebnis-Dict."""
    qid_by_title = fetch_wikidata_ids(wiki_titles)
    if not qid_by_title:
        return {}
    titles_by_qid: dict[str, list[str]] = {}
    for title, qid in qid_by_title.items():
        titles_by_qid.setdefault(qid, []).append(title)
    athlete_id_by_qid = fetch_strava_ids(list(titles_by_qid.keys()))
    return {
        title: STRAVA_PROFILE_URL.format(athlete_id)
        for qid, athlete_id in athlete_id_by_qid.items()
        for title in titles_by_qid[qid]
    }
