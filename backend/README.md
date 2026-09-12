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

### Vor-/Nachname, Saison-Team-Links, Strava-Profile (Stand 2026-09-12)

- **Namenstrennung:** `riders.first_name`/`riders.last_name` werden beim
  Kader-Scraping mit `wikipedia_riders.split_name()` aus dem vollen Namen
  abgeleitet. Nachname = letztes Wort plus vorangehende bekannte
  Namenspartikel (`van`, `der`, `von`, `de`, `la`, ... - siehe
  `NAME_PARTICLES`), damit z.B. "Mathieu van der Poel" korrekt als Vorname
  "Mathieu" / Nachname "van der Poel" gesplittet wird. Kein Wörterbuch
  aller Sprachen - Einzelfälle mit unüblichen Namensformen können falsch
  getrennt werden. **Standard-Sortierung ist jetzt nach Nachname**
  (`ORDER BY last_name, first_name`) statt nach vollem Namen, sowohl in
  `GET /api/riders` als auch im CSV-Export.
- **Team-Link pro Saison:** `GET /api/riders/{id}` liefert zusätzlich zu
  `history` (den rohen Zeiträumen aus der Wikipedia-Infobox) ein Feld
  `seasons` - eine Zeile pro Kalenderjahr, das der Fahrer laut Historie bei
  einem **aktuell bekannten WorldTour-Team** (also einem Team aus unserer
  `teams`-Tabelle) verbracht hat, jeweils mit Link auf die Team-Wikipedia-
  Seite (`db.get_rider_seasons`, CSV-Äquivalent `export_seasons` /
  `GET /api/export/seasons.csv`). Zeiträume bei Teams, die nicht in
  `teams` stehen (typischerweise Continental-/ProConti-Stationen aus der
  Nachwuchszeit), zählen bewusst NICHT als World-Tour-Saison. Ein offenes
  Ende ("2019–", aktuelles Team) läuft bis `RACE_SEASON_YEAR`.
