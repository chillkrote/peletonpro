// ===== FAHRER: gemeinsame Bausteine =====
// Wird von drei Stellen genutzt: dem "Fahrer"-Tab auf teams.html (komplette,
// durchsuch-/filterbare Liste), dem Kader-Ausschnitt auf der Team-Detailseite
// (team.js) und der Fahrer-Detailseite (rider.js). Bündelt hier, damit
// Darstellung (Initialen, Geburtsdatum, Strava-Link, Team-Badge) überall
// gleich aussieht.

import { Api, escapeHtml, safeUrl } from './api.js';
import {
    errorPanel, formatCalendarDate, loadingPanel, pendingPanel, riderInitials, statePanel,
} from './ui.js';

export function formatBirthDate(dateStr) {
    return formatCalendarDate(dateStr) || null;
}

function stravaLink(rider) {
    if (!rider.strava_url) return '';
    return `<a class="strava-link" href="${safeUrl(rider.strava_url)}" target="_blank" rel="noopener noreferrer" title="Strava-Profil" onclick="event.stopPropagation()"><i class="fab fa-strava"></i></a>`;
}

function teamBadge(rider) {
    if (!rider.current_team_id) {
        return `<span class="team-badge muted">kein Team</span>`;
    }
    return `<a class="team-badge" href="team.html?id=${encodeURIComponent(rider.current_team_id)}" onclick="event.stopPropagation()">${escapeHtml(rider.current_team_name || rider.current_team_id)}</a>`;
}

function riderRow(rider) {
    const searchKey = `${rider.name} ${rider.country || ''} ${rider.current_team_name || ''}`.toLowerCase();
    return `
        <tr class="rider-row" data-id="${escapeHtml(rider.id)}" data-search="${escapeHtml(searchKey)}" data-team="${escapeHtml(rider.current_team_id || '')}">
            <td class="rname">
                <div class="last">${escapeHtml(rider.last_name || rider.name)}</div>
                <div class="first">${escapeHtml(rider.first_name || '')}</div>
            </td>
            <td class="rcountry">${rider.country ? `<i class="fas fa-flag"></i> ${escapeHtml(rider.country)}` : '–'}</td>
            <td class="rteam">${teamBadge(rider)}</td>
            <td class="rstrava">${stravaLink(rider) || '<span class="no-strava">–</span>'}</td>
        </tr>
    `;
}

function renderRidersTable(container, riders, teams) {
    const teamOptions = [...teams].sort((a, b) => a.name.localeCompare(b.name));
    container.innerHTML = `
        <div class="riders-toolbar">
            <div class="search-box">
                <i class="fas fa-search"></i>
                <input type="text" id="rider-search" placeholder="Fahrer, Land oder Team suchen…" autocomplete="off">
            </div>
            <select id="rider-team-filter">
                <option value="">Alle Teams</option>
                ${teamOptions.map((t) => `<option value="${escapeHtml(t.id)}">${escapeHtml(t.name)}</option>`).join('')}
            </select>
            <span class="riders-count" id="riders-count"></span>
        </div>
        <div class="rider-table-wrap">
            <table class="rider-table">
                <thead>
                    <tr>
                        <th>Fahrer <span class="sort-hint">(sortiert nach Nachname)</span></th>
                        <th>Land</th>
                        <th>Team</th>
                        <th>Strava</th>
                    </tr>
                </thead>
                <tbody id="rider-tbody">${riders.map(riderRow).join('')}</tbody>
            </table>
        </div>
    `;

    const tbody = container.querySelector('#rider-tbody');
    tbody.querySelectorAll('.rider-row').forEach((row) => {
        row.addEventListener('click', () => {
            window.location.href = `rider.html?id=${encodeURIComponent(row.dataset.id)}`;
        });
    });

    const searchInput = container.querySelector('#rider-search');
    const teamFilter = container.querySelector('#rider-team-filter');
    const countLabel = container.querySelector('#riders-count');

    function applyFilters() {
        const q = searchInput.value.trim().toLowerCase();
        const teamId = teamFilter.value;
        let visible = 0;
        tbody.querySelectorAll('.rider-row').forEach((row) => {
            const show = (!q || row.dataset.search.includes(q)) && (!teamId || row.dataset.team === teamId);
            row.hidden = !show;
            if (show) visible += 1;
        });
        countLabel.textContent = `${visible} von ${riders.length} Fahrern`;
    }

    searchInput.addEventListener('input', applyFilters);
    teamFilter.addEventListener('change', applyFilters);
    applyFilters();
}

