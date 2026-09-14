"""Das UCI-Punktereglement aus docs/ in die Datenbank laden.

WARUM AUS EINER CSV UND NICHT AUS DER MIGRATION
-----------------------------------------------
Die 1564 Punktwerte stehen in `docs/uci-punkte-<saison>.csv`. Sie ein
zweites Mal als INSERT-Block in eine Migration zu schreiben hiesse, beim
naechsten Reglement-Jahrgang zwei Kopien pflegen zu muessen - und beim
ersten Vergessen waere nicht mehr erkennbar, welche gilt. Die CSV ist die
Quelle, diese Datei traegt sie in die Datenbank.

Nebenwirkung, die ausdruecklich gewollt ist: die Zahlen sind im
Repository nachprüfbar (`scripts/check-uci-punkte.py`) statt nur in der
Produktionsdatenbank.

WARUM EIN HASH-MERKER
---------------------
Der Loader laeuft beim Prozessstart. Eine Instanz auf Renders kostenlosem
Plan startet mehrmals pro Stunde neu (gemessen, siehe Migration 0007) -
ohne Merker wuerden bei jedem Aufwachen 1564 Zeilen geschrieben. Genau die
Falle, die der Saison-Takt an anderer Stelle beseitigt hat. Gleicher
SHA-256 wie beim letzten Lauf: der Loader tut nichts.

WAS ER NICHT TUT
----------------
`uci_rennstufe.race_id` bleibt unberuehrt. Der Rennname aus dem Reglement
laesst sich nicht verlaesslich auf `races.id` abbilden - das Reglement
selbst schreibt "Oomlop Nieuwsblad" fuer Omloop Nieuwsblad und fuehrt
"Lloyds Tour of Britain Women" in einer Tabelle ohne das "Women". Ein
Namensabgleich wuerde bei jeder Umbenennung still falsche Punkte liefern.
Die Zuordnung ist deshalb ein eigener, bewusster Schritt; bis dahin ist
sie als `race_id IS NULL` abfragbar und wird unten gezaehlt.
"""
import csv
import hashlib
import logging
import pathlib
import re
from typing import Optional

from . import db

logger = logging.getLogger(__name__)

# docs/ liegt neben backend/, nicht darin: die Dateien sind Quelle UND
# Dokumentation und gehoeren deshalb nicht in den Anwendungsbaum.
DOCS = pathlib.Path(__file__).resolve().parent.parent.parent / "docs"

WERTE_MUSTER = re.compile(r"^uci-punkte-(\d{4})\.csv$")


def _sha256(pfad: pathlib.Path) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def _saisons() -> list[tuple[int, pathlib.Path, Optional[pathlib.Path]]]:
    """Alle vorhandenen Reglement-Jahrgaenge, aeltester zuerst.

    Ueber das Dateinamensmuster statt ueber eine Liste im Code: ein neuer
    Jahrgang wird dann durch Hinzufuegen der CSV wirksam, ohne Codeaenderung
    und ohne dass jemand eine Konstante nachziehen muss."""
    gefunden = []
    for pfad in sorted(DOCS.glob("uci-punkte-*.csv")):
        m = WERTE_MUSTER.match(pfad.name)
        if not m:
            continue
        saison = int(m.group(1))
        stufen = DOCS / f"uci-punkte-{saison}-wt-stufen.csv"
        gefunden.append((saison, pfad, stufen if stufen.exists() else None))
    return gefunden


