# PelotonPro Backend

FastAPI-Backend, das die Frontend-Seite (`../index.html`) mit aktuellen
Daten versorgt: UCI Teams, Rennkalender, (Live-)Ergebnisse und ein
aggregierter Radsport-Newsfeed.

## Architektur

```
Scheduler (APScheduler, Hintergrund-Thread)
  -> Scraper (Wikipedia-API) / RSS-Aggregator
  -> Cache (In-Memory + JSON-Datei unter data/)
  -> REST-API (FastAPI) --GET--> Frontend (index.html)
```

Die API liest **nie live** von den Quellen, sondern immer aus dem Cache.
Das hält Requests schnell, schont die Zielseiten und sorgt dafür, dass ein
einzelner fehlschlagender Scraping-Lauf nicht die ganze Seite lahmlegt -
es wird einfach der letzte funktionierende Stand weiter ausgeliefert
(inkl. `error`-Feld in der API-Antwort, falls der letzte Versuch
fehlschlug).

## Datenquelle: Wikipedia (statt procyclingstats.com)

Teams und Rennkalender/-ergebnisse kommen von der englischen Wikipedia
(MediaWiki-API, `action=parse`), auf ausdrücklichen Wunsch nach dem unten
dokumentierten procyclingstats.com-Blocking-Problem. Grund für die
Entscheidung, konsequent bei Wikipedia zu bleiben (auch für Ergebnisse,
statt bei Dutzenden unterschiedlich strukturierten Rennveranstalter-
Webseiten): eine einzige, konsistente Tabellenstruktur über alle Seiten
hinweg (`table.wikitable`), keine Blockierung von Cloud-Hosting-IPs, und
Teams/Ergebnisse müssen ohnehin nicht in Echtzeit aktuell sein.

- **`app/scrapers/wikipedia.py`** - gemeinsamer API-Helfer: `fetch_section(page, überschrift_substring)`
  holt zuerst die Abschnitts-Liste einer Seite (`prop=sections`) und dann
  das gerenderte HTML genau des passenden Abschnitts (`prop=text&section=N`).
- **`app/scrapers/wikipedia_teams.py`** - VERIFIZIERT (Stand 2026-09-11).
  Artikel "UCI World Tour", Abschnitt "Current UCI WorldTeams (2026
  season)": eine `<table class="wikitable sortable">` mit Team-Link,
  Land (Flagge+Text) und Season-Spalten. Deckt nur die WorldTeams
  (oberste Stufe, aktuell 18 Teams) ab - **keine ProTeams oder
  Continental Teams**, da Wikipedias UCI-World-Tour-Artikel diese nicht
  auflistet (anders als procyclingstats.com).
- **`app/scrapers/wikipedia_races.py`** - VERIFIZIERT (Stand 2026-09-11).
  - Kalender: Saison-Artikel `"{Jahr} UCI World Tour"`, Abschnitt
    "Events" - eine `<table class="wikitable plainrowheaders">` mit
    Renn-Link+Länderflagge, Datum, Sieger/Zweiter/Dritter.
  - Ergebnisse: der eigene Wikipedia-Artikel jedes Rennens (Link kommt
    direkt aus der Kalendertabelle). Etappenrennen nutzen den Abschnitt
    "General classification" (von Wikipedia selbst schon auf Top 10
    begrenzt), Eintagesrennen den Abschnitt "Result" - beide mit
    derselben Rank/Rider/Team/Time-Tabellenstruktur, nur mit
    unterschiedlicher Rang-Zellenart (`<th scope="row">` bzw. `<td>`).

So testet man die Parser ohne Netzwerkzugriff gegen gespeichertes HTML
(z.B. per Browser-Devtools oder `action=parse&prop=text&section=N`
kopiert):

```python
from app.scrapers.wikipedia_teams import parse_worldteams_section
from app.scrapers.wikipedia_races import parse_calendar_section, parse_result_section

teams = parse_worldteams_section(open("worldteams_section.html", encoding="utf-8").read())
races = parse_calendar_section(open("events_section.html", encoding="utf-8").read(), 2026)
result = parse_result_section(open("result_section.html", encoding="utf-8").read(), "tour-de-france", "Tour de France")
```

Mit echtem Netzwerkzugriff (lokal) direkt gegen die Live-API:

