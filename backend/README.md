# PelotonPro Backend

FastAPI-Backend, das die Frontend-Seite (`../index.html`) mit aktuellen
Daten versorgt: UCI Teams, Rennkalender, (Live-)Ergebnisse und ein
aggregierter Radsport-Newsfeed.

## Architektur

```
Scheduler (APScheduler, Hintergrund-Thread)
  -> Scraper (Wikipedia-API) / RSS-Aggregator
  -> Postgres (app/db.py, app/db_races.py)   [Teams, Fahrer, Rennen]
     bzw. Cache (In-Memory + JSON-Datei)     [nur News, app/cache.py]
  -> REST-API (FastAPI) --GET--> Frontend (index.html)
```

Die API liest **nie live** von den Quellen, sondern immer aus dem
gespeicherten Stand. Das hält Requests schnell, schont die Zielseiten und
sorgt dafür, dass ein einzelner fehlschlagender Scraping-Lauf nicht die
ganze Seite lahmlegt - es wird einfach der letzte funktionierende Stand
weiter ausgeliefert.

Alles außer News liegt in Postgres. Der JSON-Cache bediente früher auch
Teams und Rennen; warum er das nicht mehr tut, steht unter
"Doppelstrukturen".

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
- **`app/scrapers/wikipedia_race_history.py`** - VERIFIZIERT
  (Stand 2026-09-11). Seeding aus den Saison-Übersichtsseiten, dann pro
  Rennen der eigene Artikel (Infobox, Etappenliste, Ergebnisse).
  Etappenrennen nutzen den Abschnitt "General classification" (von
  Wikipedia selbst schon auf Top 10 begrenzt), Eintagesrennen den
  Abschnitt "Result" - beide mit derselben
  Rank/Rider/Team/Time-Tabellenstruktur, nur mit unterschiedlicher
  Rang-Zellenart (`<th scope="row">` bzw. `<td>`). Der Zeilen-Parser dafür
  steht in `app/scrapers/wikipedia_tables.py`.
  Ein zweiter Scraper (`wikipedia_races.py`) las dieselben Seiten für
  einen eigenen Kalender-/Ergebnis-Pfad; er ist entfallen, siehe
  "Doppelstrukturen".

So testet man die Parser ohne Netzwerkzugriff gegen gespeichertes HTML
(z.B. per Browser-Devtools oder `action=parse&prop=text&section=N`
kopiert):

```python
from app.scrapers.wikipedia_teams import parse_worldteams_section
from app.scrapers.wikipedia_race_history import parse_season_page, parse_race_infobox

teams = parse_worldteams_section(open("worldteams_section.html", encoding="utf-8").read())
races = parse_season_page(open("season_page.html", encoding="utf-8").read(), 2026)
infobox = parse_race_infobox(open("race_article.html", encoding="utf-8").read())
```

Der Ergebnis-Zeilen-Parser steht in `app/scrapers/wikipedia_tables.py`
(`parse_result_row`) und lässt sich einzeln gegen eine gespeicherte
Tabellenzeile testen.

Mit echtem Netzwerkzugriff (lokal) direkt gegen die Live-API:

```bash
cd backend
python -m app.scrapers.wikipedia_teams   # sollte Team-Objekte ausgeben

# Renn-Historie hat kein __main__; der Einstieg ueber Netz ist:
python -c "from app.scrapers.wikipedia_race_history import fetch_season_race_list; \
           print(fetch_season_race_list(2026, 'wt')[:3])"
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
- Aggressives Speichern: Teams und Kader werden nur 1x täglich neu
  geholt, Renn-Details nur einmal pro Rennen - aber **erst nach dem
  Rennen** (`RACE_DETAIL_GRACE_DAYS`, siehe "Ergebnisse erst nach dem
  Rennen abrufen"). Danach steht `races.results_fetched_at` und das Rennen
  wird nicht erneut abgefragt. Ein Live-Ticker wäre hier ohnehin nicht
  sinnvoll, da Wikipedia nicht in Echtzeit editiert wird - Endstände stehen
  nach Rennende dauerhaft im Artikel.

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

Teams, Fahrer und deren Team-Zugehörigkeit über die Jahre liegen in einer
**persistenten Postgres-Datenbank** (`app/db.py`). Grund für die echte
Persistenz: ein vollständiger Rebuild aller ~500 Fahrer-Historien (ein
Wikipedia-Abruf pro Fahrer, respektvoll ratenlimitiert) dauert 15-20
Minuten - das soll nicht nach jedem Render-Neustart (Deploy, Aufwachen aus
dem Schlafmodus) erneut passieren, wie es beim flüchtigen Cache der Fall
wäre. Aus demselben Grund liegen dort inzwischen auch die Teams, siehe
"Doppelstrukturen".

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
- **`scheduler.refresh_rosters`** - läuft alle `REFRESH_INTERVAL_ROSTERS`
  Sekunden (Default 24 h): aktualisiert die Kader aller aktuellen Teams
  (ein Abruf pro Team) und schreibt nur geänderte Fahrer.
- **`scheduler.refresh_rider_details`** - läuft alle
  `REFRESH_INTERVAL_RIDER_DETAILS` Sekunden (Default 3 Min): holt die volle Historie für
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
  "Mathieu" / Nachname "van der Poel" gesplittet wird. **Standard-Sortierung
  ist nach Nachname** (`ORDER BY last_name, first_name`) statt nach vollem
  Namen, sowohl in `GET /api/riders` als auch im CSV-Export. Wo die
  Heuristik falsch liegt und was dagegen getan ist, steht unter
  "Familiennamen aus Wikidata".
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
  `scrapers/wikidata.py` befüllt, im selben `refresh_rider_details`-Job wie
  die Team-Historie, gebatcht über `STRAVA_BATCH_SIZE` Fahrer pro Lauf
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

### Familiennamen aus Wikidata (Befund 16)

`split_name` nimmt das letzte Wort plus vorangehende Partikel. Der
Standardfall stimmt, die niederländisch/deutschen Partikel-Namen auch.
Falsch liegt die Heuristik bei **spanischen und portugiesischen
Doppelnachnamen**:

| voller Name | Heuristik | richtig |
|---|---|---|
| Juan Ayuso Pesquera | "Juan Ayuso" / **"Pesquera"** | "Juan" / **"Ayuso Pesquera"** |
| Carlos Rodríguez Cano | "Carlos Rodríguez" / **"Cano"** | "Carlos" / **"Rodríguez Cano"** |

Das ist keine Kosmetik: die Standardsortierung geht über `last_name`, und
auf der Fahrer-Detailseite ist der Nachname die Überschrift.

Wikidata führt Familiennamen als
[P734](https://www.wikidata.org/wiki/Property:P734), bei Doppelnachnamen
als **zwei Aussagen in Reihenfolge**. Damit ist der Fall entscheidbar statt
geraten - und die Maschinerie dafür stand schon da: derselbe Weg
Wikipedia-Titel → QID → Property, den der Strava-Abgleich benutzt.

#### Übernommen wird nur, was aufgeht

`nachname_aus_wikidata` akzeptiert einen Wikidata-Familiennamen nur, wenn
er als **Suffix des vollen Namens auf Wortgrenzen** aufgeht. Wikidata
enthält auch Geburtsnamen, Namen in anderen Schriften und schlicht Fehler;
keiner davon darf einen Namen in der Datenbank überschreiben. Passt nichts,
bleibt das Ergebnis von `split_name` stehen.

Verglichen wird ohne diakritische Zeichen und ohne Groß-/Kleinschreibung
("Pogacar" gegen "Pogačar", "Kung" gegen "Küng") - **gespeichert** wird
dagegen immer die Schreibweise aus dem vollen Namen. Die Datenbank soll
`name == first_name + " " + last_name` erfüllen, und der volle Name ist die
Quelle mit den richtigen Akzenten.

Vier Schutzregeln, jede davon gegengeprüft (siehe unten):

| Regel | wogegen |
|---|---|
| Vergleich auf Wortgrenzen | "gaard" darf nicht auf "Vingegaard" passen |
| Vergleichsfaltung | "Pogacar" muss auf "Pogačar" passen |
| längster Kandidat gewinnt | "Pesquera" darf "Ayuso Pesquera" nicht verdrängen |
| Nachname darf nicht den ganzen Namen einnehmen | sonst bleibt kein Vorname übrig |

#### Migration 0005 schreibt keinen Namen um

Sie legt nur `riders.name_source` an:

| Wert | Bedeutung |
|---|---|
| `NULL` | noch nicht bei Wikidata nachgefragt |
| `heuristik` | nachgefragt, Wikidata hatte nichts Passendes |
| `wikidata` | Wikidata hat bestätigt oder korrigiert |

Die Spalte ist der Rückweg: ohne sie wäre eine falsche Wikidata-Korrektur
nicht von einem Heuristik-Ergebnis zu unterscheiden. Ein erneuter Durchlauf
ist ein `UPDATE riders SET name_source = NULL`. Sie steht auch im
CSV-Export von `riders` - eine Herkunftsangabe, die man nicht sehen kann,
nützt nichts, und die CSV-Exporte sind der einzige Weg, von aussen in diese
Datenbank zu schauen.

Das Nachfragen erledigt `scheduler._namen_abgleichen()`, gebatcht über
`NAME_BATCH_SIZE` Fahrer pro Lauf, im selben Job wie Historie und Strava,
einmal pro Fahrer (wie dort).

#### Mitgenommen: `riders.wikidata_qid` wird endlich gefüllt

Die Spalte kam mit Migration 0002 und wurde von **nichts** geschrieben -
sie war leer. Der Familiennamen-Job löst den Wikipedia-Titel ohnehin zur
QID auf, also trägt er sie ein. Das ist die Vorarbeit für Befund 7
Schritt 3 (`riders.id` auf die QID umstellen). Auf der Spalte liegt ein
partieller UNIQUE-Index; zwei Fahrer auf derselben QID wären ein
Datenfehler (eine Wikipedia-Weiterleitung, zwei Kaderzeilen für dieselbe
Person) und werden gemeldet, brechen aber den Lauf nicht ab.

#### Was hier nicht überprüfbar war

**Wikidata ist aus dieser Arbeitsumgebung nicht erreichbar** (HTTP 000,
Egress-Proxy) - wie Wikipedia. Die **Antwortform** von
`wbgetentities` für eine Item-Property ist damit ungeprüft: der Code nimmt
`mainsnak.datavalue.value.id` an.

Dagegen zwei Vorkehrungen statt einer Annahme:

1. `_claim_ziel` liest defensiv und akzeptiert auch eine blanke
   Zeichenkette.
2. Jede Aussage ohne lesbare Ziel-ID wird gezählt und als **Warnung**
   geloggt. Stimmt die Form nicht, steht das im Log - statt dass der
   Abgleich still bei null bleibt.

Und der Job berichtet, was herauskam:

```
Familiennamen-Abgleich: <n> Fahrer geprüft, <n> korrigiert, <n> bestätigt,
<n> ohne Wikidata-Treffer, <n> QIDs nachgetragen
```

Bleibt "korrigiert" dauerhaft 0, während "geprüft" hochläuft, ist die
Annahme falsch. Jede Korrektur wird zusätzlich einzeln geloggt, mit dem
Ergebnis der Heuristik daneben.

Ebenfalls ungeprüft: **wie viele Fahrer im Bestand betroffen sind.** Die
Datenbank nimmt keine externen Verbindungen an, ich kann die Namen nicht
abfragen. Bei 517 Fahrern mit spanischen und portugiesischen Namen im Feld
ist eine zweistellige Zahl plausibel - gemessen ist sie nicht, und das Log
nach dem Deploy sagt es.

#### Prüfen

```bash
DATABASE_URL=postgresql://... python3 scripts/check-namen.py
PGPORT=5599 ./scripts/check-migration-0005.sh
```

`check-namen.py` prüft drei Dinge. Die **Regel** an 14 Namen, die es
wirklich gibt, inklusive aller vier Ablehnungsgründe. Den **Parser**, indem
es HTTP-Antworten in der dokumentierten Form fälscht - und zusätzlich in
einer abweichenden, um zu belegen, dass die Warnung dann wirklich kommt.
Und den **Job** gegen eine echte Datenbank: Doppelnachname korrigiert,
einfacher Name bestätigt, Fahrer ohne Wikidata-Item auf `heuristik`, QID
nachgetragen, `name` bei allen unverändert, und ein zweiter Lauf fragt
nicht erneut.

Gefälscht wird auf HTTP-Ebene, nicht auf Funktionsebene: so laufen
`fetch_wikidata_ids`, `fetch_family_names`, `fetch_labels` und der Parser
wirklich, statt umgangen zu werden.

Gegengeprüft, dass das Skript etwas taugt: jede der vier Schutzregeln
einzeln entfernt, jedes Mal schlagen genau die dafür zuständigen
Prüfungen fehl.

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
`refresh_rosters`-Zyklus, also täglich) für **jede** WorldTour-Saison eines Fahrers eine
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
| `GET /api/export/riders.csv` | `riders` (inkl. `first_name`/`last_name`/`name_source`/`strava_url`/`wikidata_qid`) + aufgelöster `current_team_name`, sortiert nach Nachname |
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

### Ergebnisse erst nach dem Rennen abrufen

Ein Fehler, der Daten dauerhaft verloren hat, ohne irgendwo aufzufallen.

**Was passiert ist.** Der Rückstand des Detail-Backfills war
`results_fetched_at IS NULL` - ohne Rücksicht darauf, ob das Rennen schon
gefahren war. Ein Saisonkalender wird aber komplett auf einmal geseedet,
also standen im Januar auch die Rennen vom Oktober in der Tabelle. Deren
Wikipedia-Seite existiert zu dem Zeitpunkt oft schon (Streckenverlauf,
Teilnehmerliste), eine Ergebnistabelle nicht.

Der Abruf lieferte deshalb nichts. `replace_race_details` setzte
`results_fetched_at = now()` trotzdem - die Funktion markiert **unbedingt**,
nicht abhängig davon, ob Ergebnisse dabei waren. Damit war das Rennen für
immer erledigt und wurde nie wieder abgefragt. Das Log meldete zufrieden
`noch 0 Rennen ausstehend`.

**Wie es sich gezeigt hat.** Im Frontend, nur falsch herum: `js/races.js`
zeigt bei `results_fetched_at IS NULL` und Startdatum in der Zukunft
„bevorstehend". Weil die Spalte gesetzt war, stand dort stattdessen
„Ergebnisse ansehen" und beim Aufklappen „Keine Ergebnisliste erfasst." -
eine endgültige Aussage über ein Rennen, das noch nicht gefahren war. Das
Frontend war richtig gebaut; das Backend hat seine Annahme gebrochen.

**Der Fix.** Ein Rennen wird erst zum Abruf angeboten, wenn sein Enddatum
mindestens `RACE_DETAIL_GRACE_DAYS` (Default 3) Tage zurückliegt:

```sql
results_fetched_at IS NULL
AND wiki_url IS NOT NULL
AND (
    coalesce(end_date, start_date) IS NULL
    OR coalesce(end_date, start_date) <= current_date - %(karenz)s::int
)
```

Die Bedingung steht als `db_races._DETAILS_FAELLIG` an **einer** Stelle, für
die Abfrage und für die Zählung. Vorher stand sie zweimal da - die gemeldete
Zahl „noch N Rennen ausstehend" wäre bei jeder Änderung von der Abfrage
abgewichen. Ohne Datum (weder Ende noch Start bekannt) lässt sich nicht
beurteilen, ob das Rennen stattgefunden hat: dann wird abgerufen wie bisher.

Drei Tage, weil Ergebnistabellen meist innerhalb eines Tages eingetragen
werden und ein Puffer nichts kostet - ein Rennen, das noch wartet, blockiert
nichts.

**Folge für das Log:** `noch N Rennen ausstehend` zeigt für die laufende
Saison jetzt eine Zahl größer null, solange Rennen noch bevorstehen. Das ist
ehrlich, nicht kaputt.

**Die Reparatur** macht Migration 0006. Sie setzt `results_fetched_at` auf
NULL zurück, und zwar nur bei Zeilen, bei denen der Abruf **beweisbar** zu
früh war:

```sql
results_fetched_at::date < coalesce(end_date, start_date)
```

Also: abgerufen, bevor das Rennen zu Ende war - je Zeile nachrechenbar,
keine Schätzung. Bewusst **nicht** zurückgesetzt werden Zeilen, die kurz
nach dem Ende abgerufen wurden und trotzdem keine Ergebnisse haben: die
können echt undokumentiert sein (schlecht gepflegte Continental-Rennen), und
sie alle erneut abzurufen wäre Wikipedia-Last ohne belegten Nutzen. Wer das
doch will:

```sql
UPDATE races SET results_fetched_at = NULL
WHERE results_fetched_at IS NOT NULL
  AND id NOT IN (SELECT DISTINCT race_id FROM race_results);
