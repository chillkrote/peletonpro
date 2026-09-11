# PelotonPro Backend

FastAPI-Backend, das die Frontend-Seite (`../index.html`) mit aktuellen
Daten versorgt: UCI Teams, Rennkalender, (Live-)Ergebnisse und ein
aggregierter Radsport-Newsfeed.

## Architektur

```
Scheduler (APScheduler, Hintergrund-Thread)
  -> Scraper (procyclingstats.com) / RSS-Aggregator
  -> Cache (In-Memory + JSON-Datei unter data/)
  -> REST-API (FastAPI) --GET--> Frontend (index.html)
```

Die API liest **nie live** von den Quellen, sondern immer aus dem Cache.
Das hält Requests schnell, schont die Zielseiten und sorgt dafür, dass ein
einzelner fehlschlagender Scraping-Lauf nicht die ganze Seite lahmlegt -
es wird einfach der letzte funktionierende Stand weiter ausgeliefert
(inkl. `error`-Feld in der API-Antwort, falls der letzte Versuch
fehlschlug).

## Status der Scraper-Selektoren

Diese Entwicklungsumgebung hat keinen Netzwerkzugriff auf
procyclingstats.com (vom Sandbox-Proxy blockiert). Verifizierung erfolgte
daher, wo möglich, gegen von echten Seitenaufrufen kopiertes HTML:

- **`app/scrapers/pcs_teams.py` - VERIFIZIERT** (2026-09-11) gegen echtes
  HTML von `/teams/worldtour` (WorldTeams + ProTeams). Die Struktur ist
  KEINE Tabelle, sondern `<h4>`-Überschriften gefolgt von
  `<ul class="list">`-Listen; die Kategorie ergibt sich aus dem
  Überschriften-Text ("UCI WorldTeams" / "UCI ProTeams"). Die
  Continental-Teams-Seite (`/teams/continental`) wird mit der gleichen
  Logik geparst, ist aber selbst NICHT gegen echtes HTML verifiziert -
  falls dort keine Teams ankommen, prüfen, ob die Seite eine abweichende
  Struktur hat.
- **`app/scrapers/pcs_races.py` - UNVERIFIZIERT.** Selektoren basieren
  weiterhin auf einer (unbestätigten) tabellenbasierten Annahme.

So testet man die Parser ohne Netzwerkzugriff gegen gespeichertes HTML
(z.B. per Browser-Devtools kopiert):

```python
from app.scrapers.pcs_teams import parse_teams_page
teams = parse_teams_page(open("sample.html", encoding="utf-8").read())
```

Mit echtem Netzwerkzugriff (lokal) direkt gegen die Live-Seite:

```bash
cd backend
python -m app.scrapers.pcs_teams   # sollte Team-Objekte ausgeben
python -m app.scrapers.pcs_races   # sollte Race-Objekte ausgeben
```

Falls keine oder falsche Daten erscheinen: Die Selektor-Konstanten am
Anfang der jeweiligen Datei (z.B. `SECTION_HEADING_SELECTOR`,
`TEAM_LINK_SELECTOR`, `RACE_ROW_SELECTOR`) an die tatsächliche
Seitenstruktur anpassen (Browser-Devtools -> Element inspizieren -> CSS-
Selektor ablesen).

## Scraping-Ethik

- Eigener `User-Agent` mit Kontakt/Repo-Link (`SCRAPER_USER_AGENT` in
  `.env`), damit der Seitenbetreiber den Bot einordnen kann.
- Mindestabstand zwischen Requests an dieselbe Quelle
  (`SCRAPER_REQUEST_DELAY_SECONDS`, Default 2s).
- Aggressives Caching: Teams/Kalender werden nur 1x täglich neu geholt,
  Ergebnisse nur für Rennen, die laut Kalender aktuell laufen.
- **Vor dem Live-Betrieb unbedingt selbst die aktuellen Nutzungsbedingungen
  und `robots.txt` von procyclingstats.com prüfen** - das haben wir aus
  dieser Umgebung heraus nicht verifizieren können, und die rechtliche
  Verantwortung dafür liegt beim Betreiber dieser Seite, nicht bei diesem
  Code.

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

## API-Endpunkte

| Endpunkt | Beschreibung |
|---|---|
| `GET /api/teams?category=wt\|pro\|cont` | Alle Teams, optional gefiltert |
| `GET /api/races` | Rennkalender (Saison) |
| `GET /api/calendar` | Kalenderansicht (ein Eintrag pro Rennstart) |
| `GET /api/results?status=live\|finished\|upcoming` | (Live-)Ergebnisse |
| `GET /api/news?limit=30` | Aggregierter Newsfeed |
| `GET /api/health` | Health-Check |

Jede Antwort enthält zusätzlich `last_updated` (ISO-Timestamp des letzten
erfolgreichen Scraping-Laufs) und `error` (Fehlermeldung des letzten
Versuchs, `null` falls erfolgreich).
