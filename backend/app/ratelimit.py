"""Rate Limiting für die öffentliche API.

Die API hat keine Authentifizierung, läuft auf einer einzigen Free-Instanz
und hat teure Endpunkte: `/api/race-history/{id}` löst mehrere Abfragen aus,
die CSV-Exporte lesen ganze Tabellen. Ein einzelner Skript-Loop genügte, um
den Service und das knappe Verbindungskontingent der Datenbank lahmzulegen -
und mit wachsendem Bestand wird das wichtiger, nicht unwichtiger.

Die Grenzen sind an echten Seitenaufrufen bemessen, nicht geraten:

    index.html   4 Requests (Teams, Rennen, News, Fahrer)
    teams.html   1, plus 2 beim Wechsel auf den Fahrer-Tab
    team.html    4 (Teams, Rennen, Ergebnisse, Kader)
    rider.html   2 (Fahrer, Teams)
    races.html   2 (Saisons, eine Saison), plus 1 pro aufgeklapptem Rennen
    news.html    1

Ein Besucher, der zügig durch alle Seiten klickt und ein Dutzend Rennen
aufklappt, kommt damit auf 30-40 Requests in wenigen Minuten. Der Default
von 120/Minute lässt das bequem zu und stoppt einen Loop trotzdem früh.
Alle Werte per Env-Var überschreibbar.
"""
import logging
import os

from fastapi import Request
from slowapi import Limiter

logger = logging.getLogger(__name__)

# Grenzen im slowapi-Format ("<Anzahl>/<Zeitraum>").
RATE_LIMIT_DEFAULT = os.environ.get("RATE_LIMIT_DEFAULT", "120/minute")
# Detailansicht eines Rennens: mehrere Abfragen pro Aufruf. Wer Rennen
# aufklappt, schafft realistisch keine 60 pro Minute.
RATE_LIMIT_RACE_DETAIL = os.environ.get("RATE_LIMIT_RACE_DETAIL", "60/minute")
# Team-Saison-Statistik: drei Abfragen pro Aufruf, davon zwei Aggregationen
# über race_results. Dieselbe Größenordnung wie die Renn-Detailansicht.
RATE_LIMIT_TEAM_STATS = os.environ.get("RATE_LIMIT_TEAM_STATS", "60/minute")
# CSV-Export: liest ganze Tabellen. Ein Mensch braucht das ein paar Mal am
# Tag, nicht ein paar Mal pro Minute.
RATE_LIMIT_EXPORT = os.environ.get("RATE_LIMIT_EXPORT", "10/hour")

# Anzahl vertrauenswürdiger Proxies vor der Anwendung. Auf Render ist das
# genau einer (der Router des Anbieters).
TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "1"))


def client_key(request: Request) -> str:
    """Schlüssel für die Drosselung: die echte Client-IP.

    Hinter Renders Router ist `request.client.host` die Adresse des Proxys -
    ohne Korrektur landen damit ALLE Besucher in einem gemeinsamen Kontingent
    und blockieren sich gegenseitig.

    Die echte Adresse steht in `X-Forwarded-For`. Wichtig ist, von welchem
    Ende gelesen wird: der Header ist eine Kette, und ein Client kann einen
    eigenen Wert mitschicken. Der Proxy HÄNGT die tatsächliche Adresse
    hinten AN - der erste Eintrag ist also client-kontrolliert und wäre
    fälschbar (ein Angreifer bekäme pro Request ein frisches Kontingent),
    der letzte kommt vom Proxy und ist vertrauenswürdig.

    Gelesen wird deshalb TRUSTED_PROXY_COUNT Einträge vom Ende her.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if chain:
            index = max(0, len(chain) - TRUSTED_PROXY_COUNT)
            return chain[index]
    if request.client is not None:
        return request.client.host
    return "unbekannt"


# Eine Instanz für die ganze Anwendung. Sie liegt hier und nicht in main.py,
# damit auch die Router sie importieren können, ohne einen Zirkelbezug auf
# main.py zu erzeugen.
limiter = Limiter(
    key_func=client_key,
    default_limits=[RATE_LIMIT_DEFAULT],
    # headers_enabled ist nötig, damit slowapi überhaupt Header setzt -
    # retry_after allein genügt nicht (nachgemessen: Retry-After blieb
    # leer). Mit beidem kommen Retry-After sowie X-RateLimit-Limit,
    # -Remaining und -Reset, sodass ein Client weiß, wann er wieder darf.
    headers_enabled=True,
    retry_after="delta-seconds",
)
