// ===== RACES-SEITE =====
// Rennkalender + Ergebnisse. Laufende Rennen (heutiges Datum zwischen
// start_date und end_date) werden zuerst angezeigt, der Rest kalendarisch
// (aufsteigend nach Datum). Klick auf eine Zeile klappt die Top-Ergebnisse
// des Rennens auf (sofern vorhanden).
const RACE_TYPE_LABEL = {
    gt: 'Grand Tour',
    monument: 'Monument',
    stage_race: 'Etappenrennen',
    one_day: 'Eintagesrennen',
};

document.addEventListener('DOMContentLoaded', async () => {
    renderNav({ crumbs: [{ label: 'Start', href: 'index.html' }, { label: 'Races' }] });

    const content = document.getElementById('races-content');
    if (renderComingSoonIfWomen(content)) return;

    content.innerHTML = loadingPanel('Lade Rennkalender…');
    try {
        const [racesRes, resultsRes] = await Promise.all([Api.getRaces(), Api.getResults()]);
        renderRaces(content, racesRes.races || [], resultsRes.results || []);
    } catch (err) {
        console.error('Fehler beim Laden der Rennen:', err);
        content.innerHTML = errorPanel('Rennen konnten nicht geladen werden.');
    }
});

function loadingPanel(text) {
    return `<div class="state-panel"><i class="fas fa-spinner fa-spin"></i><h3>${escapeHtml(text)}</h3></div>`;
}

function errorPanel(text) {
    return `<div class="state-panel"><i class="fas fa-exclamation-triangle"></i><h3>${escapeHtml(text)}</h3><p>Bitte später erneut versuchen.</p></div>`;
}

function todayIso() {
    return new Date().toISOString().slice(0, 10);
}

function isLiveRace(race) {
    const today = todayIso();
    return race.start_date <= today && today <= race.end_date;
}

function formatDayMonth(dateStr) {
    const date = new Date(dateStr);
    return {
        day: date.toLocaleDateString('de-DE', { day: '2-digit' }),
        month: date.toLocaleDateString('de-DE', { month: 'short' }).replace('.', '').toUpperCase(),
    };
}

function sectionLabel(text) {
    return `<div class="section-label"><span>${escapeHtml(text)}</span><span class="line"></span></div>`;
}

function renderRaces(container, races, results) {
    if (races.length === 0) {
        container.innerHTML = `<div class="state-panel"><i class="fas fa-calendar-xmark"></i><h3>Keine Rennen gefunden</h3></div>`;
        return;
    }

    const resultsByRace = Object.fromEntries(results.map((r) => [r.race_id, r]));
    const live = races.filter(isLiveRace);
    const rest = races
        .filter((r) => !isLiveRace(r))
        .sort((a, b) => a.start_date.localeCompare(b.start_date));

    let html = '';
    if (live.length > 0) {
        html += sectionLabel('Läuft gerade');
        html += `<div class="race-list">${live.map((r) => raceRowHtml(r, resultsByRace[r.id], true)).join('')}</div>`;
    }
    html += sectionLabel('Rennkalender');
    html += `<div class="race-list">${rest.map((r) => raceRowHtml(r, resultsByRace[r.id], false)).join('')}</div>`;

    container.innerHTML = html;
    attachExpandHandlers(container, resultsByRace);
}

function raceRowHtml(race, result, live) {
    const { day, month } = formatDayMonth(race.start_date);
    const typeLabel = RACE_TYPE_LABEL[race.type] || race.type;
    const winner = result && result.results && result.results.length > 0 ? result.results[0] : null;

    let resultHtml;
    if (live) {
        resultHtml = `<div class="result-preview muted">läuft gerade</div>`;
    } else if (winner) {
        resultHtml = `
            <div class="result-preview">
                <div class="flag-dot"><i class="fas fa-trophy" style="font-size:11px"></i></div>
                <div>
                    <div class="wname">${escapeHtml(winner.rider)}</div>
                    <div class="wteam">${escapeHtml(winner.team)}</div>
                </div>
            </div>`;
    } else {
        resultHtml = `<div class="result-preview muted">${race.start_date > todayIso() ? 'bevorstehend' : 'noch kein Ergebnis'}</div>`;
    }

    return `
        <div class="race-row ${live ? 'is-live' : ''}" data-race-id="${escapeHtml(race.id)}">
            <div class="date"><div class="d">${day}</div><div class="m">${month}</div></div>
            <div class="divider"></div>
            <div class="info">
                <div class="toprow">
                    <span class="name">${escapeHtml(race.name)}</span>
                    ${live ? '<span class="badge badge-live">Live</span>' : `<span class="badge badge-${escapeHtml(race.type)}">${escapeHtml(typeLabel)}</span>`}
                </div>
                <div class="country">${escapeHtml(race.country)}${race.stages ? ` · ${race.stages} Etappen` : ''}</div>
            </div>
            ${resultHtml}
            <i class="fas fa-chevron-right chev"></i>
        </div>
    `;
}

function attachExpandHandlers(container, resultsByRace) {
    container.querySelectorAll('.race-row').forEach((row) => {
        row.addEventListener('click', () => {
            const result = resultsByRace[row.dataset.raceId];
            const alreadyOpen = row.nextElementSibling && row.nextElementSibling.classList.contains('race-results-panel');

            container.querySelectorAll('.race-results-panel').forEach((p) => p.remove());
            container.querySelectorAll('.race-row.expanded').forEach((r) => r.classList.remove('expanded'));
            if (alreadyOpen) return;

            if (!result || !result.results || result.results.length === 0) return;
            row.classList.add('expanded');
            const panel = document.createElement('div');
            panel.className = 'race-results-panel';
            panel.innerHTML = `
                <table>
                    <thead><tr><th>#</th><th>Fahrer</th><th>Team</th><th>Zeit</th></tr></thead>
                    <tbody>
                        ${result.results
                            .map(
                                (r) => `
                            <tr>
                                <td class="pos">${escapeHtml(String(r.position))}</td>
                                <td>${escapeHtml(r.rider)}</td>
                                <td class="team-name">${escapeHtml(r.team)}</td>
                                <td>${escapeHtml(r.time || r.gap || '-')}</td>
                            </tr>`
                            )
                            .join('')}
                    </tbody>
                </table>
            `;
            row.after(panel);
        });
    });
}
