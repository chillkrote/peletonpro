// ===== GEMEINSAME UI-HELFER =====
// Wird von allen Seiten geladen, vor den seitenspezifischen Skripten.
//
// Hier liegt, was mehr als eine Seite braucht: Datums-Formatierung,
// Zustands-Panels (Laden/Fehler) und die Initialen für die Logo-Kreise.
// Alle drei lagen vorher mehrfach kopiert im Baum - die Datums-Formatierung
// vierfach (races.js zweimal, team.js, riders.js), und alle vier Kopien
// hatten denselben Zeitzonen-Fehler (siehe unten); errorPanel dreifach in
// zwei verschiedenen Fassungen; die Initialen zweifach mit zwei
// Trennregeln.

// ---------------------------------------------------------------------------
// Kalenderdaten
// ---------------------------------------------------------------------------
// Das Backend liefert reine Kalenderdaten als ISO-String ("2026-03-21"):
// Renndatum, Etappendatum, Geburtsdatum. Diese Angaben haben keine Uhrzeit
// und keine Zeitzone - der 21. März ist überall der 21. März.
//
// `new Date("2026-03-21")` erzeugt daraus nach ECMAScript aber UTC-Mitternacht,
// und `toLocaleDateString` rendert das in der Zeitzone des Besuchers. Westlich
// von UTC kommt dabei der Vortag heraus:
//
//   TZ=Europe/Berlin     -> 21. März 2026   (richtig, zufällig)
//   TZ=America/New_York  -> 20. März 2026   (falsch)
//
// Deshalb wird der String zerlegt und über den Drei-Argument-Konstruktor
// gebaut, der LOKALE Mitternacht erzeugt. Damit stimmt die Anzeige in jeder
// Zeitzone.

function parseCalendarDate(iso) {
    if (!iso) return null;
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso));
    if (!match) return null;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const date = new Date(year, month - 1, day);
    // Date rollt Unsinn stillschweigend weiter ("2026-13-45" -> 14.02.2027).
    // Aus Postgres-DATE-Spalten kann das nicht kommen, aber ein Helfer, der
    // ein falsches Datum liefert statt zuzugeben, dass er nichts erkennt,
    // ist eine Falle - deshalb gegengeprüft.
    if (
        date.getFullYear() !== year ||
        date.getMonth() !== month - 1 ||
        date.getDate() !== day
    ) {
        return null;
    }
    return date;
}

// Formatiert ein Kalenderdatum. `options` wie bei toLocaleDateString.
// Liefert '' bei fehlendem oder unlesbarem Datum, damit Aufrufer nicht
// jedes Mal selbst prüfen müssen.
function formatCalendarDate(iso, options = { day: '2-digit', month: '2-digit', year: 'numeric' }) {
    const date = parseCalendarDate(iso);
    if (date === null || Number.isNaN(date.getTime())) return '';
    return date.toLocaleDateString('de-DE', options);
}

// Heutiges Datum als ISO-Kalenderdatum in der Zeitzone des Besuchers.
// Bewusst NICHT über toISOString(): das liefert das UTC-Datum und läge an
// den Tagesgrenzen gegen die lokal angezeigten Renndaten daneben.
function todayCalendarIso() {
    const now = new Date();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    return `${now.getFullYear()}-${month}-${day}`;
}

// ---------------------------------------------------------------------------
// Echte Zeitstempel
// ---------------------------------------------------------------------------
// Für Werte MIT Uhrzeit und Zeitzone (RSS-`published`) ist `new Date(...)`
// korrekt und darf nicht umgebaut werden - dort ist der Zeitpunkt gemeint,
// nicht der Kalendertag. Siehe js/news.js::formatRelative.

// ---------------------------------------------------------------------------
// Zustands-Panels
// ---------------------------------------------------------------------------
// errorPanel lag dreifach kopiert in races.js, rider.js und team.js, in zwei
// verschiedenen Fassungen: die in races.js nahm einen zweiten Parameter
// (detail) und zeigte ohne ihn "Bitte später erneut versuchen.", die beiden
// anderen kannten ihn nicht. Hier steht die Fassung mit detail - aber OHNE
// den Vorgabetext: bei "Dieser Fahrer wurde nicht gefunden." hilft späteres
// Erneut-Versuchen nicht, und eine Aufforderung dazu wäre irreführend. Die
// zwei Aufrufe in races.js, die den Satz wirklich wollen, übergeben ihn
// jetzt selbst.
//
// team.js hatte seine Kopien beim Umbau auf /api/teams/{id}/stats verloren,
// ohne sie zu ersetzen - errorPanel und initials waren dort nicht mehr
// definiert, und team.html lädt kein Skript, das sie mitbringt. Die
// Team-Detailseite lief damit in einen ReferenceError. Das behebt dieser
// Schritt mit.

// Die Auszeichnung stand vierzehnmal wortgleich im Baum, jedes Mal nur mit
// anderem Icon und Text. Hier einmal, mit dem Icon als Parameter. `detail`
// ist optional und wird weggelassen, statt einen Vorgabesatz zu erfinden.
// `klasse` deckt die kleine Variante ab ("state-panel small"), die der
// Kader-Ausschnitt auf der Team-Seite benutzt.
function statePanel(icon, text, detail, klasse = 'state-panel') {
    const extra = detail ? `<p>${escapeHtml(detail)}</p>` : '';
    return `<div class="${escapeHtml(klasse)}"><i class="${escapeHtml(icon)}"></i><h3>${escapeHtml(text)}</h3>${extra}</div>`;
}

function loadingPanel(text) {
    return statePanel('fas fa-spinner fa-spin', text);
}

function errorPanel(text, detail) {
    return statePanel('fas fa-exclamation-triangle', text, detail);
}

// "Noch nichts da" ist kein Fehler: der Scheduler befüllt gerade. Eigene
// Funktion, weil der Satz an mehreren Stellen gleich lauten soll - `was`
// benennt darin die Quelle ("Die Renn-Historie", "Die Fahrer-Datenbank").
function pendingPanel(text, was) {
    return statePanel(
        'fas fa-hourglass-half', text,
        `${was} wird gerade im Hintergrund befüllt - schau in ein paar Minuten wieder vorbei.`,
    );
}

// ---------------------------------------------------------------------------
// Initialen für die Logo-/Avatar-Kreise
// ---------------------------------------------------------------------------
// Bewusst ZWEI Funktionen über einem gemeinsamen Kern, nicht eine: Team- und
// Personennamen müssen unterschiedlich getrennt werden, und das ist kein
// Versehen, das sich zusammenfassen ließe.
//
//   "Bahrain–Victorious"   Team   -> "BV"   (Strich trennt die Namensteile)
//   "Jean-Pierre Drucker"  Person -> "JD"   (Strich gehört zum Vornamen)
//
// Eine gemeinsame Funktion müsste sich für eine Trennregel entscheiden und
// würde die andere Seite falsch abkürzen ("JP" für Jean-Pierre Drucker).

function initialsFrom(name, separator) {
    return String(name || '')
        .split(separator)
        .filter(Boolean)
        .slice(0, 2)
        .map((word) => word[0])
        .join('')
        .toUpperCase();
}

// Teamnamen: Leerzeichen, Bindestrich und Halbgeviertstrich trennen.
function teamInitials(name) {
    return initialsFrom(name, /[\s–-]+/);
}

// Personennamen: nur Leerzeichen trennen.
function riderInitials(name) {
    return initialsFrom(name, /\s+/);
}
