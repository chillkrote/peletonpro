#!/usr/bin/env python3
"""Prueft den Wikidata-Familiennamen-Abgleich (Befund 16).

    DATABASE_URL=postgresql://... python3 scripts/check-namen.py

Geprueft wird in drei Teilen:

  1. Die REGEL (nachname_aus_wikidata) an Namen, die es wirklich gibt -
     inklusive der Faelle, die die Heuristik falsch trennt, und aller
     Gruende, aus denen ein Wikidata-Wert abgelehnt werden muss.
  2. Der PARSER: die Antwortform von wbgetentities. Wikidata ist aus dieser
     Arbeitsumgebung nicht erreichbar (HTTP 000), die Form ist also
     ungeprueft. Der Test faelscht deshalb HTTP-Antworten in der
     dokumentierten Form UND in einer abweichenden - und prueft, dass die
     abweichende eine Warnung ausloest statt still bei null zu bleiben.
  3. Der JOB gegen eine echte Datenbank: was am Ende in riders steht.

Gefaelscht wird auf HTTP-Ebene (scrapers.http.get), nicht auf Funktionsebene:
so laufen fetch_wikidata_ids, fetch_family_names, fetch_labels und der
Parser wirklich, statt umgangen zu werden.
"""
import logging
import pathlib
import sys
import urllib.parse

WURZEL = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL / "backend"))

fehler = 0


def meld(titel: str, stand: str) -> None:
    print(f"  {titel:<58} {stand}")


def pruefe(titel: str, ist, soll) -> None:
    global fehler
    if ist == soll:
        meld(titel, "ok")
    else:
        meld(titel, f"FEHLER: {ist!r} != {soll!r}")
        fehler += 1


# ---------------------------------------------------------------------------
# 1. Die Regel
# ---------------------------------------------------------------------------
from app.scrapers.wikipedia_riders import (  # noqa: E402
    nachname_aus_wikidata,
    split_name,
)

print("=== 1. Die Regel: Wikidata-Familienname gegen vollen Namen ===")

# (voller Name, P734-Labels, erwartetes Ergebnis)
REGEL_FAELLE = [
    # Doppelnachnamen - genau die Faelle, die die Heuristik falsch trennt
    ("Juan Ayuso Pesquera", ["Ayuso", "Pesquera"], ("Juan", "Ayuso Pesquera")),
    ("Carlos Rodriguez Cano", ["Rodriguez", "Cano"], ("Carlos", "Rodriguez Cano")),
    # Akzente: Wikidata schreibt oft ohne, der volle Name mit - die
    # Schreibweise des vollen Namens muss gewinnen
    ("Tadej Pogacar", ["Pogacar"], ("Tadej", "Pogacar")),
    # Partikel-Namen, die die Heuristik schon richtig hat
    ("Mathieu van der Poel", ["van der Poel"], ("Mathieu", "van der Poel")),
    ("Jonas Vingegaard", ["Vingegaard"], ("Jonas", "Vingegaard")),
    # Nur der letzte Teil gepflegt: laengster Treffer gewinnt, aber es gibt
    # nur einen - der Nachname wird dann NICHT auf "Ayuso Pesquera" geraten
    ("Juan Ayuso Pesquera", ["Pesquera"], ("Juan Ayuso", "Pesquera")),
    # Teil UND ganzer Nachname gepflegt: der laengere muss gewinnen. Genau
    # dafuer sind die Kandidaten nach Wortzahl sortiert - ohne die
    # Sortierung wuerde "Pesquera" zuerst passen und "Ayuso" verloren gehen.
    ("Juan Ayuso Pesquera", ["Pesquera", "Ayuso Pesquera"],
     ("Juan", "Ayuso Pesquera")),
    # Echte diakritische Zeichen: Wikidata ohne, der volle Name mit. Ohne
    # die Vergleichsfaltung wuerde genau dieser Fall abgelehnt - und es ist
    # der haeufigste im Feld.
    ("Tadej Pogačar", ["Pogacar"], ("Tadej", "Pogačar")),
    ("Stefan Küng", ["Kung"], ("Stefan", "Küng")),
    # Ablehnungen
    ("Jonas Vingegaard", ["Hansen"], None),            # Geburtsname
    ("Jonas Vingegaard", [], None),                    # keine Aussage
    ("Jonas Vingegaard", ["Jonas Vingegaard"], None),  # deckt den ganzen Namen
    ("Vingegaard", ["Vingegaard"], None),              # kein Vorname uebrig
    ("Jonas Vingegaard", ["gaard"], None),             # nur Wortteil, keine Grenze
]
for name, labels, erwartet in REGEL_FAELLE:
    pruefe(f"{name!r} + {labels}", nachname_aus_wikidata(name, labels), erwartet)

# Der Punkt der ganzen Uebung: bei diesen Namen weicht die Regel von der
# Heuristik ab, und zwar in die richtige Richtung.
abweichungen = [
    (n, split_name(n), nachname_aus_wikidata(n, l))
    for n, l, e in REGEL_FAELLE
    if e is not None and nachname_aus_wikidata(n, l) != split_name(n)
]
pruefe("genau drei Faelle weichen von der Heuristik ab", len(abweichungen), 3)
for name, heur, neu in abweichungen:
    print(f"      {name}: Heuristik {heur} -> Wikidata {neu}")

