"""Reglement-Rennnamen den Zeilen in `races` zuordnen.

WARUM DAS NICHT DER LOADER MACHT
--------------------------------
`uci_rennstufe.rennen_reglement` ist der Name, wie er im UCI-Reglement
steht. `races.name` ist der Name, wie er auf Wikipedia steht. Die beiden
stimmen oft, aber nicht immer überein - und das Reglement selbst schreibt
"Oomlop Nieuwsblad" für Omloop Nieuwsblad und lässt bei "Lloyds Tour of
Britain Women" in einer Tabelle das "Women" weg. Ein Abgleich, der jeden
Namen irgendwie zuordnet, würde bei jeder Umbenennung still falsche Punkte
erzeugen.

Deshalb ordnet dieses Modul nur zu, was es BELEGEN kann, und lässt alles
andere auf NULL stehen. Eine offene Zuordnung ist abfragbar
(`WHERE race_id IS NULL`) und steht in der Log-Meldung; eine falsche wäre
unsichtbar. Die Richtung des Irrtums ist hier die ganze Entscheidung.

DREI STUFEN, GETRENNT GEZÄHLT
-----------------------------
    exakt       Vergleichsform beider Namen identisch.
    enthalten   der Reglement-Name steht als ganzes Wortfolge in GENAU
                einem Kandidaten ("Tour of Guangxi" in "Gree-Tour of
                Guangxi").
    aehnlich    Ähnlichkeit >= SCHWELLE und mindestens ABSTAND besser als
                der zweitbeste Kandidat.

Getrennt gezählt, weil die drei nicht gleich verlässlich sind: wer die
Zahlen im Log sieht, weiß, wie viel davon geraten ist. "exakt" braucht
keine Nachprüfung, "aehnlich" schon.

WANN ES LÄUFT
-------------
Beim Prozessstart, direkt nach dem Reglement-Loader. Das ist billig -
reines SQL, keine externen Abrufe - und es arbeitet nur an Zeilen mit
`race_id IS NULL`. Ist alles zugeordnet, tut es nichts. Es muss ausserdem
wiederholt laufen, weil die Rennen einer Saison erst über die Zeit geseedet
werden: ein Rennen, das beim ersten Lauf noch nicht in `races` stand, wird
beim nächsten gefunden. Ein Takt wie bei den Wikipedia-Jobs (app/kadenz.py)
wäre hier also falsch.
"""
import logging
import re
from difflib import SequenceMatcher
from typing import Optional

from . import db
from .text import normalize_dashes, vergleichsform

logger = logging.getLogger(__name__)

# Nur zuordnen, wenn es deutlich ist. Lieber eine Zuordnung liegen lassen -
# die faellt als NULL auf - als eine falsche schreiben, die niemand sieht.
SCHWELLE = 0.90
ABSTAND = 0.05

# Wie viele offene Namen ins Log geschrieben werden. Der Rest waere eine
# Logzeile, die niemand liest; die vollstaendige Liste steht in der
# Datenbank.
LOG_GRENZE = 12

_MEHRFACH_LEER = re.compile(r"\s+")
_UM_BINDESTRICH = re.compile(r"\s*-\s*")


def rennform(name: str) -> str:
    """Vergleichsform eines Rennnamens.

    Über `text.vergleichsform` hinaus: Striche vereinheitlichen und
    Leerzeichen um Bindestriche entfernen. Das Reglement schreibt
    "Paris - Nice" und "Tirreno - Adriatico", Wikipedia "Paris–Nice" - ohne
    diesen Schritt wäre nicht eine einzige dieser Zuordnungen exakt."""
    gefaltet = vergleichsform(normalize_dashes(name))
    return _MEHRFACH_LEER.sub(" ", _UM_BINDESTRICH.sub("-", gefaltet)).strip()


