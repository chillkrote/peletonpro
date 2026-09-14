// ===== FAHRER-DETAILSEITE =====
// Zeigt ein einzelnes Fahrerprofil (aus dem query-param ?id=): Stammdaten,
// aktuelles Team, Wikipedia- und Strava-Link (falls über Wikidata gefunden,
// siehe backend/app/scrapers/wikidata.py), die Saison-für-Saison-Historie
// in der World Tour inkl. UCI-Punkte (aktuell noch ein Platzhalter - siehe
// backend/README.md, Abschnitt "Bekannte Lücke": ein künftiger Import aus
// einer anderen UCI-Punkte-Datenbank soll die Werte nachtragen) sowie,
// darunter, alle Team-Stationen laut Wikipedia-Infobox (auch außerhalb der
// World Tour, z.B. frühere Continental-Teams) und die Ergebnisse aus der
// Renn-Historie.
import { Api, escapeHtml, safeUrl } from './api.js';
import { apiGender, renderComingSoonIfWomen, renderNav } from './nav.js';
import { formatBirthDate } from './riders.js';
import { errorPanel, formatCalendarDate, loadingPanel, riderInitials, starten } from './ui.js';

starten(async () => {
    renderNav({ crumbs: [{ label: 'Start', href: 'index.html' }, { label: 'Teams & Fahrer', href: 'teams.html' }, { label: 'Fahrer' }] });

    const content = document.getElementById('rider-content');
    if (await renderComingSoonIfWomen(content, async () => {
        const res = await Api.getRiders(null, { limit: 1, gender: apiGender() });
        return !res.total;
    })) return;

    const riderId = new URLSearchParams(window.location.search).get('id');
    if (!riderId) {
        content.innerHTML = errorPanel('Kein Fahrer angegeben.');
        return;
    }

    content.innerHTML = loadingPanel('Lade Fahrer…');
    try {
        const [rider, teamsRes] = await Promise.all([
            Api.getRider(riderId),
            Api.getTeams(null, apiGender()).catch(() => ({ teams: [] })),
        ]);
        renderRider(content, rider, teamsRes.teams || []);
        // Erst nach dem Rendern des Profils: die Ergebnisliste ist ein
        // eigener, paginierter Endpunkt, und das Profil soll nicht auf sie
        // warten. Bewusst ohne await - ein Fehler dort darf die Seite nicht
        // in den catch-Zweig unten ziehen, der "Fahrer nicht gefunden"
        // zeigen würde.
        ladeErgebnisse(riderId);
    } catch (err) {
        // 404 heißt: diese Fahrer-ID gibt es nicht. Alles andere ist ein
        // Fehler auf unserer Seite - vorher stand in beiden Fällen "wurde
        // nicht gefunden", auch wenn das Backend gar nicht erreichbar war.
        // Nachgemessen mit abgeschaltetem Backend: die Seite behauptete, den
        // Fahrer gebe es nicht. Gleiche Unterscheidung wie in js/team.js.
        console.error('Fehler beim Laden des Fahrers:', err);
        content.innerHTML = err && err.status === 404
            ? errorPanel('Dieser Fahrer wurde nicht gefunden.')
            : errorPanel('Fahrer konnte nicht geladen werden.', 'Bitte später erneut versuchen.');
    }
});

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

        <div class="team-wins-wrap" id="ergebnisse">
            <h2>Ergebnisse</h2>
            <div id="ergebnis-inhalt">${loadingPanel('Lade Ergebnisse…')}</div>
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


// ===== ERGEBNISSE =====
// Möglich geworden durch race_results.rider_id (Migration 0004). Vorher
// stand dort nur der Name als Text, und diese Liste hätte über einen
// Namensvergleich gehen müssen - mit derselben stillen Lücke, die die
// Team-Statistik hatte (siehe backend/README.md, "Ergebniszeilen:
// verknüpft statt nur beschriftet").

// Muss zum Default des Endpunkts passen (RESULTS_DEFAULT_LIMIT in
// routers/riders.py). Serverseitiges Maximum ist 200.
const ERGEBNISSE_PRO_SEITE = 50;