// Holt ALLE Fahrer und blättert dabei über offset weiter. Vorher ein
// einzelner Aufruf ohne limit: das Backend liefert dann seine Obergrenze
// (1000 Zeilen) und die Liste war ab dem 1001. Fahrer stillschweigend
// abgeschnitten - keine Meldung, kein Hinweis, nur fehlende Fahrer. Bei
// ~500 WorldTour-Fahrern fiel das nicht auf; mit dem Frauen-Radsport oder
// weiteren Kategorien schon. Dasselbe Muster wie js/races.js::loadSeason.
async function loadAllRiders() {
    const riders = [];
    let offset = 0;
    for (;;) {
        const res = await Api.getRiders(null, { offset });
        if (res.error) return { riders, error: res.error };
        riders.push(...(res.riders || []));
        offset += res.limit;
        if (riders.length >= res.total || !(res.riders || []).length) break;
    }
    return { riders, error: null };
}

export async function initRidersTab(container) {
    container.innerHTML = loadingPanel('Lade Fahrer…');
    try {
        const [ridersRes, teamsRes] = await Promise.all([loadAllRiders(), Api.getTeams()]);
        if (ridersRes.error) {
            container.innerHTML = statePanel('fas fa-database', 'Fahrer-Datenbank nicht verfügbar', ridersRes.error);
            return;
        }
        const riders = ridersRes.riders || [];
        if (riders.length === 0) {
            container.innerHTML = pendingPanel('Noch keine Fahrer geladen', 'Die Fahrer-Datenbank');
            return;
        }
        renderRidersTable(container, riders, teamsRes.teams || []);
    } catch (err) {
        console.error('Fehler beim Laden der Fahrer:', err);
        container.innerHTML = errorPanel('Fahrer konnten nicht geladen werden.', 'Bitte später erneut versuchen.');
    }
}

export async function renderTeamRoster(container, teamId) {
    container.innerHTML = statePanel('fas fa-spinner fa-spin', 'Lade Kader…', null, 'state-panel small');
    try {
        const { riders, error } = await Api.getRiders(teamId);
        if (error) {
            container.innerHTML = `<p class="roster-empty">Fahrer-Datenbank nicht verfügbar.</p>`;
            return;
        }
        if (!riders || riders.length === 0) {
            container.innerHTML = `<p class="roster-empty">Noch kein Kader für dieses Team geladen.</p>`;
            return;
        }
        container.innerHTML = `
            <div class="roster-grid">
                ${riders
                    .map(
                        (r) => `
                    <a class="roster-card" href="rider.html?id=${encodeURIComponent(r.id)}">
                        <div class="rc-avatar">${escapeHtml(riderInitials(r.name))}</div>
                        <div class="rc-name">
                            <div class="last">${escapeHtml(r.last_name || r.name)}</div>
                            <div class="first">${escapeHtml(r.first_name || '')}</div>
                        </div>
                        ${r.country ? `<div class="rc-country"><i class="fas fa-flag"></i> ${escapeHtml(r.country)}</div>` : ''}
                        ${stravaLink(r)}
                    </a>`
                    )
                    .join('')}
            </div>
        `;
    } catch (err) {
        console.error('Fehler beim Laden des Kaders:', err);
        container.innerHTML = `<p class="roster-empty">Kader konnte nicht geladen werden.</p>`;
    }
}