- **Strava-Profile:** `riders.strava_url` wird von
  `scrapers/wikidata.py` befüllt, im selben `refresh_riders`-Job wie die
  Team-Historie, gebatcht über `STRAVA_BATCH_SIZE` Fahrer pro Lauf
  (`strava_checked_at IS NULL`). Statt einer Ad-hoc-Websuche pro Fahrer
  (skaliert nicht für ~500 Fahrer und ist nicht Teil dieser
  Scraping-Architektur) wird die öffentliche, strukturierte
  Wikidata-Property
  [P5283 "Strava ID of a professional sport person"](https://www.wikidata.org/wiki/Property:P5283)
  genutzt: Wikipedia-Titel -> Wikidata-QID (`action=query&prop=pageprops`)
  -> Strava-Athleten-ID (`action=wbgetentities`), beides gebatcht (bis zu
  50 pro Request). Nur ein Bruchteil der Fahrer hat diese Property
  gepflegt - fehlende Treffer sind normal, kein Fehler. Der Check läuft
  pro Fahrer nur einmal (wie bei der Historie), nicht periodisch erneut -
  ein nachträglich angelegtes Strava-Profil wird also nicht automatisch
  nachgetragen.

### Bekannte Lücke: UCI-Ranking-Punkte pro Saison (Platzhalter, Stand 2026-09-12)

UCI-Ranking-Punkte pro Fahrer und Saison lassen sich **nicht automatisiert
scrapen** - Recherche ergab keine zuverlässige, in großem Umfang
abrufbare Quelle dafür:

- Wikipedia-Fahrerartikel (Infobox `Template:Infobox cyclist`) haben kein
  Feld für UCI-Punkte pro Saison - nur Team-Saison-Seiten
  (`Template:Infobox cycling team season`) zeigen ein Team-Gesamtranking,
  keine Einzelfahrer-Punkte.
- procyclingstats.com führt diese Daten (`/rankings/me/uci-season-individual`),
  blockiert aber Cloud-Hosting-IP-Bereiche wie Render (siehe oben,
  "Historie: procyclingstats.com blockiert Cloud-Hosting").
- uci.org selbst ist eine clientseitig gerenderte SPA ohne per HTTP
  scrapbare Rankings (siehe oben, "uci.org als Alternative geprüft").

Da die Werte später aus einer anderen Datenbank nachgetragen werden
sollen, legt `db.ensure_season_point_placeholders()` (läuft in jedem
`refresh_riders`-Zyklus) für **jede** WorldTour-Saison eines Fahrers eine
feste Platzhalter-Zeile in der neuen Tabelle `rider_season_points`
(`rider_id`, `year`, `uci_points` - `uci_points` initial `NULL`) an,
per SQL aus den vorhandenen `rider_team_stints` abgeleitet
(`generate_series` über `start_year`..`COALESCE(end_year, RACE_SEASON_YEAR)`,
nur für Stints mit bekanntem `team_id`). So hat ein künftiger Import ein
verlässliches `(rider_id, year)`-Ziel für ein `UPDATE ... SET uci_points = ...`,
ohne selbst ermitteln zu müssen, welche Kombinationen überhaupt existieren.
Bereits importierte Werte werden nie überschrieben (`ON CONFLICT DO
NOTHING` beim Anlegen der Platzhalter), und mit fortschreitender Saison
(`RACE_SEASON_YEAR` steigt) legt derselbe Job automatisch neue
Platzhalter für laufende Team-Zugehörigkeiten an. `uci_points` erscheint
sowohl in `GET /api/riders/{id}` (`seasons[].uci_points`) als auch in
`GET /api/export/seasons.csv` - aktuell überall `null`/leer, bis der
externe Import läuft.

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

### CSV-Export

`app/routers/export.py` liefert die Tabellen roh als CSV-Download (z.B.
für Excel/Pandas, unabhängig von der JSON-API):

| Endpunkt | Inhalt |
|---|---|
| `GET /api/export/teams.csv` | komplette `teams`-Tabelle |
| `GET /api/export/riders.csv` | `riders` (inkl. `first_name`/`last_name`/`strava_url`) + aufgelöster `current_team_name`, sortiert nach Nachname |
| `GET /api/export/stints.csv` | `rider_team_stints` + aufgelöste `rider_name`/`team_wiki_url` (Zeiträume, nicht pro Saison) |
| `GET /api/export/seasons.csv` | eine Zeile pro Fahrer und Kalenderjahr bei einem WorldTour-Team (aus den Stints abgeleitet, siehe oben) |

Wie `/api/riders*` liefert auch `/api/export/*` HTTP 503, solange
`DATABASE_URL` nicht gesetzt ist.

## Renn-Historie (WorldTour/ProSeries/Continental Touren seit 2020, Stand 2026-09-12)

Zweite, fachlich eigenständige Datenbank in derselben Postgres-Instanz
(`app/db_races.py`, Schema separat von `app/db.py`) mit jedem UCI-WorldTour-,
ProSeries- und Continental-Tour-Rennen (Africa/Asia/Europe/America/Oceania
Tour) seit `RACE_HISTORY_START_YEAR` (Default 2020), inkl. Distanz,
Etappenzahl, Ergebnisliste (mind. Top 10, sofern Wikipedia das hergibt) und
bei Mehretagenrennen derselben Angaben pro Etappe.

**Umfang bewusst bei 2020 begonnen, nicht 2010:** World Tour + ProSeries +
alle 5 Continental Touren seit 2010 wären schätzungsweise 5.000+ Rennen mit
weit über 10.000 nötigen Wikipedia-Abrufen gewesen - mehrere Tage
Hintergrund-Scraping allein für den Erstaufbau. Ab 2020 sind es (verifiziert
im produktiven Seeding-Lauf, siehe unten) rund 2.000 Rennen - deutlich mehr
als ursprünglich geschätzt, da die UCI Europe Tour mit ~170-200 Rennen pro
Saison der mit Abstand größte Circuit ist. `RACE_HISTORY_START_YEAR` lässt
sich jederzeit absenken (Umgebungsvariable) - das Seeding ist idempotent
(`race_history_seed_log`), bereits geladene Jahre werden dabei nicht
erneut angefasst, es kommen nur weitere hinzu.

- **`app/scrapers/wikipedia_race_history.py`** - anders als die übrigen
  Scraper in diesem Projekt NICHT einzeln gegen echte Wikipedia-Antworten
  vorab verifiziert (bei geschätzt 1.000+ verschiedenen Renn-Artikeln über 7
  Jahre und 7 Kategorien/Circuits nicht praktikabel vorab durchzuprüfen).
  Stattdessen bewusst defensiv: mehrere Titel-/Abschnitts-Kandidaten
  probieren, alle Parse-Funktionen liefern bei unbekannter Struktur `None`/
  leere Liste statt einen Fehler zu werfen. Die Saison-Tabelle wird
  spaltennamen- statt positionsbasiert geparst (Renn-Namen-Spalte über
  Kopfzeilen-Text wie "race"/"event" gesucht, nicht per fester Position -
  siehe nächster Punkt) und über ALLE Wikitables einer Seite mit
  erkennbarer Namens-Spalte summiert statt nur eine auszuwählen. Gegen
  konstruierte HTML-Fixtures (Datum-Parsing inkl. Jahreswechsel,
  World-Tour- und Continental-Tabellenformat inkl. Multi-Tabellen-Summe,
  Infobox, Ergebnis- und Etappen-Übersichtstabelle) unit-getestet.
  **Ein Struktur-Bug wurde bereits im ersten Produktivlauf gefunden und
  behoben (Stand 2026-09-12):** die ursprüngliche Version nahm an, der
  Rennname stehe im Zeilenkopf (`<th>`) oder in der ersten `<td>`, und
  wählte pro Seite nur die EINE größte Tabelle. Das gilt nur für die
  World-Tour-Kalenderseiten. "2020 UCI Europe Tour" hat die Spalten in der
  Reihenfolge Date/Race name/... UND verteilt seinen Kalender auf 7-10
  separate Tabellen (eine pro Zeitraum) statt einer Gesamttabelle; "2020
  UCI ProSeries" hat die Renn-Spalte erst an fünfter Position. Beides
  führte zu (gültig abgerufenen, aber leeren) 0-Rennen-Ergebnissen für
  einzelne Jahr/Kategorie-Kombinationen, die trotzdem als geseedet markiert
  wurden - gefunden per temporärer Diagnose-Route/Logging gegen die echten
  Seiten (gleiches Vorgehen wie bei den übrigen Scrapern, siehe unten),
  behoben durch die jetzige spaltennamen-basierte, summierende Logik.
  Betraf nicht nur die 0-Fälle: die UCI Europe Tour war dadurch auch in
  Jahren, die schon vorher ein plausibles Ergebnis lieferten, um das
  5-6-fache unterzählt (eine einzelne Tabelle statt aller ~7-10). Ob
  weitere, bisher unbemerkte Kombinationen ähnlich betroffen sind, zeigt
  sich am ehesten an ungewöhnlich niedrigen `race_history_seed_log.race_count`-
  Werten im Vergleich zu benachbarten Jahren.
- **Zwei Scheduler-Phasen** (`scheduler.refresh_race_history`, läuft alle
  `REFRESH_INTERVAL_RACE_HISTORY` Sekunden, Default 3 Min):
  1. *Seeding*: pro (Kategorie, Circuit, Saison), die noch nicht versucht
     wurde, wird einmal die Saison-Übersichtsseite abgerufen (z.B. "2021
     UCI World Tour", "2021 UCI Africa Tour") und jedes gefundene Rennen
     als Skeleton-Zeile (Name, Zeitraum, Wikipedia-URL) angelegt - schnell
     (ein Abruf pro Kombination), läuft komplett in einem Durchgang.
  2. *Backfill*: für bis zu `RACE_HISTORY_DETAIL_BATCH_SIZE` Rennen ohne
     Detail-Daten wird die eigene Wikipedia-Seite abgerufen - das ist der
     teure Teil (bei einem 21-Etappen-Grand-Tour mit dokumentierten
     Einzeletappen-Ergebnissen leicht 20+ Requests für ein einziges
     Rennen), daher batchweise über viele Läufe verteilt, priorisiert nach
     Kategorie (World Tour zuerst) und Saison (neueste zuerst - eher
     vollständig dokumentiert als ältere Rennen).
- **Historische Formatbrüche**, für die Kandidaten-Titel probiert werden:
  die "UCI World Tour" heißt erst ab 2011 so (davor "UCI ProTour" bis
  2010 - relevant erst, wenn `RACE_HISTORY_START_YEAR` auf 2010 abgesenkt
  wird); UCI ProSeries gibt es erst seit 2020 (frühere Jahre liefern
  planmäßig 0 Rennen); Continental-Tour-Saisons liefen früher über den
  Winter (z.B. "2010–11 UCI Africa Tour"), neuere über das Kalenderjahr.
- **Etappen-Details sind best-effort**: Datum/Distanz/Start-Ziel stammen
  aus einer Etappen-Übersichtstabelle irgendwo auf der Rennseite (Spalten-
  namen variieren zwischen Rennen/Jahren), Etappen-ERGEBNISSE aus eigenen
  "Stage N"-Abschnitten, sofern die Rennseite solche hat - bei kleineren
  oder älteren Rennen oft nicht vorhanden. Fehlt eine Quelle, bleibt das
  jeweilige Feld leer statt die ganze Etappe/das ganze Rennen zu verwerfen.

### Bekannte Lücken: Höhenmeter (Platzhalter) und Veranstalter-Website (nicht weiter gescraped)

- **Höhenmeter** (`races.elevation_m`, `race_stages.elevation_m`): wie bei
  `riders.uci_points` auf Wikipedia für kein Rennen strukturiert erfasst -
  nur als unstrukturierte Profil-Grafik auf manchen Rennseiten, nicht als
  Zahl. Bleibt NULL, bis ein künftiger Import aus einer anderen Quelle die
  Werte nachträgt; die Spalte existiert bereits dafür.
- **Veranstalter-Website** (`races.organizer_website`, z.B.
  amstelgoldrace.nl): wird aus der Wikipedia-Infobox übernommen, sofern
  dort als "Website" gepflegt - aber NICHT selbst weiter gescraped. Jede
  Veranstalter-Seite hat ihre eigene, oft clientseitig gerenderte Struktur
  ohne gemeinsames Muster (anders als Wikipedias einheitliches Infobox-
  Template, das die gesamte Scraping-Architektur dieses Projekts erst
  praktikabel macht) - ein generischer Parser dafür wäre pro Rennen
  Handarbeit und würde nicht im großen Maßstab funktionieren. Das Feld ist
  als Link für Nutzer gedacht, nicht als weitere Scraping-Quelle.

### CSV-Export

| Endpunkt | Inhalt |
|---|---|
| `GET /api/export/races.csv` | komplette `races`-Tabelle |
| `GET /api/export/race_results.csv` | `race_results` + aufgelöste `race_name`/`stage_number` (NULL = Gesamt-/Eintagesrennen-Ergebnis) |
| `GET /api/export/race_stages.csv` | `race_stages` + aufgelöste `race_name` |

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
6. **Renn-Historie-Backfill (siehe oben) braucht durchgängige Laufzeit:**
   der Free-Tier-Schlafmodus (Punkt 3) pausiert auch diesen Hintergrund-Job
   - ohne eingehende Requests kommt der mehrstündige/-tägige Erstaufbau
   ins Stocken, bis der nächste Request den Service aufweckt. Für einen
   zügigen, durchgängigen Erstaufbau entweder einen "Always On"-Plan
   nutzen oder den Service während des Backfills regelmäßig anpingen
   (z.B. `curl .../api/health` per Cron).

## API-Endpunkte

| Endpunkt | Beschreibung |
|---|---|
| `GET /api/teams?category=wt\|pro\|cont` | Alle Teams, optional gefiltert |
| `GET /api/races` | Rennkalender (Saison) |
| `GET /api/calendar` | Kalenderansicht (ein Eintrag pro Rennstart) |
| `GET /api/results?status=live\|finished\|upcoming` | (Live-)Ergebnisse |
| `GET /api/news?limit=30` | Aggregierter Newsfeed |
| `GET /api/riders?team=<team_id>` | Fahrer, optional nach aktuellem Team gefiltert, sortiert nach Nachname |
| `GET /api/riders/{id}` | Ein Fahrer inkl. `history` (rohe Team-Zeiträume) und `seasons` (pro Saison abgeleiteter Team-Link, siehe "Vor-/Nachname, Saison-Team-Links, Strava-Profile" oben) |
| `GET /api/race-history?season=&category=wt\|proseries\|continental&circuit=africa\|asia\|europe\|america\|oceania&limit=&offset=` | Renn-Historie seit 2020, gefiltert/paginiert, ohne Ergebnisse/Etappen (siehe "Renn-Historie" oben) |
| `GET /api/race-history/{id}` | Ein Rennen inkl. `results` (Top 10+) und bei Mehretagenrennen `stages[]` (je Etappe eigene `results`) |
| `GET /api/health` | Health-Check |

Da die Teams-Quelle (Wikipedia) nur WorldTeams abdeckt, liefert
`category=pro` und `category=cont` aktuell immer eine leere Liste.

Die `/api/riders*`- und `/api/race-history*`-Endpunkte liefern
`{"riders": [], "error": "..."}` bzw. `{"races": [], "error": "..."}` (Liste)
oder HTTP 503 (Detail), solange `DATABASE_URL` nicht gesetzt ist (siehe
"Fahrer-Datenbank"/"Renn-Historie" oben) - kein `last_updated`, da sie
nicht über den Cache-Mechanismus laufen.

Jede Antwort enthält zusätzlich `last_updated` (ISO-Timestamp des letzten
erfolgreichen Scraping-Laufs) und `error` (Fehlermeldung des letzten
Versuchs, `null` falls erfolgreich).
