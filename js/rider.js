// ===== FAHRER-DETAILSEITE =====
// Zeigt ein einzelnes Fahrerprofil (aus dem query-param ?id=): Stammdaten,
// aktuelles Team, Wikipedia- und Strava-Link (falls über Wikidata gefunden,
// siehe backend/app/scrapers/wikidata.py), die Saison-für-Saison-Historie
// in der World Tour inkl. UCI-Punkte (aktuell noch ein Platzhalter - siehe
// backend/README.md, Abschnitt "Bekannte Lücke": ein künftiger Import aus
// einer anderen UCI-Punkte-Datenbank soll die Werte nachtragen) sowie,
// darunter, alle Team-Stationen laut Wikipedia-Infobox (auch außerhalb der
// World Tour, z.B. frühere Continental-Teams).
document.addEventListener('DOMContentLoaded', async () => {
    renderNav({ crumbs: [{ label: 'Start', href: 'index.html' }, { label: 'Teams & Fahrer', href: 'teams.html' }, { label: 'Fahrer' }] });

    const content = document.getElementById('rider-content');
    if (renderComingSoonIfWomen(content)) return;

    const riderId = new URLSearchParams(window.location.search).get('id');
    if (!riderId) {
        content.innerHTML = errorPanel('Kein Fahrer angegeben.');
        return;
    }

    content.innerHTML = `<div class="state-panel"><i class="fas fa-spinner fa-spin"></i><h3>Lade Fahrer…</h3></div>`;
    try {
        const [rider, teamsRes] = await Promise.all([
            Api.getRider(riderId),
            Api.getTeams().catch(() => ({ teams: [] })),
        ]);
        renderRider(content, rider, teamsRes.teams || []);
    } catch (err) {
        console.error('Fehler beim Laden des Fahrers:', err);
        content.innerHTML = errorPanel('Dieser Fahrer wurde nicht gefunden.');
    }
});

function errorPanel(text) {
    return `<div class="state-panel"><i class="fas fa-exclamation-triangle"></i><h3>${escapeHtml(text)}</h3></div>`;
}

function renderRider(container, rider, teams) {
    document.title = `${rider.name} – PelotonPro`;
    renderNav({ crumbs: [{ label: 'Start', href: 'index.html' }, { label: 'Teams & Fahrer', href: 'teams.html' }, { label: rider.name }] });

    // seasons[].team_wiki_url -> unsere interne Team-ID, damit wir intern
    // verlinken können statt immer auf Wikipedia zu verweisen (jede Saison
    // ist laut Backend ohnehin bei einem uns bekannten WorldTour-Team, siehe
    // db.get_rider_seasons).
    const teamIdByWikiUrl = new Map(teams.filter((t) => t.source_url).map((t) => [t.source_url, t.id]));
    const seasons = [...(rider.seasons || [])].sort((a, b) => b.year - a.year);
    const history = [...(rider.history || [])].sort((a, b) => b.start_year - a.start_year);

    function teamCell(name, wikiUrl) {
        const internalId = wikiUrl ? teamIdByWikiUrl.get(wikiUrl) : null;
        if (internalId) return `<a href="team.html?id=${encodeURIComponent(internalId)}">${escapeHtml(name)}</a>`;
        if (wikiUrl) return `<a href="${safeUrl(wikiUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(name)}</a>`;
        return escapeHtml(name);
    }

    container.innerHTML = `
        <div class="team-banner rider-banner">
            <div class="logo-circle-lg rider-avatar">${escapeHtml(riderInitials(rider.name))}</div>
            <div>
                <h1>${escapeHtml(rider.last_name || rider.name)}<span class="rider-first"> ${escapeHtml(rider.first_name || '')}</span></h1>
                <div class="meta">
                    ${rider.country ? `<span><i class="fas fa-flag"></i> ${escapeHtml(rider.country)}</span><span class="sep">·</span>` : ''}
                    ${rider.birth_date ? `<span><i class="fas fa-cake-candles"></i> ${formatBirthDate(rider.birth_date)}</span><span class="sep">·</span>` : ''}
                    ${rider.current_team_id ? `<a class="wiki-link" href="team.html?id=${encodeURIComponent(rider.current_team_id)}"><i class="fas fa-shield-halved"></i> ${escapeHtml(rider.current_team_name || '')}</a><span class="sep">·</span>` : ''}
                    ${rider.wiki_url ? `<a class="wiki-link" href="${safeUrl(rider.wiki_url)}" target="_blank" rel="noopener noreferrer"><i class="fab fa-wikipedia-w"></i> Wikipedia</a>` : ''}
                    ${rider.strava_url ? `<span class="sep">·</span><a class="wiki-link strava" href="${safeUrl(rider.strava_url)}" target="_blank" rel="noopener noreferrer"><i class="fab fa-strava"></i> Strava</a>` : ''}
                </div>
            </div>
        </div>

        <div class="team-wins-wrap">
            <h2>Karriere in der World Tour</h2>
            ${
                seasons.length > 0
                    ? `
                <div class="season-table-wrap">
                    <table class="season-table">
                        <thead><tr><th>Saison</th><th>Team</th><th>UCI-Punkte</th></tr></thead>
                        <tbody>
                            ${seasons
                                .map(
                                    (s) => `
                                <tr>
                                    <td class="season-year">${s.year}</td>
                                    <td>${teamCell(s.team_name, s.team_wiki_url)}</td>
                                    <td class="season-points">${
                                        s.uci_points !== null && s.uci_points !== undefined
                                            ? s.uci_points
                                            : '<span class="tbd" title="Wird nachgetragen, sobald eine Quelle dafür verfügbar ist">noch nicht erfasst</span>'
                                    }</td>
                                </tr>`
                                )
                                .join('')}
                        </tbody>
                    </table>
                </div>`
                    : `<p style="color:var(--text-muted);font-size:14px">Noch keine World-Tour-Saison erfasst.</p>`
            }
        </div>

        ${
            history.length > 0
                ? `
        <div class="team-wins-wrap">
            <h2>Alle Team-Stationen (laut Wikipedia)</h2>
            <ul class="stints-list">
                ${history
                    .map(
                        (h) => `
                    <li>
                        <span class="stint-years">${h.start_year}${h.end_year && h.end_year !== h.start_year ? `–${h.end_year}` : h.end_year ? '' : '–'}</span>
                        <span class="stint-team">${teamCell(h.team_name, h.team_wiki_url)}</span>
                    </li>`
                    )
                    .join('')}
            </ul>
        </div>`
                : ''
        }
    `;
}