```

Diese Migration ändert einen **Bestandswert** - laut "Kein Backup, und was
das für Migrationen heisst" normalerweise gesperrt. Zulässig ist es hier,
weil das Kriterium dort die Wiederherstellbarkeit ist, nicht die
Spaltenart: `results_fetched_at` ist ein Merker, kein Inhalt. Verloren geht
der Zeitstempel eines Abrufs, der nichts gefunden hat; Name, Datum,
Kategorie, Wiki-URL und die (leeren) Ergebnisse bleiben unangetastet, und
der nächste Job-Lauf trägt den Merker neu ein - diesmal nach dem Rennen.

#### Prüfen

```bash
PGPORT=5599 ./scripts/check-migration-0006.sh
```

18 Prüfungen über sechs Fälle, alle relativ zum heutigen Datum aufgebaut
(damit der Test in jedem Jahr läuft): ein Rennen in der Zukunft und eines
mitten im Verlauf werden zurückgesetzt; eines, das spät abgerufen wurde und
trotzdem leer ist, eines mit Ergebnissen und eines ohne jedes Datum bleiben
unangetastet. Dazu: kein Stammdatum und keine Ergebniszeile verändert, und
die Karenzzeit bestimmt genau, was zum Abruf angeboten wird - bei Karenz 0
bleiben die künftigen Rennen trotzdem aussen, weil ihr Enddatum in der
Zukunft liegt.

Gegengeprüft mit vier Manipulationen, jede scheitert an den zuständigen
Prüfungen: ohne die Datumsbedingung sind die künftigen Rennen wieder fällig
(der alte Zustand); mit einer eigenen Bedingung in der Zählung weicht die
gemeldete Zahl von der Abfrage ab; setzt die Migration alles statt nur das
Beweisbare zurück, verlieren drei korrekte Zeilen ihren Merker; tut sie
nichts, bleiben die beiden falschen stehen.

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

Das Frontend braucht einen HTTP-Server - per Doppelklick aus dem
Dateimanager geöffnet bleiben die Seiten leer, weil ES-Module von `file://`
nicht laden (siehe "Frontend: ES-Module statt globaler Namen"):

```bash
cd ..                 # Wurzelverzeichnis, wo die HTML-Dateien liegen
python3 -m http.server 8000
```

Dann `http://localhost:8000/index.html` öffnen. `js/api.js` erkennt
`localhost` bzw. `127.0.0.1` am Hostnamen und spricht automatisch
`http://localhost:8001` an.

## Deployment auf Render.com

1. Repo mit Render verbinden, `backend/render.yaml` wird automatisch
   erkannt (Blueprint).
2. `CORS_ORIGINS` in den Render-Umgebungsvariablen auf die tatsächliche
   GitHub-Pages-URL setzen.
3. **Free-Tier-Einschränkung:** Render setzt kostenlose Web Services nach
   ~15 Minuten Inaktivität in den Schlafmodus - der Hintergrund-Scheduler
   pausiert dann ebenfalls, bis der nächste Request den Service aufweckt.
   Für einen wirklich durchgängig aktuellen Newsfeed ist mittelfristig ein
   kostenpflichtiger "Always On"-Plan nötig.
4. Kein persistentes Disk-Volume im Free-Tier - der JSON-Cache geht bei
   jedem Neustart/Deploy verloren. Das betrifft nur noch News (siehe
   "Doppelstrukturen"), und unkritisch, weil der Scheduler beim Start
   sofort neu scraped. Teams, Fahrer und Rennen liegen in Postgres und
   sind davon nicht betroffen.
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

## Hintergrund-Jobs

| Job | Takt | Zeitbudget | Pool | Was er tut |
|---|---|---|---|---|
| `refresh_teams` | 24 h | – | scrape | WorldTeams-Übersicht in die `teams`-Tabelle |
| `refresh_rosters` | 24 h | – | scrape | Kader aller Teams + UCI-Punkte-Platzhalter |
| `refresh_rider_details` | 15 min | 120 s | scrape | Rückstand: Team-Historie, Strava |
| `refresh_race_history` | 15 min | 600 s | scrape | Renn-Seeding und Detail-Backfill |
| `refresh_news` | 15 min | – | default | RSS-Feeds |

### Ein Worker für alles, was Wikipedia abfragt

Der `scrape`-Pool hat genau **einen** Worker. Parallelität bringt dort nichts:
`scrapers/http.py` lässt ohnehin nur einen Request alle
`SCRAPER_REQUEST_DELAY_SECONDS` pro Host durch. Zwei gleichzeitige
Wikipedia-Jobs haben sich deshalb nur gegenseitig ausgebremst - jeder lief
doppelt so lange, beide überschritten ihr Intervall, und APScheduler verwarf
die nächsten Läufe (`maximum number of running instances reached`, belegt in
den Render-Logs vom 12.09.). Der Newsfeed läuft im `default`-Pool, weil er
andere Hosts anspricht und nicht hinter den Wikipedia-Jobs warten soll.

**Achtung bei der Umstellung auf einen Worker:** ein Job, der auf den Worker
wartet, startet später als geplant - und APSchedulers Default
(`misfire_grace_time=1s`) verwirft ihn dann komplett. In einem Testlauf lief
`refresh_rider_details` dadurch **gar nicht mehr**, es war nur eine andere
Art, Läufe zu verlieren. Deshalb ist `misfire_grace_time` auf das jeweilige
Intervall gesetzt: eine Verspätung von bis zu einem Intervall ist hier
unkritisch, besser spät als nie. Dazu ein Startversatz
(`JOB_START_STAGGER_SECONDS`), damit sich beim Hochfahren nicht alle Jobs
gleichzeitig anstellen.

### Zeitbudget statt fester Batch-Größe

Die beiden Rückstands-Jobs arbeiten sich durch eine Warteschlange von Stunden
bis Tagen. Vorher holten sie eine feste Zahl Einträge pro Lauf - die Laufzeit
hing damit vom Inhalt ab (ein Etappenrennen kostet ein Vielfaches an Abrufen
gegenüber einem Eintagesrennen) und lag regelmäßig über dem Intervall.

Jetzt arbeiten sie, solange Budget übrig ist (`scheduler.Budget`). Die
Batch-Größe ist nur noch das Abfrage-Fenster, die Laufzeit bestimmt das
Budget - und bleibt damit vorhersagbar unter dem Intervall.

Zwei Fallstricke, die dabei einzubauen waren:

- Ein fehlgeschlagener Eintrag behält `results_fetched_at`/`history_fetched_at`
  auf `NULL` und käme in der nächsten Batch-Abfrage **desselben Laufs** sofort
  wieder. Ohne Gegenmaßnahme verbrennt der Job sein Budget auf denselben
  kaputten Seiten. Beide Schleifen merken sich die versuchten IDs.
- Das Abfrage-Fenster muss um die bereits versuchten wachsen
  (`limit=batch + len(attempted)`), sonst liefert die Abfrage immer wieder
  dieselben gescheiterten Einträge und der Lauf kommt nie an ihnen vorbei.
  Getestet mit 20 dauerhaft kaputten Rennen vor 23 intakten: die intakten
  werden abgearbeitet, nur die kaputten bleiben offen.

### Einen Job einzeln ausführen

```bash
cd backend
python -m app.scheduler refresh_race_history
```

Greift auf dieselbe `JOBS`-Liste zu wie der Scheduler - es gibt also keine
zweite Registrierung, die auseinanderlaufen kann.

**Wofür das gedacht ist:** Der Renn-Backfill braucht durchgängige Laufzeit,
die eine kostenlose Web-Instanz nicht liefert - Render setzt sie nach ~15
Minuten ohne Requests schlafen, und der Scheduler-Thread pausiert mit. Der
richtige Ort für den Bestandsaufbau ist deshalb ein **Render Cron Job** oder
ein Background Worker, nicht ein Thread im Webserver:

| Feld | Wert |
|---|---|
| Build Command | `cd backend && pip install -r requirements.txt` |
| Command | `cd backend && python -m app.scheduler refresh_race_history` |
| Schedule | z.B. `*/20 * * * *` |
| Env: `DATABASE_URL` | aus `peletonpro-db` |
| Env: `RACE_HISTORY_RUN_SECONDS` | passend zum Schedule wählen |

Solange das nicht eingerichtet ist, läuft der Backfill nur, wenn die
Web-Instanz wach ist.

`refresh_rosters` und `refresh_rider_details` waren bis vor Kurzem **ein**
Job (`refresh_riders`) mit gemeinsamem Drei-Minuten-Takt. Das hieß: alle drei
Minuten 18 Wikipedia-Seiten abrufen und 517 Fahrer neu schreiben, für Daten,
die sich ein paar Mal im Jahr ändern (Transferperiode, Nachverpflichtungen).
Weil alle Scraper sich in `scrapers/http.py` eine Drosselung von zwei
Sekunden pro Host teilen, hat dieser Job damit den Renn-Detail-Backfill
ausgehungert - und beide Jobs liefen länger als ihr eigenes Intervall, sodass
APScheduler laufend Läufe verwarf (`maximum number of running instances
reached`).

Der Kader-Teil läuft jetzt im Tagestakt, der Rückstands-Abbau behält den
kurzen. Damit sinken die Wikipedia-Abrufe für Kader von bis zu **18 alle drei
Minuten** auf **18 pro Tag**.

### Nur schreiben, was sich geändert hat

`refresh_rosters` vergleicht jeden gescrapten Fahrer mit dem Stand in der
Datenbank (`db.get_rider_fingerprints`) und schreibt nur die Abweichungen.
Gemessen mit 18 Teams und 517 Fahrern gegen eine lokale Postgres-16-Instanz:

| Lauf | geschriebene Fahrer | SQL-Abfragen |
|---|---|---|
| 1 (Erstbefüllung) | 517 | 3 |
| 2 (unverändert) | **0** | 2 |
| 3 (ein Wechsel) | 1 | 3 |

Der Vergleich läuft bewusst **nicht** über `last_updated`: dieser Zeitstempel
wird von jedem Upsert neu gesetzt und sagt nur, wann zuletzt geschrieben
wurde, nicht ob sich etwas geändert hat. `birth_date` kommt aus Postgres als
`date`-Objekt und vom Scraper als ISO-String und wird vor dem Vergleich
normalisiert - sonst gälte jeder Fahrer bei jedem Lauf als geändert.

## Schema-Migrationen

Das Schema lag als String-Literal im Code - `SCHEMA` in `app/db.py`,
`SCHEMA_RACES` in `app/db_races.py` - und wurde bei jedem App-Start neu
ausgeführt, mit handschriftlich angehängten
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Es gab keine Möglichkeit
festzustellen, welcher Stand in Produktion läuft. Bei zwei Änderungen geht
das; bei denen, die Frauen-Radsport und mehr Historie mitbringen (neue
Spalten, neue Schlüssel, neue Tabellen), verliert man den Überblick.

Jetzt: nummerierte `.sql`-Dateien in `backend/migrations/`, eine Tabelle
`schema_migrations`, ein Runner in `app/migrations.py`.

### Eine neue Migration anlegen

Neue Datei `backend/migrations/NNNN_kurzer_name.sql` mit der nächsten
freien Nummer anlegen und das SQL hineinschreiben - beim nächsten App-Start
läuft sie automatisch. Eine bereits angewendete Datei darf **nicht** mehr
geändert werden: der Runner prüft die Prüfsumme und bricht sonst ab;
Korrekturen gehören in eine neue Migration.

### Warum kein Alembic

Alembics Wert liegt in der Autogenerierung aus SQLAlchemy-Modellen. Dieses
Projekt hat kein ORM - es schreibt SQL direkt mit psycopg. Jede
Alembic-Revision wäre hier ein `op.execute("...")` mit demselben SQL darin,
nur mit Boilerplate obendrüber, plus eine Abhängigkeit, die SQLAlchemy auf
eine 512-MB-Instanz zieht.