# Die Heuristik bleibt fuer alles zustaendig, was Wikidata nicht klaert.
pruefe("Heuristik unveraendert (van der Poel)",
       split_name("Mathieu van der Poel"), ("Mathieu", "van der Poel"))
pruefe("Heuristik unveraendert (Doppelnachname falsch, wie bisher)",
       split_name("Juan Ayuso Pesquera"), ("Juan Ayuso", "Pesquera"))


# ---------------------------------------------------------------------------
# 2. Der Parser: gefaelschte HTTP-Antworten in der API-Form
# ---------------------------------------------------------------------------
print("=== 2. Antwortform von wbgetentities ===")

from app.scrapers import http as scraper_http  # noqa: E402


class Antwort:
    """Minimales Response-Objekt: der Code ruft nur .json()."""

    def __init__(self, nutzlast):
        self._nutzlast = nutzlast

    def json(self):
        return self._nutzlast


# Fahrer-Item -> (QID, P734-Ziel-QIDs, Label je Namens-QID)
WELT = {
    "Juan Ayuso": ("Q60148487", ["Q65921478", "Q37398531"]),
    "Tadej Pogacar": ("Q18576956", ["Q50385371"]),
    "Jonas Vingegaard": ("Q29053081", ["Q50327347"]),
    "Ohne Wikidata": (None, []),
    "Ohne Familienname": ("Q99999999", []),
}
LABELS = {
    "Q65921478": "Ayuso",
    "Q37398531": "Pesquera",
    "Q50385371": "Pogacar",
    "Q50327347": "Vingegaard",
}

abweichende_form = {"an": False}
aufrufe = {"n": 0}


def falscher_get(url: str):
    aufrufe["n"] += 1
    teile = urllib.parse.urlparse(url)
    p = urllib.parse.parse_qs(teile.query)
    aktion = p.get("action", [""])[0]

    if aktion == "query":  # Wikipedia-Titel -> QID
        seiten = {}
        for i, titel in enumerate(p.get("titles", [""])[0].split("|")):
            qid = WELT.get(titel, (None, []))[0]
            seiten[str(i)] = {
                "title": titel,
                **({"pageprops": {"wikibase_item": qid}} if qid else {}),
            }
        return Antwort({"query": {"pages": seiten}})

    if aktion == "wbgetentities":
        ids = p.get("ids", [""])[0].split("|")
        props = p.get("props", [""])[0]
        if props == "claims":
            entities = {}
            for qid in ids:
                ziele = next((z for q, z in WELT.values() if q == qid), [])
                if abweichende_form["an"]:
                    # Wert als blankes Objekt ohne "id" - so wuerde es
                    # aussehen, wenn die Annahme ueber die Form falsch ist.
                    claims = [{"mainsnak": {"datavalue": {"value": {"foo": z}}}}
                              for z in ziele]
                else:
                    claims = [{"mainsnak": {"datavalue": {
                        "value": {"entity-type": "item", "id": z}}}} for z in ziele]
                entities[qid] = {"claims": {"P734": claims} if claims else {}}
            return Antwort({"entities": entities})
        if props == "labels":
            return Antwort({"entities": {
                qid: {"labels": {"en": {"value": LABELS[qid]}}} if qid in LABELS else {}
                for qid in ids
            }})
    raise AssertionError(f"unerwartete Anfrage: {url}")


scraper_http.get = falscher_get
# Beide Module haben `get` beim Import gebunden.
from app.scrapers import wikidata as wd_mod, wikipedia as wp_mod  # noqa: E402
wd_mod.get = falscher_get
wp_mod.get = falscher_get

from app.scrapers.wikidata import fetch_family_names  # noqa: E402
from app.scrapers.wikipedia import fetch_wikidata_ids  # noqa: E402

qids = fetch_wikidata_ids(list(WELT))
pruefe("Titel -> QID fuer die vier mit Item", len(qids), 4)
pruefe("Titel ohne Item fehlt", "Ohne Wikidata" in qids, False)

namen = fetch_family_names(sorted(set(qids.values())))
pruefe("P734 in dokumentierter Form gelesen",
       namen.get("Q60148487"), ["Ayuso", "Pesquera"])
pruefe("Reihenfolge der Aussagen erhalten",
       namen.get("Q60148487"), ["Ayuso", "Pesquera"])
pruefe("Item ohne P734 fehlt im Ergebnis", "Q99999999" in namen, False)

# Abweichende Form: das Ergebnis ist leer UND es gibt eine Warnung. Die
# Warnung ist der Punkt - ohne sie bliebe der Abgleich still bei null.
class Sammler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.zeilen = []

    def emit(self, record):
        self.zeilen.append(record.getMessage() if record.args is None
                           else record.msg % record.args)


sammler = Sammler()
sammler.setLevel(logging.WARNING)
wd_mod.logger.addHandler(sammler)
abweichende_form["an"] = True
namen_falsch = fetch_family_names(sorted(set(qids.values())))
abweichende_form["an"] = False
wd_mod.logger.removeHandler(sammler)

