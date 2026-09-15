"""UCI-Punkte aus den Ergebniszeilen berechnen.

WAS SIE RECHNET, UND WAS NICHT
------------------------------
Gesamtklassement (`gc`) und Etappen (`etappe`) der WorldTour - das ist,
wofuer die Daten reichen. Die uebrigen elf Anlaesse nicht: Nebenwertungen
und Trikottraeger sind gar nicht modelliert, der Kontinentalkalender
braucht eine Unterscheidung, die `taxonomy.Category` nicht kennt, und
Meisterschaften, WM und Olympia stehen nicht im Kalender. Die vollstaendige
Bestandsaufnahme steht in docs/uci-punkte.md.

Die Summe hier ist deshalb KEINE UCI-Rangliste, sondern ein Teil davon. Sie
wird bewusst nicht nach `rider_season_points.uci_points` geschrieben - eine
Teilsumme in einer Spalte, die "UCI-Punkte" heisst, waere eine stille
Falschaussage.

ARTIKEL 2.6.001 - DIE AUSFALLREGEL
----------------------------------
"If only one stage or prologue is completed and the other stages are
cancelled, only the points for the stage will be awarded ... No additional
points will be awarded (e.g. for the general time classification ...)."

Der Ausloeser - "cancelled" - steht nirgends in unseren Daten. Das
naechstliegende Signal ist: ein Rennen MIT Etappen, das Ergebnisse fuer
genau EINE Etappe hat. Danach wird die Regel angewandt.

Dieses Signal ist nicht beweisend: ein Rennen, dessen Etappen nur teilweise
gescraped wurden, sieht genauso aus. Deshalb wird jede Anwendung als
WARNUNG geloggt, mit Rennnamen. Die Regel soll fast nie greifen; greift sie
oft, ist das kein Beleg fuer viele Absagen, sondern fuer luecken im
Scraping. Die Warnung ist die einzige Stelle, an der dieser Unterschied
auffallen kann.

WER KEINE rider_id HAT, BEKOMMT KEINE PUNKTE
--------------------------------------------
`race_results.rider_id` ist nur dort gesetzt, wo sich der Name einem Fahrer
zuordnen liess. Ohne ID laesst sich die Zeile keinem Fahrer gutschreiben.
Das ist keine stille Luecke: die Zahl steht in der Log-Meldung, und sie
sagt zugleich, wie vollstaendig die Rechnung ueberhaupt sein kann.
Gemessen am 15.09.2026: 133 von 980 Zeilen ohne ID, also 13,6 %.

DIE HAERTERE GRENZE STEHT IN DER QUELLE
---------------------------------------
Derselbe Lauf meldete "0 ausserhalb der Skala" - keine einzige der 980
Zeilen hatte eine Platzierung tiefer als die Skala reicht (60 im
Gesamtklassement, 15 auf der Etappe). Englische Wikipedia-Rennartikel
fuehren typischerweise eine Top-10; die Plaetze 11 bis 60 gibt es dort
schlicht nicht.

Nachgerechnet sind das 26 % der Punkte eines Rennens, in jeder Stufe
gleich - nicht die Mehrheit. Die fehlenden Punkte gehoeren aber bestimmten
Fahrern GANZ: wer eine Saison lang zwischen Platz 11 und 20 faehrt, steht
hier mit null da. Es liegt NICHT an diesem Code und auch nicht am Parser
(wikipedia_tables.parse_result_row liest jede Zeile, ohne Begrenzung) -
es ist eine Quellenfrage. Siehe docs/uci-punkte.md.
"""
import logging
from typing import Optional

from . import db

logger = logging.getLogger(__name__)

# Anlaesse, die diese Rechnung abdeckt. Bewusst eine kurze, feste Liste
# statt "alles was in uci_punkte steht": jeder weitere Anlass braucht eine
# eigene Quelle und eine eigene Regel, nicht nur einen Tabelleneintrag.
ANLAESSE = ("gc", "etappe")