```bash
cd backend
python -m app.scrapers.wikipedia_teams   # sollte Team-Objekte ausgeben
python -m app.scrapers.wikipedia_races   # sollte Race-Objekte ausgeben
```

Falls keine oder falsche Daten erscheinen: Wikipedia-Artikel werden von
Freiwilligen bearbeitet und können sich in Überschrift-Text oder
Tabellenspalten ändern - `fetch_section()` sucht Überschriften per
Teilstring-Match (case-insensitiv), das ist robuster als exakte Section-
Indizes, aber kein Schutz gegen inhaltliche Umbenennungen.

## Scraping-Ethik

- Eigener `User-Agent` mit Kontakt/Repo-Link (`SCRAPER_USER_AGENT` in
  `.env`) - von Wikipedia für automatisierte API-Zugriffe ausdrücklich
  empfohlen.
- Mindestabstand zwischen Requests an dieselbe Quelle
  (`SCRAPER_REQUEST_DELAY_SECONDS`, Default 2s), auch gegenüber der
  Wikipedia-API.
- Aggressives Caching: Teams/Kalender werden nur 1x täglich neu geholt,
  Ergebnisse 1x pro Stunde für alle bereits gestarteten Saison-Rennen
  (kein "nur während des Rennens"-Fenster mehr, siehe
  `scheduler.refresh_results` - Wikipedia-Endstände bleiben nach
  Rennende dauerhaft im Artikel stehen, ein Live-Ticker wäre hier ohnehin
  nicht sinnvoll, da Wikipedia nicht in Echtzeit editiert wird).

### Historie: procyclingstats.com blockiert Cloud-Hosting (Stand 2026-09-11)

Im echten Deployment auf Render.com liefert procyclingstats.com auf **jeden**
Request (`/teams/worldtour`, `/teams/continental`, `/races.php`) durchgehend
`403 Forbidden` - unabhängig vom `User-Agent` (getestet mit dem
transparenten Bot-UA und mit einem vollständigen Chrome-UA, beides ohne
Erfolg). Das deutet auf eine IP-basierte Blockierung von
Cloud-/Hosting-Adressbereichen oder eine TLS-/JS-basierte Bot-Erkennung
hin, die ein einfacher HTTP-Client grundsätzlich nicht umgehen kann.

Es wurde bewusst **keine weitere Umgehung versucht** (kein Proxy-Rotieren,
kein Headless-Browser-Stealth, kein TLS-Fingerprint-Spoofing) - das wäre
ein Versuch, den Bot-Schutz der Seite gegen ihren erklärten Willen zu
umgehen, nicht nur ein Konfigurationsproblem zu beheben. Der Newsfeed
(Cyclingnews + Google News RSS) ist davon nicht betroffen und funktioniert
im Live-Deployment fehlerfrei (150 Einträge beim ersten Test).

Die Entscheidung fiel auf Option 1 (alternative Datenquelle) - siehe
"Datenquelle: Wikipedia" oben. Die `pcs_teams.py`/`pcs_races.py`-Scraper
aus diesem Abschnitt wurden entfernt, da sie ungenutzt und dauerhaft
blockiert waren.

### uci.org als Alternative geprüft (Stand 2026-09-11) - nicht per einfachem HTTP-Scraping nutzbar

Auf expliziten Wunsch wurde geprüft, ob `uci.org` (offizielle UCI-Seite) als
Datenquelle für Teams taugt. Ergebnis, verifiziert über eine temporäre
Diagnose-Route im Live-Deployment (per Render-Logs ausgewertet, danach
wieder entfernt):

- `https://www.uci.org/road/teams` ist von Render aus erreichbar (Status
  200, kein IP-Block wie bei procyclingstats.com).
- Die Seite ist aber eine **client-seitig gerenderte Single-Page-App**:
  Das Server-HTML enthält nur ein Navigations-Grundgerüst, einen
  Google-Tag-Manager-Block und einen großen `webSettings`-JS-Konfigurationsblock
  (i18n-Strings für Kalender/Rankings/Team-Details usw.), aber keine
  einzige echte Team- oder Fahrer-Bezeichnung im HTML.