def _enthalten(kurz: str, lang: str) -> bool:
    """Ob `kurz` als ganze Wortfolge in `lang` steht.

    An Wortgrenzen, damit "tour" nicht in "detour" trifft. Bindestrich und
    Leerzeichen gelten beide als Grenze - "Tour of Guangxi" soll in
    "Gree-Tour of Guangxi" treffen."""
    if kurz == lang:
        return True
    muster = r"(?:^|[\s-])" + re.escape(kurz) + r"(?:$|[\s-])"
    return re.search(muster, lang) is not None


def _beste(ziel: str, kandidaten: dict[str, str]) -> tuple[Optional[str], str]:
    """(race_id, Stufe) für den besten Kandidaten, oder (None, Grund).

    `kandidaten` ist {race_id: rennform(races.name)}."""
    exakt = [rid for rid, form in kandidaten.items() if form == ziel]
    if len(exakt) == 1:
        return exakt[0], "exakt"
    if len(exakt) > 1:
        # Zwei Zeilen in races mit demselben Namen - das ist ein Datenfehler
        # in races, nicht eine Frage der Zuordnung. Nicht raten.
        #
        # Diese Pruefung ist REDUNDANT: zwei identische Kandidaten treffen
        # auch den Enthalten-Zweig unten zweimal und landen dort ebenfalls
        # bei "mehrdeutig". Belegt durch eine Gegenprobe, die diesen Zweig
        # ausbaut - die Test-Suite bleibt gruen. Sie steht hier trotzdem,
        # weil sie den Fall benennt; wer den Enthalten-Zweig umbaut, darf
        # sich aber NICHT darauf verlassen, dass diese Zeile ihn abfaengt.
        return None, "mehrdeutig"

    treffer = [rid for rid, form in kandidaten.items() if _enthalten(ziel, form)]
    if len(treffer) == 1:
        return treffer[0], "enthalten"
    if len(treffer) > 1:
        return None, "mehrdeutig"

    bewertet = sorted(
        ((SequenceMatcher(None, ziel, form).ratio(), rid)
         for rid, form in kandidaten.items()),
        reverse=True,
    )
    if not bewertet:
        return None, "keine Kandidaten"
    beste_quote, beste_id = bewertet[0]
    if beste_quote < SCHWELLE:
        return None, "zu unaehnlich"
    zweite = bewertet[1][0] if len(bewertet) > 1 else 0.0
    if beste_quote - zweite < ABSTAND:
        return None, "mehrdeutig"
    return beste_id, "aehnlich"


