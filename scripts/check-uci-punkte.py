#!/usr/bin/env python3
"""Prueft die beiden UCI-Punkte-Dateien unter docs/.

    python3 scripts/check-uci-punkte.py

Bewusst KEINE zweite Kopie der Zahlen: ein Test, der die Tabelle noch
einmal enthaelt, prueft nur, ob zweimal derselbe Tippfehler gemacht wurde.
Geprueft werden stattdessen EIGENSCHAFTEN, die aus dem Reglement folgen -
und die ein Uebertragungsfehler mit hoher Wahrscheinlichkeit bricht:

  * kein Platz doppelt, keine Luecke in der Platzfolge
  * Punkte nie negativ oder null, und mit steigendem Platz nie steigend
  * wo die Stufen eine Rangfolge sind (WorldTour, Kontinentalkalender),
    zahlt die hoehere Stufe auf demselben Platz nie weniger als die
    niedrigere - das faengt vertauschte Spalten
  * Maenner- und Frauenskala sind identisch, mit genau einer
    dokumentierten Ausnahme
  * jede WorldTour-Stufe hat Rennen zugeordnet, und jedes Rennen mit
    Etappen-, Trikot- oder Nebenklassement-Punkten hat auch ein
    Gesamtklassement

Die Werte selbst wurden beim Anlegen maschinell gegen den Text der PDF
verglichen (1564 von 1564 Werten, keine Abweichung) - siehe
docs/uci-punkte.md, Abschnitt "Wie die Zahlen geprueft wurden".
"""
import csv
import pathlib
import sys
from collections import defaultdict

WURZEL = pathlib.Path(__file__).resolve().parent.parent
PUNKTE_CSV = WURZEL / "docs" / "uci-punkte-2026.csv"
STUFEN_CSV = WURZEL / "docs" / "uci-punkte-2026-wt-stufen.csv"

# Anlaesse, deren Stufen eine echte Rangfolge bilden (Stufe 1 ist das
# hoeher bewertete Rennen). Bei nat_meisterschaft, kont_meisterschaft und
# wm_olympia sind die Spalten KEINE Rangfolge, sondern verschiedene
# Disziplinen (Strassenrennen, Zeitfahren, U23) - dort gilt die Regel
# nicht, und sie ist im Reglement auch verletzt (WM: U23-Strassenrennen
# Platz 21 gibt 5 Punkte, Elite-Zeitfahren nur 3).
RANGFOLGE = {
    "gc": ["gc1", "gc2", "gc3", "gc4", "gc5"],
    "etappe": ["et1", "et2", "et3", "et4"],
    "nebenklassement": ["nk1", "nk2"],
    "trikot": ["tr1", "tr2", "tr3", "tr4"],
    "kk_gc": ["proseries", "class1", "class2", "class2u"],
    "kk_etappe": ["proseries", "class1", "class2", "class2u"],
    "kk_trikot": ["proseries", "class1", "class2", "class2u"],
}

# Die eine dokumentierte Abweichung zwischen Maennern und Frauen: die
# Frauen-Tabelle "Final results in Continental Calendar Events" hat keine
# Spalte 1.2U/2.2U. Die Etappen- und Trikot-Tabellen der Frauen haben sie.
NUR_MAENNER = {("kk_gc", "class2u")}

# Rennen, die das Reglement in zwei Schreibweisen fuehrt. Solche Faelle
# sind der Grund, warum ein Rennen nicht ueber seinen Namen zugeordnet
# werden darf - siehe docs/uci-punkte.md.
BEKANNTE_NAMENSABWEICHUNGEN = {
    ("w", "Lloyds Tour of Britain"),   # im Gesamtklassement "... Women"
}

fehler = 0


def pruefe(name, ist, soll):
    global fehler
    ok = ist == soll
    if not ok:
        fehler += 1
    print(f"  {name:<62} {'ok' if ok else f'FEHLER (ist {ist!r}, soll {soll!r})'}")