async function ladeErgebnisse(riderId) {
    const inhalt = document.getElementById('ergebnis-inhalt');
    if (!inhalt) return;

    let offset = 0;
    let gesamt = 0;
    const zeilen = [];

    // Benannte Funktion, damit sie sich selbst als "Weitere laden"-Handler
    // übergeben kann. Ein erster Entwurf stand hier mit arguments.callee.
    // Das ist im strict mode - und Module laufen immer so - ein
    // vergifteter Zugriff: er wirft beim AUFRUF einen TypeError, nicht beim
    // Laden. Die Seite hätte also normal ausgesehen und erst beim Klick auf
    // "Weitere laden" nichts getan. Nachgemessen mit
    // scripts/check-rider-results.mjs: drei Prüfungen schlagen fehl, die
    // Liste bleibt bei 50 Zeilen stehen.
    async function naechsteSeite() {
        const res = await Api.getRiderResults(riderId, { limit: ERGEBNISSE_PRO_SEITE, offset });
        // Der Endpunkt antwortet auch bei einem Datenbankproblem mit 200 und
        // `error` im Rumpf (siehe routers/messages.py) - das muss hier
        // geprüft werden, sonst sieht ein Ausfall wie "keine Ergebnisse" aus.
        if (res.error) throw new Error(res.error);
        zeilen.push(...(res.results || []));
        offset += ERGEBNISSE_PRO_SEITE;
        gesamt = res.total || 0;
        zeichne(inhalt, zeilen, gesamt, naechsteSeite);
    }

    try {
        await naechsteSeite();
    } catch (err) {
        console.error('Fehler beim Laden der Ergebnisse:', err);
        inhalt.innerHTML = errorPanel('Ergebnisse konnten nicht geladen werden.',
            'Das Profil oben ist davon nicht betroffen.');
    }
}

function zeichne(inhalt, zeilen, gesamt, mehrLaden) {
    if (zeilen.length === 0) {
        inhalt.innerHTML = `<p style="color:var(--text-muted);font-size:14px">Für diesen Fahrer sind noch keine Ergebnisse erfasst.</p>`;
        return;
    }

    inhalt.innerHTML = `
        <div class="season-table-wrap">
            <table class="season-table rider-results">
                <thead><tr><th>Saison</th><th>Rennen</th><th>Platz</th><th>Zeit / Abstand</th></tr></thead>
                <tbody>${zeilen.map(zeile).join('')}</tbody>
            </table>
        </div>
        <p class="rr-count">${zeilen.length} von ${gesamt} Platzierungen</p>
        ${zeilen.length < gesamt ? `<button type="button" class="rr-more" id="ergebnis-mehr">Weitere laden</button>` : ''}
    `;

    const knopf = document.getElementById('ergebnis-mehr');
    if (knopf) {
        knopf.addEventListener('click', async () => {
            knopf.disabled = true;
            knopf.textContent = 'Lädt…';
            try {
                await mehrLaden();
            } catch (err) {
                console.error('Fehler beim Nachladen der Ergebnisse:', err);
                knopf.disabled = false;
                knopf.textContent = 'Erneut versuchen';
            }
        }, { once: true });
    }
}

function zeile(r) {
    // stage_number NULL heisst Gesamtwertung ODER Eintagesrennen - was von
    // beiden, steht nicht in der Ergebniszeile. Deshalb gar kein Zusatz
    // statt einer Behauptung; nur Etappen werden benannt. Gleiche
    // Unterscheidung wie in js/team.js.
    const etappe = r.stage_number ? ` <span class="wr-stage">Etappe ${r.stage_number}</span>` : '';
    // Nur Tag und Monat: das Jahr steht schon in der Saison-Spalte daneben.
    const datum = r.start_date
        ? formatCalendarDate(r.start_date, { day: '2-digit', month: 'short' })
        : '';
    return `
        <tr>
            <td class="season-year">${r.season}</td>
            <td>
                <a href="races.html">${escapeHtml(r.race_name)}</a>${etappe}
                ${r.is_grand_tour ? ` <span class="gt-badge" title="Grand Tour">GT</span>` : ''}
                ${datum ? `<div class="rr-date">${escapeHtml(datum)}</div>` : ''}
            </td>
            <td class="rr-pos">${r.position === 1 ? `<i class="fas fa-trophy trophy"></i> ` : ''}${r.position}</td>
            <td class="rr-gap">${r.time_or_gap ? escapeHtml(r.time_or_gap) : '—'}</td>
        </tr>`;
}