def zuordnen(saison: Optional[int] = None) -> dict:
    """Setzt `uci_rennstufe.race_id`, wo es belegbar ist.

    Ohne `saison`: alle Jahrgaenge, die noch offene Zeilen haben - nicht nur
    RACE_SEASON_YEAR. Ein zweiter Reglement-Jahrgang (docs/uci-punkte-2027.csv)
    wuerde sonst geladen, aber nie zugeordnet, und das faellt erst auf, wenn
    jemand die Punkte des Vorjahres nachrechnen will.

    Eine bereits gesetzte race_id wird nie angefasst - die Zuordnung kann
    von Hand korrigiert worden sein, und ein Lauf dieses Moduls darf das
    nicht wieder einreissen.

    Wirft nicht: ein fehlgeschlagener Abgleich darf den Start nicht
    verhindern."""
    if saison is None:
        try:
            with db._connect() as conn:
                saisons = [z["saison"] for z in conn.execute(
                    "SELECT DISTINCT saison FROM uci_rennstufe "
                    "WHERE race_id IS NULL ORDER BY saison"
                ).fetchall()]
        except Exception as exc:  # noqa: BLE001
            logger.error("Rennzuordnung: Saisons nicht lesbar: %s", exc)
            return {"exakt": 0, "enthalten": 0, "aehnlich": 0, "offen": 0}
        gesamt = {"exakt": 0, "enthalten": 0, "aehnlich": 0, "offen": 0}
        for jahr in saisons:
            for k, v in zuordnen(jahr).items():
                gesamt[k] += v
        return gesamt
    bericht = {"exakt": 0, "enthalten": 0, "aehnlich": 0, "offen": 0}
    offene_namen: list[str] = []
    try:
        with db._connect() as conn:
            offen = conn.execute(
                "SELECT saison, gender, anlass, stufe, rennen_reglement "
                "FROM uci_rennstufe WHERE saison = %s AND race_id IS NULL "
                "ORDER BY gender, anlass, rennen_reglement",
                (saison,),
            ).fetchall()
            if not offen:
                return bericht

            # Kandidaten je Geschlecht einmal holen, nicht je Zeile: bei 121
            # Zeilen waeren das 121 Abfragen fuer zwei Ergebnismengen.
            kandidaten: dict[str, dict[str, str]] = {}
            for gender in sorted({z["gender"] for z in offen}):
                kandidaten[gender] = {
                    z["id"]: rennform(z["name"]) for z in conn.execute(
                        "SELECT id, name FROM races "
                        "WHERE season = %s AND gender = %s AND category = 'wt'",
                        (saison, gender),
                    ).fetchall()
                }

            # Je Zeile EINMAL bewerten.
            bewertet = [
                (zeile, *_beste(rennform(zeile["rennen_reglement"]),
                                kandidaten.get(zeile["gender"], {})))
                for zeile in offen
            ]

            # Innerhalb eines Anlasses darf ein Rennen nicht zweimal vergeben
            # werden. Deshalb in der Reihenfolge der Verlaesslichkeit
            # zuteilen: ein exakter Treffer darf nicht von einem geratenen
            # verdraengt werden, nur weil der in der Zeilenfolge vorher kam.
            vergeben: dict[tuple[str, str], set[str]] = {}
            gefunden = []
            for stufe_name in ("exakt", "enthalten", "aehnlich"):
                for zeile, race_id, art in bewertet:
                    if race_id is None or art != stufe_name:
                        continue
                    schluessel = (zeile["gender"], zeile["anlass"])
                    if race_id in vergeben.setdefault(schluessel, set()):
                        continue
                    vergeben[schluessel].add(race_id)
                    gefunden.append((zeile["rennen_reglement"], zeile["gender"],
                                     zeile["anlass"], race_id, art))

            for name, gender, anlass, race_id, art in gefunden:
                conn.execute(
                    "UPDATE uci_rennstufe SET race_id = %s WHERE saison = %s "
                    "AND gender = %s AND anlass = %s AND rennen_reglement = %s "
                    "AND race_id IS NULL",
                    (race_id, saison, gender, anlass, name),
                )
                bericht[art] += 1

            zugeordnet = {(n, g, a) for n, g, a, _, _ in gefunden}
            for zeile in offen:
                if (zeile["rennen_reglement"], zeile["gender"],
                        zeile["anlass"]) not in zugeordnet:
                    bericht["offen"] += 1
                    eintrag = f"{zeile['gender']}/{zeile['rennen_reglement']}"
                    if eintrag not in offene_namen:
                        offene_namen.append(eintrag)
    except Exception as exc:  # noqa: BLE001 - Start darf nicht scheitern
        logger.error("Rennzuordnung fehlgeschlagen: %s", exc)
        return bericht

    if not any(bericht.values()):
        return bericht
    logger.info(
        "Rennzuordnung %d: %d exakt, %d enthalten, %d aehnlich, %d offen",
        saison, bericht["exakt"], bericht["enthalten"], bericht["aehnlich"],
        bericht["offen"],
    )
    if offene_namen:
        logger.info(
            "Rennzuordnung %d offen (%d Namen): %s%s",
            saison, len(offene_namen), "; ".join(offene_namen[:LOG_GRENZE]),
            f" ... und {len(offene_namen) - LOG_GRENZE} weitere"
            if len(offene_namen) > LOG_GRENZE else "",
        )
    return bericht
