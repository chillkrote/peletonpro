# UCI-Punkte: wofür es sie gibt und wie sie hier abgelegt sind

## Woher die Zahlen kommen

**UCI Cycling Regulations, Teil 2 „Road Races", Kapitel X „UCI Rankings",
Artikel 2.10.001–2.10.036**, Ausgabe **01.09.2026** (Dokumentkennung
`E0726`, Seiten 80–110). Das Kapitel enthält die vollständigen Skalen für
Männer (Art. 2.10.008) **und** Frauen (Art. 2.10.017).

Das Reglement wird jährlich neu herausgegeben, und die Skalen ändern sich
dabei. Deshalb steht das Jahr im Dateinamen: `uci-punkte-2026.csv` ist die
Ausgabe 2026 und wird von einer späteren Ausgabe **nicht überschrieben**,
sondern ergänzt. Ohne das liesse sich eine historische Rangliste nie mehr
nachrechnen.

## Die beiden Datendateien

| Datei | Was drin steht |
|---|---|
| `uci-punkte-2026.csv` | `geschlecht, anlass, stufe, platz, punkte` — **1564 Zeilen**, alle Punktwerte aus allen 26 Tabellen des Kapitels |
| `uci-punkte-2026-wt-stufen.csv` | `geschlecht, anlass, stufe, rennen` — **121 Zeilen**, welches WorldTour-Rennen in welcher Stufe läuft |

Die Punktwerte stehen **nur** in der CSV, nicht zusätzlich in diesem Text.
Eine Tabelle, die in einer Datendatei und in einer Dokumentation steht,
läuft beim ersten Reglement-Update auseinander, und dann ist nicht mehr
erkennbar, welche der beiden stimmt. Wer eine Übersicht lesen will:

```bash
python3 -c "
import csv, collections
d = collections.defaultdict(dict)
for z in csv.DictReader(open('docs/uci-punkte-2026.csv')):
    d[(z['geschlecht'], z['anlass'], z['stufe'])][int(z['platz'])] = z['punkte']
for k, v in d.items():
    print('%-2s %-20s %-10s Platz 1: %-5s Tiefe: %d' % (k[0], k[1], k[2], v[1], len(v)))
"
```

## Die Ranglisten, in die die Punkte fließen

| Rangliste | Artikel | Wie sie entsteht |
|---|---|---|
| Männer Einzel-Weltrangliste | 2.10.002 | 52 Wochen rollierend |
| Männer Einzel – nur Eintagesrennen | 2.10.002 bis | dieselbe Skala, nur Eintagesrennen |
| Männer Einzel – nur Etappenrennen | 2.10.002 ter | dieselbe Skala, nur Etappenrennen |
| Männer Nationen | 2.10.004 | Summe der **8 besten** Fahrer je Nationalität |
| Männer U23 Nationen | 2.10.004 bis | Summe der 8 besten U23 |
| Männer Teams | 2.10.004 ter | Summe der **20 besten** Fahrer unter Vertrag |
| Frauen Einzel-Weltrangliste | 2.10.011 | 52 Wochen rollierend |
| Frauen Teams | 2.10.014 | Summe der **8 besten** Fahrerinnen |
| Frauen Nationen | 2.10.015 | Summe der **5 besten** |
| Frauen U23 Nationen | 2.10.015 bis | Summe der 5 besten U23 |
| Männer Kontinental (je Kontinent) | 2.10.018–2.10.028 | Einzel; Team = **10 beste**; Nationen = **8 beste** |

Elite und U23 stehen in **derselben** Einzelrangliste. Die
„UCI Women's WorldTour"-Rangliste (§4, Art. 2.10.032–036) ist zum
01.01.2025 abgeschafft.

**Wichtiger Unterschied:** die Einzel- und Nationen-Ranglisten sind
**rollierend über 52 Wochen**, die Team-Ranglisten sind es **nicht** — sie
werden zum Saisonstart auf null gesetzt und zählen die besten N Fahrer, die
**zum Zeitpunkt der Rangliste** unter Vertrag stehen. Eine
Team-Rangliste lässt sich also nicht aus einer rollierenden
Fahrer-Rangliste ableiten; sie braucht die Punkte je Fahrer **und
Zeitpunkt**.

## Wofür es Punkte gibt

Dreizehn Anlässe. Der Schlüssel `anlass` in der CSV ist die technische
Bezeichnung, `stufe` unterscheidet die Spalten der jeweiligen Tabelle.

