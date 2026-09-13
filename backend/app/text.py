"""Text-Normalisierung, die mehrere Scraper brauchen.

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

    `wikipedia_races._parse_date_range` machte das schon selbst, aber nur für
    zwei der sieben Strich-Varianten, und `wikipedia_riders._parse_year_range`
    gar nicht - die beiden Parser widersprachen sich also. Jetzt eine Stelle
    für beide.
    """
    return _SPACE_RE.sub(" ", _DASH_RE.sub("-", text))
