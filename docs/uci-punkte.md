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

## Was in diesem Dokument fehlt

**Artikel 2.6.001.** Beide Skalen verweisen darauf: „The awarding of points
for stage races is in accordance with article 2.6.001 regarding the
duration of the event." Die Punktevergabe bei Etappenrennen hängt also von
der **Renndauer** ab, und dieser Artikel steht in Kapitel VI, nicht in
Kapitel X. **Ohne ihn ist die Berechnung für Etappenrennen unvollständig.**

**Kontinental-Ranglisten für Frauen.** §3 (Art. 2.10.018 ff.) regelt nur
die Männer. Ob es für Frauen keine Kontinentalrangliste gibt oder sie an
anderer Stelle steht, lässt sich aus diesem Kapitel nicht entscheiden.

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

## Schema-Vorschlag

Die wichtigste Erkenntnis aus der Prüfung: **Männer- und Frauenskala sind
zahlengleich** — überall außer der einen fehlenden `class2u`-Spalte. Zwei
getrennte Tabellen wären also nicht nur doppelte Pflege, sie wären doppelte
Pflege für **dieselben Zahlen**. Eine Tabelle mit einer
Geschlechts-Spalte, wie sie das Projekt schon für Fahrer, Teams und Rennen
hat:

```sql
-- Welche Stufen es in welcher Saison gibt. Eigene Tabelle, damit die
-- beiden folgenden per Fremdschlüssel darauf zeigen können - eine
-- Rennzuordnung auf eine Stufe ohne Skala wird damit unmöglich, statt
-- erst beim Rechnen als stilles Null-Ergebnis aufzufallen.
CREATE TABLE uci_stufe (
    saison  INTEGER NOT NULL,
    gender  TEXT    NOT NULL,
    anlass  TEXT    NOT NULL,
    stufe   TEXT    NOT NULL,
    PRIMARY KEY (saison, gender, anlass, stufe)
);

-- Die Skala selbst. Ganzzahlig: im Reglement stehen nur ganze Zahlen.
CREATE TABLE uci_punkte (
    saison  INTEGER NOT NULL,
    gender  TEXT    NOT NULL,
    anlass  TEXT    NOT NULL,
    stufe   TEXT    NOT NULL,
    platz   INTEGER NOT NULL CHECK (platz >= 1),
    punkte  INTEGER NOT NULL CHECK (punkte > 0),
    PRIMARY KEY (saison, gender, anlass, stufe, platz),
    FOREIGN KEY (saison, gender, anlass, stufe)
        REFERENCES uci_stufe (saison, gender, anlass, stufe)
);

-- Welches Rennen in welcher Stufe läuft. Pro Saison, weil die UCI die
-- Listen jährlich ändert. race_id statt Rennname - siehe Fallstrick 1.
CREATE TABLE uci_rennstufe (
    saison   INTEGER NOT NULL,
    gender   TEXT    NOT NULL,
    anlass   TEXT    NOT NULL,
    stufe    TEXT    NOT NULL,
    race_id  TEXT    NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    PRIMARY KEY (saison, gender, anlass, race_id),
    FOREIGN KEY (saison, gender, anlass, stufe)
        REFERENCES uci_stufe (saison, gender, anlass, stufe)
);
```

`anlass` gehört als vierte Achse nach `app/taxonomy.py`, neben `gender`,
`category` und `circuit` — als `Literal[...]`, aus dem die Werte per
`get_args()` abgeleitet werden, und der CHECK in der Migration aus
derselben Quelle. Sonst stünde das Vokabular in der Datenbank, im Modell
und im Frontend je einmal, und `scripts/check-vokabular.py` würde es
melden. `stufe` dagegen **nicht**: die Stufen sind saisonabhängige Daten,
kein Vokabular.

### Drei Fallstricke

**1. Die WorldTour-Stufe ist nicht aus der Rennkategorie ableitbar.** Sie
ist eine Liste **namentlich genannter Rennen**, und die Zusammensetzung
ändert sich jede Saison. Über den Namen zuordnen geht auch nicht: das
Reglement selbst schreibt „Omloop Nieuwsblad" im Gesamtklassement der
Frauen als **„Oomlop Nieuwsblad"**, und „Lloyds Tour of Britain Women"
in der Trikot-Tabelle als „Lloyds Tour of Britain". Beide Schreibweisen
stehen unverändert in der CSV — sie sind die Quelle, nicht der Fehler. Die
Zuordnung braucht deshalb eine `race_id`, die von Hand oder halbautomatisch
einmal pro Saison gesetzt wird. Ein Namensabgleich würde bei jeder
Umbenennung still falsche Punkte liefern („In Flanders Fields - From
Middelkerke to Wevelgem" hieß früher Gent–Wevelgem).

**2. Die heutige Taxonomie reicht nicht.**
`taxonomy.Category` kennt `wt | proseries | continental`. Die Punkteskala
unterscheidet im Kontinentalkalender aber **Class 1**, **Class 2** und
**1.2U/2.2U** — auf Platz 1 sind das 125, 40 und 30 Punkte, also ein
Faktor 4. Alle drei landen heute in `continental`. Solange das so ist,
lassen sich für Rennen des Kontinentalkalenders **keine** Punkte
berechnen. Das ist eine echte Schema-Lücke, keine Bequemlichkeit.

**3. `rider_season_points.uci_points` ist `INTEGER`.**
Mannschaftszeitfahren-Punkte werden auf ein Hundertstel geteilt. Sobald
ein Fahrer 12,86 Punkte hat, ist die Spalte zu grob — sie braucht
`NUMERIC(8,2)`. Das ist eine Typänderung an einer Bestandsspalte, also nach
der Regel in `backend/README.md` („Kein Backup, und was das für Migrationen
heisst") erlaubt, solange nichts verloren geht: `INTEGER` → `NUMERIC` ist
verlustfrei. Die Spalte ist ausserdem heute noch überall `NULL`.

### Was das Schema noch nicht abdeckt

Die Tabellen oben halten das **Reglement**. Für eine eigene Berechnung
fehlen die Ergebnisse in einer Tiefe, die das Projekt heute nicht hat:
Etappenergebnisse einzeln, Nebenklassements, wer welches Trikot an welchem
Tag getragen hat, und bei Mannschaftszeitfahren die Liste der
Zielankömmlinge. Ein **Import** fertiger Punktzahlen braucht davon nichts —
er schreibt nur in `rider_season_points`. Der Unterschied ist erheblich,
und die Entscheidung zwischen beiden Wegen sollte vor dem ersten Schema
fallen, nicht danach.
