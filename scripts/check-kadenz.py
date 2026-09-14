#!/usr/bin/env python3
"""Prueft den Abruf-Takt der Voll-Aktualisierungs-Jobs (Punkt 2).

    DATABASE_URL=postgresql://... python3 scripts/check-kadenz.py

Geprueft wird:

  1. Der PLAN: welcher Takt in welchem Monat gilt, und dass ein Job ohne
     Plan einen Fehler wirft statt stillschweigend durchzulaufen.
  2. Die FAELLIGKEIT an den Grenzen: kein Lauf vermerkt, knapp davor, genau
     auf der Grenze, danach.
  3. Das TOR gegen eine echte Datenbank - der eigentliche Punkt: zweimal
     denselben Job aufrufen, und beim zweiten Mal darf KEIN Abruf
     stattfinden. Genau das war kaputt (gemessen: 14 Kader-Abrufe an einem
     Tag bei nominell 24 Stunden Intervall).

Die Wikipedia-Abrufe sind ersetzt und gezaehlt - Wikipedia ist aus dieser
Arbeitsumgebung nicht erreichbar, und gezaehlt werden soll ohnehin, OB
abgerufen wird.
"""
import os
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

WURZEL = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL / "backend"))

fehler = 0


def pruefe(titel: str, ist, soll) -> None:
    global fehler
    if ist == soll:
        print(f"  {titel:<58} ok")
    else:
        print(f"  {titel:<58} FEHLER: {ist!r} != {soll!r}")
        fehler += 1


# ---------------------------------------------------------------------------
# 1. Der Plan
# ---------------------------------------------------------------------------
from app.kadenz import (  # noqa: E402
    GRUNDTAKT_TAGE,
    ist_faellig,
    naechster_lauf_in,
    takt_tage,
)

print("=== 1. Der Plan: Takt je Monat ===")
# Kader: die beiden Sprunge im Jahr eng, dazwischen der Grundtakt.
KADER_SOLL = {1: 3, 2: 7, 3: 30, 4: 30, 5: 30, 6: 30,
              7: 30, 8: 7, 9: 7, 10: 30, 11: 30, 12: 30}
ist_plan = {m: takt_tage("refresh_rosters", date(2026, m, 15)) for m in range(1, 13)}
pruefe("Kader-Takt je Monat", ist_plan, KADER_SOLL)
pruefe("Januar am engsten", min(ist_plan.values()), 3)
pruefe("Maerz hat KEINEN eigenen Takt", ist_plan[3], GRUNDTAKT_TAGE)
pruefe("August und September eng (Stagiaires)", (ist_plan[8], ist_plan[9]), (7, 7))
pruefe("Teams: Januar eng, sonst Grundtakt",
       (takt_tage("refresh_teams", date(2026, 1, 5)),
        takt_tage("refresh_teams", date(2026, 6, 5))), (7, GRUNDTAKT_TAGE))

# Ein Job ohne Plan muss auffallen, nicht stillschweigend als "nie faellig"
# oder "immer faellig" durchgehen.
try:
    takt_tage("refresh_news", date(2026, 6, 1))
    pruefe("Job ohne Plan wirft KeyError", "kein Fehler", "KeyError")
except KeyError:
    pruefe("Job ohne Plan wirft KeyError", "KeyError", "KeyError")

print("=== 2. Faelligkeit an den Grenzen ===")
# September: Takt 7 Tage.
jetzt = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
pruefe("kein Lauf vermerkt -> faellig", ist_faellig("refresh_rosters", None, jetzt), True)
pruefe("vor 6 Tagen  -> nicht faellig",
       ist_faellig("refresh_rosters", jetzt - timedelta(days=6), jetzt), False)
pruefe("genau 7 Tage -> faellig",
       ist_faellig("refresh_rosters", jetzt - timedelta(days=7), jetzt), True)
pruefe("vor 8 Tagen  -> faellig",
       ist_faellig("refresh_rosters", jetzt - timedelta(days=8), jetzt), True)
# Der Januar-Sprung: derselbe Abstand, andere Antwort. Maßgeblich ist der
# HEUTIGE Monat, nicht der des letzten Laufs.
jan = datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc)
pruefe("4 Tage her, im Januar -> faellig (Takt 3)",
       ist_faellig("refresh_rosters", jan - timedelta(days=4), jan), True)
pruefe("4 Tage her, im Juni -> nicht faellig (Takt 30)",
       ist_faellig("refresh_rosters", datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
                   datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)), False)
pruefe("Restzeit ohne Lauf ist 0",
       naechster_lauf_in("refresh_rosters", None, jetzt), timedelta(0))
pruefe("Restzeit nach 2 Tagen (Sep, Takt 7)",
       naechster_lauf_in("refresh_rosters", jetzt - timedelta(days=2), jetzt).days, 5)

# ---------------------------------------------------------------------------
# 3. Das Tor gegen eine echte Datenbank
# ---------------------------------------------------------------------------
print("=== 3. Das Tor: zweimal aufrufen, einmal arbeiten ===")