pruefe("abweichende Form ergibt keine Namen", namen_falsch, {})
pruefe("abweichende Form loest eine Warnung aus",
       any("ohne lesbare Ziel-ID" in z for z in sammler.zeilen), True)


# ---------------------------------------------------------------------------
# 3. Der Job gegen eine echte Datenbank
# ---------------------------------------------------------------------------
print("=== 3. Der Job: was am Ende in riders steht ===")

import os  # noqa: E402

if not os.environ.get("DATABASE_URL"):
    print("  DATABASE_URL fehlt - Teil 3 uebersprungen")
    print()
    print("UNVOLLSTAENDIG: Teil 3 braucht eine Datenbank.")
    sys.exit(1)

from app import db, scheduler  # noqa: E402

with db._connect() as conn:
    conn.execute("DELETE FROM rider_team_stints")
    conn.execute("DELETE FROM riders")
    conn.execute("DELETE FROM teams")
    conn.execute(
        "INSERT INTO teams (id, name, category, country, code, gender, wiki_url) "
        "VALUES ('uae', 'UAE', 'wt', 'AE', 'UAE', 'm', 'https://x')"
    )
    for rid, name, titel in [
        ("juan-ayuso", "Juan Ayuso Pesquera", "Juan Ayuso"),
        ("tadej-pogacar", "Tadej Pogacar", "Tadej Pogacar"),
        ("jonas-vingegaard", "Jonas Vingegaard", "Jonas Vingegaard"),
        ("ohne-wikidata", "Niemand Bekannt", "Ohne Wikidata"),
        ("ohne-familienname", "Kein Nachname Bekannt", "Ohne Familienname"),
    ]:
        vor, nach = split_name(name)
        conn.execute(
            "INSERT INTO riders (id, name, first_name, last_name, country, "
            "wiki_url, current_team_id, gender) VALUES "
            "(%s, %s, %s, %s, 'XX', %s, 'uae', 'm')",
            (rid, name, vor, nach, f"https://en.wikipedia.org/wiki/{titel.replace(' ', '_')}"),
        )

vorher = {}
with db._connect() as conn:
    for z in conn.execute("SELECT id, name, first_name, last_name FROM riders").fetchall():
        vorher[z["id"]] = (z["name"], z["first_name"], z["last_name"])

pruefe("fuenf Fahrer eingespielt", len(vorher), 5)
pruefe("Heuristik hat den Doppelnachnamen falsch",
       vorher["juan-ayuso"][1:], ("Juan Ayuso", "Pesquera"))

scheduler._namen_abgleichen()

with db._connect() as conn:
    nachher = {
        z["id"]: (z["name"], z["first_name"], z["last_name"], z["name_source"], z["wikidata_qid"])
        for z in conn.execute(
            "SELECT id, name, first_name, last_name, name_source, wikidata_qid FROM riders"
        ).fetchall()
    }

pruefe("Doppelnachname korrigiert",
       nachher["juan-ayuso"][1:4], ("Juan", "Ayuso Pesquera", "wikidata"))
pruefe("einfacher Name bestaetigt",
       nachher["tadej-pogacar"][1:4], ("Tadej", "Pogacar", "wikidata"))
pruefe("ohne Wikidata-Item -> heuristik",
       nachher["ohne-wikidata"][1:4], ("Niemand", "Bekannt", "heuristik"))
pruefe("Item ohne P734 -> heuristik",
       nachher["ohne-familienname"][1:4], ("Kein Nachname", "Bekannt", "heuristik"))
pruefe("QID nachgetragen (Ayuso)", nachher["juan-ayuso"][4], "Q60148487")
pruefe("keine QID ohne Item", nachher["ohne-wikidata"][4], None)
# Je Fahrer-ID vergleichen, nicht positionsweise: zwei SELECTs ohne
# ORDER BY liefern die Zeilen nicht in derselben Reihenfolge. Genau daran
# ist die erste Fassung dieser Pruefung gescheitert - die Werte waren
# gleich, der Vergleich falsch.
pruefe("name unveraendert bei allen fuenf",
       {i: n[0] for i, n in nachher.items()},
       {i: v[0] for i, v in vorher.items()})

# Jeder Fahrer wurde genau einmal gefragt: ein zweiter Lauf findet nichts.
aufrufe_vorher = aufrufe["n"]
scheduler._namen_abgleichen()
pruefe("zweiter Lauf fragt nicht erneut", aufrufe["n"], aufrufe_vorher)

# name == first_name + " " + last_name, die Zusage von set_rider_name
zusammengesetzt = [
    (n[0], f"{n[1]} {n[2]}".strip()) for n in nachher.values()
]
pruefe("name == Vorname + Nachname bei allen",
       all(voll == teile for voll, teile in zusammengesetzt), True)

print()
if fehler == 0:
    print("Alle Pruefungen bestanden.")
else:
    print(f"{fehler} Pruefung(en) fehlgeschlagen.")
sys.exit(1 if fehler else 0)
