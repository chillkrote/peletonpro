// ===== API CLIENT =====
// Basis-URL des Backends. Lokal (Entwicklung) automatisch localhost:8001,
// sonst die deployte Render-URL. Bei Bedarf vor dem Laden dieses Skripts
// überschreiben: <script>window.PELOTONPRO_API_BASE = '...';</script>
const API_BASE =
    window.PELOTONPRO_API_BASE ||
    (['localhost', '127.0.0.1'].includes(window.location.hostname)
        ? 'http://localhost:8001'
        : 'https://peletonpro-api.onrender.com'); // TODO: nach dem Deployment auf Render anpassen

async function apiGet(path) {
    const response = await fetch(`${API_BASE}${path}`);
    if (!response.ok) {
        throw new Error(`API-Fehler ${response.status} bei ${path}`);
    }
    return response.json();
}

// Kleine Sicherheitshelfer: Daten aus API/Scraping/RSS sind externer
// Herkunft und werden per innerHTML gerendert - daher immer escapen bzw.
// Protokoll von URLs validieren, bevor sie in href/src landen.
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function safeUrl(url) {
    if (!url) return '#';
    try {
        const parsed = new URL(url, window.location.href);
        return ['http:', 'https:'].includes(parsed.protocol) ? parsed.href : '#';
    } catch {
        return '#';
    }
}

const Api = {
    getTeams(category) {
        return apiGet(`/api/teams${category ? `?category=${category}` : ''}`);
    },
    getRaces() {
        return apiGet('/api/races');
    },
    getCalendar() {
        return apiGet('/api/calendar');
    },
    getResults(status) {
        return apiGet(`/api/results${status ? `?status=${status}` : ''}`);
    },
    getNews(limit = 30) {
        return apiGet(`/api/news?limit=${limit}`);
    },
    getRiders(team) {
        return apiGet(`/api/riders${team ? `?team=${encodeURIComponent(team)}` : ''}`);
    },
    getRider(id) {
        return apiGet(`/api/riders/${encodeURIComponent(id)}`);
    },
    getRaceHistory({ season, category, circuit, limit = 3000, offset = 0 } = {}) {
        const params = new URLSearchParams();
        if (season) params.set('season', season);
        if (category) params.set('category', category);
        if (circuit) params.set('circuit', circuit);
        params.set('limit', limit);
        params.set('offset', offset);
        return apiGet(`/api/race-history?${params.toString()}`);
    },
    getRaceHistoryDetail(id) {
        return apiGet(`/api/race-history/${encodeURIComponent(id)}`);
    },
};
