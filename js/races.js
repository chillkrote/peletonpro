// ===== RACES-SEITE =====
// Rennkalender aus der Renn-Historie-Datenbank (WorldTour/ProSeries/
// Continental seit 2020, siehe backend/README.md "Renn-Historie"). Nach
// Saison getrennt (Tabs), innerhalb einer Saison optional nach Kategorie
// gefiltert (Chips). Sortierung innerhalb einer Saison: primär nach Datum,
// aber laufende Rennen und Grand Tours werden unabhängig vom Datum immer
// oben angezeigt (jeweils eigene Sektion). Ergebnisse (Top 10, bei
// Etappenrennen zusätzlich pro Etappe) werden erst beim Aufklappen einer
// Zeile nachgeladen (GET /api/race-history/{id}) statt für alle Rennen
// einer Saison vorab - bei teils 200+ Rennen/Saison wäre das zu viel auf
// einmal.
const CATEGORY_LABEL = { wt: 'World Tour', proseries: 'ProSeries', continental: 'Continental' };
const CIRCUIT_LABEL = { africa: 'Africa Tour', asia: 'Asia Tour', europe: 'Europe Tour', america: 'America Tour', oceania: 'Oceania Tour' };
const GRAND_TOUR_NAMES = new Set(['Tour de France', 'Giro d\'Italia', 'Vuelta a España', 'Vuelta a Espana']);

// Rennen werden pro Saison geladen und hier zwischengespeichert, statt alle
// Saisons auf einmal zu holen: die Renn-Historie umfasst schon jetzt ~2.000
// Rennen und wächst mit jeder weiteren Datenbank. Serverseitig ist limit
// ohnehin auf 500 begrenzt.
const racesBySeason = new Map();
let SEASONS = [];
let selectedSeason = null;
let selectedCategory = '';
const detailCache = new Map();

document.addEventListener('DOMContentLoaded', async () => {
    renderNav({ crumbs: [{ label: 'Start', href: 'index.html' }, { label: 'Races' }] });

    const content = document.getElementById('races-content');
    if (renderComingSoonIfWomen(content)) return;

    content.innerHTML = loadingPanel('Lade Rennkalender…');
    try {
        const res = await Api.getRaceSeasons();
        if (res.error) {
            content.innerHTML = errorPanel('Rennkalender-Datenbank nicht verfügbar.', res.error);
            return;
        }
        SEASONS = res.seasons || [];
        if (SEASONS.length === 0) {
            content.innerHTML = `<div class="state-panel"><i class="fas fa-hourglass-half"></i><h3>Noch keine Rennen geladen</h3><p>Die Renn-Historie wird gerade im Hintergrund befüllt - schau in ein paar Minuten wieder vorbei.</p></div>`;
            return;
        }
        await initSeasonsAndCategories();
    } catch (err) {
        console.error('Fehler beim Laden des Rennkalenders:', err);
        content.innerHTML = errorPanel('Rennkalender konnte nicht geladen werden.');
    }
});

// Holt eine Saison einmalig und merkt sie sich. Blättert über offset weiter,
// falls eine Saison die serverseitige Obergrenze überschreitet - die UCI
// Europe Tour allein bringt 170-200 Rennen pro Saison mit.
async function loadSeason(season) {
    if (racesBySeason.has(season)) return racesBySeason.get(season);
    const races = [];
    let offset = 0;
    for (;;) {
        const res = await Api.getRaceHistory({ season, offset });
        if (res.error) throw new Error(res.error);
        races.push(...(res.races || []));
        offset += res.limit;
        if (races.length >= res.total || !(res.races || []).length) break;
    }
    racesBySeason.set(season, races);
    return races;
}

function loadingPanel(text) {
    return `<div class="state-panel"><i class="fas fa-spinner fa-spin"></i><h3>${escapeHtml(text)}</h3></div>`;
}

function errorPanel(text, detail) {
    return `<div class="state-panel"><i class="fas fa-exclamation-triangle"></i><h3>${escapeHtml(text)}</h3><p>${escapeHtml(detail || 'Bitte später erneut versuchen.')}</p></div>`;
}

// Lokales Kalenderdatum (siehe js/ui.js). Vorher das UTC-Datum aus
// toISOString(), was an den Tagesgrenzen gegen die lokal angezeigten
// Renndaten daneben lag.
function todayIso() {
    return todayCalendarIso();
}

function isLiveRace(race) {
    return !!race.start_date && !!race.end_date && race.start_date <= todayIso() && todayIso() <= race.end_date;
}

function isGrandTour(race) {
    return GRAND_TOUR_NAMES.has(race.name);
}

function byDateAsc(a, b) {
    return (a.start_date || '9999-99-99').localeCompare(b.start_date || '9999-99-99');
}

function formatDayMonth(dateStr) {
    const day = formatCalendarDate(dateStr, { day: '2-digit' });
    if (!day) return { day: '?', month: '' };
    return {
        day,
        month: formatCalendarDate(dateStr, { month: 'short' }).replace('.', '').toUpperCase(),
    };
}

function formatDateShort(dateStr) {
    return formatCalendarDate(dateStr, { day: '2-digit', month: 'short' });
}

