"""Geschlechts-Dimension: Werte und ID-Bildung.

Rennen, Fahrer und Teams tragen seit Migration 0002 ein Feld `gender`
('m'/'w'). Diese Datei hält den erlaubten Wertebereich und die eine Regel,
nach der das Geschlecht in eine ID eingeht.

DIE REGEL UND WARUM SIE SO AUSSIEHT
-----------------------------------
Männer-IDs bleiben unverändert, Frauen-IDs bekommen das Präfix "w--".

Damit ist keine Datenmigration nötig: jede der ~2.000 Renn-Zeilen, 517
Fahrer-Zeilen und 18 Team-Zeilen behält ihren Primärschlüssel, und kein
Fremdschlüssel muss nachgezogen werden. Der Preis ist eine Asymmetrie -
"m" ist implizit. Das ist bewusst gewählt: die Alternative schreibt
Primärschlüssel über fünf Tabellen um, und dafür gibt es (Stand
2026-09-13) kein automatisches Backup dieser Datenbank.

Warum genau zwei Bindestriche und nicht "w-": weil `text.slugify`
Zeichenfolgen zu einem EINZELNEN "-" zusammenzieht und Ränder abschneidet.
Kein Slug enthält also "--", und keiner beginnt oder endet mit "-".
Nachgemessen über 50.000 Zufallsfolgen aus einem Alphabet mit Leerzeichen,
Strichen aller Art, Apostrophen und Satzzeichen: null Verstösse.

Daraus folgt: eine ID mit "--" ist eindeutig eine Frauen-ID, und keine
Bestands-ID kann eine sein. Ein einfaches "w-" wäre NICHT sicher gewesen -
"W Smith" wird zu "w-smith", und das ist ein gültiger Männer-Slug.
"""
from typing import Literal

Gender = Literal["m", "w"]

GENDERS: tuple[str, ...] = ("m", "w")
GENDER_DEFAULT: Gender = "m"

# Siehe Modul-Docstring: slugify erzeugt nie "--".
_FRAUEN_PRAEFIX = "w--"


def gender_prefix(gender: str) -> str:
    """Das ID-Präfix für ein Geschlecht: "" für Männer, "w--" für Frauen."""
    if gender not in GENDERS:
        raise ValueError(f"Unbekanntes Geschlecht: {gender!r} (erlaubt: {GENDERS})")
    return "" if gender == "m" else _FRAUEN_PRAEFIX


def gender_of_id(kennung: str) -> Gender:
    """Liest das Geschlecht aus einer ID zurück.

    Nur für Diagnose und Tests gedacht - im Betrieb steht das Geschlecht in
    der Spalte `gender`, und die ist die Quelle. Diese Funktion belegt, dass
    die ID-Regel umkehrbar ist."""
    return "w" if _FRAUEN_PRAEFIX in kennung else "m"
