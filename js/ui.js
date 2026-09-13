// ===== GEMEINSAME UI-HELFER =====
// Wird von allen Seiten geladen, vor den seitenspezifischen Skripten.
//
// Aktuell die Datums-Formatierung. Sie lag vorher vierfach kopiert in
// races.js (zweimal), team.js und riders.js - und alle vier hatten denselben
// Fehler (siehe unten). Weitere Helfer, die heute noch mehrfach existieren
// (errorPanel, loadingPanel, initials), gehören ebenfalls hierher.

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