def _faellige_rennen(conn, saison: Optional[int]) -> list[dict]:
    """Rennen mit Zuordnung, deren Ergebnisse neuer sind als die Rechnung.

    `results_fetched_at IS NULL` heisst: noch nie abgerufen, also nichts zu
    rechnen. Sonst gilt neu gerechnet werden muss, was noch nie gerechnet
    wurde oder seither neue Ergebnisse bekommen hat."""
    bedingung = "AND r.season = %(saison)s" if saison is not None else ""
    return conn.execute(
        f"""
        SELECT DISTINCT r.id, r.name, r.season, r.gender, r.end_date, r.start_date
          FROM races r
          JOIN uci_rennstufe z ON z.race_id = r.id
         WHERE r.results_fetched_at IS NOT NULL
           AND (r.punkte_berechnet_at IS NULL
                OR r.punkte_berechnet_at < r.results_fetched_at)
           {bedingung}
         ORDER BY r.id
        """,
        {"saison": saison},
    ).fetchall()


def _stufen(conn, race_id: str) -> dict[str, str]:
    """{anlass: stufe} fuer dieses Rennen."""
    return {
        z["anlass"]: z["stufe"] for z in conn.execute(
            "SELECT anlass, stufe FROM uci_rennstufe WHERE race_id = %s", (race_id,)
        ).fetchall()
    }


def _skala(conn, saison: int, gender: str, anlass: str, stufe: str) -> dict[int, int]:
    return {
        z["platz"]: z["punkte"] for z in conn.execute(
            "SELECT platz, punkte FROM uci_punkte WHERE saison = %s AND gender = %s "
            "AND anlass = %s AND stufe = %s",
            (saison, gender, anlass, stufe),
        ).fetchall()
    }


