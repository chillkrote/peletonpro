// ===== TEAMS & FAHRER-SEITE =====
// Zwei Tabs in einer Seite: "Teams" (Kachel-Grid, Klick führt zur
// Team-Detailseite team.html?id=...) und "Fahrer" (komplette, durchsuch-
// bare Fahrerliste aus der Datenbank, siehe js/riders.js). Der Fahrer-Tab
// wird erst beim ersten Klick geladen, damit ein Seitenaufruf ohne
// Fahrer-Interesse nicht unnötig ~500 Datensätze lädt.
document.addEventListener('DOMContentLoaded', async () => {
    renderNav({ crumbs: [{ label: 'Start', href: 'index.html' }, { label: 'Teams & Fahrer' }] });

    const teamsContent = document.getElementById('teams-content');
    const ridersContent = document.getElementById('riders-content');
    if (renderComingSoonIfWomen(teamsContent)) return;

    initTabs(teamsContent, ridersContent);

    teamsContent.innerHTML = `<div class="state-panel"><i class="fas fa-spinner fa-spin"></i><h3>Lade Teams…</h3></div>`;
    try {
        const { teams } = await Api.getTeams();
        renderTeams(teamsContent, teams || []);
    } catch (err) {
        console.error('Fehler beim Laden der Teams:', err);
        teamsContent.innerHTML = `<div class="state-panel"><i class="fas fa-exclamation-triangle"></i><h3>Teams konnten nicht geladen werden.</h3><p>Bitte später erneut versuchen.</p></div>`;
    }
});

let teamsSubtitleText = 'UCI WorldTeams der World Tour';

function initTabs(teamsContent, ridersContent) {
    const tabs = document.getElementById('teams-tabs');
    if (!tabs) return;
    const subtitle = document.getElementById('teams-subtitle');
    let ridersLoaded = false;

    tabs.querySelectorAll('button').forEach((btn) => {
        btn.addEventListener('click', () => {
            if (btn.classList.contains('active')) return;
            tabs.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b === btn));

            const showRiders = btn.dataset.tab === 'riders';
            teamsContent.hidden = showRiders;
            ridersContent.hidden = !showRiders;
            if (subtitle) {
                subtitle.textContent = showRiders
                    ? 'Alle Fahrer der World Tour, standardmäßig nach Nachname sortiert'
                    : teamsSubtitleText;
            }
            if (showRiders && !ridersLoaded) {
                ridersLoaded = true;
                initRidersTab(ridersContent);
            }
        });
    });
}

function initials(name) {
    return name
        .split(/[\s–-]+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((word) => word[0])
        .join('')
        .toUpperCase();
}

function renderTeams(container, teams) {
    teamsSubtitleText = `${teams.length} UCI WorldTeams der World Tour`;
    const subtitle = document.getElementById('teams-subtitle');
    if (subtitle) subtitle.textContent = teamsSubtitleText;

    if (teams.length === 0) {
        container.innerHTML = `<div class="state-panel"><i class="fas fa-users-slash"></i><h3>Keine Teams gefunden</h3></div>`;
        return;
    }

    const sorted = [...teams].sort((a, b) => a.name.localeCompare(b.name));
    container.innerHTML = `
        <div class="team-grid">
            ${sorted
                .map(
                    (team) => `
                <a class="team-card" href="team.html?id=${encodeURIComponent(team.id)}">
                    <div class="bar"></div>
                    <div class="logo-circle">
                        ${team.logo ? `<img src="${safeUrl(team.logo)}" alt="" loading="lazy" onerror="this.parentElement.textContent='${escapeHtml(initials(team.name))}';">` : escapeHtml(initials(team.name))}
                    </div>
                    <h3>${escapeHtml(team.name)}</h3>
                    <div class="country"><i class="fas fa-flag"></i> ${escapeHtml(team.country)}</div>
                </a>
            `
                )
                .join('')}
        </div>
    `;
}