function sectionLabel(text) {
    return `<div class="section-label"><span>${escapeHtml(text)}</span><span class="line"></span></div>`;
}

function categoryLabel(race) {
    if (race.category === 'continental' && race.circuit) return CIRCUIT_LABEL[race.circuit] || 'Continental';
    return CATEGORY_LABEL[race.category] || race.category;
}

// ---------------------------------------------------------------------- //
// Saison-Tabs + Kategorie-Filter
// ---------------------------------------------------------------------- //

async function initSeasonsAndCategories() {
    const seasons = SEASONS;
    const currentYear = new Date().getFullYear();
    selectedSeason = seasons.includes(currentYear) ? currentYear : seasons[0];

    const seasonTabs = document.getElementById('season-tabs');
    seasonTabs.innerHTML = seasons
        .map((s) => `<button type="button" data-season="${s}" class="${s === selectedSeason ? 'active' : ''}">${s}</button>`)
        .join('');
    seasonTabs.querySelectorAll('button').forEach((btn) => {
        btn.addEventListener('click', () => {
            if (btn.classList.contains('active')) return;
            seasonTabs.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b === btn));
            selectedSeason = Number(btn.dataset.season);
            renderCurrentSelection();  // lädt die Saison bei Bedarf nach
        });
    });

    const categories = [
        { value: '', label: 'Alle' },
        { value: 'wt', label: 'World Tour' },
        { value: 'proseries', label: 'ProSeries' },
        { value: 'continental', label: 'Continental' },
    ];
    const categoryFilters = document.getElementById('category-filters');
    categoryFilters.innerHTML = categories
        .map((c) => `<button type="button" class="chip ${c.value === selectedCategory ? 'active' : ''}" data-category="${c.value}">${escapeHtml(c.label)}</button>`)
        .join('');
    categoryFilters.querySelectorAll('.chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            categoryFilters.querySelectorAll('.chip').forEach((c) => c.classList.remove('active'));
            chip.classList.add('active');
            selectedCategory = chip.dataset.category;
            renderCurrentSelection();
        });
    });

    renderCurrentSelection();
}

async function renderCurrentSelection() {
    const content = document.getElementById('races-content');
    if (!racesBySeason.has(selectedSeason)) {
        content.innerHTML = loadingPanel(`Lade Saison ${selectedSeason}…`);
    }
    let races;
    try {
        races = await loadSeason(selectedSeason);
    } catch (err) {
        console.error('Fehler beim Laden der Saison:', err);
        content.innerHTML = errorPanel(`Saison ${selectedSeason} konnte nicht geladen werden.`);
        return;
    }
    if (selectedCategory) races = races.filter((r) => r.category === selectedCategory);
    renderRaceList(content, races);
}

// ---------------------------------------------------------------------- //
// Renn-Liste: laufende Rennen und Grand Tours zuerst, Rest nach Datum
// ---------------------------------------------------------------------- //

function renderRaceList(container, races) {
    if (races.length === 0) {
        container.innerHTML = `<div class="state-panel"><i class="fas fa-calendar-xmark"></i><h3>Keine Rennen in dieser Auswahl</h3></div>`;
        return;
    }

    const live = races.filter(isLiveRace).sort(byDateAsc);
    const grandTours = races.filter((r) => !isLiveRace(r) && isGrandTour(r)).sort(byDateAsc);
    const rest = races.filter((r) => !isLiveRace(r) && !isGrandTour(r)).sort(byDateAsc);

    let html = '';
    if (live.length > 0) {
        html += sectionLabel('Läuft gerade');
        html += `<div class="race-list">${live.map((r) => raceRowHtml(r, true)).join('')}</div>`;
    }
    if (grandTours.length > 0) {
        html += sectionLabel('Grand Tours');
        html += `<div class="race-list">${grandTours.map((r) => raceRowHtml(r, false)).join('')}</div>`;
    }
    html += sectionLabel(`Rennkalender ${selectedSeason}`);
    html += rest.length > 0
        ? `<div class="race-list">${rest.map((r) => raceRowHtml(r, false)).join('')}</div>`
        : `<p class="race-panel-empty" style="max-width:1280px;margin:0 auto;padding:0 24px 40px">Keine weiteren Rennen in dieser Auswahl.</p>`;

    container.innerHTML = html;
    attachExpandHandlers(container);
}

