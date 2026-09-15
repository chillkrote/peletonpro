#!/usr/bin/env python3
"""Prueft den Abgleich Reglement-Rennname -> races.id.

    DATABASE_URL=postgresql://... python3 scripts/check-uci-zuordnung.py

Eine LEERE Datenbank genuegt - das Skript wendet die Migrationen selbst an
und legt sich seine Rennen hin.

Der Punkt dieses Tests ist NICHT, dass moeglichst viel zugeordnet wird. Er
ist, dass nichts FALSCH zugeordnet wird: eine offene Zuordnung faellt als
race_id IS NULL auf, eine falsche erzeugt still zu hohe Punktzahlen. Die
Haelfte der Pruefungen unten belegt deshalb, dass etwas NICHT passiert.
"""
import os
import pathlib
import sys

WURZEL = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL / "backend"))

fehler = 0


def pruefe(name, ist, soll):
    global fehler
    ok = ist == soll
    if not ok:
        fehler += 1
    print(f"  {name:<56} {'ok' if ok else f'FEHLER (ist {ist!r}, soll {soll!r})'}")


if not os.environ.get("DATABASE_URL"):
    print("DATABASE_URL fehlt.")
    sys.exit(1)

from app import db, uci_punkte, uci_zuordnung  # noqa: E402
from app.migrations import run_migrations  # noqa: E402

run_migrations()
uci_punkte.lade_reglement()

SAISON = 2026

# Rennen, wie sie ein Wikipedia-Scrape hinterlassen wuerde. Absichtlich mit
# den Fallstricken: Halbgeviertstriche statt Bindestrichen, ein Sponsor vor
# dem Namen, ein Rennen der falschen Kategorie, eines der falschen Saison.
RENNEN = [
    ("2026-wt-tour-de-france",      "Tour de France",          2026, "wt", "m"),
    ("2026-wt-paris-nice",          "Paris–Nice",              2026, "wt", "m"),
    ("2026-wt-liege",               "Liège–Bastogne–Liège",    2026, "wt", "m"),
    ("2026-wt-gree-tour-of-guangxi", "Gree–Tour of Guangxi",   2026, "wt", "m"),
    ("2026-wt-omloop",              "Omloop Het Nieuwsblad",   2026, "wt", "m"),
    # Dieses Rennen fuehren Reglement-Tabellen fuer BEIDE Geschlechter unter
    # demselben Namen. Es ist hier als Maennerrennen angelegt: ohne den
    # Geschlechtsfilter wuerde die Frauen-Zeile darauf zugeordnet. Das ist
    # der Fall, der den Filter ueberhaupt pruefbar macht - ohne ihn blieb die
    # Gegenprobe "Geschlechtsfilter entfernt" gruen.
    ("2026-wt-santos-tour-down-under", "Santos Tour Down Under", 2026, "wt", "m"),
    # Kategorie passt nicht: darf nie Kandidat sein.
    ("2026-proseries-il-lombardia", "Il Lombardia",            2026, "proseries", "m"),
    # Falsche Saison: darf nie Kandidat sein.
    ("2025-wt-tour-de-suisse",      "Tour de Suisse",          2025, "wt", "m"),
    # Zwei Zeilen mit demselben Namen - Datenfehler in races, nicht raten.
    ("2026-wt-strade-bianche",      "Strade Bianche",          2026, "wt", "m"),
    ("2026-wt-strade-bianche-2",    "Strade Bianche",          2026, "wt", "m"),
]

with db._connect() as conn:
    for rid, name, season, kategorie, gender in RENNEN:
        conn.execute(
            "INSERT INTO races (id, name, season, category, gender) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (rid, name, season, kategorie, gender),
        )

print("=== 1. Vergleichsform ===")
rf = uci_zuordnung.rennform
pruefe("'Paris - Nice' == 'Paris–Nice'", rf("Paris - Nice"), rf("Paris–Nice"))
pruefe("Akzente gefaltet", rf("Liège-Bastogne-Liège"), "liege-bastogne-liege")
pruefe("Wortgrenze: 'tour' nicht in 'detour'",
       uci_zuordnung._enthalten("tour", "detour"), False)
pruefe("Wortgrenze: nach Bindestrich schon",
       uci_zuordnung._enthalten("tour of guangxi", "gree-tour of guangxi"), True)

print("=== 2. Der Abgleich ===")
bericht = uci_zuordnung.zuordnen(SAISON)


