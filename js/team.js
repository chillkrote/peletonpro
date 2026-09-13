// ===== TEAM-DETAILSEITE =====
// Zeigt ein einzelnes Team (aus dem query-param ?id=): Name, Land,
// Wikipedia-Link, Saison-Statistiken (Siege/Podestplätze/Top-10) aus den
// Rennergebnissen, sowie den aktuellen Kader aus der Fahrer-Datenbank
// (js/riders.js: renderTeamRoster) mit Link auf jedes Fahrerprofil.
import { Api, escapeHtml, safeUrl } from './api.js';
import { renderComingSoonIfWomen, renderNav } from './nav.js';
import { renderTeamRoster } from './riders.js';
import { errorPanel, formatCalendarDate, loadingPanel, starten, teamInitials } from './ui.js';

starten(async () => {
    renderNav({ crumbs: [{ label: 'Start', href: 'index.html' }, { label: 'Teams & Fahrer', href: 'teams.html' }, { label: 'Team' }] });

    const content = document.getElementById('team-content');
    if (renderComingSoonIfWomen(content)) return;

    const teamId = new URLSearchParams(window.location.search).get('id');
    if (!teamId) {
        content.innerHTML = errorPanel('Kein Team angegeben.');
        return;
    }

    content.innerHTML = loadingPanel('Lade Team…');
    try {
        // Das Team kommt über GET /api/teams/{id} - vorher wurde die
        // komplette Team-Liste geholt und darin mit find() gesucht.
        // Statistik und Siege kommen aus der Renn-Historie-Datenbank (ein
        // Aufruf, Aggregation per GROUP BY im Backend) statt aus dem
        // flüchtigen Cache mit Berechnung im Browser.
        const [team, statsRes] = await Promise.all([
            Api.getTeam(teamId),
            Api.getTeamStats(teamId).catch(() => null),
        ]);
        renderTeam(content, team, statsRes);
        renderTeamRoster(document.getElementById('team-roster'), teamId);
    } catch (err) {
        // 404 vom Backend heißt: diese Team-ID gibt es nicht. Alles andere
        // ist ein Fehler auf unserer Seite - beides soll der Besucher
        // unterschiedlich lesen können.
        console.error('Fehler beim Laden des Teams:', err);
        content.innerHTML = err && err.status === 404
            ? errorPanel('Dieses Team wurde nicht gefunden.')
            : errorPanel('Team konnte nicht geladen werden.', 'Bitte später erneut versuchen.');
    }
});


function renderTeam(container, team, statsRes) {
    document.title = `${team.name} – PelotonPro`;
    renderNav({ crumbs: [{ label: 'Start', href: 'index.html' }, { label: 'Teams & Fahrer', href: 'teams.html' }, { label: team.name }] });

    const stats = (statsRes && statsRes.stats) || { wins: 0, podiums: 0, top_ten: 0, races: 0 };
    const wins = (statsRes && statsRes.wins) || [];
    const season = (statsRes && statsRes.season) || new Date().getFullYear();

    container.innerHTML = `
        <div class="team-banner">
            <div class="logo-circle-lg">
                ${team.logo ? `<img src="${safeUrl(team.logo)}" alt="" onerror="this.parentElement.textContent='${escapeHtml(teamInitials(team.name))}';">` : escapeHtml(teamInitials(team.name))}
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
            <div class="stat-card"><div class="val">${stats.wins}</div><div class="lbl">Siege</div></div>
            <div class="stat-card"><div class="val">${stats.podiums}</div><div class="lbl">Podestplätze</div></div>
            <div class="stat-card"><div class="val">${stats.top_ten}</div><div class="lbl">Top-10-Platzierungen</div></div>
        </div>

        <div class="team-wins-wrap">
            <h2>Siege ${season}</h2>
            ${
                wins.length > 0
                    ? wins
                          .map(
                              (w) => `
                <a class="win-row" href="races.html">
                    <i class="fas fa-trophy trophy"></i>
                    <div>
                        <div class="wr-name">${escapeHtml(w.race_name)}${
                            w.stage_number ? ` <span class="wr-stage">Etappe ${w.stage_number}</span>` : ''
                        }</div>
                        <div class="wr-meta">${escapeHtml(w.rider)}${
                            w.start_date ? ` · ${formatCalendarDate(w.start_date, { day: '2-digit', month: 'long', year: 'numeric' })}` : ''
                        }</div>
                    </div>
                </a>`
                          )
                          .join('')
                    : `<p style="color:var(--text-muted);font-size:14px">Noch keine Siege erfasst.</p>`
            }
        </div>

        <div class="team-wins-wrap">
            <h2>Kader</h2>
            <div id="team-roster"></div>
        </div>
    `;
}