if not os.environ.get("DATABASE_URL"):
    print("  DATABASE_URL fehlt - Teil 3 uebersprungen")
    print()
    print("UNVOLLSTAENDIG: Teil 3 braucht eine Datenbank.")
    sys.exit(1)

from app import db, scheduler  # noqa: E402
from app.migrations import run_migrations  # noqa: E402
from app.models import RosterRider, Team  # noqa: E402

# Schema selbst herstellen, damit der Aufruf aus dem README genuegt (eine
# leere Datenbank und DATABASE_URL). Dass 0007 dabei ueberhaupt anwendbar
# ist, ist die erste Aussage dieses Teils.
run_migrations()

# Die Tabelle selbst: eine Zeile je Job, kein Verlauf. Dass Migration 0007
# nichts Bestehendes anfasst, deckt check-migrations.sh ab (Schritt 3
# migriert eine befuellte Datenbank und vergleicht) - hier nur die Form.
with db._connect() as conn:
    spalten = {
        z["column_name"]: (z["data_type"], z["is_nullable"])
        for z in conn.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'job_runs'"
        ).fetchall()
    }
    pk = conn.execute(
        "SELECT count(*) AS n FROM pg_constraint "
        "WHERE conrelid = 'job_runs'::regclass AND contype = 'p'"
    ).fetchone()["n"]
pruefe("job_runs hat genau zwei Spalten", sorted(spalten), ["job", "last_success"])
pruefe("last_success ist NOT NULL", spalten["last_success"][1], "NO")
pruefe("job ist Primaerschluessel", pk, 1)

abrufe = {"teams": 0, "kader": 0}
kader_faellt_aus = {"an": False}

TEAM = Team(id="uae", name="UAE Team Emirates XRG", category="wt",
            country="AE", code="UAE", gender="m",
            source_url="https://en.wikipedia.org/wiki/UAE")


def falsche_teams():
    abrufe["teams"] += 1
    return [TEAM]


def falscher_kader(team):
    abrufe["kader"] += 1
    if kader_faellt_aus["an"]:
        raise RuntimeError("Wikipedia nicht erreichbar (Test)")
    return [("tadej-pogacar", RosterRider(
        name="Tadej Pogacar", country="SI",
        wiki_url="https://en.wikipedia.org/wiki/P", birth_date=None))]


scheduler.fetch_current_worldteams = falsche_teams
scheduler.roster_riders_for_team = falscher_kader

with db._connect() as conn:
    conn.execute("DELETE FROM job_runs")
    conn.execute("DELETE FROM rider_team_stints")
    conn.execute("DELETE FROM riders")
    conn.execute("DELETE FROM teams")

# --- Teams
scheduler.refresh_teams()
pruefe("erster Team-Lauf ruft ab", abrufe["teams"], 1)
pruefe("Lauf ist vermerkt", db.letzter_joblauf("refresh_teams") is not None, True)
scheduler.refresh_teams()
pruefe("zweiter Team-Lauf ruft NICHT ab", abrufe["teams"], 1)
scheduler.refresh_teams(force=True)
pruefe("force=True ruft trotzdem ab", abrufe["teams"], 2)

# --- Kader
scheduler.refresh_rosters()
pruefe("erster Kader-Lauf ruft ab", abrufe["kader"], 1)
scheduler.refresh_rosters()
pruefe("zweiter Kader-Lauf ruft NICHT ab", abrufe["kader"], 1)
pruefe("Fahrer geschrieben", db.get_rider_count(), 1)

# --- Zeitreise: Vermerk zurueckdatieren, dann ist wieder faellig.
def zurueckdatieren(job: str, tage: int) -> None:
    with db._connect() as conn:
        conn.execute(
            "UPDATE job_runs SET last_success = now() - (%s || ' days')::interval "
            "WHERE job = %s", (tage, job),
        )

zurueckdatieren("refresh_rosters", 31)
scheduler.refresh_rosters()
pruefe("nach 31 Tagen wieder faellig", abrufe["kader"], 2)
zurueckdatieren("refresh_rosters", 2)
scheduler.refresh_rosters()
pruefe("nach 2 Tagen nicht faellig", abrufe["kader"], 2)

# --- Totalausfall: nicht vermerken, damit der naechste Lauf es erneut
# versucht. Sonst waere ein Wikipedia-Ausfall fuer einen ganzen Takt als
# erledigt abgehakt.
with db._connect() as conn:
    conn.execute("DELETE FROM job_runs WHERE job = 'refresh_rosters'")
kader_faellt_aus["an"] = True
scheduler.refresh_rosters()
pruefe("Totalausfall ruft ab", abrufe["kader"], 3)
pruefe("Totalausfall wird NICHT vermerkt",
       db.letzter_joblauf("refresh_rosters"), None)
kader_faellt_aus["an"] = False
scheduler.refresh_rosters()
pruefe("danach wird erneut versucht", abrufe["kader"], 4)
pruefe("und jetzt vermerkt",
       db.letzter_joblauf("refresh_rosters") is not None, True)

print()
if fehler == 0:
    print("Alle Pruefungen bestanden.")
else:
    print(f"{fehler} Pruefung(en) fehlgeschlagen.")
sys.exit(1 if fehler else 0)