def _lade_saison(conn, saison: int, werte_csv: pathlib.Path,
                 stufen_csv: Optional[pathlib.Path]) -> dict:
    werte = list(csv.DictReader(werte_csv.open(encoding="utf-8")))
    zuordnung = list(csv.DictReader(stufen_csv.open(encoding="utf-8"))) if stufen_csv else []

    stufen = {(z["geschlecht"], z["anlass"], z["stufe"]) for z in werte}
    stufen |= {(z["geschlecht"], z["anlass"], z["stufe"]) for z in zuordnung}

    conn.cursor().executemany(
        "INSERT INTO uci_stufe (saison, gender, anlass, stufe) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT DO NOTHING",
        [(saison, g, a, s) for g, a, s in sorted(stufen)],
    )
    conn.cursor().executemany(
        """
        INSERT INTO uci_punkte (saison, gender, anlass, stufe, platz, punkte)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (saison, gender, anlass, stufe, platz)
        DO UPDATE SET punkte = EXCLUDED.punkte
        """,
        [(saison, z["geschlecht"], z["anlass"], z["stufe"], int(z["platz"]),
          int(z["punkte"])) for z in werte],
    )
    # race_id bleibt stehen: nur die Stufe wird nachgezogen, falls die UCI
    # ein Rennen umgruppiert hat. Eine einmal gesetzte Zuordnung ist
    # Handarbeit und darf durch einen Reload nicht verloren gehen.
    conn.cursor().executemany(
        """
        INSERT INTO uci_rennstufe (saison, gender, anlass, stufe, rennen_reglement)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (saison, gender, anlass, rennen_reglement)
        DO UPDATE SET stufe = EXCLUDED.stufe
        """,
        [(saison, z["geschlecht"], z["anlass"], z["stufe"], z["rennen"])
         for z in zuordnung],
    )

    # Was aus der CSV verschwunden ist, muss auch aus der Datenbank
    # verschwinden - sonst bliebe eine Skala, die das Reglement nicht mehr
    # kennt, stillschweigend gueltig. Reihenfolge: erst die Blaetter, dann
    # uci_stufe, weil deren Fremdschluessel kaskadiert.
    entfernt = {}
    cur = conn.execute(
        """
        DELETE FROM uci_punkte u WHERE u.saison = %(saison)s AND NOT EXISTS (
            SELECT 1 FROM unnest(%(g)s::text[], %(a)s::text[], %(s)s::text[],
                                 %(p)s::int[]) AS t(g, a, s, p)
             WHERE t.g = u.gender AND t.a = u.anlass AND t.s = u.stufe AND t.p = u.platz)
        """,
        {"saison": saison,
         "g": [z["geschlecht"] for z in werte], "a": [z["anlass"] for z in werte],
         "s": [z["stufe"] for z in werte], "p": [int(z["platz"]) for z in werte]},
    )
    entfernt["punkte"] = cur.rowcount
    cur = conn.execute(
        """
        DELETE FROM uci_rennstufe u WHERE u.saison = %(saison)s AND NOT EXISTS (
            SELECT 1 FROM unnest(%(g)s::text[], %(a)s::text[], %(r)s::text[])
                        AS t(g, a, r)
             WHERE t.g = u.gender AND t.a = u.anlass AND t.r = u.rennen_reglement)
        """,
        {"saison": saison,
         "g": [z["geschlecht"] for z in zuordnung], "a": [z["anlass"] for z in zuordnung],
         "r": [z["rennen"] for z in zuordnung]},
    )
    entfernt["rennstufe"] = cur.rowcount
    cur = conn.execute(
        """
        DELETE FROM uci_stufe u WHERE u.saison = %(saison)s AND NOT EXISTS (
            SELECT 1 FROM unnest(%(g)s::text[], %(a)s::text[], %(s)s::text[])
                        AS t(g, a, s)
             WHERE t.g = u.gender AND t.a = u.anlass AND t.s = u.stufe)
        """,
        {"saison": saison,
         "g": [g for g, _, _ in sorted(stufen)], "a": [a for _, a, _ in sorted(stufen)],
         "s": [s for _, _, s in sorted(stufen)]},
    )
    entfernt["stufe"] = cur.rowcount

    offen = conn.execute(
        "SELECT count(*) AS n FROM uci_rennstufe "
        "WHERE saison = %s AND race_id IS NULL", (saison,)
    ).fetchone()["n"]
    return {"werte": len(werte), "zuordnung": len(zuordnung), "stufen": len(stufen),
            "entfernt": entfernt, "ohne_race_id": offen}


def lade_reglement() -> int:
    """Laedt jeden Jahrgang, dessen CSV sich geaendert hat. Gibt die Zahl
    der geladenen Jahrgaenge zurueck (0 = alles aktuell).

    Wirft nicht: ein fehlgeschlagener Reglement-Load darf den Start nicht
    verhindern. Ohne Skalen laesst sich nichts berechnen, aber der Rest der
    Anwendung laeuft unverändert weiter - dieselbe Abwaegung wie bei den
    Migrationen in main.py."""
    if not db.is_configured():
        logger.info("UCI-Reglement übersprungen: keine Datenbank konfiguriert")
        return 0

    geladen = 0
    for saison, werte_csv, stufen_csv in _saisons():
        dateien = [p for p in (werte_csv, stufen_csv) if p is not None]
        hashes = {p.name: _sha256(p) for p in dateien}
        try:
            with db._connect() as conn:
                bekannt = {
                    z["datei"]: z["sha256"] for z in conn.execute(
                        "SELECT datei, sha256 FROM uci_quelle WHERE datei = ANY(%s)",
                        (list(hashes),),
                    ).fetchall()
                }
                if bekannt == hashes:
                    logger.debug("UCI-Reglement %d unverändert", saison)
                    continue
                if stufen_csv is None:
                    logger.warning(
                        "UCI-Reglement %d: keine Stufen-Datei "
                        "(uci-punkte-%d-wt-stufen.csv) - WorldTour-Rennen bleiben "
                        "ohne Stufe", saison, saison)
                bericht = _lade_saison(conn, saison, werte_csv, stufen_csv)
                conn.cursor().executemany(
                    "INSERT INTO uci_quelle (datei, sha256, geladen_am) "
                    "VALUES (%s, %s, now()) "
                    "ON CONFLICT (datei) DO UPDATE SET sha256 = EXCLUDED.sha256, "
                    "geladen_am = now()",
                    sorted(hashes.items()),
                )
            geladen += 1
            entfernt = bericht["entfernt"]
            logger.info(
                "UCI-Reglement %d geladen: %d Punktwerte, %d Stufen, "
                "%d Rennzuordnungen (%d noch ohne race_id)%s",
                saison, bericht["werte"], bericht["stufen"], bericht["zuordnung"],
                bericht["ohne_race_id"],
                f", {sum(entfernt.values())} veraltete Zeilen entfernt"
                if sum(entfernt.values()) else "",
            )
        except Exception as exc:  # noqa: BLE001 - Start darf nicht scheitern
            logger.error("UCI-Reglement %d nicht geladen: %s", saison, exc)
    return geladen
