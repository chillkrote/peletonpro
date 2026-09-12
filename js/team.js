// ===== TEAM-DETAILSEITE =====
// Zeigt ein einzelnes Team (aus dem query-param ?id=): Name, Land,
// Wikipedia-Link, Saison-Statistiken (Siege/Podestplätze/Top-10) aus den
// Rennergebnissen, sowie den aktuellen Kader aus der Fahrer-Datenbank
// (js/riders.js: renderTeamRoster) mit Link auf jedes Fahrerprofil.
document.addEventListener('DOMContentLoaded', async () => {
    renderNav({ crumbs: [{ label: 'Start', href: 'index.html' }, { label: 'Teams & Fahrer', href: 'teams.html' }, { label: 'Team' }] });

    const content = document.getElementById('team-content');
    if (renderComingSoonIfWomen(content)) return;

    const teamId = new URLSearchParams(window.location.search).get('id');
    if (!teamId) {
        content.innerHTML = errorPanel('Kein Team angegeben.');
        return;
    }

    content.innerHTML = `<div class="state-panel"><i class="fas fa-spinner fa-spin"></i><h3>Lade Team…</h3></div>`;
    try {
        const [teamsRes, racesRes, resultsRes] = await Promise.all([Api.getTeams(), Api.getRaces(), Api.getResults()]);
        const team = (teamsRes.teams || []).find((t) => t.id === teamId);
        if (!team) {
            content.innerHTML = errorPanel('Dieses Team wurde nicht gefunden.');
            return;
        }
        renderTeam(content, team, racesRes.races || [], resultsRes.results || []);
        renderTeamRoster(document.getElementById('team-roster'), teamId);
    } catch (err) {
        console.error('Fehler beim Laden des Teams:', err);
        content.innerHTML = errorPanel('Team konnte nicht geladen werden.');
    }
});

function errorPanel(text) {
    return `<div class="state-panel"><i class="fas fa-exclamation-triangle"></i><h3>${escapeHtml(text)}</h3></div>`;
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

function formatDate(dateStr) {
    return new Date(dateStr).toLocaleDateString('de-DE', { day: '2-digit', month: 'long', year: 'numeric' });
}

function computeStats(team, results) {
    let wins = 0;
    let podiums = 0;
    let topTen = 0;
    results.forEach((result) => {
        const idx = (result.results || []).findIndex((r) => r.team === team.name);
        if (idx === -1) return;
        topTen += 1;
        if (idx === 0) wins += 1;
        if (idx <= 2) podiums += 1;
    });
    return { wins, podiums, topTen };
}

function renderTeam(container, team, races, results) {
    document.title = `${team.name} – PelotonPro`;
    renderNav({ crumbs: [{ label: 'Start', href: 'index.html' }, { label: 'Teams & Fahrer', href: 'teams.html' }, { label: team.name }] });

    const racesById = Object.fromEntries(races.map((r) => [r.id, r]));
    const stats = computeStats(team, results);

    const wins = results
        .map((result) => ({ result, winner: (result.results || [])[0] }))
        .filter((entry) => entry.winner && entry.winner.team === team.name)
        .map((entry) => ({ race: racesById[entry.result.race_id], rider: entry.winner.rider }))
        .filter((entry) => entry.race)
        .sort((a, b) => b.race.start_date.localeCompare(a.race.start_date));

    container.innerHTML = `
        <div class="team-banner">
            <div class="logo-circle-lg">
                ${team.logo ? `<img src="${safeUrl(team.logo)}" alt="" onerror="this.parentElement.textContent='${escapeHtml(initials(team.name))}';">` : escapeHtml(initials(team.name))}
            </div>
            <div>
                <h1>${escapeHtml(team.name)}</h1>
                <div class="meta">
                    <span><i class="fas fa-flag"></i> ${escapeHtml(team.country)}</span>
                    <span class="sep">·</span>
                    <span>UCI WorldTeam</span>
                    ${team.source_url ? `<span class="sep">·</span><a class="wiki-link" href="${safeUrl(team.source_url)}" target="_blank" rel="noopener noreferrer"><i class="fab fa-wikipedia-w"></i> Wikipedia</a>` : ''}
                </div>
            </div>
        </div>

        <div class="stats-row">
            <div class="stat-card"><div class="val">${stats.wins}</div><div class="lbl">Saisonsiege</div></div>
            <div class="stat-card"><div class="val">${stats.podiums}</div><div class="lbl">Podestplätze</div></div>
            <div class="stat-card"><div class="val">${stats.topTen}</div><div class="lbl">Top-10-Platzierungen</div></div>
        </div>

        <div class="team-wins-wrap">
            <h2>Saisonsiege 2026</h2>
            ${
                wins.length > 0
                    ? wins
                          .map(
                              (w) => `
                <a class="win-row" href="races.html">
                    <i class="fas fa-trophy trophy"></i>
                    <div>
                        <div class="wr-name">${escapeHtml(w.race.name)}</div>
                        <div class="wr-meta">${escapeHtml(w.rider)} · ${formatDate(w.race.start_date)}</div>
                    </div>
                </a>`
                          )
                          .join('')
                    : `<p style="color:var(--text-muted);font-size:14px">Noch keine Saisonsiege erfasst.</p>`
            }
        </div>

        <div class="team-wins-wrap">
            <h2>Kader</h2>
            <div id="team-roster"></div>
        </div>
    `;
}
