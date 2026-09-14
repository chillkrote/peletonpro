// ===== STARTSEITE =====
// Nur die 3 Kacheln (Races/Teams/News) + Gender-Umschalter. Lädt lediglich
// die Anzahl je Bereich für die kleinen Badges auf den Kacheln.
import { Api } from './api.js';
import { apiGender, isWomen, renderNav } from './nav.js';
import { starten } from './ui.js';

starten(async () => {
    renderNav();

    if (isWomen()) {
        document.querySelectorAll('.tile .bignum').forEach((el) => {
            el.textContent = 'bald verfügbar';
        });
        return;
    }

    try {
        const [teamsRes, racesRes, newsRes, ridersRes] = await Promise.all([
            Api.getTeams(null, apiGender()),
            // Nur die Gesamtzahl, nicht die Rennen selbst: limit=1 holt eine
            // Zeile, `total` nennt den vollen Bestand (siehe
            // routers/race_history.py).
            Api.getRaceHistory({ limit: 1, gender: apiGender() }).catch(() => null),
            Api.getNews(1),
            // Ebenso nur die Zahl. Vorher holte die Startseite alle ~500
            // Fahrer, um sie zu zählen - mit dem Frauen-Radsport wären das
            // ein paar Tausend, für eine Zahl in einer Kachel.
            // Fahrer-DB kann fehlen (kein DATABASE_URL) - dann bleibt die
            // Kachel bei der Teams-Zahl.
            Api.getRiders(null, { limit: 1, gender: apiGender() }).catch(() => null),
        ]);
        const teamCount = (teamsRes.teams || []).length;
        const riderCount = ridersRes && !ridersRes.error ? ridersRes.total : null;
        const raceCount = racesRes && !racesRes.error ? racesRes.total : null;
        setBadge('tile-races-count', raceCount !== null ? `${raceCount} Rennen` : '–');
        setBadge('tile-teams-count', riderCount !== null ? `${teamCount} Teams · ${riderCount} Fahrer` : `${teamCount} Teams`);
        setBadge('tile-news-count', newsRes.last_updated ? 'aktuell' : '–');
    } catch (err) {
        console.error('Fehler beim Laden der Kachel-Kennzahlen:', err);
    }
});

function setBadge(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}
