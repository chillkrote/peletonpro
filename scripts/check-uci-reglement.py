#!/usr/bin/env python3
"""Prueft Migration 0008 und den Reglement-Loader gegen ein echtes Postgres.

    DATABASE_URL=postgresql://... python3 scripts/check-uci-reglement.py

Eine LEERE Datenbank genuegt - das Skript wendet die Migrationen selbst an.

Der eigentliche Punkt ist Teil 3: der Loader darf beim zweiten Aufruf
NICHTS tun. Ohne diese Eigenschaft wuerden auf dem kostenlosen Plan bei
jedem Aufwachen 1564 Zeilen geschrieben - genau die Verschwendung, die der
Saison-Takt (Migration 0007) an anderer Stelle beseitigt hat.
"""
import csv
import os
import pathlib
import shutil
import sys
import tempfile
from decimal import Decimal

WURZEL = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL / "backend"))

fehler = 0


def pruefe(name, ist, soll):
    global fehler
    ok = ist == soll
    if not ok:
        fehler += 1
    print(f"  {name:<58} {'ok' if ok else f'FEHLER (ist {ist!r}, soll {soll!r})'}")


if not os.environ.get("DATABASE_URL"):
    print("DATABASE_URL fehlt.")
    sys.exit(1)

from app import db, uci_punkte  # noqa: E402
from app.migrations import run_migrations  # noqa: E402

run_migrations()

print("=== 1. Form der Tabellen ===")
with db._connect() as conn:
    tabellen = {
        z["table_name"] for z in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE 'uci_%'"
        ).fetchall()
    }
    typ = conn.execute(
        "SELECT data_type, numeric_precision, numeric_scale "
        "FROM information_schema.columns "
        "WHERE table_name = 'rider_season_points' AND column_name = 'uci_points'"
    ).fetchone()
    nullable = {
        z["column_name"]: z["is_nullable"] for z in conn.execute(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'uci_rennstufe'"
        ).fetchall()
    }
# uci_punkte_fahrer kommt aus Migration 0009 (die Berechnung) und gehoert
# nicht zu 0008 - sie steht hier trotzdem in der Erwartung, weil dieses
# Skript die Migrationen vollstaendig anwendet. Eine Tabelle, die
# unerwartet auftaucht oder fehlt, soll auffallen.
pruefe("die uci_-Tabellen sind vollstaendig", sorted(tabellen),
       ["uci_punkte", "uci_punkte_fahrer", "uci_quelle", "uci_rennstufe",
        "uci_stufe"])
pruefe("uci_points ist NUMERIC(8,2)",
       (typ["data_type"], typ["numeric_precision"], typ["numeric_scale"]),
       ("numeric", 8, 2))
pruefe("race_id darf NULL sein", nullable["race_id"], "YES")
pruefe("rennen_reglement darf nicht NULL sein", nullable["rennen_reglement"], "NO")

print("=== 2. Erster Ladevorgang ===")
erwartet_werte = sum(1 for _ in csv.DictReader(
    (WURZEL / "docs" / "uci-punkte-2026.csv").open(encoding="utf-8")))
erwartet_zuordnung = sum(1 for _ in csv.DictReader(
    (WURZEL / "docs" / "uci-punkte-2026-wt-stufen.csv").open(encoding="utf-8")))

pruefe("ein Jahrgang geladen", uci_punkte.lade_reglement(), 1)
with db._connect() as conn:
    z = lambda t: conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]  # noqa: E731
    punkte, stufen, rennstufe = z("uci_punkte"), z("uci_stufe"), z("uci_rennstufe")
    ohne = conn.execute(
        "SELECT count(*) AS n FROM uci_rennstufe WHERE race_id IS NULL"
    ).fetchone()["n"]
    quellen = z("uci_quelle")
    tdf = conn.execute(
        "SELECT punkte FROM uci_punkte WHERE saison = 2026 AND gender = 'm' "
        "AND anlass = 'gc' AND stufe = 'gc1' AND platz = 1"
    ).fetchone()["punkte"]
pruefe("alle Punktwerte aus der CSV", punkte, erwartet_werte)
pruefe("alle Rennzuordnungen aus der CSV", rennstufe, erwartet_zuordnung)
pruefe("jede Zuordnung noch ohne race_id", ohne, erwartet_zuordnung)
pruefe("Stufen aus beiden Dateien", stufen, 87)
pruefe("beide Quelldateien vermerkt", quellen, 2)
pruefe("Stichprobe Tour-Sieg (m/gc/gc1/1)", tdf, 1300)

print("=== 3. Zweiter Ladevorgang tut nichts ===")
pruefe("nichts geladen (Hash unverändert)", uci_punkte.lade_reglement(), 0)
with db._connect() as conn:
    pruefe("Punktwerte unverändert",
           conn.execute("SELECT count(*) AS n FROM uci_punkte").fetchone()["n"],
           erwartet_werte)