- Es gibt genau ein gebündeltes Skript (`/assets/<version>/main.js`), keine
  im Quelltext sichtbaren `/api/`- oder GraphQL-Endpunkte, und die
  Navigations-Links nutzen 22-stellige Hash-IDs (z.B.
  `/for-uci-teams/1XCm9CiRz9q5DHMCXOYCyN`) - typisch für eine Headless-CMS-
  Anbindung (z.B. Contentful), deren Daten erst nach Ausführung des
  JavaScript-Bundles im Browser nachgeladen werden.
- Die Seite läuft zusätzlich hinter Cloudflare (`cdn-cgi/scripts/...`).

Ein einfacher HTTP-Client (wie unser `httpx`-basierter Scraper) bekommt hier
also grundsätzlich keine Team-Daten zu sehen, unabhängig von Blocking -
es fehlt schlicht am Rendern. Das würde einen Headless-Browser (z.B.
Playwright) im Backend erfordern, was auf Renders kostenlosem Plan wegen
RAM-/Zeitlimits kaum praktikabel ist und zusätzlich an Cloudflares
Bot-Erkennung scheitern könnte. uci.org wird daher **nicht** als
Datenquelle verwendet - stattdessen wird Wikipedia genutzt, siehe
"Datenquelle: Wikipedia" oben.

## Fahrer-Datenbank (Teams <-> Fahrer, Team-Wechsel-Historie)

Zusätzlich zum flüchtigen JSON-Cache gibt es eine **persistente Postgres-
Datenbank** (`app/db.py`) für Fahrer und deren Team-Zugehörigkeit über die
Jahre. Grund für die echte Persistenz (anders als bei Teams/Rennen/News):
ein vollständiger Rebuild aller ~500 Fahrer-Historien (ein
Wikipedia-Abruf pro Fahrer, respektvoll ratenlimitiert) dauert 15-20
Minuten - das soll nicht nach jedem Render-Neustart (Deploy, Aufwachen aus
dem Schlafmodus) erneut passieren, wie es beim flüchtigen Cache der Fall
wäre.

- **`app/scrapers/wikipedia_riders.py`** - VERIFIZIERT (Stand 2026-09-12).
  - Kader: Team-Wikipedia-Seite, Abschnitt mit "roster" im Namen (i.d.R.
    "Team roster") - ein oder zwei nebeneinander stehende Tabellen. Statt
    uns auf Spalten-/Colspan-Zählung zu verlassen (variiert leicht
    zwischen Teams), wird pro Zeile der erste Fahrer-Link mit Text sowie
    das Geburtsdatum über die hCard-Klasse `span.bday` gesucht.
  - Historie: Infobox im Lead-Abschnitt (`section=0`, wird von
    `prop=sections` nicht mitgezählt, daher ein eigener
    `fetch_lead_section()`-Helfer statt `fetch_section()`) jedes
    Fahrer-Artikels. Block "Professional teams" mit einer Zeile pro
    Zeitraum (z.B. "2017–2018" -> "Rog–Ljubljana", "2019–" -> aktuelles,
    noch laufendes Team). Separates Feld "Current team" liefert zusätzlich
    den Link auf die aktuelle Team-Seite.
- **`app/db.py`** - Schema (`teams`, `riders`, `rider_team_stints`) +
  Zugriffsfunktionen. `is_configured()` prüft, ob `DATABASE_URL` gesetzt
  ist; ohne sie bleiben `/api/riders*` leer/deaktiviert, der Rest der App
  läuft unverändert weiter.
- **`scheduler.refresh_riders`** - läuft alle `REFRESH_INTERVAL_RIDERS`
  Sekunden (Default 3 Min): aktualisiert zuerst die Kader aller aktuellen
  Teams (schnell, ein Abruf pro Team), holt danach die volle Historie für
  bis zu `RIDER_HISTORY_BATCH_SIZE` Fahrer (Default 30), die noch keine
  haben (`history_fetched_at IS NULL`) - verteilt die ~500 nötigen Abrufe
  also über mehrere Läufe statt eines einzigen ~20-minütigen Blocks. Ist
  die Datenbank einmal vollständig befüllt, wird jeder Lauf günstig (kein
  Rückstand mehr), das kurze Intervall schadet dann nicht mehr.
- Ein Fahrer, der ein Team verlässt (Karriereende, Wechsel ohne dass das
  neue Team schon im aktuellen Kader-Scrape auftaucht), behält bis zum
  nächsten erfolgreichen Kader-Abgleich sein zuletzt bekanntes
  `current_team_id` - kein Cross-Check über alle Teams hinweg, um
  fälschlich "verwaiste" Fahrer zu erkennen. Bekannte Einschränkung,
  aktuell nicht behoben.

