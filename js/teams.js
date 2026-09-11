// ===== TEAMS-SEITE =====
// Kachel-Grid aller Teams. Klick führt zur Team-Detailseite (team.html?id=...).
document.addEventListener('DOMContentLoaded', async () => {
    renderNav({ crumbs: [{ label: 'Start', href: 'index.html' }, { label: 'Teams' }] });

    const content = document.getElementById('teams-content');
    if (renderComingSoonIfWomen(content)) return;

    content.innerHTML = `<div class="state-panel"><i class="fas fa-spinner fa-spin"></i><h3>Lade Teams…</h3></div>`;
    try {
        const { teams } = await Api.getTeams();
        renderTeams(content, teams || []);
    } catch (err) {
        console.error('Fehler beim Laden der Teams:', err);
        content.innerHTML = `<div class="state-panel"><i class="fas fa-exclamation-triangle"></i><h3>Teams konnten nicht geladen werden.</h3><p>Bitte später erneut versuchen.</p></div>`;
    }
});

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
    const subtitle = document.getElementById('teams-subtitle');
    if (subtitle) subtitle.textContent = `${teams.length} UCI WorldTeams der World Tour`;

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