Was stattdessen dasteht, sind rund 150 Zeilen: eine Tabelle, eine
Reihenfolge, ein Lock. Der Preis ist, dass Alembics selten gebrauchte
Fähigkeiten fehlen (Verzweigungen, Autogenerierung, `stamp`). Kommt später
ein ORM dazu, ist der Wechsel ein `alembic stamp` auf den dann erreichten
Stand - die Entscheidung verbaut nichts.

### Kein Rückweg, absichtlich

Es gibt kein `downgrade`. Ein Rückweg, der nur auf dem Papier existiert,
ist gefährlicher als keiner: die meisten Schema-Rückwärtsschritte verlieren
Daten (eine gelöschte Spalte kommt nicht zurück), und niemand probt sie.
Der ehrliche Rückweg dieses Projekts ist das Backup (siehe Abschnitt
"Backup") - vor einer Migration, die Daten anfasst, ein Dump; geht sie
schief, ein Restore.

### Wann und wie es läuft

Im FastAPI-`lifespan` beim Start, vor dem Scheduler - dort, wo vorher die
zwei `init_schema()`-Aufrufe standen. Renders Free-Plan bietet keinen
Shell-Zugriff und kein `preDeployCommand`, ein Aufruf beim Start ist also
der einzige Weg, der ohne Handarbeit funktioniert. Von Hand geht es auch:

```bash
cd backend
python -m app.migrations status    # welcher Stand ist angewendet?
python -m app.migrations upgrade   # offene Migrationen anwenden
```

Drei Eigenschaften, die beim Bauen jeweils erst durch einen Test
sichtbar wurden:

- **Advisory Lock.** Der Lauf hält `pg_advisory_lock`, damit zwei
  gleichzeitig startende Instanzen nicht dieselbe Migration fahren. Das
  Lock hängt an der Verbindung und fällt mit ihr weg - anders als ein
  selbstgebautes "Sperre"-Feld in einer Tabelle, das nach einem Absturz
  hängen bleibt.
- **Autocommit, und eine eigene Verbindung.** Läge der ganze Lauf in einer
  Transaktion, würden alle Migrationen zusammen am Ende committen: bricht
  das ab, ist auch die erste, längst erfolgreiche Migration weg. Jede
  Migration bekommt deshalb ihre eigene Transaktion, zusammen mit ihrem
  Eintrag in `schema_migrations` - ein halb angewendeter Stand, der als
  angewendet gilt, wäre das schlimmere Ergebnis.

  Die Verbindung dafür kommt **nicht** aus dem Pool. `autocommit` bleibt
  sonst an der zurückgegebenen Verbindung hängen (psycopg_pool stellt es
  nicht wieder her), und der nächste Nutzer derselben Verbindung steht in
  Autocommit - womit die server-side Cursor des CSV-Exports brechen
  ("DECLARE CURSOR can only be used in transaction blocks"). Nachgemessen,
  bevor das behoben war: vier von sieben CSV-Exporten lieferten HTTP 200
  mit **leerem Rumpf**.
- **`CREATE TABLE IF NOT EXISTS` ist nicht race-frei.** Existenzprüfung und
  Anlegen sind zwei Schritte; dazwischen kann eine andere Sitzung die
  Tabelle erzeugen, und dann schlägt das Anlegen mit `DuplicateTable` fehl -
  trotz `IF NOT EXISTS`. Genau daran ist der zweite von zwei gleichzeitigen
  Läufen gescheitert, bevor der Lock vor dem Katalog-Zugriff lag. Der Fall
  wird zusätzlich abgefangen: dass die Tabelle schon da ist, war ja das
  Ziel.

### Die erste Migration und die laufende Produktion

`0001_bestand.sql` ist der Schemastand von vorher, wörtlich aus den beiden
String-Literalen übernommen. Sie läuft auch gegen die bestehende
Produktionsdatenbank, in der alles schon existiert - dort fehlt
`schema_migrations`, 0001 gilt also als nicht angewendet. Sie ist deshalb
durchgehend idempotent (`IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`) und
rührt vorhandene Daten nicht an. Genau so lief dieses SQL vorher bei jedem
Start.

Ab `0002` ist diese Rücksicht nicht mehr nötig: dann ist bekannt, welcher
Stand angewendet wurde, und gewöhnliches `ALTER TABLE` genügt.

### Prüfen

```bash
PGPORT=5599 ./scripts/check-migrations.sh
```

Das Skript legt Testdatenbanken an und prüft sieben Dinge: leeres Schema
wird aufgebaut, ein zweiter Lauf tut nichts, eine Datenbank im
Produktionsstand (Tabellen inkl. der per `ALTER` ergänzten Spalten, mit
Daten) wird ohne jede Änderung an Zeilen oder Feldern migriert, das so
entstandene Schema ist identisch zu dem aus einer leeren Datenbank, eine
nachträglich geänderte Migration bricht ab, eine fehlerhafte lässt nichts
halb angewendet zurück, und zwei gleichzeitige Läufe wenden dieselbe
Migration genau einmal an.

Den Produktionsstand für Schritt 3 holt das Skript per `git show` aus
`origin/main` - also aus dem Code, der wirklich lief, nicht aus dem
aktuellen Baum. Die Testdaten stehen im Skript selbst: als sie noch in
einer externen Datei lagen, scheiterte das Einspielen einmal still, und
die Vergleiche verglichen 0 Zeilen mit 0 Zeilen und bestanden scheinbar.
Das Skript bricht jetzt ab, wenn keine Testdaten drin sind.

Je Migration gibt es zusätzlich ein eigenes Skript, das die fachliche
Wirkung prüft statt nur den Ablauf:

```bash
PGPORT=5599 ./scripts/check-migration-0002.sh   # Geschlechts-Dimension
PGPORT=5599 ./scripts/check-migration-0003.sh   # Taxonomie
PGPORT=5599 ./scripts/check-migration-0004.sh   # Ergebnis-IDs
PGPORT=5599 ./scripts/check-migration-0005.sh   # Namensquelle
PGPORT=5599 ./scripts/check-migration-0006.sh   # Ergebnisse nachholen
python3 scripts/check-vokabular.py              # braucht keine Datenbank
```

`check-migration-0003.sh` prüft sechs Dinge: die Constraints werden auf
einer leeren Datenbank gesetzt; eine befüllte wird migriert, ohne dass sich
eine Zeilenzahl oder ein bestehender Spaltenwert ändert; jede der sechs
unmöglichen `(category, circuit)`-Kombinationen wird vom richtigen
Constraint abgelehnt und jede der fünf möglichen angenommen; Altvokabular
im Bestand führt zu einer Meldung mit allen Befunden, ohne dass etwas
angewendet wird; das Vokabular steht nur an einer Stelle; die
Anzeige-Übersetzungen in `js/races.js` haben genau die Schlüssel des Enums.

`check-vokabular.py` parst die Dateien unter `backend/app` und meldet
Literal-Typen und fest getippte Aufzählungen, die ein Vokabular ein zweites
Mal beschreiben. Absichtlich kein `grep`: eine Textsuche kann einen
Kommentar, der das alte Vokabular zitiert, nicht von echtem Code
unterscheiden - die erste Fassung dieses Tests scheiterte genau daran und
hätte sich durch Umformatieren beschwichtigen lassen. Im Syntaxbaum tauchen
Kommentare und Docstrings nicht auf. Ein einzelner Wert bleibt erlaubt
(`category="wt"` im Scraper ist ein Schreibvorgang, keine Aufzählung).

### Kein Backup, und was das für Migrationen heisst

Diese Datenbank hat keinen Rückweg. Zwei Gründe, beide gemessen, nicht
vermutet:

- Der **Free-Plan** bietet keine automatischen Backups.
- Die **`ipAllowList` ist leer** (abgefragt über die Render-API). Render
  lässt damit keine externen Verbindungen zu. Ein `pg_dump` von aussen ist
  nicht möglich, egal von welchem Rechner - auch nicht mit der External
  Database URL.

Ein Render Cron Job für `app/backup.py` wäre der saubere Weg, ist aber
kostenpflichtig; dieses Projekt soll vorerst kostenlos bleiben. Was bleibt:

1. **Die sieben CSV-Exporte im Browser** herunterladen
   (`/api/export/*.csv`). Sie gehen über den Webservice, der intern an die
   Datenbank kommt, und brauchen kein lokales Werkzeug. Grenze: sie prüfen
   ihre Zeilenzahlen nicht (siehe unten).
2. **Eine IP im Render-Dashboard freischalten** und dann lokal dumpen. Das
   öffnet die Datenbank nach aussen, solange die Regel steht.

Die praktische Folge steht als Regel für jede Migration: **solange es
keinen Rückweg gibt, darf eine Migration nur Dinge tun, die sich neu
berechnen lassen.** Das heisst konkret:

| erlaubt | nicht erlaubt ohne Dump |
|---|---|
| Spalte hinzufügen | Spalte löschen |
| neue Spalte füllen | Bestandsspalte überschreiben |
| Constraint setzen (und bei Verstoss abbrechen) | Werte umschreiben, damit ein Constraint passt |
| Index anlegen | Primärschlüssel ändern |

Die Migrationen 0002 (gender), 0003 (Taxonomie) und 0004 (Ergebnis-IDs)
halten sich daran - keine von ihnen hat einen Bestandswert angefasst, und
die Prüfskripte belegen das jeweils an einer befüllten Testdatenbank. Offen
und ausdrücklich gesperrt sind damit Befund 7 Schritt 3 (`riders.id` auf die
Wikidata-QID) und ein späteres `DROP` von `race_results.rider_name` /
`team_name`.

### Bekannte Grenze des CSV-Exports (nicht des Backups)

Scheitert die Abfrage eines `/api/export/*.csv`-Endpunkts erst nachdem das
Streamen begonnen hat, ist der Statuscode 200 schon gesendet - der Client
bekommt eine abgeschnittene oder leere Datei, die wie ein Erfolg aussieht.
Das liegt am Streaming selbst und nicht an einer verschluckten Exception.

Das **Backup** teilt diese Grenze nicht: `app/backup.py` verbindet sich
direkt per psycopg, geht nicht über HTTP, und `verify` vergleicht die
Zeilenzahlen im Manifest gegen die Datenbank. Ein abgeschnittener Dump
fällt dort auf. Wer die CSV-Endpunkte für ein Backup benutzt, sollte die
Zeilenzahlen selbst gegenprüfen.

## Geschlechts-Dimension

Weder `races` noch `riders` noch `teams` hatten eine Spalte für Geschlecht,
und die Primärschlüssel entstanden allein aus Name, Saison und Kategorie.
Gegen den echten Code ausgeführt:

```
race_id_for(2026, 'wt', 'Ronde van Vlaanderen')  ->  2026-wt-ronde-van-vlaanderen
                                                     identisch für M und W
rider_id_for('Simon Yates')                      ->  simon-yates
                                                     jede zweite Person gleichen
                                                     Namens in derselben Zeile
```

Das Frauen-Rennen hätte das Männer-Rennen per `ON CONFLICT (id) DO UPDATE`
stillschweigend überschrieben statt daneben zu existieren. Migration
`0002_gender.sql` und `app/gender.py` beheben das.

### Die ID-Regel: "w--" als Präfix

Männer-IDs bleiben **unverändert**, Frauen-IDs bekommen das Präfix `w--`:

| | Männer | Frauen |
|---|---|---|
| Rennen | `2026-wt-ronde-van-vlaanderen` | `w--2026-wt-ronde-van-vlaanderen` |
| Fahrer | `simon-yates` | `w--simon-yates` |
| Team | `sd-worx-protime` | `w--sd-worx-protime` |

Damit ist **keine Datenmigration nötig**: jede der ~2.000 Renn-Zeilen, 517
Fahrer-Zeilen und 18 Team-Zeilen behält ihren Primärschlüssel, und kein
Fremdschlüssel muss nachgezogen werden. Der Preis ist eine Asymmetrie -
"m" ist implizit.

Das ist die bewusste Wahl gegenüber der Alternative, die bestehenden IDs
mit umzubenennen. Der Grund ist nicht Bequemlichkeit: es gibt für diese
Datenbank kein automatisches Backup (Renders Cron Jobs sind
kostenpflichtig, und das Projekt soll vorerst kostenlos bleiben), und ein
Umschreiben von Primärschlüsseln über fünf Tabellen ohne Netz ist genau
die Migration, die man nicht fährt.

**Warum genau zwei Bindestriche.** `text.slugify` zieht Zeichenfolgen zu
einem *einzelnen* `-` zusammen und schneidet Ränder ab. Kein Slug enthält
also `--`. Nachgemessen über 50.000 Zufallsfolgen aus einem Alphabet mit
Leerzeichen, Strichen aller Art, Apostrophen und Satzzeichen: null
Verstösse. Daraus folgt, dass eine ID mit `--` eindeutig eine Frauen-ID ist
und keine Bestands-ID eine sein kann.

Ein einfaches `w-` wäre **nicht** sicher gewesen: `slugify("W Smith")`
ergibt `w-smith`, und das ist ein gültiger Männer-Slug. Mit `w-` als
Präfix hätte eine Fahrerin "Smith" mit einem Fahrer "W Smith" kollidiert -
also genau der Fehler, den diese Änderung behebt.

Belegt gegen den Code aus `origin/main`: 22 IDs (Rennen mit und ohne
Circuit, Fahrernamen mit Umlauten/Akzenten/Bindestrichen, Teamnamen)
erzeugen mit `gender='m'` zeichengleich die alten IDs, und die Schnittmenge
zwischen allen Männer- und allen Frauen-IDs ist leer.

### Was in der Datenbank steht

`gender CHAR(1) NOT NULL DEFAULT 'm'` mit `CHECK (gender IN ('m','w'))` auf
`races`, `riders` und `teams`. `CHAR(1)` mit CHECK statt eines Enum-Typs:
`ALTER TYPE ... ADD VALUE` ist in Postgres nicht transaktional
zurücknehmbar, und ein CHECK lässt sich in einer gewöhnlichen Migration
ändern.

