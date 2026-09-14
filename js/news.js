// ===== NEWS-SEITE =====
// Erste Meldung groß als Featured-Card, Rest im Karten-Grid. Filter-Chips
// nach Quelle werden dynamisch aus den geladenen Daten gebaut.
import { Api, escapeHtml, safeUrl } from './api.js';
import { renderComingSoonIfWomen, renderNav } from './nav.js';
import { errorPanel, loadingPanel, starten, statePanel } from './ui.js';

let allNews = [];
let currentSource = 'all';

starten(async () => {
    renderNav({ crumbs: [{ label: 'Start', href: 'index.html' }, { label: 'News' }] });

    const content = document.getElementById('news-content');
    // Ohne Leer-Prüfung: der RSS-Auszug ist allgemeine Radsport-Presse
    // und kennt keine Geschlechts-Dimension. Bei "Frauen" steht hier
    // deshalb weiter der Platzhalter - wie bisher.
    if (await renderComingSoonIfWomen(content)) return;

    content.innerHTML = loadingPanel('Lade News…');
    try {
        const { news } = await Api.getNews(30);
        allNews = news || [];
        renderPage(content);
    } catch (err) {
        console.error('Fehler beim Laden der News:', err);
        content.innerHTML = errorPanel('News konnten nicht geladen werden.', 'Bitte später erneut versuchen.');
    }
});

function formatRelative(dateStr) {
    if (!dateStr) return '';
    const then = new Date(dateStr).getTime();
    if (Number.isNaN(then)) return '';
    const diffMs = Date.now() - then;
    const hours = Math.floor(diffMs / (1000 * 60 * 60));
    if (hours < 1) return 'vor wenigen Minuten';
    if (hours < 24) return `vor ${hours} Stunde${hours === 1 ? '' : 'n'}`;
    const days = Math.floor(hours / 24);
    return `vor ${days} Tag${days === 1 ? '' : 'en'}`;
}

function getFiltered() {
    if (currentSource === 'all') return allNews;
    return allNews.filter((item) => item.source === currentSource);
}

function renderPage(container) {
    if (allNews.length === 0) {
        container.innerHTML = statePanel('fas fa-newspaper', 'Keine News verfügbar');
        return;
    }

    const sources = [...new Set(allNews.map((item) => item.source))];
    const chipsHtml = `
        <div class="news-filters">
            <span class="chip ${currentSource === 'all' ? 'active' : ''}" data-source="all">Alle</span>
            ${sources.map((s) => `<span class="chip ${currentSource === s ? 'active' : ''}" data-source="${escapeHtml(s)}">${escapeHtml(s)}</span>`).join('')}
        </div>
    `;

    container.innerHTML = `<div id="news-featured"></div>${chipsHtml}<div id="news-grid-wrap"></div>`;
    container.querySelectorAll('.chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            currentSource = chip.dataset.source;
            renderPage(container);
        });
    });

    renderList();
}

function renderList() {
    const filtered = getFiltered();
    const featuredWrap = document.getElementById('news-featured');
    const gridWrap = document.getElementById('news-grid-wrap');
    if (!featuredWrap || !gridWrap) return;

    if (filtered.length === 0) {
        featuredWrap.innerHTML = '';
        gridWrap.innerHTML = statePanel('fas fa-filter', 'Keine News für diese Auswahl');
        return;
    }

    const [featured, ...rest] = filtered;
    featuredWrap.innerHTML = `
        <div class="featured-news">
            <a class="card" href="${safeUrl(featured.link)}" target="_blank" rel="noopener noreferrer">
                <div class="img"><span class="tag">Top-Story</span></div>
                <div class="body">
                    <div class="source">${escapeHtml(featured.source)}</div>
                    <h2>${escapeHtml(featured.title)}</h2>
                    ${featured.summary ? `<p class="excerpt">${escapeHtml(featured.summary)}</p>` : ''}
                    <div class="time">${escapeHtml(formatRelative(featured.published))}</div>
                </div>
            </a>
        </div>
    `;

    gridWrap.innerHTML = `
        <div class="news-grid">
            ${rest
                .map(
                    (item) => `
                <a class="news-card" href="${safeUrl(item.link)}" target="_blank" rel="noopener noreferrer">
                    <div class="thumb"><span class="source-pill">${escapeHtml(item.source)}</span></div>
                    <div class="cbody">
                        <h3>${escapeHtml(item.title)}</h3>
                        <div class="time">${escapeHtml(formatRelative(item.published))}</div>
                    </div>
                </a>
            `
                )
                .join('')}
        </div>
    `;
}