function raceRowHtml(race, live) {
    const { day, month } = formatDayMonth(race.start_date);
    const metaParts = [categoryLabel(race)];
    if (race.num_stages) metaParts.push(`${race.num_stages} Etappen`);
    if (race.distance_km) metaParts.push(`${Math.round(race.distance_km)} km`);

    let resultHtml;
    if (live) {
        resultHtml = `<div class="result-preview muted">läuft gerade</div>`;
    } else if (!race.results_fetched_at) {
        resultHtml = `<div class="result-preview muted">${(race.start_date || '') > todayIso() ? 'bevorstehend' : 'Details folgen'}</div>`;
    } else {
        resultHtml = `<div class="result-preview muted">Ergebnisse ansehen</div>`;
    }

    return `
        <div class="race-row ${live ? 'is-live' : ''}" data-race-id="${escapeHtml(race.id)}">
            <div class="date"><div class="d">${day}</div><div class="m">${month}</div></div>
            <div class="divider"></div>
            <div class="info">
                <div class="toprow">
                    <span class="name">${escapeHtml(race.name)}</span>
                    ${live ? '<span class="badge badge-live">Live</span>' : ''}
                    ${isGrandTour(race) ? '<span class="badge badge-gt">Grand Tour</span>' : ''}
                </div>
                <div class="country">${escapeHtml(metaParts.join(' · '))}</div>
            </div>
            ${resultHtml}
            <i class="fas fa-chevron-right chev"></i>
        </div>
    `;
}

// ---------------------------------------------------------------------- //
// Ergebnisse (inkl. Etappen) werden erst beim Aufklappen nachgeladen
// ---------------------------------------------------------------------- //

function attachExpandHandlers(container) {
    container.querySelectorAll('.race-row').forEach((row) => {
        row.addEventListener('click', async () => {
            const raceId = row.dataset.raceId;
            const alreadyOpen = row.nextElementSibling && row.nextElementSibling.classList.contains('race-results-panel');

            container.querySelectorAll('.race-results-panel').forEach((p) => p.remove());
            container.querySelectorAll('.race-row.expanded').forEach((r) => r.classList.remove('expanded'));
            if (alreadyOpen) return;

            row.classList.add('expanded');
            const panel = document.createElement('div');
            panel.className = 'race-results-panel';
            panel.innerHTML = `<div class="state-panel small"><i class="fas fa-spinner fa-spin"></i><h3>Lade Ergebnisse…</h3></div>`;
            row.after(panel);

            try {
                let detail = detailCache.get(raceId);
                if (!detail) {
                    detail = await Api.getRaceHistoryDetail(raceId);
                    detailCache.set(raceId, detail);
                }
                panel.innerHTML = renderResultPanel(detail);
            } catch (err) {
                console.error('Fehler beim Laden der Ergebnisse:', err);
                panel.innerHTML = `<p class="race-panel-empty">Ergebnisse konnten nicht geladen werden.</p>`;
            }
        });
    });
}

function renderResultPanel(detail) {
    const parts = [];

    const links = [];
    if (detail.organizer_website) links.push(`<a href="${safeUrl(detail.organizer_website)}" target="_blank" rel="noopener noreferrer"><i class="fas fa-globe"></i> Offizielle Seite</a>`);
    if (detail.wiki_url) links.push(`<a href="${safeUrl(detail.wiki_url)}" target="_blank" rel="noopener noreferrer"><i class="fab fa-wikipedia-w"></i> Wikipedia</a>`);
    if (links.length > 0) parts.push(`<div class="race-panel-links">${links.join('<span class="sep">·</span>')}</div>`);

    if (detail.results && detail.results.length > 0) {
        parts.push(resultsTableHtml(detail.results, detail.stages && detail.stages.length > 0 ? 'Gesamtwertung' : null));
    } else if (!detail.results_fetched_at) {
        parts.push(`<p class="race-panel-empty">Details werden noch geladen.</p>`);
    } else {
        parts.push(`<p class="race-panel-empty">Keine Ergebnisliste erfasst.</p>`);
    }

    if (detail.stages && detail.stages.length > 0) {
        parts.push(`
            <div class="stage-breakdown">
                ${detail.stages
                    .map((s) => {
                        const meta = [
                            s.date ? formatDateShort(s.date) : null,
                            s.start_location && s.end_location ? `${escapeHtml(s.start_location)} – ${escapeHtml(s.end_location)}` : null,
                            s.distance_km ? `${Math.round(s.distance_km)} km` : null,
                        ]
                            .filter(Boolean)
                            .join(' · ');
                        const winner = s.results && s.results.length > 0 ? s.results[0] : null;
                        return `
                        <div class="stage-row">
                            <div class="stage-num">${s.stage_number}</div>
                            <div class="stage-meta">${meta || '–'}</div>
                            <div class="stage-winner${winner ? '' : ' muted'}">${winner ? `<i class="fas fa-trophy"></i> ${escapeHtml(winner.rider)}` : 'kein Ergebnis erfasst'}</div>
                        </div>`;
                    })
                    .join('')}
            </div>
        `);
    }

    return parts.join('');
}

function resultsTableHtml(results, caption) {
    return `
        ${caption ? `<div class="results-caption">${escapeHtml(caption)}</div>` : ''}
        <table>
            <thead><tr><th>#</th><th>Fahrer</th><th>Team</th><th>Zeit</th></tr></thead>
            <tbody>
                ${results
                    .map(
                        (r) => `
                    <tr>
                        <td class="pos">${escapeHtml(String(r.position))}</td>
                        <td>${escapeHtml(r.rider)}</td>
                        <td class="team-name">${escapeHtml(r.team || '')}</td>
                        <td>${escapeHtml(r.time_or_gap || '-')}</td>
                    </tr>`
                    )
                    .join('')}
            </tbody>
        </table>
    `;
}