def zuordnung(anlass, name, gender="m"):
    with db._connect() as conn:
        z = conn.execute(
            "SELECT race_id FROM uci_rennstufe WHERE saison = %s AND gender = %s "
            "AND anlass = %s AND rennen_reglement = %s",
            (SAISON, gender, anlass, name)
        ).fetchone()
    return z["race_id"] if z else "ZEILE FEHLT"


pruefe("Tour de France exakt zugeordnet",
       zuordnung("gc", "Tour de France"), "2026-wt-tour-de-france")
pruefe("Paris - Nice trotz Strichvariante",
       zuordnung("gc", "Paris - Nice"), "2026-wt-paris-nice")
pruefe("Liège-Bastogne-Liège trotz Akzenten",
       zuordnung("gc", "Liège-Bastogne-Liège"), "2026-wt-liege")
pruefe("Tour of Guangxi ueber Namensbestandteil",
       zuordnung("gc", "Tour of Guangxi"), "2026-wt-gree-tour-of-guangxi")
pruefe("mindestens ein exakter Treffer", bericht["exakt"] >= 3, True)
# Drei, nicht einer: "Tour of Guangxi" steht bei den Maennern in gc,
# etappe UND trikot. Dasselbe Rennen darf in verschiedenen Anlaessen
# zugeordnet werden - nur innerhalb eines Anlasses nicht zweimal.
pruefe("drei 'enthalten'-Treffer (ein Rennen, drei Anlaesse)",
       bericht["enthalten"], 3)

# Die abgeleiteten Zuordnungen muessen namentlich im Log stehen, nicht nur
# gezaehlt: "2 aehnlich" ohne die Namen ist eine Beunruhigung ohne Handhabe.
# Genau das war beim ersten Produktionslauf der Fall.
print("=== 2b. Abgeleitete Zuordnungen stehen namentlich im Log ===")
import logging  # noqa: E402
from io import StringIO  # noqa: E402

puffer = StringIO()
haken = logging.StreamHandler(puffer)
log = logging.getLogger("app.uci_zuordnung")
log.addHandler(haken)
log.setLevel(logging.INFO)
with db._connect() as conn:
    conn.execute(
        "UPDATE uci_rennstufe SET race_id = NULL WHERE saison = %s "
        "AND rennen_reglement = 'Tour of Guangxi'", (SAISON,)
    )
uci_zuordnung.zuordnen(SAISON)
log.removeHandler(haken)
ausgabe = puffer.getvalue()
pruefe("Meldung 'abgeleitet' vorhanden", "abgeleitet" in ausgabe, True)
pruefe("der abgeleitete Name steht drin", "Tour of Guangxi" in ausgabe, True)
pruefe("die Art steht dabei", "(enthalten)" in ausgabe, True)
pruefe("die race_id steht dabei",
       "2026-wt-gree-tour-of-guangxi" in ausgabe, True)

print("=== 3. Was NICHT zugeordnet werden darf ===")
# Das Reglement schreibt "Omloop Nieuwsblad", Wikipedia "Omloop Het
# Nieuwsblad". Die Aehnlichkeit ist 0,895 - knapp UNTER der Schwelle von
# 0,90, also bleibt die Zeile offen. Diese Zuordnung ist inhaltlich
# richtig und wird trotzdem nicht gesetzt: das ist der Preis der
# konservativen Schwelle, und er ist absichtlich so gewaehlt. Eine offene
# Zeile faellt auf, eine falsche nicht.
pruefe("'Omloop Nieuwsblad' knapp unter der Schwelle -> offen",
       zuordnung("gc", "Omloop Nieuwsblad"), None)
# Der Tippfehler des Reglements steht nur in der Frauen-Tabelle.
pruefe("'Oomlop Nieuwsblad' (Frauen) bleibt offen",
       zuordnung("gc", "Oomlop Nieuwsblad", "w"), None)
pruefe("Strade Bianche mehrdeutig -> offen",
       zuordnung("gc", "Strade Bianche"), None)
pruefe("Il Lombardia (falsche Kategorie) bleibt offen",
       zuordnung("gc", "Il Lombardia"), None)
pruefe("Tour de Suisse (falsche Saison) bleibt offen",
       zuordnung("gc", "Tour de Suisse"), None)
with db._connect() as conn:
    frauen = conn.execute(
        "SELECT count(*) AS n FROM uci_rennstufe "
        "WHERE saison = %s AND gender = 'w' AND race_id IS NOT NULL", (SAISON,)
    ).fetchone()["n"]
