"""Wikidata-Anbindung: Strava-Profile und Familiennamen der Fahrer.

Nutzt die öffentliche Wikidata-Property P5283 ("Strava ID of a
professional sport person", https://www.wikidata.org/wiki/Property:P5283)
statt einer Ad-hoc-Websuche pro Fahrer: das ist strukturiert, in Batches
abfragbar (bis zu 50 Fahrer pro Request) und zuverlässig - eine echte
Volltextsuche pro Name ist weder Teil dieser Scraping-Architektur noch
skaliert sie sinnvoll für ~500 Fahrer. Nicht jeder Profi hat ein aktives
Strava-Profil bzw. eine gepflegte Wikidata-Property dafür; fehlende
Einträge werden einfach ausgelassen (kein Fehler).

Dieselbe Maschinerie holt die Familiennamen (P734, Befund 16). Der Grund
steht bei `nachname_aus_wikidata` in scrapers/wikipedia_riders.py: die
Namenstrennung per Heuristik liegt bei spanischen und portugiesischen
Doppelnachnamen falsch, und Wikidata führt die Namensteile einzeln und in
Reihenfolge.
"""
import logging
import urllib.parse

from .http import get
from .wikipedia import fetch_wikidata_ids

logger = logging.getLogger(__name__)

WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
STRAVA_PROPERTY = "P5283"
STRAVA_PROFILE_URL = "https://www.strava.com/pros/{}"
# https://www.wikidata.org/wiki/Property:P734 ("family name"). Der Wert ist
# ein eigenes Wikidata-Item, nicht eine Zeichenkette - der Name steht erst
# im Label dieses Items. Daher zwei Abfragen (Claims, dann Labels).
FAMILY_NAME_PROPERTY = "P734"
# Wikidata erlaubt 50 Entitäten pro wbgetentities-Aufruf.
BATCH = 50


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


def _claim_ziel(claim: dict) -> str | None:
    """Die Ziel-QID einer Aussage auf ein anderes Item.

    `mainsnak.datavalue.value` ist bei einem Item-Wert ein Objekt
    ({"entity-type": "item", "id": "Q123", ...}). Die Funktion nimmt
    zusätzlich eine blanke Zeichenkette an: die Form dieser Antwort ist aus
    dieser Arbeitsumgebung nicht überprüfbar (Wikidata ist hier nicht
    erreichbar), und ein defensiver Zugriff kostet nichts. Passt nichts,
    gibt sie None zurück - der Aufrufer zählt das und meldet es."""
    wert = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
    if isinstance(wert, dict):
        ziel = wert.get("id")
        return ziel if isinstance(ziel, str) else None
    return wert if isinstance(wert, str) else None


def fetch_family_names(qids: list[str]) -> dict[str, list[str]]:
    """Fahrer-QID -> Familiennamen (Labels der P734-Items), in der
    Reihenfolge der Aussagen.

    Mehrere Namen sind der interessante Fall: spanische und portugiesische
    Doppelnachnamen stehen als zwei Aussagen. Die Reihenfolge ist die der
    API-Antwort. Ist sie einmal falsch, entsteht daraus KEIN falscher Name:
    `nachname_aus_wikidata` prüft, ob das Ergebnis als Suffix des vollen
    Namens aufgeht, und lehnt sonst ab.

    Zwei Abfragerunden, beide gebatcht: erst die Aussagen der Fahrer-Items,
    dann die Labels der Namens-Items."""
    if not qids:
        return {}

    namens_qids_je_fahrer: dict[str, list[str]] = {}
    ohne_ziel = 0
    for i in range(0, len(qids), BATCH):
        batch = qids[i:i + BATCH]
        data = _api_get({"action": "wbgetentities", "ids": "|".join(batch), "props": "claims"})
        for qid, entity in data.get("entities", {}).items():
            claims = entity.get("claims", {}).get(FAMILY_NAME_PROPERTY) or []
            ziele = []
            for claim in claims:
                ziel = _claim_ziel(claim)
                if ziel:
                    ziele.append(ziel)
                else:
                    ohne_ziel += 1
            if ziele:
                namens_qids_je_fahrer[qid] = ziele

    if ohne_ziel:
        # Wenn die Antwortform anders ist als angenommen, steht das hier -
        # statt dass die Zuordnung still bei null bleibt.
        logger.warning(
            "Wikidata: %d %s-Aussagen ohne lesbare Ziel-ID (Antwortform "
            "abweichend?)", ohne_ziel, FAMILY_NAME_PROPERTY,
        )

    alle_namens_qids = sorted({q for qs in namens_qids_je_fahrer.values() for q in qs})
    label_je_qid = fetch_labels(alle_namens_qids)
    return {
        fahrer_qid: [label_je_qid[q] for q in namens_qids if q in label_je_qid]
        for fahrer_qid, namens_qids in namens_qids_je_fahrer.items()
        if any(q in label_je_qid for q in namens_qids)
    }


def fetch_labels(qids: list[str], sprache: str = "en") -> dict[str, str]:
    """QID -> Label in der gewünschten Sprache, gebatcht.

    Englisch, weil die Fahrernamen aus der englischen Wikipedia kommen und
    die Schreibweisen damit zusammenpassen. Ein fehlendes Label wird
    ausgelassen; welche Schreibweise am Ende gespeichert wird, entscheidet
    ohnehin `nachname_aus_wikidata` anhand des vollen Namens."""
    if not qids:
        return {}
    ergebnis: dict[str, str] = {}
    for i in range(0, len(qids), BATCH):
        batch = qids[i:i + BATCH]
        data = _api_get({
            "action": "wbgetentities", "ids": "|".join(batch),
            "props": "labels", "languages": sprache,
        })
        for qid, entity in data.get("entities", {}).items():
            wert = entity.get("labels", {}).get(sprache, {}).get("value")
            if wert:
                ergebnis[qid] = wert
    return ergebnis
