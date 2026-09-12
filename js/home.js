// ===== STARTSEITE =====
// Nur die 3 Kacheln (Races/Teams/News) + Gender-Umschalter. Lädt lediglich
// die Anzahl je Bereich für die kleinen Badges auf den Kacheln.
document.addEventListener('DOMContentLoaded', async () => {
    renderNav();

    if (isWomen()) {
        document.querySelectorAll('.tile .bignum').forEach((el) => {
            el.textContent = 'bald verfügbar';
        });
        return;
    }

    try {
        const [teamsRes, racesRes, newsRes, ridersRes] = await Promise.all([
            Api.getTeams(),
            Api.getRaces(),
            Api.getNews(1),
            Api.getRiders().catch(() => null), // Fahrer-DB kann fehlen (kein DATABASE_URL) - Kachel bleibt dann bei Teams-Zahl
        ]);
        const teamCount = (teamsRes.teams || []).length;
        const riderCount = ridersRes && !ridersRes.error ? (ridersRes.riders || []).length : null;
        setBadge('tile-races-count', `${(racesRes.races || []).length} Rennen`);
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