pruefe("keine Frauen-Zeile zugeordnet (keine Frauen-Rennen da)", frauen, 0)
pruefe("offene Zeilen gemeldet", bericht["offen"] > 0, True)
pruefe("nichts 'aehnlich' geraten", bericht["aehnlich"], 0)

print("=== 4. Wiederholter Lauf ===")
zweiter = uci_zuordnung.zuordnen(SAISON)
pruefe("zweiter Lauf ordnet nichts Neues zu",
       (zweiter["exakt"], zweiter["enthalten"], zweiter["aehnlich"]), (0, 0, 0))
pruefe("Tour de France weiterhin zugeordnet",
       zuordnung("gc", "Tour de France"), "2026-wt-tour-de-france")

print("=== 5. Handarbeit wird nicht ueberschrieben ===")
with db._connect() as conn:
    conn.execute(
        "INSERT INTO races (id, name, season, category, gender) VALUES "
        "('2026-wt-von-hand', 'Von Hand', 2026, 'wt', 'm') "
        "ON CONFLICT (id) DO NOTHING"
    )
    conn.execute(
        "UPDATE uci_rennstufe SET race_id = '2026-wt-von-hand' WHERE saison = %s "
        "AND gender = 'm' AND anlass = 'gc' AND rennen_reglement = 'Omloop Nieuwsblad'",
        (SAISON,),
    )
uci_zuordnung.zuordnen(SAISON)
pruefe("von Hand gesetzte race_id bleibt",
       zuordnung("gc", "Omloop Nieuwsblad"), "2026-wt-von-hand")

print("=== 6. Die Schwelle greift ===")
# Ein Name, der aehnlich, aber nicht gleich ist - und dessen zweitbester
# Kandidat weit weg liegt. Muss ueber "aehnlich" zugeordnet werden.
kandidaten = {"a": rf("Tour de Romandie"), "b": rf("Volta a Catalunya")}
pruefe("'Tour de Romandi' -> aehnlich",
       uci_zuordnung._beste(rf("Tour de Romandi"), kandidaten)[1], "aehnlich")
# Zwei fast gleich gute Kandidaten: nicht raten.
eng = {"a": rf("Tour de Romandie"), "b": rf("Tour de Romandia")}
pruefe("zwei gleich gute Kandidaten -> mehrdeutig",
       uci_zuordnung._beste(rf("Tour de Romandi"), eng)[1], "mehrdeutig")
pruefe("gar keine Kandidaten -> eigener Grund",
       uci_zuordnung._beste(rf("Irgendwas"), {})[1], "keine Kandidaten")

print("=== 7. Ohne Saison-Angabe: alle Jahrgaenge ===")
# Ein zweiter Reglement-Jahrgang. Ohne die Schleife ueber alle Saisons
# waere er geladen, aber nie zugeordnet - und das faellt erst auf, wenn
# jemand die Punkte des Vorjahres nachrechnen will.
with db._connect() as conn:
    conn.execute(
        "INSERT INTO races (id, name, season, category, gender) VALUES "
        "('2027-wt-tour-de-france', 'Tour de France', 2027, 'wt', 'm') "
        "ON CONFLICT (id) DO NOTHING"
    )
    conn.execute(
        "INSERT INTO uci_stufe (saison, gender, anlass, stufe) "
        "VALUES (2027, 'm', 'gc', 'gc1') ON CONFLICT DO NOTHING"
    )
    conn.execute(
        "INSERT INTO uci_rennstufe (saison, gender, anlass, stufe, rennen_reglement) "
        "VALUES (2027, 'm', 'gc', 'gc1', 'Tour de France') ON CONFLICT DO NOTHING"
    )
uci_zuordnung.zuordnen()          # ohne Saison-Angabe
with db._connect() as conn:
    z2027 = conn.execute(
        "SELECT race_id FROM uci_rennstufe WHERE saison = 2027 "
        "AND rennen_reglement = 'Tour de France'"
    ).fetchone()["race_id"]
pruefe("Jahrgang 2027 ebenfalls zugeordnet", z2027, "2027-wt-tour-de-france")
pruefe("2026 nicht durcheinandergebracht",
       zuordnung("gc", "Tour de France"), "2026-wt-tour-de-france")

print()
if fehler:
    print(f"{fehler} FEHLER.")
    sys.exit(1)
print("Alle Pruefungen bestanden.")
