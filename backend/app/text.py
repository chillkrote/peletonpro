"""Text-Helfer, die mehr als eine Stelle braucht: Normalisierung und slugify.

Wikipedia-Artikel werden von Freiwilligen geschrieben, und dieselbe Angabe
steht je nach Autor mit unterschiedlichen Strichen und Leerzeichen da. Wer
dagegen mit einem engen regulären Ausdruck arbeitet, verliert Zeilen still -
genau das ist bei den Fahrer-Zeiträumen passiert (siehe
scrapers/wikipedia_riders.YEAR_RANGE_RE).
"""
import re

# Alle Striche, die in Zeitraum-Angaben auftreten, auf den einfachen
# Bindestrich normalisieren:
#   U+2010 Bindestrich, U+2011 geschützter Bindestrich,
#   U+2012 Ziffernstrich, U+2013 Halbgeviertstrich (der häufigste Fall),
#   U+2014 Geviertstrich, U+2015 Horizontalstrich, U+2212 Minuszeichen.
_DASHES = "‐‑‒–—―−"
_DASH_RE = re.compile(f"[{_DASHES}]")

# Geschütztes und schmales geschütztes Leerzeichen tauchen um Striche herum
# auf (U+00A0, U+202F) und ebenso als Tausendertrenner.
_SPACE_RE = re.compile("[   ]")


def normalize_dashes(text: str) -> str:
    """Vereinheitlicht Striche und geschützte Leerzeichen.

    Der (inzwischen entfallene) Datums-Parser in wikipedia_races.py machte
    das schon selbst, aber nur für zwei der sieben Strich-Varianten, und
    `wikipedia_riders._parse_year_range` gar nicht - die beiden Parser
    widersprachen sich also. Jetzt eine Stelle für alle.
    """
    return _SPACE_RE.sub(" ", _DASH_RE.sub("-", text))


# ---------------------------------------------------------------------------
# IDs aus Namen
# ---------------------------------------------------------------------------
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Baut aus einem Namen eine ID: Kleinbuchstaben, alles andere zu "-".

    Diese Funktion erzeugt PRIMARY KEYs - rider_id, team_id und (über
    db_races.race_id_for) race_id. Ihr Ergebnis steht damit in der
    Datenbank und in Links. Sie darf sich deshalb nicht verhalten ändern,
    auch nicht "besser": jede Änderung erzeugt für bestehende Zeilen neue
    IDs, und der nächste Upsert legt Dubletten an statt zu aktualisieren.

    Vorher stand derselbe Zweizeiler dreimal im Baum (wikipedia_teams.py,
    wikipedia_riders.py, db_races.py) plus eine vierte, tote Kopie in
    wikipedia_race_history.py. Alle drei lebenden Kopien waren
    zeichengleich - nachgewiesen über die Ausgabe gegen echte Namen, siehe
    backend/README.md, Abschnitt "Eine Stelle für slugify".

    Zur Erinnerung, was die Funktion NICHT tut: Umlaute und Akzente werden
    nicht transliteriert, sondern wie jedes andere Sonderzeichen zu "-".
    "Tobias Müller" wird also zu "tobias-m-ller", nicht "tobias-mueller".
    Das ist unschön, aber es ist der Stand, auf dem die vorhandenen Zeilen
    beruhen. Wer das ändern will, braucht eine Migration, die die alten
    IDs mitnimmt (Befund 7: stabile Fahrer-IDs).
    """
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug or "unknown"
