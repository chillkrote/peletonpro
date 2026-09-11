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
        const [teamsRes, racesRes, newsRes] = await Promise.all([
            Api.getTeams(),
            Api.getRaces(),
            Api.getNews(1),
        ]);
        setBadge('tile-races-count', `${(racesRes.races || []).length} Rennen`);
        setBadge('tile-teams-count', `${(teamsRes.teams || []).length} Teams`);
        setBadge('tile-news-count', newsRes.last_updated ? 'aktuell' : '–');
    } catch (err) {
        console.error('Fehler beim Laden der Kachel-Kennzahlen:', err);
    }
});

function setBadge(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}