def main() -> int:
    for pfad in (PUNKTE_CSV, STUFEN_CSV):
        if not pfad.exists():
            print(f"FEHLT: {pfad}")
            return 1

    skalen = defaultdict(dict)   # (geschlecht, anlass, stufe) -> {platz: punkte}
    doppelt = []
    for z in csv.DictReader(PUNKTE_CSV.open(encoding="utf-8")):
        key = (z["geschlecht"], z["anlass"], z["stufe"])
        platz = int(z["platz"])
        if platz in skalen[key]:
            doppelt.append((key, platz))
        skalen[key][platz] = int(z["punkte"])

    print("=== 1. Form der Punktetabelle ===")
    pruefe("kein Platz doppelt", doppelt, [])
    pruefe("Geschlechter genau m und w",
           sorted({k[0] for k in skalen}), ["m", "w"])

    luecken = [k for k, v in skalen.items() if sorted(v) != list(range(1, len(v) + 1))]
    pruefe("Platzfolge ohne Luecke, beginnt bei 1", luecken, [])
    pruefe("keine Punktzahl <= 0",
           [(k, p) for k, v in skalen.items() for p, pk in v.items() if pk <= 0], [])
    pruefe("keine Skala tiefer als Platz 60",
           [k for k, v in skalen.items() if len(v) > 60], [])

    nicht_fallend = []
    for k, v in skalen.items():
        for platz in range(1, len(v)):
            if v[platz + 1] > v[platz]:
                nicht_fallend.append((k, platz))
    pruefe("Punkte steigen nie mit dem Platz", nicht_fallend, [])

    print("=== 2. Rangfolge der Stufen ===")
    verstoesse = []
    for anlass, stufen in RANGFOLGE.items():
        for geschlecht in ("m", "w"):
            vorhanden = [s for s in stufen if (geschlecht, anlass, s) in skalen]
            for hoch, tief in zip(vorhanden, vorhanden[1:]):
                oben = skalen[(geschlecht, anlass, hoch)]
                unten = skalen[(geschlecht, anlass, tief)]
                for platz, punkte in unten.items():
                    if oben.get(platz, 0) < punkte:
                        verstoesse.append((geschlecht, anlass, hoch, tief, platz))
    pruefe("hoehere Stufe zahlt nie weniger als niedrigere", verstoesse, [])

    print("=== 3. Maenner- und Frauenskala ===")
    nur_m = sorted((a, s) for (g, a, s) in skalen if g == "m"
                   and ("w", a, s) not in skalen)
    nur_w = sorted((a, s) for (g, a, s) in skalen if g == "w"
                   and ("m", a, s) not in skalen)
    pruefe("Skalen nur bei den Maennern", set(nur_m), NUR_MAENNER)
    pruefe("keine Skala nur bei den Frauen", nur_w, [])
    unterschiedlich = sorted((a, s) for (g, a, s) in skalen if g == "m"
                             and ("w", a, s) in skalen
                             and skalen[("m", a, s)] != skalen[("w", a, s)])
    pruefe("sonst ueberall identische Zahlen", unterschiedlich, [])

    print("=== 4. Zuordnung Rennen -> Stufe ===")
    rennen = defaultdict(set)    # (geschlecht, anlass) -> {stufe}
    nach_stufe = defaultdict(set)
    for z in csv.DictReader(STUFEN_CSV.open(encoding="utf-8")):
        rennen[(z["geschlecht"], z["anlass"])].add(z["rennen"])
        nach_stufe[(z["geschlecht"], z["anlass"], z["stufe"])].add(z["rennen"])

    wt_anlaesse = {"gc", "etappe", "nebenklassement", "trikot"}
    ohne_rennen = sorted(k for k in skalen if k[1] in wt_anlaesse and k not in nach_stufe)
    pruefe("jede WorldTour-Stufe hat Rennen", ohne_rennen, [])
    ohne_skala = sorted(k for k in nach_stufe if k not in skalen)
    pruefe("jede zugeordnete Stufe hat eine Skala", ohne_skala, [])

    # Ein Rennen, das Etappen-, Trikot- oder Nebenklassement-Punkte gibt,
    # muss auch im Gesamtklassement stehen - es ist ein Etappenrennen der
    # WorldTour.
    unbekannt = []
    for geschlecht in ("m", "w"):
        gesamt = rennen[(geschlecht, "gc")]
        for anlass in ("etappe", "trikot", "nebenklassement"):
            for r in rennen[(geschlecht, anlass)]:
                if r not in gesamt and (geschlecht, r) not in BEKANNTE_NAMENSABWEICHUNGEN:
                    unbekannt.append((geschlecht, anlass, r))
    pruefe("Etappen-/Trikot-Rennen haben ein Gesamtklassement", unbekannt, [])

    print()
    if fehler:
        print(f"{fehler} FEHLER.")
        return 1
    print("Alle Pruefungen bestanden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
