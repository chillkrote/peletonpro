#!/usr/bin/env python3
"""Ruft jeden API-Endpunkt ab und schreibt Status + Rumpf als JSON.

Zweck: zwei Code-Stände gegen dieselben Daten vergleichen. Erst der Diff
zeigt, ob eine Umstrukturierung die Antworten verändert hat - und wenn ja,
muss jede Abweichung erklärbar sein.

    DATABASE_URL=postgresql://... python3 scripts/api-snapshot.py raus.json

Läuft in-process über FastAPIs TestClient, nicht über einen Port: kein
Warten auf den Start, kein Proxy dazwischen, und ein Fehler beim Import
fällt als Traceback auf statt als Verbindungsfehler.

Zeitstempel (`last_updated`, `fetched_at`, ...) werden ersetzt, weil sie
zwischen zwei Läufen zwangsläufig abweichen - der erste Versuch dieses
Vergleichs meldete deshalb Unterschiede, die keine waren.
"""
import json
import pathlib
import re
import sys

WURZEL = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL / "backend"))

FLUECHTIG = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
FLUECHTIGE_FELDER = {"last_updated", "fetched_at", "updated_at", "generated_at"}

# In CSV-Rümpfen stehen die Zeitstempel nicht als Feld, sondern mitten in der
# Zeile - ohne diese Ersetzung meldete der Vergleich drei Exporte als
# verändert, obwohl nur die von der Datenbank gesetzten `now()`-Werte der
# beiden Testdatenbanken um Millisekunden auseinanderlagen. Nur
# Sekundenbruchteile und Zeitzone werden mitgenommen, damit ein echtes Datum
# aus den Daten (start_date, birth_date) erhalten bleibt.
FLUECHTIG_IM_TEXT = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?"
)


def _entfluechtigen(wert):
    if isinstance(wert, dict):
        return {
            k: ("<zeitstempel>" if k in FLUECHTIGE_FELDER and v else _entfluechtigen(v))
            for k, v in wert.items()
        }
    if isinstance(wert, list):
        return [_entfluechtigen(v) for v in wert]
    if isinstance(wert, str) and FLUECHTIG.match(wert):
        return "<zeitstempel>"
    return wert


def abfragen() -> list[str]:
    """Die abgefragten Pfade - Vollständigkeit ist hier der Punkt, deshalb
    stehen auch die 404/422-Fälle mit drin."""
    pfade = [
        "/api/health",
        "/api/news",
        "/api/teams",
        "/api/teams?category=wt",
        "/api/teams?category=pro",
        "/api/teams?gender=m",
        "/api/teams?gender=w",
        "/api/teams?gender=x",
        "/api/teams/uae",
        "/api/teams/gibtsnicht",
        "/api/teams/uae/stats",
        "/api/teams/uae/stats?season=2026",
        "/api/teams/uae/stats?season=1800",
        "/api/riders",
        "/api/riders?team=uae",
        "/api/riders?gender=w",
        "/api/riders?limit=1",
        "/api/riders?limit=0",
        "/api/riders?offset=-1",
        "/api/riders/gibtsnicht",
        "/api/riders/tadej-pogacar/results",
        "/api/riders/tadej-pogacar/results?limit=2",
        "/api/riders/tadej-pogacar/results?limit=2&offset=2",
        "/api/riders/tadej-pogacar/results?limit=0",
        "/api/riders/tadej-pogacar/results?limit=201",
        "/api/riders/gibtsnicht/results",
        "/api/race-history",
        "/api/race-history?season=2026",
        "/api/race-history?category=wt",
        "/api/race-history?category=proseries",
        "/api/race-history?category=continental",
        "/api/race-history?category=cont",
        "/api/race-history?category=continental&circuit=europe",
        "/api/race-history?circuit=mars",
        "/api/race-history?gender=w",
        "/api/race-history?limit=1&offset=1",
        "/api/race-history/seasons",
        "/api/race-history/seasons?gender=w",
        "/api/race-history/2026-wt-tdf",
        "/api/race-history/gibtsnicht",
        "/api/export/teams.csv",
        "/api/export/riders.csv",
        "/api/export/rider_team_stints.csv",
        "/api/export/rider_season_points.csv",
        "/api/export/races.csv",
        "/api/export/race_stages.csv",
        "/api/export/race_results.csv",
        "/openapi.json",
    ]
    return pfade


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    ziel = pathlib.Path(sys.argv[1])

    from fastapi.testclient import TestClient

    from app.main import app

    ergebnis: dict[str, dict] = {}
    with TestClient(app) as client:
        for pfad in abfragen():
            antwort = client.get(pfad)
            rumpf: object
            if antwort.headers.get("content-type", "").startswith("application/json"):
                try:
                    rumpf = _entfluechtigen(antwort.json())
                except ValueError:
                    rumpf = antwort.text
            else:
                rumpf = FLUECHTIG_IM_TEXT.sub("<zeitstempel>", antwort.text)
            ergebnis[pfad] = {"status": antwort.status_code, "rumpf": rumpf}

    ziel.write_text(json.dumps(ergebnis, indent=1, sort_keys=True, ensure_ascii=False))
    codes: dict[int, int] = {}
    for eintrag in ergebnis.values():
        codes[eintrag["status"]] = codes.get(eintrag["status"], 0) + 1
    print(f"{len(ergebnis)} Abfragen -> {ziel}")
    print("  " + ", ".join(f"{c}x HTTP {s}" for s, c in sorted(codes.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
