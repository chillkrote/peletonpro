// ===== TEAMS & FAHRER-SEITE =====
// Zwei Tabs in einer Seite: "Teams" (Kachel-Grid, Klick führt zur
// Team-Detailseite team.html?id=...) und "Fahrer" (komplette, durchsuch-
// bare Fahrerliste aus der Datenbank, siehe js/riders.js). Der Fahrer-Tab
// wird erst beim ersten Klick geladen, damit ein Seitenaufruf ohne
// Fahrer-Interesse nicht unnötig ~500 Datensätze lädt.
import { Api, escapeHtml, safeUrl } from './api.js';
import { apiGender, renderComingSoonIfWomen, renderNav } from './nav.js';
import { initRidersTab } from './riders.js';
import { errorPanel, loadingPanel, starten, statePanel, teamInitials } from './ui.js';

starten(async () => {
    renderNav({ crumbs: [{ label: 'Start', href: 'index.html' }, { label: 'Teams & Fahrer' }] });

    const teamsContent = document.getElementById('teams-content');
    const ridersContent = document.getElementById('riders-content');
    if (await renderComingSoonIfWomen(teamsContent, async () => {
        const res = await Api.getTeams(null, apiGender());
        return !(res.teams || []).length;
    })) return;

    initTabs(teamsContent, ridersContent);

    teamsContent.innerHTML = loadingPanel('Lade Teams…');
    try {
        const { teams } = await Api.getTeams(null, apiGender());
        renderTeams(teamsContent, teams || []);
    } catch (err) {
        console.error('Fehler beim Laden der Teams:', err);
        teamsContent.innerHTML = errorPanel('Teams konnten nicht geladen werden.', 'Bitte später erneut versuchen.');
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

function renderTeams(container, teams) {
    teamsSubtitleText = `${teams.length} UCI WorldTeams der World Tour`;
    const subtitle = document.getElementById('teams-subtitle');
    if (subtitle) subtitle.textContent = teamsSubtitleText;

    if (teams.length === 0) {
        container.innerHTML = statePanel('fas fa-users-slash', 'Keine Teams gefunden');
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
                        ${team.logo ? `<img src="${safeUrl(team.logo)}" alt="" loading="lazy" onerror="this.parentElement.textContent='${escapeHtml(teamInitials(team.name))}';">` : escapeHtml(teamInitials(team.name))}
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