**Render-Postgres-Free-Tier-Hinweis:** die kostenlose Datenbank läuft nach
30 Tagen ab (`expiresAt` bei Erstellung) und wird dann von Render gelöscht,
sofern sie nicht vorher auf einen bezahlten Plan angehoben wird. Rechtzeitig
vor Ablauf upgraden oder die Datenbank neu erstellen (Daten gehen dabei
verloren, bauen sich aber automatisch binnen ~20 Minuten wieder auf).

So testet man die Parser ohne Netzwerkzugriff gegen gespeichertes HTML:

```python
from app.scrapers.wikipedia_riders import parse_team_roster, parse_rider_history

roster = parse_team_roster(open("roster_section.html", encoding="utf-8").read())
history = parse_rider_history(open("rider_infobox.html", encoding="utf-8").read())
```

## Lokal starten

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # ggf. anpassen
uvicorn app.main:app --reload --port 8001
```

API läuft dann unter `http://localhost:8001`, z.B.
`http://localhost:8001/api/teams`.

## Deployment auf Render.com

1. Repo mit Render verbinden, `backend/render.yaml` wird automatisch
   erkannt (Blueprint).
2. `CORS_ORIGINS` in den Render-Umgebungsvariablen auf die tatsächliche
   GitHub-Pages-URL setzen.
3. **Free-Tier-Einschränkung:** Render setzt kostenlose Web Services nach
   ~15 Minuten Inaktivität in den Schlafmodus - der Hintergrund-Scheduler
   pausiert dann ebenfalls, bis der nächste Request den Service aufweckt.
   Für einen wirklich durchgängig aktuellen Newsfeed/Live-Ticker ist
   mittelfristig ein kostenpflichtiger "Always On"-Plan nötig.
4. Kein persistentes Disk-Volume im Free-Tier - der JSON-Cache geht bei
   jedem Neustart/Deploy verloren. Unkritisch, da der Scheduler beim Start
   sofort neu scraped (dauert wenige Sekunden bis Minuten, je nach Anzahl
   Requests).
5. **Python-Version ist auf 3.11 gepinnt** (`backend/.python-version`).
   Ohne diese Datei wählt Render standardmäßig die neueste Python-Version
   (aktuell 3.14), für die es noch kein vorgebautes Wheel für
   `pydantic-core==2.23.4` gibt - pip versucht dann, es aus Rust-Quellcode
   zu bauen, was in Renders Build-Sandbox an einem read-only
   Cargo-Cache-Verzeichnis scheitert (`Build failed`). Bei einem Upgrade
   von FastAPI/Pydantic kann die gepinnte Version ggf. wieder angehoben
   werden, sobald aktuelle Wheels verfügbar sind.

## API-Endpunkte

| Endpunkt | Beschreibung |
|---|---|
| `GET /api/teams?category=wt\|pro\|cont` | Alle Teams, optional gefiltert |
| `GET /api/races` | Rennkalender (Saison) |
| `GET /api/calendar` | Kalenderansicht (ein Eintrag pro Rennstart) |
| `GET /api/results?status=live\|finished\|upcoming` | (Live-)Ergebnisse |
| `GET /api/news?limit=30` | Aggregierter Newsfeed |
| `GET /api/riders?team=<team_id>` | Fahrer, optional nach aktuellem Team gefiltert |
| `GET /api/riders/{id}` | Ein Fahrer inkl. `history` (Team-Wechsel-Liste) |
| `GET /api/health` | Health-Check |

Da die Teams-Quelle (Wikipedia) nur WorldTeams abdeckt, liefert
`category=pro` und `category=cont` aktuell immer eine leere Liste.

Die `/api/riders*`-Endpunkte liefern `{"riders": [], "error": "..."}` bzw.
HTTP 503, solange `DATABASE_URL` nicht gesetzt ist (siehe "Fahrer-
Datenbank" oben) - kein `last_updated`, da sie nicht über den Cache-
Mechanismus laufen.

Jede Antwort enthält zusätzlich `last_updated` (ISO-Timestamp des letzten
erfolgreichen Scraping-Laufs) und `error` (Fehlermeldung des letzten
Versuchs, `null` falls erfolgreich).
