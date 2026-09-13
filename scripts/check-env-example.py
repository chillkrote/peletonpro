#!/usr/bin/env python3
"""Gleicht backend/.env.example gegen die im Code gelesenen Umgebungsvariablen ab.

    python3 scripts/check-env-example.py

Meldet drei Dinge und endet mit Code 1, wenn eines davon auftritt:

  FEHLT        eine Variable, die der Code liest, steht nicht in .env.example.
               Folge: sie wird beim Deployen vergessen. Genau so lief der
               Service am 12.09.2026 ohne DATABASE_URL - die App startet dann
               und liefert leere Listen, statt sich zu beschweren.
  ÜBERZÄHLIG   eine Variable steht in .env.example, wird aber nirgends
               gelesen. Folge: jemand setzt sie und wundert sich, dass nichts
               passiert. Entstand nach dem Abbau des alten Renn-Pfades
               (REFRESH_INTERVAL_CALENDAR/-RESULTS).
  ABWEICHUNG   der Wert in .env.example ist nicht der Code-Default und steht
               nicht in ABSICHTLICH_ANDERS. Manche Beispielwerte sollen
               bewusst abweichen (der CORS-Eintrag für GitHub Pages etwa);
               die stehen unten namentlich mit Begründung, statt dass ein
               Kommentar sie stumm entschuldigt.

Die Variablen werden per AST aus dem Quellcode gelesen (os.environ.get,
os.getenv, os.environ[...]), nicht per grep - ein Grep über Klammern und
Punkte geht zu leicht still schief.
"""
import ast
import pathlib
import re
import sys

WURZEL = pathlib.Path(__file__).resolve().parent.parent
APP = WURZEL / "backend" / "app"
BEISPIEL = WURZEL / "backend" / ".env.example"

# Variablen, deren Beispielwert absichtlich nicht der Code-Default ist.
# Namentlich hier, nicht per Kommentar-Heuristik: ein Kommentar, der irgendwo
# das Wort "Default" enthält, würde sonst jede Abweichung stumm durchlassen.
ABSICHTLICH_ANDERS = {
    "CORS_ORIGINS": "Produktionswert - GitHub Pages muss mit drin stehen",
    "BACKUP_KEEP": "Vorschlag für den Cron-Job; Code-Default 0 behält alles",
    "CACHE_DIR": "relativer Pfad auf dasselbe Verzeichnis, das der Default ausrechnet",
    "BACKUP_DIR": "relativer Pfad auf dasselbe Verzeichnis, das der Default ausrechnet",
}


def gelesene_variablen() -> dict[str, tuple[str, str]]:
    """Name -> (Datei, Default-Ausdruck als Text)."""
    treffer: dict[str, tuple[str, str]] = {}
    for pfad in sorted(APP.rglob("*.py")):
        baum = ast.parse(pfad.read_text(encoding="utf-8"))
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Attribute):
                ziel = knoten.func
                ist_environ_get = (
                    ziel.attr == "get"
                    and isinstance(ziel.value, ast.Attribute)
                    and ziel.value.attr == "environ"
                )
                if (ist_environ_get or ziel.attr == "getenv") and knoten.args \
                        and isinstance(knoten.args[0], ast.Constant):
                    name = knoten.args[0].value
                    default = (
                        ast.unparse(knoten.args[1]) if len(knoten.args) > 1
                        else "(ohne Default)"
                    )
                    treffer.setdefault(name, (str(pfad.relative_to(WURZEL)), default))
            if isinstance(knoten, ast.Subscript) and isinstance(knoten.value, ast.Attribute) \
                    and knoten.value.attr == "environ" and isinstance(knoten.slice, ast.Constant):
                treffer.setdefault(
                    knoten.slice.value, (str(pfad.relative_to(WURZEL)), "(Pflicht)")
                )
    return treffer


def beispiel_einlesen() -> tuple[dict[str, str], dict[str, str]]:
    """Liefert (Name -> Wert, Name -> Kommentarblock darüber)."""
    werte: dict[str, str] = {}
    kommentare: dict[str, str] = {}
    block: list[str] = []
    for zeile in BEISPIEL.read_text(encoding="utf-8").splitlines():
        treffer = re.match(r"^#?\s*([A-Z_0-9]+)=(.*)$", zeile)
        if treffer:
            werte[treffer.group(1)] = treffer.group(2).strip()
            kommentare[treffer.group(1)] = "\n".join(block)
            block = []
        elif zeile.startswith("#"):
            block.append(zeile)
        else:
            block = []
    return werte, kommentare


def default_als_text(ausdruck: str) -> str | None:
    """Wertet einfache Default-Ausdrücke aus; None, wenn nicht auswertbar."""
    ausdruck = ausdruck.strip()
    if ausdruck in ("(ohne Default)", "(Pflicht)"):
        return None
    try:
        return str(ast.literal_eval(ausdruck))
    except (ValueError, SyntaxError):
        pass
    treffer = re.fullmatch(r"str\((.+)\)", ausdruck)
    if treffer:
        try:
            return str(eval(treffer.group(1), {"__builtins__": {}}))  # noqa: S307
        except Exception:  # noqa: BLE001
            return None
    return None


def main() -> int:
    gelesen = gelesene_variablen()
    werte, _kommentare = beispiel_einlesen()

    fehlt = sorted(set(gelesen) - set(werte))
    ueberzaehlig = sorted(set(werte) - set(gelesen))
    abweichungen = []
    for name, (_, ausdruck) in sorted(gelesen.items()):
        if name not in werte:
            continue
        default = default_als_text(ausdruck)
        wert = werte[name]
        if default is None or not wert or default == wert:
            continue
        if name in ABSICHTLICH_ANDERS:
            continue
        abweichungen.append((name, default, wert))

    print(f"{len(gelesen)} Variablen im Code, {len(werte)} in backend/.env.example")
    for name in fehlt:
        datei, default = gelesen[name]
        print(f"  FEHLT        {name:32} gelesen in {datei}, Default {default}")
    for name in ueberzaehlig:
        print(f"  ÜBERZÄHLIG   {name:32} wird nirgends gelesen")
    for name, default, wert in abweichungen:
        print(f"  ABWEICHUNG   {name:32} Code={default!r}, Beispiel={wert!r} "
              f"- wenn gewollt, mit Begründung in ABSICHTLICH_ANDERS aufnehmen")

    probleme = len(fehlt) + len(ueberzaehlig) + len(abweichungen)
    print("Abgleich in Ordnung." if probleme == 0 else f"{probleme} Abweichung(en).")
    return 1 if probleme else 0


if __name__ == "__main__":
    sys.exit(main())
