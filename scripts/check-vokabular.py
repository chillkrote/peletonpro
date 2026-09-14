#!/usr/bin/env python3
"""Prueft, dass die Vokabulare der drei Achsen nur in ihrem eigenen Modul stehen.

Befund 9 war, dass dieselbe Aufzaehlung an mehreren Stellen getippt war:
`category` als Literal in models.py UND in db_races.py UND im Router,
`gender` in sieben Dateien, die Circuits in config.py und im Scheduler. Die
Kopien liefen auseinander - /api/teams?category=pro nahm Werte an, die der
Scraper nie schreibt.

Der Test greift nicht nach Text, sondern parst die Dateien: gesucht werden
(a) Literal[...]-Typen, die einen Wert einer Achse aufzaehlen, und
(b) Tupel/Listen/Mengen, die zwei oder mehr Werte derselben Achse enthalten.
Beides ist eine zweite Quelle fuer ein Vokabular. Kommentare und Docstrings
tauchen im Syntaxbaum nicht als solche Knoten auf und koennen den Test daher
weder ausloesen noch bestehen lassen - anders als eine Textsuche, die beides
verwechselt (und die genau deshalb hier nicht benutzt wird).

Ein einzelner Wert ist erlaubt: der Scraper schreibt fest category="wt", das
ist ein Schreibvorgang und keine Aufzaehlung.
"""
import ast
import pathlib
import sys

WURZEL = pathlib.Path(__file__).resolve().parent.parent
APP = WURZEL / "backend" / "app"

sys.path.insert(0, str(WURZEL / "backend"))
from app.gender import GENDERS  # noqa: E402
from app.taxonomy import CATEGORIES, CIRCUITS  # noqa: E402

# Achse -> (Werte, Modul das sie besitzt). Die Alt-Werte "pro"/"cont" stehen
# mit in der Kategorie-Achse: sie sind totes Vokabular und duerfen in keiner
# Datei mehr als Typ auftauchen, auch nicht in taxonomy.py.
ACHSEN = {
    "category": (frozenset(CATEGORIES), APP / "taxonomy.py"),
    "circuit": (frozenset(CIRCUITS), APP / "taxonomy.py"),
    "gender": (frozenset(GENDERS), APP / "gender.py"),
}
ALTWERTE = frozenset({"pro", "cont"})


def _strings(knoten: ast.AST) -> list[str]:
    return [
        k.value
        for k in ast.walk(knoten)
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    ]


def _ist_literal(knoten: ast.Subscript) -> bool:
    ziel = knoten.value
    name = ziel.attr if isinstance(ziel, ast.Attribute) else getattr(ziel, "id", "")
    return name == "Literal"


def pruefe_datei(pfad: pathlib.Path) -> list[str]:
    baum = ast.parse(pfad.read_text(encoding="utf-8"), filename=str(pfad))
    relativ = pfad.relative_to(WURZEL)
    befunde: list[str] = []
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Subscript) and _ist_literal(knoten):
            werte = set(_strings(knoten.slice))
            for achse, (vokabular, besitzer) in ACHSEN.items():
                treffer = werte & vokabular
                if treffer and pfad != besitzer:
                    befunde.append(
                        f"{relativ}:{knoten.lineno}: Literal mit {achse}-Werten "
                        f"{sorted(treffer)} - gehoert nach "
                        f"{besitzer.relative_to(WURZEL)}"
                    )
            if werte & ALTWERTE:
                befunde.append(
                    f"{relativ}:{knoten.lineno}: Literal mit totem Vokabular "
                    f"{sorted(werte & ALTWERTE)}"
                )
        elif isinstance(knoten, (ast.Tuple, ast.List, ast.Set)):
            werte = _strings(knoten)
            for achse, (vokabular, besitzer) in ACHSEN.items():
                treffer = [w for w in werte if w in vokabular]
                if len(treffer) >= 2 and pfad != besitzer:
                    befunde.append(
                        f"{relativ}:{knoten.lineno}: fest getippte "
                        f"{achse}-Aufzaehlung {treffer} - gehoert nach "
                        f"{besitzer.relative_to(WURZEL)}"
                    )
    return befunde


def main() -> int:
    dateien = sorted(APP.rglob("*.py"))
    assert dateien, f"keine Python-Dateien unter {APP}"
    befunde = [b for pfad in dateien for b in pruefe_datei(pfad)]
    if befunde:
        print(f"FEHLER: {len(befunde)} Vokabular-Kopie(n) in {len(dateien)} Dateien:")
        for b in befunde:
            print(f"  {b}")
        return 1
    print(f"ok: {len(dateien)} Dateien geprueft, kein Vokabular doppelt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