def _rechne_rennen(conn, rennen: dict) -> dict:
    race_id = rennen["id"]
    stufen = _stufen(conn, race_id)
    bericht = {"zeilen": 0, "punkte": 0, "ohne_rider_id": 0, "ausserhalb": 0,
               "doppelt": 0}

    etappen_mit_ergebnis = conn.execute(
        "SELECT count(DISTINCT stage_id) AS n FROM race_results "
        "WHERE race_id = %s AND stage_id IS NOT NULL", (race_id,)
    ).fetchone()["n"]
    hat_etappen = conn.execute(
        "SELECT count(*) AS n FROM race_stages WHERE race_id = %s", (race_id,)
    ).fetchone()["n"] > 0

    # Art. 2.6.001: ein Etappenrennen, von dem nur eine Etappe gefahren
    # wurde, gibt AUSSCHLIESSLICH Etappenpunkte.
    nur_etappe = hat_etappen and etappen_mit_ergebnis == 1
    if nur_etappe:
        logger.warning(
            "Art. 2.6.001 greift bei %r (%s): Etappenrennen mit Ergebnissen "
            "für genau eine Etappe - kein Gesamtklassement gewertet. Falls das "
            "Rennen nicht abgebrochen wurde, fehlen Etappen-Ergebnisse",
            rennen["name"], race_id)

    conn.execute("DELETE FROM uci_punkte_fahrer WHERE race_id = %s", (race_id,))

    for anlass in ANLAESSE:
        if anlass not in stufen:
            continue
        if anlass == "gc" and nur_etappe:
            continue
        skala = _skala(conn, rennen["season"], rennen["gender"], anlass, stufen[anlass])
        if not skala:
            logger.warning(
                "Keine Skala für %s/%s/%s/%s - %r übersprungen",
                rennen["season"], rennen["gender"], anlass, stufen[anlass],
                rennen["name"])
            continue
        # Gesamtklassement: stage_id IS NULL. Etappen: stage_id gesetzt.
        wo = "IS NULL" if anlass == "gc" else "IS NOT NULL"
        zeilen = conn.execute(
            f"""
            SELECT e.rider_id, e.position, e.stage_id, s.stage_date
              FROM race_results e
              LEFT JOIN race_stages s ON s.id = e.stage_id
             WHERE e.race_id = %s AND e.stage_id {wo}
            """,
            (race_id,),
        ).fetchall()
        for zeile in zeilen:
            bericht["zeilen"] += 1
            if zeile["rider_id"] is None:
                bericht["ohne_rider_id"] += 1
                continue
            punkte = skala.get(zeile["position"])
            if punkte is None:
                # Platz tiefer als die Skala reicht - das ist der Normalfall
                # fuer das halbe Feld, kein Fehler.
                bericht["ausserhalb"] += 1
                continue
            cur = conn.execute(
                """
                INSERT INTO uci_punkte_fahrer
                    (race_id, stage_id, rider_id, anlass, position, punkte, punkt_datum)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (race_id, zeile["stage_id"], zeile["rider_id"], anlass,
                 zeile["position"], punkte,
                 zeile["stage_date"] or rennen["end_date"] or rennen["start_date"]),
            )
            if cur.rowcount:
                bericht["punkte"] += 1
            else:
                # Derselbe Fahrer steht in diesem Anlass zweimal im Ergebnis.
                # Das ist ein Datenfehler in race_results, keine
                # Punkteverdopplung - gezaehlt statt verschwiegen.
                bericht["doppelt"] += 1

    conn.execute(
        "UPDATE races SET punkte_berechnet_at = now() WHERE id = %s", (race_id,))
    return bericht


def berechne(saison: Optional[int] = None) -> dict:
    """Rechnet alle faelligen Rennen. Gibt eine Zusammenfassung zurueck.

    Wirft nicht: eine fehlgeschlagene Rechnung darf den Start nicht
    verhindern. Je Rennen eine eigene Transaktion, damit ein kaputtes
    Rennen nicht die uebrigen mitreisst - dieselbe Ueberlegung wie bei der
    Handzuordnung in app/uci_zuordnung.py."""
    gesamt = {"rennen": 0, "zeilen": 0, "punkte": 0, "ohne_rider_id": 0,
              "ausserhalb": 0, "doppelt": 0, "fehler": 0}
    if not db.is_configured():
        return gesamt
    try:
        with db._connect() as conn:
            faellig = _faellige_rennen(conn, saison)
    except Exception as exc:  # noqa: BLE001
        logger.error("Punkteberechnung: fällige Rennen nicht lesbar: %s", exc)
        return gesamt
    if not faellig:
        return gesamt

    for rennen in faellig:
        try:
            with db._connect() as conn:
                bericht = _rechne_rennen(conn, rennen)
            gesamt["rennen"] += 1
            for schluessel in ("zeilen", "punkte", "ohne_rider_id", "ausserhalb",
                               "doppelt"):
                gesamt[schluessel] += bericht[schluessel]
        except Exception as exc:  # noqa: BLE001
            gesamt["fehler"] += 1
            logger.error("Punkteberechnung für %r fehlgeschlagen: %s",
                         rennen["name"], exc)

    logger.info(
        "UCI-Punkte berechnet: %d Rennen, %d Ergebniszeilen, davon %d gewertet, "
        "%d ohne Fahrer-ID, %d ausserhalb der Skala%s",
        gesamt["rennen"], gesamt["zeilen"], gesamt["punkte"],
        gesamt["ohne_rider_id"], gesamt["ausserhalb"],
        (f", {gesamt['doppelt']} Doppelnennungen" if gesamt["doppelt"] else "")
        + (f", {gesamt['fehler']} Rennen fehlgeschlagen" if gesamt["fehler"] else ""),
    )
    return gesamt


def rangliste(saison: int, gender: str = "m", limit: int = 10) -> list[dict]:
    """Die Teilsumme je Fahrer, beste zuerst. Fuer Stichproben und die
    Gegenprobe gegen eine veroeffentlichte Rangliste - NICHT als
    UCI-Rangliste ausgeben, siehe Modul-Docstring."""
    with db._connect() as conn:
        return conn.execute(
            """
            SELECT p.rider_id, f.name, sum(p.punkte) AS punkte, count(*) AS zeilen
              FROM uci_punkte_fahrer p
              JOIN races r ON r.id = p.race_id
              JOIN riders f ON f.id = p.rider_id
             WHERE r.season = %s AND r.gender = %s
             GROUP BY p.rider_id, f.name
             ORDER BY punkte DESC, f.name
             LIMIT %s
            """,
            (saison, gender, limit),
        ).fetchall()