Default `'m'` für den Bestand, weil alles Gespeicherte Männer-Radsport ist -
die Scraper lesen ausschliesslich Männer-Quellen
(`scrapers/wikipedia_teams.WORLDTEAMS_PAGE`,
`scrapers/wikipedia_race_history.season_page_titles`).

Dazu zusammengesetzte Indizes in der Spaltenreihenfolge der Abfragen
(`(gender, season, category)` für Rennen, `(gender, last_name, first_name)`
und `(gender, current_team_id)` für Fahrer, `(gender, name)` für Teams) -
ein Index nur auf `gender` würde bei zwei Werten kaum aussortieren.

### API

`gender` ist Filterparameter **und** Antwortfeld bei `/api/riders`,
`/api/teams`, `/api/race-history` und `/api/race-history/seasons`. Der
Default ist `'m'`: wer den Parameter nicht kennt, bekommt genau das, was es
vorher gab. Nachgemessen - 36 Endpunkte gegen den Stand davor: 19 byteweise
unverändert, 15 nur um `gender` (bzw. `wikidata_qid`) ergänzt, 0
unerwartete Abweichungen.

`gender=x` wird mit HTTP 422 abgewiesen (`Literal["m","w"]`).

Die Detail-Endpunkte (`/api/teams/{id}`, `/api/riders/{id}`,
`/api/race-history/{id}`) haben **keinen** `gender`-Parameter: das
Geschlecht steckt schon in der ID.

### Frontend

Der Umschalter in `js/nav.js` gab es schon; er zeigte nur einen
"kommt bald"-Platzhalter. Jetzt gibt `nav.apiGender()` den Wert an jeden
Listen-Aufruf weiter, und der Platzhalter entscheidet sich an der
**Antwort**:

```js
if (await renderComingSoonIfWomen(content, async () => {
    const res = await Api.getTeams(null, apiGender());
    return !(res.teams || []).length;
})) return;
```

Vorher hing er allein am Umschalter (`if (isWomen()) return true;`). Damit
hätte er auch dann noch gestanden, wenn längst Frauen-Daten in der
Datenbank liegen - und jemand hätte den Aufruf in sechs Seiten-Modulen
entfernen müssen, um das zu merken. Sobald der Frauen-Import Zeilen
schreibt, verschwindet der Platzhalter von selbst, ohne Code-Änderung.

Ein Fehler beim Abruf gilt dabei **nicht** als "keine Frauen-Daten" - die
Seite geht dann ihren eigenen Fehlerpfad, statt "kommt bald" zu behaupten,
wenn das Backend schlicht nicht erreichbar ist.

`news.html` bleibt beim reinen Platzhalter: der RSS-Auszug ist allgemeine
Radsport-Presse und kennt die Dimension nicht.

Im Browser nachgemessen (Chromium, `scripts/check-pages.mjs` plus eigene
Läufe): ohne Frauen-Daten zeigen alle vier geschlechtsabhängigen Seiten den
Platzhalter und senden `gender=w` an die API; mit zwei Frauen-Teams, zwei
Fahrerinnen und zwei Frauen-Rennen in der Datenbank verschwindet er, die
Seiten rendern, der Männer-Kalender zeigt keine Frauen-Rennen und
umgekehrt. Keine JavaScript-Fehler.

### Stabile Fahrer-IDs: der Plan

Der Namens-Slug ist von Natur aus nicht eindeutig. Das Geschlecht nimmt
einen Teil des Problems weg, aber nicht alles: zwei Fahrerinnen gleichen
Namens kollidieren weiter.

Die Lösung ist ein Schlüssel aus der Wikidata-QID. Migration 0002 legt
`riders.wikidata_qid` samt partiellem UNIQUE-Index an; die Infrastruktur
zum Füllen steht (`scrapers/wikipedia.py::fetch_wikidata_ids` holt QIDs
gebatcht, bis 50 Titel pro Request, und `scrapers/wikidata.py` nutzt sie
schon für die Strava-Profile).

Der Wechsel des Primärschlüssels ist **absichtlich nicht Teil dieses
Schritts**. Er schreibt `riders.id` und die Fremdschlüssel in
`rider_team_stints` und `rider_season_points` um, und ohne Backup ist das
nicht zu verantworten. Die Reihenfolge, wenn es soweit ist:

1. QIDs für alle Fahrer füllen (Job-Lauf, rein additiv, kein Risiko) und
   prüfen, für wie viele keine QID zu finden ist - für die braucht es die
   Wikipedia-URL als Ersatzschlüssel.
2. Vorher ein Dump - und der ist **heute nicht möglich**: die
   `ipAllowList` der Datenbank ist leer, sie nimmt also überhaupt keine
   externen Verbindungen an. Ein `pg_dump` gegen die External Database URL
   scheitert unabhängig davon, von welchem Rechner es kommt. Siehe "Kein
   Backup, und was das für Migrationen heisst" - dort stehen die beiden
   Wege, die bleiben.
3. Migration, die `riders.id` auf die QID umstellt. `rider_team_stints` und
   `rider_season_points` brauchen dafür `ON UPDATE CASCADE` auf ihrem
   Fremdschlüssel - haben sie heute nicht, nur `ON DELETE CASCADE`. Das
   muss dieselbe Migration mitbringen, sonst bleiben die Kinder auf der
   alten ID sitzen.
4. `race_results` ist **nicht** betroffen: dort steht `rider_name` als
   Text, keine `rider_id`. Das zu verknüpfen ist Befund 8 und ein eigener
   Schritt.

### Was der Frauen-Import anzufassen hat

Nach diesem Schritt ist der Frauen-Radsport eine Frage von
Scraper-Ergänzungen, nicht mehr von Schema-Arbeit. Die Stellen:

| Datei | Was |
|---|---|
| `scrapers/wikipedia_teams.py` | `WORLDTEAMS_PAGE`/`WORLDTEAMS_SECTION` zeigen auf den Artikel "UCI World Tour". Die Frauen haben eigene Seiten ("UCI Women's WorldTour", Abschnitt mit den WorldTeams). `team_id_for(name, 'w')` und `gender='w'` mitgeben. |
| `scrapers/wikipedia_race_history.py` | `season_page_titles()` baut Titel wie `"{Jahr} UCI World Tour"`. Frauen: `"{Jahr} UCI Women's World Tour"`. Die Tabellenstruktur dort ist **nicht geprüft** - das ist die eigentliche Recherche-Arbeit dieses nächsten Schritts. |
| `scrapers/wikipedia_riders.py` | `roster_riders_for_team(team)` liest den Kader-Abschnitt des Team-Artikels; bei Frauen-Teams heisst der Abschnitt möglicherweise anders. `rider_id_for(name, 'w')` und `gender='w'`. |
| `app/scheduler.py` | `refresh_teams`/`refresh_rosters`/`refresh_race_history` laufen heute je einmal für Männer. Entweder eine Schleife über `('m','w')` oder eigene Jobs - und dann das Zeitbudget prüfen, das sich auf einen Durchlauf bezieht (siehe "Zeitbudget statt fester Batch-Größe"). |
| `app/race_meta.py` | Die Grand-Tour- und Monument-Slugs der Frauen stehen dort **schon** drin (Tour de France Femmes, Giro d'Italia Women, La Vuelta Femenina, die Frauen-Monumente). Nichts zu tun, ausser die echten `races.name`-Werte gegenzuprüfen. |
| `app/config.py` | `RACE_HISTORY_CIRCUITS`/`RACE_HISTORY_START_YEAR` gelten für beide; prüfen, ab welchem Jahr die Frauen-Saisonseiten brauchbar sind. |

Nicht anzufassen: Schema, IDs, API-Parameter, Frontend - das ist mit
diesem Schritt erledigt.

### Prüfen

```bash
PGPORT=5599 ./scripts/check-migration-0002.sh
```

Sechzehn Prüfungen: Zeilenzahlen unverändert, jede Spalte ausser `gender`
unverändert (Prüfsumme über eine ausdrückliche Spaltenliste, dieselbe
Datenbank vor und nach der Migration), Bestand überall `gender='m'`, keine
verwaiste Fremdschlüssel-Referenz über alle sieben Beziehungen, ein
Männer- und ein Frauen-Rennen gleichen Namens in derselben Saison ergeben
zwei Zeilen, und `gender='x'` wird vom CHECK abgelehnt.

Verglichen wird **dieselbe** Datenbank vor und nach der Migration, nicht
zwei getrennt geseedete: `last_updated`/`seeded_at` stehen auf `now()` und
weichen dann ab, ohne dass die Migration daran schuld ist. Genau darauf
ist der erste Versuch hereingefallen.

## Datenbank-Zugriff: Verbindungs-Pool

Alle Zugriffe in `app/db.py` und `app/db_races.py` laufen über einen
`psycopg_pool.ConnectionPool`, der beim ersten Zugriff entsteht (nicht beim
Import - das Modul muss auch ohne `DATABASE_URL` importierbar bleiben) und im
`lifespan` von `app/main.py` geschlossen wird.

Vorher öffnete **jeder** Aufruf von `_connect()` eine eigene Postgres-
Verbindung. Gemessen an einem Kader-Lauf (18 Teams + 517 Fahrer):

| | vorher | nachher |
|---|---|---|
| Verbindungsaufbauten | 535 | 1 (aus dem Pool geliehen) |
| SQL-Abfragen | 535 | 2 |
| Dauer (lokal, ohne TLS) | 2,83 s | 0,02 s |

Über TLS zu Renders Postgres fällt das deutlich stärker ins Gewicht, und der
kostenlose Plan erlaubt nur wenige gleichzeitige Verbindungen - das war die
harte Grenze vor jeder Vergrößerung des Bestands.

`_connect()` hat Signatur **und Semantik** behalten: `pool.connection()`
committet beim regulären Verlassen des Blocks und rollt bei einer Exception
zurück, genau wie `psycopg.connect()` vorher. Deshalb musste kein einziger
der vielen Aufrufer angepasst werden.

Größe per Env-Var (`DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`,
`DB_POOL_TIMEOUT_SECONDS`, siehe `.env.example`). Bewusst klein: ein
Web-Prozess plus ein Scheduler mit wenigen Threads braucht nicht mehr.

### Batch-Schreibzugriffe

`upsert_teams(list)` und `upsert_riders(list)` schreiben per `executemany` in
einer Transaktion; die Einzel-Varianten `upsert_team`/`upsert_rider`
delegieren daran, damit das SQL nur an einer Stelle steht.
`scheduler.refresh_rosters` sammelt erst alle Kader und schreibt dann einmal -
die Fehlerbehandlung pro Team bleibt, ein Team mit geänderter Wikipedia-Seite
reißt die übrigen nicht mit.

Steht ein Fahrer auf zwei Kadern (bei Wechseln listen ihn beide
Team-Artikel), gewinnt jetzt der **erste** Treffer und die Doppelnennung wird
gezählt und geloggt. Vorher gewann willkürlich der letzte, ohne Hinweis. Die
saubere Lösung ist eine Zuordnung pro Saison statt eines einzelnen
`current_team_id` - siehe "Bekannte Lücken".

### Aufgelöste N+1-Abfragen

| Stelle | vorher | nachher |
|---|---|---|
| `db.replace_stints` (4 Stints) | 8 Abfragen | 3 |
| `db_races.get_race` (3 Etappen) | 6 Abfragen | 4 |
| `db_races.get_race` (21 Etappen) | 24 Abfragen | 4 |

`replace_stints` löst alle Team-Wiki-URLs in einer Abfrage
(`WHERE wiki_url = ANY(%s)`) auf statt einer pro Stint; `get_race` holt die
Ergebnisse aller Etappen mit `WHERE stage_id = ANY(%s)` und gruppiert in
Python.

Dazu zwei Teilindizes auf `riders` für die Rückstands-Abfragen des
Schedulers (`history_fetched_at IS NULL`, `strava_checked_at IS NULL`) - für
`races` gab es das Gegenstück schon, hier fehlte es. `EXPLAIN` zeigt jetzt
einen Index Scan statt Seq Scan plus Sortierung über die ganze Tabelle.

## Doppelstrukturen

Ziel des Projekts ist, weitere und größere Datenbanken einzubinden -
Frauen-Radsport, weiter zurückreichende Saisons. Jede Stelle, an der
dieselbe Sache zweimal beschrieben ist, muss dabei zweimal erweitert
werden, und die zweite Stelle wird vergessen. Dieser Abschnitt hält fest,
welche Doppelungen aufgelöst wurden und wie.

### Ein Vokabular für die drei Achsen

Für dieselbe Sache gab es zwei Aufzählungen:

| | Werte | wer schreibt sie |
|---|---|---|
| `Team.category` | `wt`, `pro`, `cont` | `scrapers/wikipedia_teams.py`, fest `"wt"` |
| `RaceRecord.category` | `wt`, `proseries`, `continental` | `db_races.upsert_race_skeleton` |

Dazu die Circuits als dritte Achse, verstreut über `config.py`, den Router,
den Scraper und `js/races.js`, und `gender` als `Literal["m", "w"]` in
sieben Dateien neben `app/gender.py`.

Die Folge war nicht theoretisch: `/api/teams?category=pro` nahm den Wert an
und antwortete zwangsläufig leer, weil keine Zeile ihn enthalten konnte -
ein Filter, der aussah als funktioniere er. Bei jeder weiteren Datenbank
hätte man alle Kopien mitpflegen müssen.

Jetzt steht jede Achse einmal:

| Achse | Werte | Modul |
|---|---|---|
| `gender` | `m`, `w` | `app/gender.py` (`Gender`, `GENDERS`) |
| `category` | `wt`, `proseries`, `continental` | `app/taxonomy.py` (`Category`, `CATEGORIES`) |
| `circuit` | `africa`, `asia`, `europe`, `america`, `oceania` | `app/taxonomy.py` (`Circuit`, `CIRCUITS`) |

Die Laufzeit-Tupel sind per `typing.get_args()` aus den Literal-Typen
abgeleitet, nicht danebengeschrieben: FastAPI und Pydantic brauchen den Typ,
Schleifen und Fehlermeldungen brauchen die Werte, und beides kommt aus einer
Quelle. Sonst stünde das Vokabular auch innerhalb dieser Module zweimal.

Die Achsen sind unabhängig filterbar, mit **einer** Abhängigkeit: `circuit`
ist ausschließlich bei `category = 'continental'` gesetzt, weil die UCI nur
die dritte Stufe geografisch gliedert. Diese Regel steht einmal als
`taxonomy.kategorie_braucht_circuit()`, wird von `pruefe_achsen()` in beide
Richtungen geprüft (vorher fehlte die zweite: ein `circuit` bei
`category='wt'` lief durch und wäre als Teil der Renn-ID in der Datenbank
gelandet - eine ID, die kein zweiter Lauf reproduziert) und ist als
`CHECK ((category = 'continental') = (circuit IS NOT NULL))` in Migration
0003 auch in der Datenbank durchgesetzt.

Aus derselben Quelle kommt jetzt auch die Seeding-Liste des Schedulers:
`taxonomy.achsen_kombinationen()` statt der fest getippten Paare in
`scheduler._race_history_series()`. Eine vierte Kategorie hätte man vorher
an zwei Stellen nachtragen müssen - und beim Vergessen der zweiten wäre sie
stillschweigend nie geseedet worden.

**Keine Datenmigration.** Gewählt wurde `wt`/`proseries`/`continental`, weil
das in der Datenbank steht. Belegt über den Schreibpfad, der alle Zeilen
abdeckt statt einer Stichprobe: `races.category` schreibt ausschließlich
`db_races.upsert_race_skeleton`, aufgerufen aus der einen Schleife in
`refresh_race_history()`, und die geht genau über diese drei Werte;
`teams.category` schreibt nur `scrapers/wikipedia_teams.py`, fest auf
`"wt"`. `pro`/`cont` war damit totes Vokabular. Das ist wichtig, weil es für
diese Datenbank kein automatisches Backup gibt (siehe
"Geschlechts-Dimension"): Migration 0003 setzt nur CHECK-Constraints und
schreibt keinen Wert um. Enthielte der Bestand trotzdem Altvokabular, würde
sie **alle** Befunde in einer Meldung nennen und abbrechen, ohne etwas
angewendet zu haben - nicht beim ersten stehenbleiben.

#### `/api/teams?category=` nimmt nur noch `wt`

Der Parameter ist auf `taxonomy.TeamCategory` getippt, und das ist derzeit
nur `wt` - nicht weil die Kategorie-Achse kleiner wäre, sondern weil die
`teams`-Tabelle nichts anderes enthalten kann: die Quelle
(Wikipedia-Artikel "UCI World Tour") listet ausschließlich WorldTeams. Ein
angenommener Wert, auf den nie eine Zeile passt, ist schlechter als ein
abgelehnter: `?category=pro` liefert jetzt 422 statt einer leeren Liste.

Kommen ProTeams oder Continental-Teams dazu, gehört der Wert in
`TeamCategory` **und** in den Scraper. Steht er nur in `TeamCategory`,
entsteht derselbe Filter wieder; der Kommentar an `TeamCategory` sagt das,
und `scripts/check-vokabular.py` erzwingt zumindest, dass er nur an dieser
einen Stelle steht.

Recherchestand dazu (2026-09-14): die Wikipedia-Seiten
`List of {Jahr} UCI ProTeams and Continental teams` existieren - per
Websuche für 2020, 2021, 2022 und 2026 bestätigt. Ihr **Tabellenaufbau**
ist ungeprüft: Wikipedia ist aus dieser Arbeitsumgebung durch den
Egress-Proxy gesperrt (403), ein Abruf war nicht möglich. Der konkrete
nächste Schritt ist damit: Seite abrufen, Spaltenaufbau mit dem von
`scrapers/wikipedia_teams.py` erwarteten vergleichen, dann Scraper und
`TeamCategory` gemeinsam erweitern. Bis dahin bleibt der Filter bei `wt`,
statt Werte anzunehmen, für die es keine Zeilen gibt.

### Ergebnisse eines Fahrers

Der erste Lesepfad, der `race_results.rider_id` benutzt - und der Grund,
warum Befund 8 überhaupt lohnt.

```
GET /api/riders/{id}/results?limit=50&offset=0
```

**Eigener Endpunkt, kein Feld in `/api/riders/{id}`.** Die Detailantwort hat
eine feste Größe (Stammdaten, Saisons, Stationen); diese Liste hat keine -
ein Fahrer mit sieben Saisons kommt auf einige hundert Zeilen, weil
Etappenergebnisse mitzählen. Als Feld hätte sie jede Profilansicht mit Daten
belastet, die erst beim Hinunterscrollen gebraucht werden. Serverseitig
`limit` max. 200, Default 50; `total` liegt in der Antwort, damit das
Frontend das Ende erkennt, ohne eine leere Seite anzufordern.

Kein `gender`-Parameter: das Geschlecht steckt in der Fahrer-ID (siehe „Die
ID-Regel").

**Warum 404 bei unbekannter ID.** Der Endpunkt prüft zuerst, ob der Fahrer
existiert. Ohne diese Prüfung wäre die Antwort auf einen Tippfehler eine
leere Liste - „hat keine Ergebnisse" statt „gibt es nicht". Dieselbe
Verwechslung, die die Team-Statistik hatte.

**Die Abfrage geht über `rider_id`, nicht über den Namen.** Ein
Namensvergleich hätte hier dieselbe stille Lücke: eine abweichende
Schreibweise in der Ergebnistabelle ergäbe eine leere Liste, die wie ein
Ergebnis aussieht.

#### Was die Seite zeigt

`js/rider.js` lädt die Liste **nach** dem Profil, ohne `await` und mit
eigenem `try/catch`. Scheitert sie, steht das Profil weiter da und nur der
Ergebnis-Abschnitt trägt eine Meldung, die das ausdrücklich sagt. Vorher
wäre der Fehler in den äusseren `catch` gelaufen, und der zeigt „Dieser
Fahrer wurde nicht gefunden" - über dem vollständig geladenen Fahrer.

Pro Zeile: Saison, Rennen, bei Etappen die Etappennummer, Platz und
Zeit/Abstand. `stage_number IS NULL` heisst Gesamtwertung **oder**
Eintagesrennen - welches von beiden, steht nicht in der Ergebniszeile,
deshalb wird dort gar nichts behauptet und nur Etappen werden benannt
(gleiche Entscheidung wie in `js/team.js`). Platz 1 bekommt das
Pokal-Symbol, Grand Tours ein Abzeichen. „Weitere laden" erscheint nur,
solange `total` grösser ist als das Geladene.

#### Prüfen

```bash
node scripts/check-rider-results.mjs   # braucht Backend :8001 + statisch :8000
```

25 Prüfungen in Chromium: die Tabelle erscheint mit 50 Zeilen, der Knopf
hängt die restlichen 10 an und verschwindet danach, Zählzeile stimmt,
Pokal genau bei den zwei Siegen, GT-Abzeichen genau bei den drei
Grand-Tour-Zeilen, ein Fahrer ohne Ergebnisse bekommt den Hinweis statt
eines Fehlers, und bei abgewürgtem Ergebnis-Endpunkt bleibt das Profil
stehen.

**Warum ein eigenes Skript und nicht `check-pages.mjs`:** dort wird
geprüft, dass die Seite rendert und keinen JavaScript-Fehler wirft. Die
Ergebnisliste wird aber absichtlich nachgeladen und fängt ihre Fehler
selbst - sie kann also still fehlen, während die Seite einwandfrei
aussieht. Genau das würde `check-pages.mjs` nicht bemerken.

Gegengeprüft, dass das Skript etwas taugt: mit `arguments.callee` statt der
benannten Funktion schlagen drei Prüfungen fehl (die Liste bleibt bei 50
Zeilen), mit einem nicht erhöhten `offset` zwei (die zweite Seite hängt
dieselben Zeilen erneut an, 100 statt 60). Nicht gegengeprüft ist der
Fehlerpfad selbst: die Zusicherung dafür existiert und besteht, aber ein
Versuch, sie gezielt zu brechen, hat statt des Fehlerpfads die Syntax
zerstört.

### Renn-Daten: ein Pfad statt zwei

Rennen gab es zweimal im Baum:

| | alter Pfad | Renn-Historie |
|---|---|---|
| Scraper | `scrapers/wikipedia_races.py` | `scrapers/wikipedia_race_history.py` |
| Speicher | JSON-Cache (`app/cache.py`) | Postgres (`races`, `race_stages`, `race_results`) |
| Modelle | `Race`, `CalendarEvent`, `RiderResult`, `LiveResult` | `RaceRecord`, `RaceStage`, `RaceResultEntry` |
| Endpunkte | `/api/races`, `/api/calendar`, `/api/results` | `/api/race-history*` |
| Umfang | aktuelle Saison | alle Saisons seit 2020 |
| Jobs | `refresh_calendar`, `refresh_results` | `refresh_race_history` |

Der alte Pfad ist entfallen. Er lieferte eine Teilmenge dessen, was die
Renn-Historie ohnehin hat, und auf Renders Free-Plan war sein Speicher nach
jedem Deploy leer - die Startseite zeigte dann einen leeren Kalender, bis
der nächste Scraping-Lauf durch war. Zwei Scraper für dieselben
Wikipedia-Seiten hieß außerdem: doppelte Wikipedia-Requests und zwei
Stellen, an denen ein geändertes Tabellenlayout repariert werden muss.

Vor dem Löschen geprüft, ob der neue Pfad den alten wirklich ersetzt: die
Team-Statistik auf der Team-Detailseite brauchte die Team-Zuordnung der
Ergebnisse. Beide Pfade benutzen denselben Zeilen-Parser
(`parse_result_row`), `race_results.team_name` ist also zeichengleich mit
dem, was im Cache unter `result.results[].team` stand. Die Statistik konnte
damit 1:1 auf die Datenbank umziehen - und zählt seitdem richtig, siehe
unten.

`parse_result_row` und die Monatsnamen-Tabelle aus `wikipedia_races.py`
braucht die Renn-Historie weiter; sie stehen jetzt in
`scrapers/wikipedia_tables.py`. Die Funktion gibt dabei direkt ein
`RaceResultEntry` zurück statt eines `RiderResult`, das der einzige
Aufrufer anschließend Feld für Feld umkopiert hat - zwei Modelle für
dieselbe Sache, eines davon weg.

### Ergebniszeilen: verknüpft statt nur beschriftet

`race_results` kannte Fahrer und Team nur als Text:

```sql
rider_name TEXT NOT NULL,
team_name  TEXT
```

Das ist der Rohwert aus der Wikipedia-Ergebnistabelle und mit nichts
verbunden. Zwei Folgen:

- Die Fahrer-Detailseite kann daraus nicht "seine Ergebnisse" zeigen
  (Befund 8).
- Die Team-Statistik verglich Zeichenketten: `res.team_name = teams.name`.
  Wird ein Team umbenannt - „Jumbo–Visma" wurde „Team Visma–Lease a Bike" -
  verliert es damit seine gesamte Historie, **ohne dass ein Fehler
  auftaucht**. Die Seite zeigt einfach null Siege für die Jahre davor
  (Befund 18).

Migration 0004 legt `rider_id` und `team_id` daneben. Additiv: die
Textspalten bleiben stehen, kein Bestandswert wird angefasst (Begründung
unter „Kein Backup, und was das für Migrationen heisst").

#### Vier Wege zur Zuordnung, und keiner rät

Der nützlichste Schlüssel lag schon da: `rider_team_stints.team_id` ist über
die **Wiki-URL** des Teams aufgelöst, nicht über den Namen. Die Tabelle weiß
also, in welchem Jahr ein Fahrer bei welchem Team war - und unter welchem
Namen dieses Team damals lief.

| Schritt | Weg | löst |
|---|---|---|
| A | `riders.name` = `rider_name`, gleiches Geschlecht | `rider_id` |
| B | `teams.name` = `team_name`, gleiches Geschlecht | heutige Teamnamen |
| C | Station des Fahrers in der Saison des Rennens | Schreibvarianten („Team Jumbo Visma" gegen „Jumbo–Visma") |
| D | Abbildung „Stationsname → team_id" | alte Namen, auch bei unbekannten Fahrern |

Jeder Schritt setzt eine ID **nur bei eindeutigem Treffer**
(`HAVING count(...) = 1`). Zwei mögliche Treffer heißen `NULL`. Eine falsche
Zuordnung wäre schlimmer als keine: sie sieht wie ein Ergebnis aus. Deshalb
bleibt auch ein Fahrer, der mitten in der Saison gewechselt ist, für Schritt
C ohne Team.

#### Die Regel steht einmal, in der Datenbank

Sie gilt für zwei Dinge: den Bestand (einmal) und jedes künftig gescrapte
Ergebnis (bei jedem Schreiben). Stünde sie zweimal - als Backfill im
SQL und als Python in `db_races.py` -, liefen die beiden auseinander, sobald
eine Regel nachgeschärft wird. Genau die Doppelung, die dieses Projekt
vermeiden will.

Sie steht deshalb als Datenbankfunktion `race_results_ids_nachtragen`: ohne
Argument für alle Zeilen, mit `race_id` für eines. Migration 0004 ruft sie
für den Bestand, `db_races.replace_race_details` für das Rennen, das es
gerade geschrieben hat - in derselben Transaktion wie die Ergebniszeilen.
Eine Änderung der Regel ist damit eine neue Migration, die die Funktion
ersetzt, und gilt sofort für beide Aufrufer.

Nebenwirkung, die erwünscht ist: wird ein Rennen erneut gescrapt, bekommen
Zeilen eine ID, die beim ersten Mal keine bekamen - etwa weil der Fahrer
damals noch nicht in `riders` stand.

#### Wie die Statistik jetzt zählt

```sql
res.team_id = %(team_id)s
OR (res.team_id IS NULL AND res.team_name = %(team_name)s)
```

Der zweite Zweig ist der alte Namensvergleich und bleibt als Rückfall für
nicht zugeordnete Zeilen. Überlappen können die beiden nicht (einer verlangt
eine gesetzte `team_id`, der andere keine), es wird also nichts doppelt
gezählt. Nachgemessen: mit gesetzten IDs liefern beide Statistik-Endpunkte
**byte-identische** Antworten wie vorher, wo der Name schon traf - der
Unterschied entsteht nur da, wo er nicht traf.

#### Was die Abdeckung realistisch ist

Gemessen in Produktion (Startlog des Deploys von Migration 0004, Lauf über
22.474 Ergebniszeilen in 15 Sekunden):

| | Zeilen | Anteil |
|---|---:|---:|
| Ergebniszeilen insgesamt | 22.474 | |
| `rider_id` gesetzt | 12.123 | 53,9 % |
| `team_id` gesetzt | 14.502 | 64,5 % |

Aufgeteilt nach Zuordnungsweg:

| Schritt | Zeilen | Anteil der zugeordneten |
|---|---:|---:|
| B heutiger Teamname | 5.414 | 37,3 % |
| C Station in der Saison | 5.446 | 37,6 % |
| D alter Teamname | 3.642 | 25,1 % |

**Die Vorhersage in dieser Datei war falsch.** Hier stand, `rider_id` werde
„für die Mehrheit der Zeilen NULL bleiben", weil `riders` nur die Kader der
aktuellen 18 WorldTeams enthält (517 Fahrer) und `race_results` über alle
Saisons seit 2020 auch ProSeries und Continental abdeckt. Tatsächlich sind
es 53,9 % zugeordnete Zeilen. Der Grund für den Irrtum: gezählt werden
Ergebnis*zeilen*, nicht Namen - dieselben 517 Fahrer tauchen über die
WorldTour-Rennen hinweg tausendfach auf, und WorldTour-Rennen stellen den
grössten Teil der Ergebnisse. Die 46,1 % ohne `rider_id` sind weiterhin die
Datenlage und kein Fehler des Backfills; deshalb bleiben die Spalten
nullable, die Fremdschlüssel `ON DELETE SET NULL` (ein gelöschter Fahrer
darf die Ergebniszeile nicht mitnehmen - das Ergebnis ist auch ohne ihn ein
Fakt) und die Indizes partiell (`WHERE ... IS NOT NULL`).

**Und hier steht, wie gross Befund 18 wirklich war:** die Schritte C und D
zusammen haben 9.088 Zeilen zugeordnet - 62,7 % aller gefundenen Teams.
Genau diese Zeilen konnte der frühere Vergleich `res.team_name = teams.name`
**nicht** finden, weil dort ein alter oder anders geschriebener Teamname
stand. Die Team-Statistik hat also nicht ein paar Randfälle verpasst,
sondern knapp zwei Drittel der zuordenbaren Ergebnisse - stillschweigend,
als „null Siege".

Die Summenprobe stimmt: B + C + D ergibt genau die 14.502 gesetzten
`team_id`. Die drei Wege überlappen sich also nicht, keine Zeile wurde
doppelt gezählt.

Messbar war das nur in Produktion: die Datenbank nimmt keine externen
Verbindungen an. Die Migration berichtet die Zahlen deshalb selbst per
`RAISE NOTICE`, und `app/migrations.py` hat dafür einen Notice-Handler -
vorher verwarf psycopg Server-Meldungen stillschweigend, eine Migration
konnte abbrechen, aber nicht berichten. Im Startlog steht nach dem Deploy:

```
0004: 22474 Ergebniszeilen insgesamt
0004: rider_id gesetzt bei 12123 Zeilen (Schritt A: 12123)
0004: team_id gesetzt bei 14502 Zeilen (B Teamname: 5414, C Station: 5446, D Altname: 3642)
```

#### Was damit möglich wird, aber noch nicht gebaut ist

Ein regelmässiger Aufruf von
`race_results_ids_nachtragen()` ohne Argument, damit neu aufgenommene Fahrer
alte Ergebnisse rückwirkend zugeordnet bekommen; das wäre ein
Volltabellen-Durchlauf und will vorher auf der Free-Tier-Datenbank
gemessen werden.

### Team-Statistik: richtig zählen statt im Browser raten

Die Werte auf der Team-Detailseite (Siege/Podestplätze/Top-10) rechnete
vorher `js/team.js::computeStats` über alle gecachten Ergebnisse. Mit
`findIndex` fand es pro Rennen nur den besten Fahrer eines Teams. Folge:
"Top-10-Platzierungen" waren *Rennen mit mindestens einer
Top-10-Platzierung*, und zwei Podestplätze desselben Teams im selben
Rennen zählten als einer.

Jetzt rechnet `/api/teams/{id}/stats` das per `count(*) FILTER (WHERE ...)`
über die Ergebniszeilen - also Platzierungen, wie das Label sagt.
Etappenergebnisse sind enthalten. Nachgemessen an Testdaten mit sechs
Ergebniszeilen für ein Team (Plätze 1, 9, 2, 2, 1, 1 über drei Rennen):
3 Siege, 5 Podestplätze, 6 Top-10, 3 Rennen.

### Teams: Tabelle statt Tabelle *und* JSON-Datei

Die Teams lagen doppelt: `refresh_teams` schrieb sie in den JSON-Cache,
`refresh_rosters` kopierte sie von dort zusätzlich in die
`teams`-Tabelle. `/api/teams` las den Cache, `/api/teams/{id}/stats` die
Tabelle. Zwei Quellen, die auseinanderlaufen konnten - und auf Renders
Free-Plan nach jedem Deploy genau das taten, weil der Cache auf dem
flüchtigen Dateisystem liegt und die Tabelle nicht.

Jetzt schreibt `refresh_teams` direkt in die Tabelle und alle Leser lesen
von dort. Die Tabelle ist die richtige Quelle: auf sie verweisen
Fremdschlüssel aus `riders` und `rider_team_stints`, sie übersteht Deploys,
und sie hat ein `category`-Feld, über das weitere Teams (Frauen-WorldTeams,
ProTeams) hinzukommen können.

`app/cache.py` bedient damit nur noch News. Das ist eine Entscheidung, die
Begründung steht im Modul-Docstring: News sind ein flacher RSS-Auszug, auf
den nichts verweist und dessen Verlust kein Datenverlust ist (der Feed
liefert sie beim nächsten Lauf wieder), und sie sind das Einzige, was die
Seite ohne Datenbank noch anzeigen kann. Dort steht auch, dass die
JSON-Persistenz auf dem Free-Plan nichts bringt - wirksam ist nur der
In-Memory-Anteil.

### Eine Stelle für `slugify`

`slugify` erzeugt die Primärschlüssel: `rider_id`, `team_id` und über
`db_races.race_id_for` auch `race_id`. Die Funktion stand dreimal im Baum
(`scrapers/wikipedia_teams.py`, `scrapers/wikipedia_riders.py`,
`db_races.py`) plus eine vierte, tote Kopie in
`scrapers/wikipedia_race_history.py`. Jetzt steht sie in `app/text.py`.

Weil ihr Ergebnis in der Datenbank steht, darf sie sich nicht verhalten
ändern: eine andere Ausgabe hieße neue IDs für bestehende Zeilen, und der
nächste Upsert legt Dubletten an statt zu aktualisieren. Nachgewiesen, dass
alte und neue Fassung zeichengleich sind - über 72 echte Namen
(Teamnamen, Fahrernamen mit Umlauten/Akzenten/Apostrophen wie
"Giro d'Italia", Rennnamen mit Halbgeviertstrich wie "Milan–San Remo",
dazu Grenzfälle: leerer String, nur Striche, Emoji, geschützte
Leerzeichen) und über 20.000 zufällige Zeichenfolgen aus einem Alphabet
mit genau diesen Sonderzeichen. Null Abweichungen.

Was `slugify` **nicht** tut: Umlaute und Akzente transliterieren. "Tobias
Müller" wird `tobias-m-ller`, nicht `tobias-mueller`. Das ist unschön, aber
es ist der Stand, auf dem die vorhandenen Zeilen beruhen; eine Änderung
braucht eine Migration, die die alten IDs mitnimmt (Befund 7, stabile
Fahrer-IDs).

### Grand Tours: eine Liste, im Backend

Die Einordnung "ist eine Grand Tour" gab es zweimal, und beide Kopien
waren je anders falsch:

- `wikipedia_races.GRAND_TOURS` verglich Slugs:
  `{"tour-de-france", "giro-d-italia", "vuelta-a-espana"}`. Der Slug von
  "Vuelta a España" ist aber `vuelta-a-espa-a` - die Vuelta fiel durch,
  sobald Wikipedia den Namen mit Akzent schrieb.
- `js/races.js::GRAND_TOUR_NAMES` verglich Anzeigenamen und führte beide
  Vuelta-Schreibweisen auf - an dieser Stelle also richtig, dafür im
  Frontend, wo es beim Erweitern der Datenbank niemand sucht.

Jetzt eine Liste in `app/race_meta.py`, verglichen über den Slug (der macht
aus Halbgeviertstrich, Bindestrich und Apostroph-Varianten dasselbe
Zeichen), mit beiden Slug-Varianten für akzentbehaftete Namen. Die
Frauen-Pendants (Tour de France Femmes, Giro d'Italia Women, La Vuelta
Femenina) stehen mit drin, damit sie nicht später im Frontend nachgetragen
werden müssen. Die fünf Monumente sind aus `wikipedia_races.py` mit
übernommen; sie sind noch von keinem Endpunkt ausgewertet.

`RaceRecord.is_grand_tour` wird beim Lesen aus dem Namen bestimmt
(`db_races._row_to_race`), ist also **keine** Tabellenspalte. Damit wirkt
eine neue Zeile in der Liste sofort für alle Saisons, auch die längst
gescrapten, und braucht keine Migration (die es noch nicht gibt, Befund
10). Der CSV-Export führt das Feld nicht - er spiegelt die
Tabellenspalten, und die Liste als `CASE`-Ausdruck in SQL zu wiederholen
wäre genau die Doppelung, die hier verschwindet.

**Nicht geprüft:** gegen welche Namen die `races`-Tabelle in der
Render-Datenbank tatsächlich gefüllt ist - sie ist aus der
Entwicklungsumgebung nicht erreichbar. Der Abgleich ist eine Zeile SQL:
`SELECT DISTINCT name FROM races ORDER BY name;`

### Frontend-Helfer in `js/ui.js`

Vierfach kopiert war die Datums-Formatierung (races.js zweimal, team.js,
riders.js) - alle vier mit demselben Zeitzonen-Fehler, siehe
"Kalenderdaten" in `js/ui.js`. Dazu kamen:

- `errorPanel` dreifach (races.js, rider.js, team.js) in zwei
  verschiedenen Fassungen: die in races.js nahm einen `detail`-Parameter
  und zeigte ohne ihn "Bitte später erneut versuchen.", die anderen
  kannten ihn nicht. In `js/ui.js` steht die Fassung mit `detail`, aber
  ohne Vorgabetext: bei "Dieser Fahrer wurde nicht gefunden." hilft
  Erneut-Versuchen nicht. Die zwei Aufrufe in races.js, die den Satz
  wirklich wollen, übergeben ihn jetzt selbst.
- die Initialen für die Logo-Kreise zweifach mit **zwei verschiedenen
  Trennregeln**. Das ist kein Versehen: Teamnamen trennen am Strich
  ("Bahrain–Victorious" -> "BV"), Personennamen nicht
  ("Jean-Pierre Drucker" -> "JD", nicht "JP"). Deshalb stehen in
  `js/ui.js` zwei Funktionen (`teamInitials`, `riderInitials`) über einem
  gemeinsamen Kern, nicht eine.

Dabei aufgefallen und mit behoben: beim Umbau von `js/team.js` auf
`/api/teams/{id}/stats` waren dessen lokale Kopien von `errorPanel` und
`initials` entfallen, ohne ersetzt zu werden - und `team.html` lädt kein
Skript, das sie mitbrachte. Die Team-Detailseite lief damit in einen
`ReferenceError`. Dass so etwas überhaupt unbemerkt passieren kann, liegt am
globalen Namensraum - dagegen siehe "Frontend: ES-Module statt globaler
Namen".

`js/team.js` holt das Team jetzt über `GET /api/teams/{id}` statt die
komplette Team-Liste zu laden und darin mit `find()` zu suchen. Damit das
"nicht gefunden" von "gerade kaputt" unterscheidbar bleibt, hängt
`apiGet` den HTTP-Status als `.status` an den Error.

### Nie gesetzte Felder entfernt

`Team.riders`, `Team.wins_season` und `Team.website` setzte der Scraper
fest auf `None`, keine Abfrage las sie, und eine Spalte in der
`teams`-Tabelle hatten sie auch nicht - Felder, die in der API-Antwort
aussahen, als kämen da Daten. Die Fahrerzahl liefert
`db.count_riders(team_id)`, die Siege `/api/teams/{id}/stats`.

Gegengeprüft, dass es die einzigen waren: für jedes Feld aller elf
Pydantic-Modelle gezählt, wie oft sein Name außerhalb von `models.py` in
`.py`- und `.js`-Dateien vorkommt. Außer diesen drei keines mit null
Treffern.

## Datenqualität

### Eine Zeile pro Fahrer und Saison

Ein Fahrer kann in EINEM Jahr in zwei Stints auftauchen: auf Wikipedia
überlappt das Startjahr eines neuen Stints regelmäßig mit dem Endjahr des
alten (Wechsel zum Saisonwechsel). Die frühere Python-Expansion erzeugte
dafür zwei Zeilen für dasselbe Jahr - auf `rider.html` stand die Saison
doppelt in der Tabelle "Karriere in der World Tour", und
`rider_seasons.csv` enthielt sie zweimal.

Reproduziert mit den Stints 2017–2018 (A), 2018–2020 (B), 2021– (C): 2018
kam zweimal. Jetzt entdoppelt `DISTINCT ON (rider_id, year)` mit
`ORDER BY ... start_year DESC` auf die Zeile des **späteren** Stints - 2018
gehört also zu Team B. Das passt zu `rider_season_points`, das mit
`PRIMARY KEY (rider_id, year)` ohnehin genau eine Zeile pro Jahr vorsieht;
eine Darstellung mit zwei Teams pro Übergangsjahr hätte dort kein Ziel.

`get_rider_seasons` und `export_seasons` teilen dafür **einen** SQL-Ausdruck
(`_SEASONS_SQL`). Vorher existierte die Ableitung zweimal - und beide Kopien
hatten denselben Fehler.

### Striche in Wikipedia-Zeiträumen

`YEAR_RANGE_RE` kannte nur Halbgeviert- und Bindestrich. Ein Geviertstrich
liess den Stint still verschwinden, ohne Log-Eintrag - bei mehr Historie
(alte Artikel sind uneinheitlicher formatiert) führt das zu unsichtbaren
Lücken. `app/text.py::normalize_dashes` vereinheitlicht jetzt alle sieben
Strich-Varianten (U+2010 bis U+2015, U+2212) sowie geschützte Leerzeichen,
und zwar für beide verbliebenen Parser: `wikipedia_riders` und
`wikipedia_race_history` machten das vorher unterschiedlich oder gar nicht.
(Ein dritter, `wikipedia_races`, ist seitdem entfallen - siehe
"Doppelstrukturen".)

Nicht erkannte Labels werden jetzt auf `DEBUG` geloggt statt stumm
verworfen. `2019/20` bleibt bewusst unerkannt: dieses Format gehört zu den
Continental-Saison-*Seiten*, nicht zu Fahrer-Infoboxen - sollte es dort doch
vorkommen, fällt es über das Log auf.

> Die bereits geladenen Historien werden davon nicht rückwirkend
> korrigiert. Ein Neuladen kostet einen Wikipedia-Abruf pro Fahrer (~517,
> ratenlimitiert also gut eine halbe Stunde) und lässt sich bei Bedarf
> anstossen mit:
> `UPDATE riders SET history_fetched_at = NULL;`

## Sicherheit

### Keine internen Fehlertexte nach außen

Die Router antworteten im Fehlerfall mit `str(exc)`. Bei einem
psycopg-Verbindungsfehler enthält der Host, Port, Benutzernamen und
Datenbanknamen - und das Frontend zeigt das `error`-Feld sichtbar an. Jetzt
gehen ausschließlich feste Texte aus `app/routers/messages.py` nach außen,
das Detail geht per `logger.exception` ins Log. Dazu ein globaler
Exception-Handler in `app/main.py` für alles, was kein Router selbst
behandelt.

Geprüft mit einer absichtlich falschen `DATABASE_URL`
(`postgresql://geheimuser:geheimpass@127.0.0.1:5599/...`): in keiner Antwort
von `/api/riders`, `/api/race-history`, `/api/riders/{id}`,
`/api/race-history/{id}` oder den Export-Routen tauchen Benutzer, Passwort,
Host, Port, `psycopg` oder ein Traceback auf.

### Begrenzte `limit`/`offset`

`limit` und `offset` gingen ungeprüft in SQL - `?limit=999999999` war damit
eine kostenlose Anfrage, die die Free-Instanz die volle Tabelle lesen, in
Pydantic-Modelle gießen und serialisieren ließ; ein negatives `offset`
erzeugte einen Postgres-Fehler, der über das `error`-Feld nach außen ging.

Jetzt `Query(200, ge=1, le=500)` bzw. `Query(0, ge=0)`, analog für
`/api/news` und `/api/riders`. Ungültige Werte werden mit 422 abgelehnt. Die
Antwort nennt zusätzlich `total`, `limit` und `offset`, damit paginiert
werden kann - `count_races`/`count_riders` teilen sich die WHERE-Klausel mit
der Listen-Abfrage (`_race_filter`/`_rider_filter`), damit Filter und
Gesamtzahl nicht auseinanderdriften, sobald eine Achse dazukommt.

Das Frontend lädt `races.html` jetzt **pro Saison** statt alles auf einmal
(vorher `limit=5000`). Die Saison-Liste kommt vom neuen leichten Endpunkt
`GET /api/race-history/seasons` - vorher leitete das Frontend sie aus der
kompletten Renn-Liste ab und musste die dafür laden.

> Die `/seasons`-Route muss im Router **vor** `/{race_id}` stehen, sonst
> matcht "seasons" als `race_id`.

### Fremd-Stylesheets

Alle sechs Seiten laden Font Awesome von `cdnjs.cloudflare.com` ohne
`integrity`. Ein kompromittiertes CDN kann damit beliebiges CSS im Kontext
der Seite ausführen - CSS reicht für Datenabfluss über Attribut-Selektoren
und Hintergrundbild-URLs.

Der Hash muss aus der echten Datei gebildet werden; ein geratener Wert
blockiert das Stylesheet komplett und die Seiten verlieren alle Icons.
`scripts/add-sri.sh` holt die Datei, prüft Grösse und Inhalt, bildet den
SHA-384 und trägt `integrity` samt `crossorigin` in alle sechs Seiten ein -
idempotent, also auch beim Versions-Upgrade erneut aufrufbar.

Selbst-Hosten wäre die dauerhafte Lösung (21 tatsächlich benutzte Icons,
gezählt über `grep -ohrE "fa-[a-z0-9-]+" *.html js/*.js`), ändert aber das
Erscheinungsbild und ist ein eigener Schritt.

**Google Fonts lässt sich nicht per SRI absichern:** Google liefert je nach
User-Agent unterschiedliches CSS aus (verschiedene Font-Formate), der Hash
ist also nicht stabil. Das Risiko ist der Art nach vergleichbar, der Weg
dagegen wäre Selbst-Hosten der Schriften - bewusst nicht in diesem Schritt.

### Rate Limiting

Die API hat keine Authentifizierung, läuft auf einer einzigen Free-Instanz
und hat teure Endpunkte. Ein Skript-Loop genügte, um Service und
Verbindungskontingent lahmzulegen.

Die Grenzen sind an echten Seitenaufrufen bemessen: Startseite 4 Requests,
Team-Detail 4, Races 2 plus 1 pro aufgeklapptem Rennen. Ein Besucher, der
zügig durchklickt, kommt auf 30-40 in wenigen Minuten.

| Bereich | Grenze | Env-Var |
|---|---|---|
| alles übrige | 120/Minute | `RATE_LIMIT_DEFAULT` |
| `/api/race-history/{id}` | 60/Minute | `RATE_LIMIT_RACE_DETAIL` |
| `/api/export/*.csv` | 10/Stunde | `RATE_LIMIT_EXPORT` |
| `/api/health` | **ausgenommen** | – |

`/api/health` ist ausdrücklich ausgenommen: Render fragt den Pfad alle ~10
Sekunden ab. Ohne die Ausnahme wurden im Test 30 von 40
Health-Check-Requests mit 429 abgewiesen - Render hätte daraus eine kaputte
Instanz gelesen und Deploys scheitern lassen.

**Die echte Client-IP** kommt aus `X-Forwarded-For`, nicht aus
`request.client.host` (das ist hinter Renders Router die Proxy-Adresse -
alle Besucher lägen in einem gemeinsamen Kontingent). Gelesen wird vom
**Ende** der Kette (`TRUSTED_PROXY_COUNT`, auf Render 1): der Proxy hängt
die echte Adresse hinten an, der erste Eintrag ist client-kontrolliert und
wäre fälschbar. Nachgemessen: ein gefälschter erster Eintrag verschafft kein
frisches Kontingent.

> **Jeder `@limiter.limit`-Endpunkt braucht `response: Response`** - sonst
> antwortet er mit **500 auf jeden Aufruf**, nicht erst bei erreichter
> Grenze. Weil `headers_enabled=True` gesetzt ist, ruft slowapi nach jedem
> Aufruf `_inject_headers()` auf, um die `X-RateLimit-*`-Header zu setzen.
> Gibt der Endpunkt keine `Response` zurück (sondern z.B. ein `dict`), holt
> slowapi das Objekt aus einem Parameter namens `response` - und wirft, wenn
> es den nicht gibt.
>
> Genau das ist hier passiert: `/api/race-history/{race_id}` war nach dem
> Einbau von `headers_enabled` durchgehend kaputt, das Aufklappen eines
> Rennens im Kalender lieferte nur noch 500. Die Drosselung selbst
> funktionierte, es stand nirgends eine Warnung, und von außen war der
> Fehler nicht von einem Datenbank-Problem zu unterscheiden. Die CSV-Exporte
> waren nicht betroffen, weil sie eine `StreamingResponse` zurückgeben -
> daher die Rückgabe-Annotationen `-> StreamingResponse` dort.
>
> `_check_ratelimit_headers` prüft beim Start jeden gedrosselten Endpunkt
> darauf und protokolliert sonst einen Fehler mit Pfad und Funktionsname.
> Gegengeprobt: mit entferntem Parameter meldet die Prüfung genau diesen
> Endpunkt, mit Parameter meldet sie nichts.

> **Stolperstelle bei einem FastAPI-Upgrade.** `SlowAPIMiddleware` ermittelt
> die Route über `_find_route_handler(app.routes, scope)` und schaut nur eine
> Ebene tief. Unter der gepinnten 0.115.0 flacht `include_router()` alle
> Routen zu `APIRoute`-Objekten ab, die Auflösung funktioniert. Neuere
> Versionen (nachgemessen mit 0.141.1) legen stattdessen ein opakes
> `_IncludedRouter`-Objekt ohne `.endpoint` ab - die Middleware hält dann
> **jede** Router-Route für ausgenommen und drosselt nichts, ohne jede
> Fehlermeldung. `_check_ratelimit_coverage` prüft das beim Start und warnt.

### Konfiguration: render.yaml und REQUIRE_DATABASE

`backend/render.yaml` beschreibt **nicht** den laufenden Service: der wurde
von Hand angelegt, und Render kann einen bestehenden Service nicht
nachträglich einem Blueprint unterstellen. Die Datei dient als Dokumentation
der richtigen Konfiguration und als Vorlage für einen Neuaufbau; wer sie
anwendet, bekommt einen zweiten Service daneben. Sie war zusätzlich falsch
(abweichender `rootDir`/`buildCommand`, kein `DATABASE_URL`, kein
`healthCheckPath`) und ist jetzt korrekt.

Ohne `DATABASE_URL` läuft die App weiter und liefert leere Listen - lokal
gewollt, in Produktion eine Falle. Genau das ist am 12.09. passiert: der
Service lief nach dem Anlegen der Datenbank noch ohne `DATABASE_URL` und
lieferte stillschweigend leere Daten. Mit `REQUIRE_DATABASE=1` bricht der
Start stattdessen ab.

### CSV-Export streamt wirklich

`StreamingResponse` war Kosmetik: `fetchall()` holte alle Zeilen in eine
Liste, `io.StringIO` baute daraus das komplette CSV, und
`iter([buffer.getvalue()])` gab es als einen Block aus - der Bestand lag
zweimal im Speicher. Jetzt läuft alles über `db.stream_query` (benannter
server-side Cursor, `EXPORT_ITERSIZE` Zeilen pro Block) und wird blockweise
als CSV ausgegeben. Spaltennamen kommen aus `cur.description`, nicht aus der
ersten Zeile - so stimmt der Kopf auch bei leerem Ergebnis.

Gemessen mit 200.000 Zeilen in `race_results` (13,5 MiB CSV):

| | RSS-Zuwachs |
|---|---|
| vorher | **186 MiB** |
| nachher | **30 MiB** |

Auf einer 512-MB-Instanz war das der Weg in den OOM-Killer, und der Zielumfang
(~2.000 Rennen × Top 10 × Etappen) liegt deutlich über den getesteten 200.000
Zeilen.

`export_seasons` expandierte die Jahre in Python und ließ sich so nicht
streamen - das macht jetzt `generate_series` in SQL. Reihenfolge und Inhalt
sind identisch, **inklusive** der doppelten Jahre bei überlappenden Stints:
das ist ein eigener Befund (siehe "Bekannte Lücken") und wird hier nicht
nebenbei mitgeändert. Alle sieben CSV-Ausgaben wurden vor und nach dem Umbau
byteweise verglichen.

Optionaler Zugriffsschutz: ist `EXPORT_TOKEN` gesetzt, verlangen alle
Export-Routen `Authorization: Bearer <token>` (Vergleich per
`secrets.compare_digest`). Ohne die Variable bleiben sie offen wie bisher.

## Frontend: ES-Module statt globaler Namen

Die sechs Seiten laden ihr JavaScript jetzt als ES-Modul - ein Tag pro
Seite, alles andere zieht das Modul per `import` selbst:

```html
<script type="module" src="js/teams.js"></script>
```

Vorher lud jede Seite vier bis fünf klassische `<script src>`-Tags, und die
Abhängigkeiten dazwischen liefen über globale Namen, ohne dass sie irgendwo
deklariert waren:

- `js/riders.js` braucht `escapeHtml`/`safeUrl` aus `js/api.js`
- `js/team.js` braucht `renderTeamRoster` aus `js/riders.js`
- `js/teams.js` braucht `initRidersTab` aus `js/riders.js`
- alle Seiten brauchen `renderNav` aus `js/nav.js`

Die einzige Absicherung war die Reihenfolge der Tags in sechs HTML-Dateien.
Was dabei schiefgeht, ist belegt: `initials` existierte zweimal, in
`js/teams.js` und `js/team.js`. Dass die eine Definition die andere nie
überschrieben hat, lag allein daran, dass die beiden Dateien nie auf
derselben Seite liegen. Und als `js/team.js` seine Kopien verlor, lief die
Team-Detailseite in einen `ReferenceError` - ohne dass irgendeine Prüfung
das gemerkt hätte, weil die Syntax ja in Ordnung war.

Mit Modulen ist jede Abhängigkeit deklariert, und ein falscher Name ist ein
harter Fehler beim Verlinken statt eines stillen `undefined`. Der Graph:

```
api.js  (keine Abhängigkeiten)
  ui.js
    nav.js
    riders.js
      home.js  news.js  races.js  rider.js  team.js  teams.js
```

Exportiert wird nur, was eine andere Datei braucht: `apiGet` und `API_BASE`
bleiben in `api.js`, `parseCalendarDate` und `initialsFrom` in `ui.js`.

### Drei Stolperstellen, die dabei geprüft wurden

**Einstiegspunkt.** Module werden deferred ausgeführt: sie laufen, wenn das
HTML geparst ist, aber bevor `DOMContentLoaded` feuert. Ein
`addEventListener('DOMContentLoaded', ...)` im Modul greift damit noch - aber
nur, weil die Reihenfolge zufällig passt. Wer das Modul später per
`import()` nachlädt, bekommt eine Seite, die stumm nichts tut. Die sechs
Seiten-Module benutzen deshalb `ui.starten()`, das den Zustand prüft
(`document.readyState`) statt auf ein Ereignis zu hoffen, das vielleicht
schon durch ist.

**Inline-Handler.** Inline-Attribute können keine Modul-Bindings sehen. Im
Baum gibt es vier, alle geprüft:

| Stelle | Handler | Braucht eine Modul-Funktion? |
|---|---|---|
| `js/riders.js` (2x) | `onclick="event.stopPropagation()"` | nein |
| `js/teams.js`, `js/team.js` | `onerror="this.parentElement.textContent='XY'"` | nein - die Initialen stehen beim Rendern schon als Literal im Attribut |

Alle vier bleiben damit gültig. Käme einer dazu, der doch eine
Modul-Funktion aufruft, gehört er auf `addEventListener` umgebaut.

**GitHub Pages.** Läuft ohne Build-Schritt: Pages liefert `.js` als
`text/javascript` (Module brauchen genau das), die Importe sind relativ und
mit Dateiendung geschrieben (`./api.js`, nicht `./api`), und `.nojekyll`
liegt im Wurzelverzeichnis, damit `js/` nicht angetastet wird. Kein Bundler,
kein npm, kein TypeScript.

Was **nicht** mehr geht: die Seiten per Doppelklick aus dem Dateimanager
öffnen. Module unterliegen CORS und laden von `file://` grundsätzlich nicht -
man sieht eine leere Seite. Lokal braucht es einen HTTP-Server, siehe
nächster Abschnitt.

### Seiten im Browser prüfen

`scripts/check-pages.mjs` lädt alle sechs Seiten in Chromium und prüft vier
Dinge pro Seite: kein JavaScript-Fehler (das fängt fehlgeschlagene Importe
und `ReferenceError`s), kein fehlgeschlagener Request auf eine eigene Datei,
die Seite hat wirklich gerendert (ein erwarteter Text muss im sichtbaren
Text stehen - ohne das besteht auch eine Seite den Test, die stumm nichts
tut), und kein Helfer hängt mehr am globalen `window`.

```bash
# Backend
cd backend && DATABASE_URL=... python3 -m uvicorn app.main:app --port 8001 &
# Statische Dateien - NICHT per file://, siehe oben
python3 -m http.server 8000 &
node scripts/check-pages.mjs
```

Externe Quellen (Font-Awesome-CDN, Google Fonts, Wikimedia-Logos) übergeht
der Test: sie sind in abgeschotteten Umgebungen nicht erreichbar und sagen
nichts über den Code.

Dazu zwei statische Prüfungen ohne Browser:

```bash
node scripts/check-js-modules.mjs     # ein Modul-Tag pro Seite, jeder import trifft ein export, keine toten Exporte
python3 scripts/check-env-example.py  # .env.example gegen die im Code gelesenen Variablen
```

`check-js-modules.mjs` nutzt aus, dass Node einen falschen Import-Namen beim
**Verlinken** des Modulgraphen meldet - also bevor irgendein Modulrumpf
läuft. Deshalb funktioniert die Prüfung, obwohl die Module beim Ausführen
`window` und `document` brauchen.

Gegengeprobt, dass die Prüfungen greifen: ein absichtlich falscher
Import-Name (`renderTeamRosterXX`) wird von `check-js-modules.mjs` und von
`check-pages.mjs` gemeldet; ein `<script>`-Tag ohne `type="module"` ebenso.
`scripts/check-js-helpers.mjs` aus dem vorherigen Schritt ist entfallen - es
prüfte, ob eine Seite das richtige Skript lädt, und genau das ist mit
Modulen deklariert.

### `.env.example` gegen den Code

`scripts/check-env-example.py` liest die Umgebungsvariablen per AST aus
`backend/app/` (`os.environ.get`, `os.getenv`, `os.environ[...]`) und meldet
drei Dinge:

- **FEHLT** - der Code liest sie, `.env.example` kennt sie nicht. Folge: sie
  wird beim Deployen vergessen. Genau so lief der Service am 12.09.2026 ohne
  `DATABASE_URL`: die App startet dann und liefert leere Listen, statt sich
  zu beschweren (dagegen gibt es inzwischen `REQUIRE_DATABASE`).
- **ÜBERZÄHLIG** - steht in `.env.example`, wird nirgends gelesen. Folge:
  jemand setzt sie und wundert sich. Entstand nach dem Abbau des alten
  Renn-Pfades (`REFRESH_INTERVAL_CALENDAR`, `REFRESH_INTERVAL_RESULTS`).
- **ABWEICHUNG** - der Beispielwert ist nicht der Code-Default. Vier
  Variablen weichen absichtlich ab (`CORS_ORIGINS` braucht die
  GitHub-Pages-Adresse, `BACKUP_KEEP=7` ist ein Vorschlag für den Cron-Job,
  `CACHE_DIR`/`BACKUP_DIR` sind relative Schreibweisen desselben
  Verzeichnisses). Die stehen namentlich mit Begründung in
  `ABSICHTLICH_ANDERS` im Skript - nicht als Kommentar in `.env.example`,
  weil eine Kommentar-Heuristik jede Abweichung stumm durchgelassen hätte
  (nachgemessen: ein auf `5/minute` verfälschtes `RATE_LIMIT_DEFAULT` wurde
  von der Kommentar-Variante nicht gemeldet, von der Liste schon).

## Backup (`app/backup.py`)

**Warum das nötig ist:** Die Produktionsdatenbank läuft auf Renders
kostenlosem Postgres-Plan. Der läuft **30 Tage nach Anlage ersatzlos ab**
(`expiresAt`, für die aktuelle Instanz `dpg-daia01m743jc73eaocb0-a` der
2026-10-12) und hat keine Backups. Damit wäre der komplette Bestand weg -
Teams, ~517 Fahrer mit Team-Historie, mehrere tausend Rennen mit Ergebnissen
und Etappen - und der Wiederaufbau per Scraper dauert (respektvoll
ratenlimitiert, siehe "Scraping-Ethik") Tage.

> **Das Backup-Skript ist die Absicherung, nicht die Lösung.** Ein Free-Plan
> lässt sich nach Ablauf nicht mehr upgraden - die Instanz ist dann weg. Der
> eigentliche Fix ist ein bezahlter Plan: Dashboard → `peletonpro-db` →
> Settings → Plan. Erst damit gibt es auch Point-in-Time-Recovery; das hier
> ersetzt kein Managed Backup.

### Zwei Verfahren, automatisch gewählt

| | `pgdump` | `csv` |
|---|---|---|
| Werkzeug | `pg_dump -Fc` / `pg_restore` | nur `psycopg` (`COPY`) + gzip |
| Sichert | Schema **und** Daten und Sequenzen | nur **Daten** |
| Restore-Ziel | auch eine völlig leere Datenbank | Datenbank mit bereits angelegtem Schema |
| Voraussetzung | `postgresql-client`, Version ≥ Server | keine (psycopg ist ohnehin Abhängigkeit) |

`choose_method()` nimmt `pgdump`, wenn die Binaries vorhanden **und nicht
älter als der Server** sind (`pg_dump` verweigert neuere Server - eine
vorhandene, aber zu alte Installation ist schlimmer als keine, weil sie
stillschweigend scheitern würde), sonst `csv`.

**Auf Renders Python-Image ist `pg_dump` nicht enthalten**, dort greift also
der CSV-Weg. Das ist kein Nachteil für den Zweck: das Schema entsteht beim
Start ohnehin aus den Migrationen (`backend/migrations`, siehe
"Schema-Migrationen") und ist im Repository versioniert - gesichert werden
müssen die Daten. Wer einen
vollständigen, schema-inklusiven Dump will, ruft das Skript lokal gegen die
**External Database URL** auf; dort ist `pg_dump` meist vorhanden.

### Aufrufe

```bash
cd backend
export DATABASE_URL=postgresql://...        # Render: Internal oder External URL

python -m app.backup dump                   # nach BACKUP_DIR (Default: backend/backups)
python -m app.backup dump --keep 7          # nur die letzten 7 Läufe behalten
python -m app.backup dump --method csv      # Verfahren erzwingen
python -m app.backup verify <pfad>          # Manifest gegen die DB prüfen
python -m app.backup restore <pfad> --force # zurückschreiben (überschreibt ALLES)
```

Jeder Lauf legt ein eigenes Verzeichnis `backups/peletonpro-<UTC-Zeitstempel>/`
an, darin `manifest.json` plus `dump.pgcustom` bzw. eine `<tabelle>.csv.gz`
pro Tabelle. Das Manifest hält Verfahren, Server-Version, Tabellen-Reihenfolge,
Zeilenzahlen und Sequenz-Stände fest - und **bewusst keine Verbindungsdaten**.

`restore` verweigert ohne `--force` den Dienst und prüft anschließend selbst
die Zeilenzahlen gegen das Manifest; bei Abweichung Exit-Code ≠ 0. `verify`
liefert 0 bei Übereinstimmung, 1 bei Abweichung - beides für einen Cron Job
auswertbar.

### Zwei Details, die ein CSV-Backup sonst still kaputt machen

1. **Sequenzen.** Werden Zeilen mit expliziten IDs zurückgeschrieben, bleibt
   `race_results_id_seq` auf 1 stehen und das nächste `INSERT` kollidiert.
   `_reset_sequences()` setzt jede Sequenz per `setval` auf `max(spalte)` der
   zugehörigen Tabelle - aus den **Daten** abgeleitet, nicht aus dem Manifest,
   damit es auch bei einem von Hand beschnittenen Dump stimmt.
2. **Tabellen-Reihenfolge.** Wird nicht hart codiert, sondern bei jedem Lauf
   aus den Fremdschlüsseln topologisch sortiert (`_table_order`). Neue
   Tabellen - etwa für Frauen-Radsport oder weitere Kategorien - werden damit
   automatisch mitgesichert und in korrekter Reihenfolge eingefügt, ohne dass
   hier etwas anzupassen ist.

### Als Render Cron Job einrichten

Dashboard → New → Cron Job, gleiches Repo:

| Feld | Wert |
|---|---|
| Runtime | Python 3 |
| Build Command | `cd backend && pip install -r requirements.txt` |
| Command | `cd backend && python -m app.backup dump --keep 7` |
| Schedule | `0 3 * * *` (täglich 03:00 UTC) |
| Env: `DATABASE_URL` | aus `peletonpro-db` (Internal Database URL) |
| Env: `BACKUP_DIR` | `/var/data/backups` bei angehängtem Disk, sonst Default |

**Wichtig:** Ein Cron Job ohne persistentes Disk verliert die Dateien beim
Ende des Laufs - der Dump muss dann im selben Command weitergeschoben werden
(S3/B2/Storage-Box). Dieses Modul schreibt absichtlich nur ins Dateisystem und
bringt keine Cloud-Zugangsdaten mit; wohin die Dateien danach wandern,
entscheidet der Cron-Command. Beispiel mit `rclone`:

```bash
cd backend && python -m app.backup dump --keep 2 && \
  rclone copy backups remote:peletonpro-backups
```

## API-Endpunkte

| Endpunkt | Beschreibung |
|---|---|
| `GET /api/teams?category=wt&gender=m\|w` | Alle Teams aus der `teams`-Tabelle, optional gefiltert |
| `GET /api/teams/{id}` | Ein Team |
| `GET /api/teams/{id}/stats?season=` | Siege, Podestplätze und Top-10-Platzierungen des Teams in einer Saison, plus die Liste der Siege |
| `GET /api/news?limit=30` | Aggregierter Newsfeed |
| `GET /api/riders?team=<team_id>&gender=m\|w&limit=&offset=` | Fahrer, optional nach aktuellem Team gefiltert, sortiert nach Nachname |
| `GET /api/riders/{id}` | Ein Fahrer inkl. `history` (rohe Team-Zeiträume) und `seasons` (pro Saison abgeleiteter Team-Link, siehe "Vor-/Nachname, Saison-Team-Links, Strava-Profile" oben) |
| `GET /api/riders/{id}/results?limit=&offset=` | Die Platzierungen eines Fahrers, neueste Saison zuerst, paginiert (Default 50, max 200) - siehe "Ergebnisse eines Fahrers" |
| `GET /api/race-history?season=&category=wt\|proseries\|continental&circuit=africa\|asia\|europe\|america\|oceania&gender=m\|w&limit=&offset=` | Renn-Historie seit 2020, gefiltert/paginiert, ohne Ergebnisse/Etappen (siehe "Renn-Historie" oben) |
| `GET /api/race-history/seasons?gender=m\|w` | Alle Saisons, für die Rennen vorliegen |
| `GET /api/race-history/{id}` | Ein Rennen inkl. `results` (Top 10+) und bei Mehretagenrennen `stages[]` (je Etappe eigene `results`) |
| `GET /api/health` | Health-Check (nicht gedrosselt) |

`gender` akzeptiert `m` oder `w`, Default `m` - wer den Parameter nicht
kennt, bekommt genau das, was es vor der Geschlechts-Dimension gab (siehe
"Geschlechts-Dimension"). Jede Antwort führt den verwendeten Wert als Feld
`gender`. Die Detail-Endpunkte haben den Parameter nicht: dort steckt das
Geschlecht schon in der ID.

`category` bei `/api/teams` akzeptiert nur `wt` (`taxonomy.TeamCategory`);
jeder andere Wert ergibt 422. Vorher nahm der Parameter zusätzlich `pro` und
`cont` an und lieferte dafür immer eine leere Liste - warum, und was beim
Erweitern dazugehört, steht unter "Ein Vokabular für die drei Achsen".

**Entfallen:** `GET /api/races`, `GET /api/calendar` und
`GET /api/results`. Sie bedienten einen zweiten Renn-Datenpfad aus dem
flüchtigen Cache; die Renn-Historie deckt dasselbe ab. Siehe "Renn-Daten:
ein Pfad statt zwei".

Alle Listen-Endpunkte (`/api/teams`, `/api/riders`, `/api/race-history`,
`/api/news`) antworten auch bei fehlender Datenbank mit HTTP 200 und
`error` im Rumpf; die Detail-Endpunkte (`/api/teams/{id}`,
`/api/riders/{id}`, `/api/riders/{id}/results`, `/api/race-history/{id}`)
mit HTTP 503. Der Unterschied
ist Absicht: `js/home.js` holt vier Listen in einem `Promise.all`, und eine
503 daraus würde alle vier Kacheln leer lassen statt nur der betroffenen.

`last_updated` liefern `/api/teams` (jüngster Wert aus
`teams.last_updated`) und `/api/news` (Zeitpunkt des letzten
erfolgreichen Scraping-Laufs aus `app/cache.py`). Die übrigen Endpunkte
haben kein `last_updated`.
