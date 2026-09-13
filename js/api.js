// ===== API CLIENT =====
// Basis-URL des Backends. Lokal (Entwicklung) automatisch localhost:8001,
// sonst die deployte Render-URL. Bei Bedarf vor dem Laden dieses Skripts
// überschreiben: <script>window.PELOTONPRO_API_BASE = '...';</script>
const API_BASE =
    window.PELOTONPRO_API_BASE ||
    (['localhost', '127.0.0.1'].includes(window.location.hostname)
        ? 'http://localhost:8001'
        : 'https://peletonpro-api.onrender.com');

// Der HTTP-Status hängt am Error als .status. Ohne das kann ein Aufrufer
// "gibt es nicht" (404) nicht von "ist gerade kaputt" unterscheiden und muss
// beides gleich melden - js/team.js unterscheidet es.
function apiError(message, status) {
    const err = new Error(message);
    err.status = status;
    return err;
}

async function apiGet(path) {
    const response = await fetch(`${API_BASE}${path}`);
    if (!response.ok) {
        // 429 ist kein Defekt, sondern die Drosselung der API (siehe
        // backend/app/ratelimit.py). Eine Meldung wie "API-Fehler 429" wäre
        // für Besucher nicht deutbar.
        if (response.status === 429) {
            const retry = Number(response.headers.get('Retry-After'));
            const wann = Number.isFinite(retry) && retry > 0
                ? `Bitte in ${retry} Sekunden erneut versuchen.`
                : 'Bitte kurz warten und erneut versuchen.';
            throw apiError(`Zu viele Anfragen. ${wann}`, 429);
        }
        throw apiError(`API-Fehler ${response.status} bei ${path}`, response.status);
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
    getTeam(id) {
        return apiGet(`/api/teams/${encodeURIComponent(id)}`);
    },
    getTeamStats(id, season) {
        const q = season ? `?season=${season}` : '';
        return apiGet(`/api/teams/${encodeURIComponent(id)}/stats${q}`);
    },
    getNews(limit = 30) {
        return apiGet(`/api/news?limit=${limit}`);
    },
    // `limit`/`offset` reichen an die Paginierung des Backends durch. Wer nur
    // die Gesamtzahl braucht, holt eine Zeile (limit=1) und liest `total` -
    // siehe js/home.js.
    getRiders(team, { limit, offset } = {}) {
        const params = new URLSearchParams();
        if (team) params.set('team', team);
        if (limit !== undefined) params.set('limit', limit);
        if (offset !== undefined) params.set('offset', offset);
        const query = params.toString();
        return apiGet(`/api/riders${query ? `?${query}` : ''}`);
    },
    getRider(id) {
        return apiGet(`/api/riders/${encodeURIComponent(id)}`);
    },
    getRaceSeasons() {
        return apiGet('/api/race-history/seasons');
    },
    // limit ist serverseitig auf 500 begrenzt (siehe routers/race_history.py).
    // Deshalb wird pro Saison geladen, nicht alles auf einmal.
    getRaceHistory({ season, category, circuit, limit = 500, offset = 0 } = {}) {
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