print("=== 4. Eine gesetzte race_id übersteht einen Reload ===")
tmp = pathlib.Path(tempfile.mkdtemp())
shutil.copy(WURZEL / "docs" / "uci-punkte-2026.csv", tmp)
shutil.copy(WURZEL / "docs" / "uci-punkte-2026-wt-stufen.csv", tmp)
echt = uci_punkte.DOCS
uci_punkte.DOCS = tmp

with db._connect() as conn:
    conn.execute(
        "INSERT INTO races (id, name, season, category) "
        "VALUES ('tour-de-france-2026', 'Tour de France', 2026, 'wt') "
        "ON CONFLICT (id) DO NOTHING"
    )
    conn.execute(
        "UPDATE uci_rennstufe SET race_id = 'tour-de-france-2026' "
        "WHERE saison = 2026 AND gender = 'm' AND anlass = 'gc' "
        "AND rennen_reglement = 'Tour de France'"
    )

# Datei aendern (ein Punktwert weniger), damit der Hash abweicht und
# wirklich neu geladen wird.
werte = list(csv.DictReader((tmp / "uci-punkte-2026.csv").open(encoding="utf-8")))
raus = [z for z in werte if not (z["geschlecht"] == "m" and z["anlass"] == "gc"
                                 and z["stufe"] == "gc1" and z["platz"] == "60")]
with (tmp / "uci-punkte-2026.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["geschlecht", "anlass", "stufe", "platz", "punkte"])
    w.writeheader()
    w.writerows(raus)

pruefe("geänderte Datei wird neu geladen", uci_punkte.lade_reglement(), 1)
with db._connect() as conn:
    behalten = conn.execute(
        "SELECT race_id FROM uci_rennstufe WHERE saison = 2026 AND gender = 'm' "
        "AND anlass = 'gc' AND rennen_reglement = 'Tour de France'"
    ).fetchone()["race_id"]
    weg = conn.execute(
        "SELECT count(*) AS n FROM uci_punkte WHERE saison = 2026 AND gender = 'm' "
        "AND anlass = 'gc' AND stufe = 'gc1' AND platz = 60"
    ).fetchone()["n"]
    jetzt = conn.execute("SELECT count(*) AS n FROM uci_punkte").fetchone()["n"]
pruefe("race_id nicht überschrieben", behalten, "tour-de-france-2026")
pruefe("aus der CSV entfernter Wert ist auch weg", weg, 0)
pruefe("genau eine Zeile weniger", jetzt, erwartet_werte - 1)

uci_punkte.DOCS = echt
shutil.rmtree(tmp)

print("=== 5. Die Fremdschlüssel greifen ===")
import psycopg  # noqa: E402

try:
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO uci_rennstufe (saison, gender, anlass, stufe, rennen_reglement) "
            "VALUES (2026, 'm', 'gc', 'gc99', 'Erfundenes Rennen')"
        )
    pruefe("Stufe ohne Skala wird abgelehnt", "angenommen", "abgelehnt")
except psycopg.errors.ForeignKeyViolation:
    pruefe("Stufe ohne Skala wird abgelehnt", "abgelehnt", "abgelehnt")

try:
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO uci_punkte (saison, gender, anlass, stufe, platz, punkte) "
            "VALUES (2026, 'm', 'gc', 'gc1', 61, 0)"
        )
    pruefe("punkte = 0 wird abgelehnt", "angenommen", "abgelehnt")
except psycopg.errors.CheckViolation:
    pruefe("punkte = 0 wird abgelehnt", "abgelehnt", "abgelehnt")

print("=== 6. Gebrochene Punkte passen in die Spalte ===")
with db._connect() as conn:
    conn.execute(
        "INSERT INTO riders (id, name, wiki_url) VALUES "
        "('test-fahrer', 'Test Fahrer', 'https://example.invalid/Test') "
        "ON CONFLICT (id) DO NOTHING"
    )
    conn.execute(
        "INSERT INTO rider_season_points (rider_id, year, uci_points) "
        "VALUES ('test-fahrer', 2026, 12.86) "
        "ON CONFLICT (rider_id, year) DO UPDATE SET uci_points = EXCLUDED.uci_points"
    )
    wert = conn.execute(
        "SELECT uci_points FROM rider_season_points WHERE rider_id = 'test-fahrer'"
    ).fetchone()["uci_points"]
pruefe("12,86 Punkte bleiben 12,86", wert, Decimal("12.86"))

print()
if fehler:
    print(f"{fehler} FEHLER.")
    sys.exit(1)
print("Alle Pruefungen bestanden.")
