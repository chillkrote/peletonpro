#!/usr/bin/env python3
"""Prueft die Punkteberechnung (Migration 0009, app/uci_berechnung.py).

    DATABASE_URL=postgresql://... python3 scripts/check-uci-berechnung.py

Eine LEERE Datenbank genuegt - das Skript wendet die Migrationen selbst an,
laedt das Reglement und legt sich seine Rennen, Etappen und Ergebnisse hin.

Geprueft wird gegen KONKRETE Zahlen aus dem Reglement (Tour-Sieg 1300,
Etappensieg 210, Platz 60 noch 15, Platz 61 nichts). Ein Test, der nur
"irgendwelche Punkte" prueft, wuerde eine um eine Position verschobene
Skala nicht bemerken - und das ist der wahrscheinlichste Fehler.
"""
import os
import pathlib
import sys
from decimal import Decimal

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

from app import db, uci_berechnung, uci_punkte  # noqa: E402
from app.migrations import run_migrations  # noqa: E402

run_migrations()
uci_punkte.lade_reglement()

SAISON = 2026


def sql(befehl, *args):
    with db._connect() as conn:
        conn.execute(befehl, args or None)


def hole(befehl, *args):
    with db._connect() as conn:
        return conn.execute(befehl, args or None).fetchall()


# --- Aufbau ---------------------------------------------------------------
# Drei Rennen: die Tour (Stufe gc1/et1, die hoechste Skala), ein Rennen der
# untersten Stufe (gc5) und ein Etappenrennen, von dem nur eine Etappe
# gefahren wurde.
for rid, name, stufen in [
    ("tour", "Testtour", {"gc": "gc1", "etappe": "et1"}),
    ("klein", "Kleines Rennen", {"gc": "gc5"}),
    ("abbruch", "Abgebrochenes Rennen", {"gc": "gc1", "etappe": "et1"}),
    ("ohne", "Ohne Zuordnung", {}),
]:
    sql("INSERT INTO races (id, name, season, category, gender, start_date, "
        "end_date, results_fetched_at) VALUES (%s, %s, %s, 'wt', 'm', "
        "'2026-07-04', '2026-07-26', now()) ON CONFLICT (id) DO NOTHING",
        rid, name, SAISON)
    for anlass, stufe in stufen.items():
        sql("INSERT INTO uci_rennstufe (saison, gender, anlass, stufe, "
            "rennen_reglement, race_id) VALUES (%s, 'm', %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            SAISON, anlass, stufe, f"{rid}-{anlass}", rid)

for i in range(1, 65):
    sql("INSERT INTO riders (id, name, wiki_url) VALUES (%s, %s, %s) "
        "ON CONFLICT (id) DO NOTHING",
        f"f{i}", f"Fahrer {i}", f"https://example.invalid/f{i}")

# Tour: Gesamtklassement Platz 1..62, Etappe 1 Platz 1..3.
for platz in range(1, 63):
    sql("INSERT INTO race_results (race_id, stage_id, position, rider_name, rider_id) "
        "VALUES ('tour', NULL, %s, %s, %s)", platz, f"Fahrer {platz}", f"f{platz}")
etappe1 = hole("INSERT INTO race_stages (race_id, stage_number, stage_date) "
               "VALUES ('tour', 1, '2026-07-05') RETURNING id")[0]["id"]
etappe2 = hole("INSERT INTO race_stages (race_id, stage_number, stage_date) "
               "VALUES ('tour', 2, '2026-07-06') RETURNING id")[0]["id"]
for platz in range(1, 4):
    sql("INSERT INTO race_results (race_id, stage_id, position, rider_name, rider_id) "
        "VALUES ('tour', %s, %s, %s, %s)", etappe1, platz, f"Fahrer {platz}", f"f{platz}")
sql("INSERT INTO race_results (race_id, stage_id, position, rider_name, rider_id) "
    "VALUES ('tour', %s, 1, 'Fahrer 5', 'f5')", etappe2)
# Eine Zeile OHNE rider_id - darf nicht punkten, muss gezaehlt werden.
sql("INSERT INTO race_results (race_id, stage_id, position, rider_name, rider_id) "
    "VALUES ('tour', %s, 2, 'Unbekannt', NULL)", etappe2)

# Kleines Rennen: Eintagesrennen, Platz 1 und 2.
for platz in (1, 2):
    sql("INSERT INTO race_results (race_id, stage_id, position, rider_name, rider_id) "
        "VALUES ('klein', NULL, %s, %s, %s)", platz, f"Fahrer {platz}", f"f{platz}")

# Abbruch: Etappenrennen mit ZWEI angelegten Etappen, aber Ergebnissen fuer
# nur eine - dazu ein Gesamtklassement, das es nach Art. 2.6.001 nicht
# geben duerfte.
a1 = hole("INSERT INTO race_stages (race_id, stage_number, stage_date) "
          "VALUES ('abbruch', 1, '2026-03-01') RETURNING id")[0]["id"]
hole("INSERT INTO race_stages (race_id, stage_number, stage_date) "
     "VALUES ('abbruch', 2, '2026-03-02') RETURNING id")
sql("INSERT INTO race_results (race_id, stage_id, position, rider_name, rider_id) "
    "VALUES ('abbruch', %s, 1, 'Fahrer 1', 'f1')", a1)
sql("INSERT INTO race_results (race_id, stage_id, position, rider_name, rider_id) "
    "VALUES ('abbruch', NULL, 1, 'Fahrer 1', 'f1')")

# Ohne Zuordnung: Ergebnis vorhanden, aber keine uci_rennstufe-Zeile.
sql("INSERT INTO race_results (race_id, stage_id, position, rider_name, rider_id) "
    "VALUES ('ohne', NULL, 1, 'Fahrer 1', 'f1')")

print("=== 1. Die Rechnung laeuft ===")
bericht = uci_berechnung.berechne(SAISON)
pruefe("drei Rennen gerechnet (das vierte hat keine Zuordnung)",
       bericht["rennen"], 3)
pruefe("eine Zeile ohne Fahrer-ID gemeldet", bericht["ohne_rider_id"], 1)
pruefe("keine Fehler", bericht["fehler"], 0)


def punkte(race_id, rider_id, anlass, stage_id=None):
    z = hole("SELECT punkte FROM uci_punkte_fahrer WHERE race_id = %s "
             "AND rider_id = %s AND anlass = %s "
             "AND coalesce(stage_id, -1) = coalesce(%s, -1)",
             race_id, rider_id, anlass, stage_id)
    return z[0]["punkte"] if z else None


print("=== 2. Die Zahlen stimmen mit dem Reglement ===")
pruefe("Tour-Gesamtsieg = 1300", punkte("tour", "f1", "gc"), Decimal("1300"))
pruefe("Tour-Gesamt Platz 2 = 1040", punkte("tour", "f2", "gc"), Decimal("1040"))
pruefe("Tour-Gesamt Platz 60 = 15", punkte("tour", "f60", "gc"), Decimal("15"))
pruefe("Tour-Gesamt Platz 61 = keine Punkte", punkte("tour", "f61", "gc"), None)
pruefe("Tour-Gesamt Platz 62 = keine Punkte", punkte("tour", "f62", "gc"), None)
pruefe("Etappensieg = 210", punkte("tour", "f1", "etappe", etappe1), Decimal("210"))
pruefe("Etappe Platz 3 = 110", punkte("tour", "f3", "etappe", etappe1), Decimal("110"))
pruefe("unterste Stufe, Sieg = 400", punkte("klein", "f1", "gc"), Decimal("400"))
pruefe("unterste Stufe, Platz 2 = 320", punkte("klein", "f2", "gc"), Decimal("320"))
pruefe("Plaetze ausserhalb der Skala gezaehlt", bericht["ausserhalb"] >= 2, True)

print("=== 3. Artikel 2.6.001 ===")
pruefe("nur eine Etappe gefahren -> Etappenpunkte",
       punkte("abbruch", "f1", "etappe", a1), Decimal("210"))
pruefe("nur eine Etappe gefahren -> KEIN Gesamtklassement",
       punkte("abbruch", "f1", "gc"), None)
pruefe("die Tour hat zwei Etappen mit Ergebnis -> Gesamtklassement zaehlt",
       punkte("tour", "f1", "gc"), Decimal("1300"))

print("=== 4. Das Datum der Punkte ===")
d = hole("SELECT punkt_datum FROM uci_punkte_fahrer WHERE race_id = 'tour' "
         "AND anlass = 'etappe' AND stage_id = %s AND rider_id = 'f1'", etappe1)
pruefe("Etappenpunkte tragen das Etappendatum",
       str(d[0]["punkt_datum"]), "2026-07-05")
d = hole("SELECT punkt_datum FROM uci_punkte_fahrer WHERE race_id = 'tour' "
         "AND anlass = 'gc' AND rider_id = 'f1'")
pruefe("Gesamtklassement traegt das Renn-Enddatum",
       str(d[0]["punkt_datum"]), "2026-07-26")

print("=== 5. Kein Rennen ohne Zuordnung ===")
pruefe("Rennen ohne uci_rennstufe bleibt ungerechnet",
       hole("SELECT count(*) AS n FROM uci_punkte_fahrer WHERE race_id = 'ohne'")[0]["n"], 0)

print("=== 6. Zweiter Lauf tut nichts ===")
zweiter = uci_berechnung.berechne(SAISON)
pruefe("kein Rennen erneut gerechnet", zweiter["rennen"], 0)
vorher = hole("SELECT count(*) AS n FROM uci_punkte_fahrer")[0]["n"]

print("=== 7. Neue Ergebnisse -> neu gerechnet, ohne Dubletten ===")
sql("UPDATE races SET results_fetched_at = now() WHERE id = 'tour'")
dritter = uci_berechnung.berechne(SAISON)
pruefe("die Tour wurde neu gerechnet", dritter["rennen"], 1)
pruefe("Zeilenzahl unveraendert (ersetzt, nicht ergaenzt)",
       hole("SELECT count(*) AS n FROM uci_punkte_fahrer")[0]["n"], vorher)
pruefe("Tour-Sieg immer noch 1300", punkte("tour", "f1", "gc"), Decimal("1300"))

print("=== 8. Doppelnennung ist ein Datenfehler, keine Verdopplung ===")
sql("INSERT INTO race_results (race_id, stage_id, position, rider_name, rider_id) "
    "VALUES ('klein', NULL, 3, 'Fahrer 1', 'f1')")
sql("UPDATE races SET results_fetched_at = now() WHERE id = 'klein'")
vierter = uci_berechnung.berechne(SAISON)
pruefe("Doppelnennung gezaehlt", vierter["doppelt"], 1)
pruefe("nur eine Zeile fuer den Fahrer",
       hole("SELECT count(*) AS n FROM uci_punkte_fahrer WHERE race_id = 'klein' "
            "AND rider_id = 'f1' AND anlass = 'gc'")[0]["n"], 1)

print("=== 9. rider_season_points bleibt unberuehrt ===")
belegt = hole("SELECT count(*) AS n FROM rider_season_points "
              "WHERE uci_points IS NOT NULL")[0]["n"]
pruefe("keine Teilsumme in die offizielle Spalte geschrieben", belegt, 0)

print("=== 10. Die Rangliste ===")
rang = uci_berechnung.rangliste(SAISON, "m", 3)
pruefe("bester Fahrer ist f1", rang[0]["rider_id"], "f1")
# f1: Tour-GC 1300 + Tour-Etappe 210 + klein-GC 400 + abbruch-Etappe 210
pruefe("seine Teilsumme ist nachrechenbar", rang[0]["punkte"], Decimal("2120"))

print()
if fehler:
    print(f"{fehler} FEHLER.")
    sys.exit(1)
print("Alle Pruefungen bestanden.")