| `anlass` | Wofür | `stufe` |
|---|---|---|
| `gc` | Endergebnis (Gesamtklassement) in WorldTour-Rennen | `gc1`…`gc5` |
| `etappe` | Prolog und Etappen in WorldTour-Etappenrennen | `et1`…`et4` |
| `nebenklassement` | Punkte- und Bergwertung der Grand Tours (Endstand) | `nk1`, `nk2` |
| `trikot` | Tragen des Führungstrikots in einem WorldTour-Rennen, **pro Etappe** | `tr1`…`tr4` |
| `kk_gc` | Endergebnis im Kontinentalkalender | `proseries`, `class1`, `class2`, `class2u` |
| `kk_etappe` | Prolog, Etappen und Halbetappen im Kontinentalkalender | dieselben |
| `kk_trikot` | Führungstrikot im Kontinentalkalender, **pro Etappe** | dieselben |
| `nat_meisterschaft` | Nationale Meisterschaften | `rr_a`, `rr_b`, `itt_a`, `itt_b`, `u23_rr`, `u23_itt` |
| `kont_meisterschaft` | Kontinentalmeisterschaften und Kontinentalspiele | `elite_rr`, `elite_itt`, `u23_rr`, `u23_itt` |
| `wm_olympia` | Olympische Spiele und Weltmeisterschaften | `elite_rr`, `elite_itt`, `u23_rr`, `u23_itt` |
| `ttt_kont` | Mannschaftszeitfahren der Kontinentalmeisterschaften | `elite` |
| `mixed_relay_kont` | Mixed-Relay-Mannschaftszeitfahren der Kontinentalmeisterschaften | `elite` |
| `mixed_relay_wm` | Mixed-Relay-Mannschaftszeitfahren der Weltmeisterschaften | `elite` |

Drei Anmerkungen zu den Stufen:

- Bei `gc`, `etappe`, `nebenklassement`, `trikot`, `kk_gc`, `kk_etappe` und
  `kk_trikot` sind die Stufen eine **Rangfolge**: Stufe 1 ist das höher
  bewertete Rennen. `scripts/check-uci-punkte.py` prüft das und würde eine
  vertauschte Spalte melden.
- Bei `nat_meisterschaft`, `kont_meisterschaft` und `wm_olympia` sind sie
  **keine** Rangfolge, sondern verschiedene Disziplinen. Dort gilt die
  Regel auch tatsächlich nicht: bei der WM gibt das U23-Straßenrennen auf
  Platz 21 noch 5 Punkte, das Elite-Zeitfahren nur 3.
- `class2u` ist die Spalte „1.2U et 2.2U" beziehungsweise „2.2U".
  **Asymmetrie im Reglement:** bei den Frauen fehlt sie in der Tabelle
  „Final results in Continental Calendar Events", ist aber in der
  Etappen- und der Trikot-Tabelle vorhanden. So steht es im Dokument; die
  CSV gibt das unverändert wieder.

Die Kategorien **A** und **B** bei den nationalen Meisterschaften: A sind
Nationen, die in der Vorsaison mindestens eine Starterin oder einen Starter
im Elite-Straßenrennen der WM hatten, B alle übrigen. Die Einteilung hängt
also vom **Vorjahr** ab und ändert sich jährlich.

## Regeln, die die Rechnung verändern

- **Mannschaftszeitfahren:** die Punkte gehen an das **Team** und werden
  **gleichmäßig** auf die Fahrer verteilt, die ins Ziel kommen — gerundet
  auf **ein Hundertstel** Punkt. Ein Fahrer kann also 12,86 Punkte haben.
- **Mixed Relay:** Aufteilung auf die Zielankömmlinge des jeweiligen
  Geschlechts nach Endklassement, ebenfalls auf 1/100 gerundet.
- **Etappenpunkte** erscheinen erst in der Rangliste, die **nach dem
  letzten Tag** des Etappenrennens erstellt wird.
- **52-Wochen-Regeln:** dasselbe Rennen zählt nie doppelt. Findet eine
  Ausgabe weniger als 52 Wochen nach der vorigen statt, zählt nur die
  neuere. Mehr als 52 Wochen: die alten Punkte bleiben, bis die neue
  Ausgabe gefahren ist. Wird das Rennen nicht mehr ausgetragen, fallen die
  Punkte erst nach 52 Wochen heraus.
- **Transfers:** Punkte bleiben beim Team, bei dem sie verdient wurden;
  ab dem Wechseldatum zählen sie für das neue Team. Bei Vertragsende
  bleiben sie beim alten Team.
- **Stagiaires:** zählen für ihr **Stammteam**, unter keinen Umständen für
  das Gastteam. Gleiches gilt zwischen Development-Team und
  WorldTeam/ProTeam — die Punkte gehen immer ans Primärteam.
- **Nationen:** die Punkte gehen an die Nationalität des Fahrers, auch bei
  Lizenz eines anderen Verbands.
- **U23-Kontinentalrangliste:** Punkte von U23-Fahrern mit Vertrag bei
  einem WorldTeam oder ProTeam zählen **nicht** — außer sie sind dort als
  Stagiaire registriert.
- **Veröffentlichung:** jeden Dienstag 02:00 Uhr MEZ.
- **Gleichstand:** Anzahl der ersten Plätze, dann der zweiten usw.; bei
  Etappenrennen zählt dafür nur das Gesamtklassement auf Zeit.
- **Kontinentalspiele:** welche Punkte geben, legt das UCI-Management
  jährlich neu fest.
- **U23-Mannschaftszeitfahren:** richtet eine Konföderation ein separates
  U23-Mannschaftszeitfahren aus, gibt es dafür **keine** Punkte.

## Artikel 2.6.001: eine Korrektur

Beide Skalen verweisen auf Artikel 2.6.001: „The awarding of points for
stage races is in accordance with article 2.6.001 **regarding the duration
of the event**." Ich hatte das als **Punkteskala nach Renndauer** gelesen —
also als fehlende Tabelle. **Das ist falsch.** Kapitel VI (Ausgabe
01.09.2026, Seiten 63–73) liegt inzwischen vor, und 2.6.001 lautet:

> Stage races shall be run over a minimum of two days with a general time
> classification. They shall be run in road race stages and time trial
> stages.
>
> **If only one stage or prologue is completed and the other stages are
> cancelled, only the points for the stage will be awarded** and included
> in the UCI Rankings. No additional points will be awarded (e.g. for the
> general time classification, wearing of the leader's jersey or secondary
> classifications).

Es ist also keine Skala, sondern eine **Ausfallregel**: „regarding the
duration" meint ein Rennen, das seine geplante Dauer *nicht erreicht* hat.
Bleibt von einem Etappenrennen nur eine Etappe oder ein Prolog übrig,
zählen **ausschließlich** die Etappenpunkte — kein Gesamtklassement, kein
Trikot, keine Nebenwertungen.

Praktisch heißt das: es fehlt **keine** Tabelle. Aber die Berechnung
braucht eine Bedingung, die leicht zu übersehen ist, weil sie nur bei
abgebrochenen Rennen greift (Wetter, Streckensperrung) — und genau dann
lieferte eine Berechnung ohne sie zu viele Punkte für die
Gesamtklassement-Zeile, die in unseren Daten trotzdem steht.

## Kapitel VI: die Regeln für Etappenrennen, die auf die Punkte wirken

| Artikel | Regel | Wirkung auf die Berechnung |
|---|---|---|
| 2.6.001 | nur eine Etappe gefahren → nur Etappenpunkte | siehe oben |
| 2.6.006 | Prologe zählen als Renntag und fürs Gesamtklassement; max. 8 km (Frauen Elite und Junioren: unter 4 km), immer Einzelzeitfahren | ein Prolog ist eine Etappe im Sinne der Etappenpunkte |
| 2.6.013 | Einzel- und Team-Gesamtklassement auf Zeit sind **verpflichtend** in WorldTour (Männer), Women's WorldTour und Women's ProSeries, sowie ProSeries und Klasse 1+2 der Männer Elite/U23 | für diese Rennen existiert immer ein Gesamtklassement |
| 2.6.018 | **kein Führungstrikot am ersten Tag** (Prolog oder erste Etappe) | ein Rennen mit N Etappen gibt Trikot-Punkte für **N−1** Etappen, nicht für N |
| 2.6.018 | maximal 4 Trikots (WorldTour, Women's WorldTour, ProSeries und Klasse 1 der Männer), sonst maximal 6; nur das Trikot des Zeit-Gesamtklassements ist Pflicht | siehe die offene Frage unten |
| 2.6.018 | führt ein Fahrer mehrere Wertungen, gilt eine Prioritätsreihenfolge (Zeit → Punkte → Berg → sonstige), und der Veranstalter **darf** den Nächstplatzierten das freie Trikot tragen lassen | der **Träger** ist nicht immer der Führende der Wertung |
| 2.6.025 | die Wertung einer Mannschaftszeitfahr-Etappe zählt „only towards the general individual time classification and the general team classification" | siehe die offene Frage unten |
| 2.6.032 | wird ein Fahrer außerhalb des Zeitlimits vom Kommissärspräsidenten weitergelassen, werden ihm **alle Punkte der Nebenwertungen entzogen** | eine Punkte-Rücknahme, die aus einem Ergebnis allein nicht hervorgeht |
| 2.6.008 | „The riders must complete the entire distance of each stage to be included in the classification" | wer nicht gewertet ist, bekommt nichts — folgt schon aus der Ergebnisliste |
| 2.6.015–2.6.017 | Gleichstandsregeln für Zeit-, Team-, Punkte- und Bergwertung | nur nötig, wenn wir Klassements selbst bilden, nicht wenn wir Endstände lesen |
| 2.6.019–2.6.021 | Zeitboni (Zwischensprints 3″/2″/1″, Ziel 10″/6″/4″) wirken **nur** aufs Einzel-Zeitklassement, nie bei Zeitfahren | verändert nicht die Punkte, aber wer das Klassement gewinnt |

### Zwei Fragen, die beide Kapitel offenlassen

**Welches Trikot gibt die Punkte?** Die Tabelle heißt „Wearing the race
leader's jersey in a UCI WorldTour event (per stage)" und hat genau eine
Zeile (Platz 1). Nach 2.6.018 gibt es aber bis zu vier Trikots. Dass nur
das Zeit-Gesamtklassement-Trikot zählt, ist die naheliegende Lesart —
**gesagt wird es in keinem der beiden Kapitel.** Und weil der Veranstalter
den Nächstplatzierten ein Trikot tragen lassen darf, ist „Träger" nicht
dasselbe wie „Führender". Vor einer Berechnung muss das geklärt werden;
eine Annahme würde hier still falsche Punkte erzeugen.

**Geben Mannschaftszeitfahr-Etappen Etappenpunkte?** Art. 2.10.008 sagt
ja: „For team time trial events **and stages** the points on the scale
shall be awarded to the team." Art. 2.6.025 sagt, die Wertung solcher
Etappen zähle nur fürs Einzel-Zeit- und Team-Gesamtklassement.
Widersprüchlich ist das nicht zwingend — 2.6.025 regelt die *Klassements
des Rennens*, 2.10.008 die *UCI-Punkte* —, aber die Auflösung steht
nirgends ausdrücklich. Auch das gehört geklärt, nicht geraten.

**Kontinental-Ranglisten für Frauen** bleiben offen: §3 (Art. 2.10.018 ff.)
regelt nur die Männer. Ob es sie nicht gibt oder sie an anderer Stelle
stehen, lässt sich aus Kapitel X nicht entscheiden.

## Wie die Zahlen geprüft wurden

Die Werte wurden nicht abgetippt, sondern **maschinell gegen den Text der
PDF verglichen** — alle 1564:

| Durchgang | Verfahren | Ergebnis |
|---|---|---|
| 1 | Zeilen, in denen **alle** Spalten gefüllt sind: spaltengenauer Vergleich | 880 Werte, **0 Abweichungen** |
| 2 | Zeilen mit Lücken (Spalten unterschiedlicher Tiefe): Vergleich der **Multimenge** der Zahlen je Platz, über 18 Tabellen | 1508 Werte, **0 abweichende Zeilen** |
| 3 | die vier kleinen Tabellen (Trikot, zwei Mannschaftszeitfahren) | 56 Werte, **0 Abweichungen** |

Warum zwei Verfahren: der PDF-Textextraktor liefert eine Zeile wie
`6 30 5 5  5` für eine Tabelle mit sechs Spalten — welche Zelle leer ist,
steht nicht im Text. Spaltengenau lesen geht dort nicht; die Multimenge der
Zahlen muss aber stimmen. Ein Tippfehler in einer Zahl fliegt damit auf.
Unentdeckt bliebe nur eine Verwechslung zweier Spalten mit **gleichem**
Wert, und die ist inhaltlich folgenlos.

Ebenso geprüft: jeder der **121 Rennnamen** kommt im PDF-Text vor
(nach Vereinheitlichung von Zeilenumbrüchen und Leerzeichen um
Bindestriche) — 0 nicht gefunden.

Laufend geprüft wird mit:

```bash
python3 scripts/check-uci-punkte.py
```

14 Prüfungen: keine doppelten Plätze, keine Lücke in der Platzfolge, keine
Punktzahl ≤ 0, Punkte steigen nie mit dem Platz, die Rangfolge der Stufen
(siehe oben), Männer- und Frauenskala identisch bis auf die eine
dokumentierte Ausnahme, und die Kreuzprüfung zwischen beiden CSV-Dateien
(jede Stufe hat Rennen, jedes Etappen- oder Trikot-Rennen hat auch ein
Gesamtklassement).

Das Skript enthält **keine** zweite Kopie der Zahlen. Ein Test, der die
Tabelle noch einmal enthält, prüft nur, ob zweimal derselbe Tippfehler
gemacht wurde. Gegengeprüft, dass die Prüfungen etwas taugen:

| Manipulation | scheitert an |
|---|---|
| `gc2` und `gc3` auf Platz 1 vertauscht | „Punkte steigen nie mit dem Platz" **und** „höhere Stufe zahlt nie weniger" |
| einen Frauenwert verändert | „sonst überall identische Zahlen" |
| Platz 30 aus einer Skala entfernt | „Platzfolge ohne Lücke" |
| ein Etappenrennen aus dem Gesamtklassement gelöscht | „Etappen-/Trikot-Rennen haben ein Gesamtklassement" |

## Das Schema (Migration 0008)

Die Entscheidung ist gefallen: die Punkte werden **selbst berechnet**, nicht
importiert. Dafür müssen die Skalen abfragbar sein — ein CSV im Repository
genügt für die Dokumentation, aber nicht für ein JOIN gegen Ergebniszeilen.
Migration 0008 legt vier Tabellen an.

Die wichtigste Erkenntnis aus der Prüfung ist dabei eingeflossen:
**Männer- und Frauenskala sind zahlengleich** — überall außer der einen
fehlenden `class2u`-Spalte. Zwei getrennte Tabellen wären nicht nur doppelte
Pflege, sie wären doppelte Pflege für *dieselben* Zahlen. Also eine Tabelle
mit `gender`-Spalte, wie das Projekt sie für Fahrer, Teams und Rennen
schon hat.

| Tabelle | Inhalt |
|---|---|
| `uci_stufe` | `(saison, gender, anlass, stufe)` — die Schlüsseltabelle |
| `uci_punkte` | `+ platz, punkte` — die Skala, `INTEGER` |
| `uci_rennstufe` | `+ rennen_reglement, race_id` — Zuordnung Rennen → Stufe |
| `uci_quelle` | `datei, sha256, geladen_am` — Merker für den Loader |

**Warum `uci_stufe` eine eigene Tabelle ist:** die beiden anderen zeigen
per Fremdschlüssel darauf. Ohne sie wäre eine Rennzuordnung auf eine Stufe
*ohne Skala* möglich — und die fällt beim Rechnen nicht als Fehler auf,
sondern als stilles Null-Ergebnis. Das ist die schlimmste Art von
Datenfehler, weil sie wie ein legitimes „keine Punkte" aussieht.

**Warum die Saison im Schlüssel steht:** das Reglement erscheint jährlich
und die Skalen ändern sich. Ein späterer Jahrgang **ergänzt**, er
überschreibt nicht.

**Gefüllt wird aus der CSV, nicht aus der Migration.** `app/uci_punkte.py`
liest `docs/uci-punkte-<saison>.csv` beim Start. Die Zahlen stehen damit
genau einmal im Repository. Der Loader findet neue Jahrgänge über das
Dateinamensmuster — eine CSV für 2027 hinzuzufügen genügt, ohne
Codeänderung.

**Der Hash-Merker ist kein Luxus.** Eine Instanz auf Renders kostenlosem
Plan startet mehrmals pro Stunde neu (gemessen, siehe Migration 0007). Ohne
Merker würden bei jedem Aufwachen 1564 Zeilen geschrieben — genau die
Verschwendung, die der Saison-Takt an anderer Stelle beseitigt hat.
Gleicher SHA-256: der Loader tut nichts.

**`rider_season_points.uci_points` ist jetzt `NUMERIC(8,2)`.**
Mannschaftszeitfahren-Punkte werden auf ein Hundertstel geteilt; ein Fahrer
kann 12,86 Punkte haben, und `INTEGER` hätte das stillschweigend gerundet.
`INTEGER` → `NUMERIC` ist verlustfrei, die Migration ist also nach der Regel
in `backend/README.md` auch ohne Backup zulässig. Sie meldet zusätzlich per
`RAISE NOTICE`, wie viele Zeilen überhaupt einen Wert hatten.

### `race_id IS NULL` ist die eigentliche Aussage

`uci_rennstufe.rennen_reglement` ist der Name **wie er im Reglement steht**,
unverändert. `race_id` ist `NULL`, solange die Zuordnung nicht gesetzt
wurde — und der Loader lässt eine gesetzte `race_id` unberührt.

Das ist Absicht. Der Reglement-Name lässt sich nicht verlässlich auf
`races.id` abbilden: das Reglement selbst schreibt **„Oomlop Nieuwsblad"**
für Omloop Nieuwsblad im Frauen-Gesamtklassement und führt „Lloyds Tour of
Britain Women" in der Trikot-Tabelle ohne das „Women". Ein Namensabgleich
würde bei jeder Umbenennung still falsche Punkte liefern („In Flanders
Fields - From Middelkerke to Wevelgem" hieß früher Gent–Wevelgem).

Der Unterschied ist: „wir wissen, dass 121 Zuordnungen fehlen" statt „die
Punkte sind irgendwie zu niedrig". Die offene Zahl ist abfragbar
(`WHERE race_id IS NULL`) und steht in jeder Loader-Meldung.

### Prüfen

```bash
DATABASE_URL=postgresql://... python3 scripts/check-uci-reglement.py
```

21 Prüfungen gegen ein echtes Postgres, eine **leere** Datenbank genügt
(das Skript wendet die Migrationen selbst an): Tabellenform und der neue
Spaltentyp, der erste Ladevorgang gegen die Zeilenzahlen der CSV, **der
zweite Ladevorgang tut nichts** (der eigentliche Punkt), eine von Hand
gesetzte `race_id` übersteht einen Reload mit geänderter Datei, ein aus der
CSV entfernter Wert verschwindet auch aus der Datenbank, die Fremdschlüssel
und CHECKs greifen, und 12,86 Punkte bleiben 12,86.

Gegengeprüft mit drei Manipulationen am Loader, jede bricht genau die
zuständige Prüfung: Hash-Merker entfernt → „nichts geladen" scheitert;
`race_id` überschreiben → „race_id nicht überschrieben" scheitert;
Löschen veralteter Zeilen ausgebaut → „aus der CSV entfernter Wert ist auch
weg" scheitert.

**Eine Korrektur am Prüf-Gerüst war nötig.** `scripts/check-migrations.sh`
verglich in Schritt 3 („kein bestehender Spaltenwert verändert") die
**Textdarstellung** der Zeilen, nicht deren Wert. Die verlustfreie
Typerweiterung macht aus `5` ein `5.00`, und der Test schlug an — obwohl
sich kein Wert geändert hatte. Der Vergleich normalisiert Zahlspalten jetzt
mit `trim_scale(...::numeric)`, misst damit den Wert statt seiner Schreibweise
und bleibt scharf: eine Testmigration, die `uci_points` auf 999 setzt, lässt
ihn nach wie vor scheitern (gegengeprüft).

## Selbst berechnen: was dafür noch fehlt

Die vier Tabellen halten das **Reglement**. Für eine eigene Berechnung
braucht es die **Ergebnisse** in einer Tiefe, die das Projekt nur teilweise
hat. Bestandsaufnahme je Anlass:

| `anlass` | braucht | Stand |
|---|---|---|
| `gc` | Endstand des Gesamtklassements + Stufe des Rennens | Ergebnisse **ja** (`race_results` mit `stage_id IS NULL`). Stufe: Tabelle da, `race_id` überall `NULL` |
| `etappe` | Ergebnis je Etappe | **ja** — `race_stages` + `race_results.stage_id` werden gescraped |
| `nebenklassement` | Endstand Punkte- und Bergwertung | **nein**, gar nicht modelliert |
| `trikot` | wer an welchem Tag welches Trikot **getragen** hat | **nein**, gar nicht modelliert — und vorher die offene Frage oben klären |
| `kk_gc`, `kk_etappe`, `kk_trikot` | wie oben, plus Unterscheidung Class 1 / Class 2 / 1.2U | **nein** — `taxonomy.Category` kennt nur `continental` für alle drei |
| `nat_meisterschaft` | Ergebnisse nationaler Meisterschaften + Kategorie A/B je Nation (hängt vom Vorjahr ab) | **nein** — diese Rennen sind nicht im Kalender |
| `kont_meisterschaft` | Ergebnisse der Kontinentalmeisterschaften und -spiele | **nein** — nicht im Kalender |
| `wm_olympia` | Ergebnisse von WM und Olympia | **nein** — nicht im Kalender |
| `ttt_kont`, `mixed_relay_kont`, `mixed_relay_wm` | Liste der **Zielankömmlinge je Team**, für die Teilung auf 1/100 | **nein** |

Der Kalender wird über `taxonomy.achsen_kombinationen()` geseedet, also
über WorldTour, ProSeries und die fünf Kontinental-Circuits. Nationale
Meisterschaften, Kontinentalmeisterschaften, WM und Olympia sind damit
**gar nicht** erfasst — sechs der dreizehn Anlässe haben heute keine
Quelle.

### Was sich damit heute schon rechnen lässt

**WorldTour-Gesamtklassement und WorldTour-Etappen** — sobald die 121
`race_id`-Zuordnungen gesetzt sind. Das sind bei den Männern die Stufen
`gc1`–`gc5` und `et1`–`et4`, also der größte Teil der Punkte der
Spitzenfahrer. Nicht die ganze Rangliste, aber ein nachrechenbarer,
prüfbarer Anfang.

### Schritt 1 ist gebaut: der Abgleich Rennname → `races.id`

`app/uci_zuordnung.py` läuft beim Start direkt nach dem Reglement-Loader
und setzt `uci_rennstufe.race_id`, **soweit es das belegen kann**. Drei
Stufen, im Log getrennt gezählt:

| Stufe | Regel |
|---|---|
| `von_hand` | aus `docs/uci-punkte-<saison>-race-ids.csv` — steht über allem anderen |
| `exakt` | Vergleichsform beider Namen identisch |
| `enthalten` | der Reglement-Name steht als ganze Wortfolge in **genau einem** Kandidaten (`Tour of Guangxi` in `Gree–Tour of Guangxi`) |
| `aehnlich` | Ähnlichkeit ≥ 0,90 **und** mindestens 0,05 besser als der zweitbeste |

Getrennt gezählt, weil die drei nicht gleich verlässlich sind — und
**namentlich geloggt**, soweit sie abgeleitet sind:

```
Rennzuordnung 2026: 44 exakt, 0 enthalten, 2 aehnlich, 75 offen
Rennzuordnung 2026 abgeleitet (2): m/'…' -> 2026-wt-… (aehnlich); …
Rennzuordnung 2026 offen (42 Namen): m/Itzulia Basque Country; …
```

Die Namen der abgeleiteten Zuordnungen standen zunächst **nicht** im Log,
nur ihre Zahl. Das war der halbe Schritt: wer wissen will, wie viel geraten
ist, will danach wissen **was** — sonst ist die Zahl eine Beunruhigung ohne
Handhabe. Beim ersten Produktionslauf (14.09.2026) meldete das Log „2
aehnlich", und welche zwei es waren, liess sich nicht mehr feststellen.
`exakt` braucht keine Nachprüfung und steht deshalb nicht in der Liste.

**Die Vergleichsform ist der halbe Erfolg.** Das Reglement schreibt
„Paris - Nice" und „Tirreno - Adriatico", Wikipedia „Paris–Nice". Ohne
Vereinheitlichung der Striche und der Leerzeichen um sie herum wäre **keine
einzige** dieser Zuordnungen exakt. Dazu die Faltung von Akzenten
(`text.vergleichsform`, dieselbe Funktion, die der Familiennamen-Abgleich
benutzt): „Liège-Bastogne-Liège" → `liege-bastogne-liege`.

**Kandidaten sind nur Rennen derselben Saison, desselben Geschlechts und
`category = 'wt'`.** Alle drei Filter sind einzeln gegengeprüft.

**Die Schwelle ist absichtlich zu streng.** „Omloop Nieuwsblad" (Reglement)
gegen „Omloop Het Nieuwsblad" (Wikipedia) erreicht **0,895** — knapp unter
0,90, also bleibt die Zeile offen, obwohl die Zuordnung inhaltlich richtig
wäre. Das ist der Preis, und er ist die richtige Richtung: eine offene
Zuordnung fällt als `race_id IS NULL` auf, eine falsche erzeugt still zu
hohe Punktzahlen. Solche Fälle gehören von Hand gesetzt — und eine von Hand
gesetzte `race_id` wird von keinem Lauf wieder angefasst.

**Es läuft bei jedem Start und über alle Jahrgänge.** Reines SQL, keine
externen Abrufe, und nur an Zeilen mit `race_id IS NULL` — ist alles
zugeordnet, tut es nichts. Wiederholt laufen **muss** es, weil die Rennen
einer Saison erst über die Zeit geseedet werden: ein Rennen, das beim ersten
Lauf noch nicht in `races` stand, wird beim nächsten gefunden. Ein Takt wie
bei den Wikipedia-Jobs (`app/kadenz.py`) wäre hier also falsch.

### Die Handdatei ist der vorgesehene Weg, kein Notbehelf

`docs/uci-punkte-2026-race-ids.csv` (`geschlecht, rennen_reglement, race_id`)
ordnet fest zu, was keine Ähnlichkeitsschwelle finden kann. Der erste
Produktionslauf hat gezeigt, warum es sie braucht: Reglement und Wikipedia
führen dieselben Rennen oft unter Namen, die **nichts miteinander zu tun
haben**.

| im Reglement | in `races` | Ähnlichkeit |
|---|---|---|
| `DSSK (Donostia San Sebastian Klasikoa)` | Clásica de San Sebastián | 0,48 |
| `In Flanders Fields - From Middelkerke to Wevelgem` | Gent–Wevelgem | 0,33 |
| `Ronde van Vlaanderen-Tour des Flandres` | Tour of Flanders | 0,48 |
| `ADAC Cyclassics` | Hamburg Cyclassics | 0,73 |
| `Itzulia Basque Country` | Tour of the Basque Country | 0,71 |
| `La Vuelta Ciclista a España` | Vuelta a España | 0,71 |
| `Omloop Nieuwsblad` | Omloop Het Nieuwsblad | 0,90 |

Eine Schwelle, die den ersten Fall fände, würde beliebig viel Falsches
mitnehmen. Die Datei liegt im Repository, ist damit nachvollziehbar und
überprüfbar, und ein Fehler darin lässt sich zurücknehmen wie jede andere
Änderung.

**Sie steht über einer bereits gesetzten `race_id`** — auch über einer, die
ein früherer maschineller Treffer geschrieben hat. Die Datei ist versioniert
und geprüft, ein Ähnlichkeitstreffer ist es nicht.

**Eine `race_id`, die es nicht gibt, wird gemeldet und übersprungen**, nicht
geschrieben. Sonst bräche der Fremdschlüssel die ganze Transaktion ab und
risse die maschinellen Zuordnungen mit — ein Tippfehler in einer Zeile
hätte alle übrigen verloren. `scripts/check-uci-punkte.py` prüft zusätzlich
ohne Datenbank, dass jeder Name in der Datei auch im Reglement vorkommt:
ein Tippfehler dort liesse die Zeile sonst still ins Leere laufen.

### Zwei Rennen fehlen in `races`

`Grand Prix Cycliste de Québec` und `Grand Prix Cycliste de Montréal` stehen
im Reglement, aber **nicht** in der Renn-Tabelle — von 36 WorldTour-Namen
der Männer sind nur 34 geseedet. Sie lassen sich deshalb nicht zuordnen, und
eine erfundene `race_id` wäre schlimmer als die Lücke. Warum das
Kalender-Seeding sie übersprungen hat, ist offen und eine eigene
Untersuchung wert.

**Die 52 Frauen-Zeilen können heute nicht aufgehen.** `races` enthält keine
Frauenrennen — der Kalender wird nur für Männer geseedet. Das ist keine
Schwäche des Abgleichs, sondern die nächste offene Baustelle.

#### Prüfen

```bash
DATABASE_URL=postgresql://... python3 scripts/check-uci-zuordnung.py
```

36 Prüfungen, leere Datenbank genügt. Die Hälfte belegt, dass etwas **nicht**
passiert: der Reglement-Tippfehler bleibt offen, zwei gleichnamige Zeilen in
`races` werden nicht geraten, ein Rennen der falschen Kategorie oder Saison
ist kein Kandidat, keine Frauen-Zeile wird auf ein Männerrennen gelegt.

Sechs Gegenproben, jede bricht genau die zuständige Prüfung: Geschlechts-
oder Kategoriefilter entfernt, Schwelle auf 0,50 gesenkt, Abstandsprüfung
ausgebaut, gesetzte `race_id` neu bewertet, Schleife auf die laufende Saison
beschränkt.

**Eine siebte Gegenprobe blieb grün**, und das ist ein Befund, nicht ein
Versehen: der Zweig, der zwei *exakt* gleiche Kandidaten abweist, ist
**redundant** — zwei identische Namen treffen auch den Enthalten-Zweig
zweimal und landen dort ebenfalls bei „mehrdeutig". Der Zweig bleibt
stehen, weil er den Fall benennt, aber im Code steht jetzt ausdrücklich,
dass sich niemand beim Umbau des Enthalten-Zweigs auf ihn verlassen darf.

## Schritt 2 ist gebaut: die Berechnung

`app/uci_berechnung.py` rechnet aus `race_results` × `uci_punkte` die
Punkte je Ergebniszeile und schreibt sie nach `uci_punkte_fahrer`
(Migration 0009).

### Warum je Ergebnis und nicht je Saison

`rider_season_points` hält eine Zahl je (Fahrer, Jahr). Das reicht für eine
Anzeige, aber nicht für drei Dinge:

1. **Nachrechnen.** Eine Saisonsumme, die von der UCI-Rangliste abweicht,
   sagt nicht, welches Rennen schuld ist. Eine Zeile je Ergebnis schon.
2. **Die 52-Wochen-Ranglisten.** Die UCI-Einzelwertung ist rollierend
   (Art. 2.10.002) und braucht das **Datum** jedes Punktgewinns. Aus Zeilen
   je Ergebnis lassen sich beide Sichten bilden, aus der Jahressumme nur
   eine. Deshalb trägt jede Zeile ein `punkt_datum` — das Etappendatum bei
   Etappen, das Renn-Enddatum beim Gesamtklassement.
3. **Neuberechnen.** Ändert sich eine Skala oder eine Zuordnung, muss die
   alte Rechnung verschwinden können, ohne dass jemand rät, welcher Anteil
   der Summe von wo kam.

### `rider_season_points.uci_points` bleibt absichtlich leer

Diese Rechnung deckt **zwei von dreizehn** Anlässen ab. Eine Teilsumme in
eine Spalte zu schreiben, die „UCI-Punkte" heisst, wäre genau die stille
Falschaussage, die dieses Projekt an anderen Stellen beseitigt hat. Wer die
Teilsumme sehen will, fragt `uci_berechnung.rangliste()` — die Funktion
heisst so und ist im Docstring als **Teil**summe gekennzeichnet.

### Artikel 2.6.001 in Code

Der Auslöser der Regel — „the other stages are **cancelled**" — steht
nirgends in unseren Daten. Das nächstliegende Signal ist: ein Rennen **mit**
Etappen, das Ergebnisse für genau **eine** Etappe hat. Danach wird
gerechnet: Etappenpunkte ja, Gesamtklassement nein.

Dieses Signal ist nicht beweisend — ein Rennen, dessen Etappen nur teilweise
gescraped wurden, sieht genauso aus. **Deshalb wird jede Anwendung als
Warnung geloggt, mit Rennnamen.** Die Regel soll fast nie greifen; greift
sie oft, ist das kein Beleg für viele Absagen, sondern für Lücken im
Scraping. Die Warnung ist die einzige Stelle, an der dieser Unterschied
auffallen kann.

### Wer keine `rider_id` hat, bekommt keine Punkte

`race_results.rider_id` ist nur dort gesetzt, wo sich der Name einem Fahrer
zuordnen liess (in Produktion rund die Hälfte der Zeilen). Ohne ID lässt
sich die Zeile keinem Fahrer gutschreiben. Die Zahl steht in der
Log-Meldung — sie sagt zugleich, wie vollständig die Rechnung überhaupt
sein kann.

### Prüfen

```bash
DATABASE_URL=postgresql://... python3 scripts/check-uci-berechnung.py
```

27 Prüfungen gegen **konkrete Zahlen aus dem Reglement**: Tour-Gesamtsieg
1300, Platz 2 1040, Platz 60 noch 15, Platz 61 nichts, Etappensieg 210,
unterste Stufe 400. Ein Test, der nur „irgendwelche Punkte" prüft, würde
eine um eine Position verschobene Skala nicht bemerken — und das ist der
wahrscheinlichste Fehler.

Dazu: Art. 2.6.001 in **beide** Richtungen (ein Rennen mit einer Etappe
bekommt kein Gesamtklassement, eines mit zweien schon), das `punkt_datum`,
ein Rennen ohne Zuordnung bleibt ungerechnet, der zweite Lauf tut nichts,
neue Ergebnisse ersetzen statt zu ergänzen, eine Doppelnennung wird gezählt
statt verdoppelt, und `rider_season_points` bleibt unberührt.

Fünf Gegenproben, jede bricht die zuständige Prüfung: Skala um eine
Position verschoben, Art. 2.6.001 nie angewandt, immer angewandt, alte
Zeilen nicht gelöscht, Merker ignoriert.

### Die weitere Reihenfolge

1. ~~Die 121 `race_id` zuordnen~~ — **gebaut**, 67 von 69 Männer-Zeilen.
2. ~~Berechnung für `gc` und `etappe`~~ — **gebaut**. Offen bleibt die
   Gegenprobe gegen eine **veröffentlichte** UCI-Rangliste: sie ist von
   dieser Arbeitsumgebung aus nicht abrufbar und braucht eine Quelle.
2. **Die Berechnung für `gc` und `etappe`** bauen, inklusive der Ausfallregel
   aus 2.6.001, und gegen eine veröffentlichte Rangliste gegenprüfen. Erst
   dieser Vergleich zeigt, ob die Kette stimmt.
3. **`taxonomy.Category` erweitern** um Class 1, Class 2 und 1.2U/2.2U.
   Das ist ein eigener Schritt mit eigenem Risiko: der Scraper setzt die
   Kategorie, Migration 0003 hat einen CHECK darauf, und das Frontend
   übersetzt sie für die Anzeige.
4. **Trikot und Nebenwertungen** — erst wenn die beiden offenen
   Reglement-Fragen geklärt sind.
5. **Meisterschaften, WM, Olympia** — eigener Kalender-Zweig, eigene
   Scraper-Arbeit.

Schritt 1 und 2 sind zusammen überschaubar. Schritt 5 ist ein Projekt für
sich.
