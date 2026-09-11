// ===== LIVE RESULTS MODULE =====
// Lädt Ergebnisse + Rennen vom Backend und aktualisiert sich selbstständig
// per Polling, damit während eines laufenden Rennens neue Zwischenstände
// ohne Neuladen der Seite erscheinen.
const LIVE_POLL_INTERVAL_MS = 60 * 1000;

class LiveResultsManager {
    constructor() {
        this.liveResultsContainer = document.getElementById('live-results');
        this.liveBadge = document.getElementById('live-badge');
        this.filterButtons = document.querySelectorAll('#live .filter-btn');
        this.currentFilter = 'all';
        this.races = [];
        this.results = [];
        this.init();
    }

    async init() {
        this.setupFilters();
        await this.loadData();
        setInterval(() => this.loadData(), LIVE_POLL_INTERVAL_MS);
    }

    setupFilters() {
        this.filterButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                this.filterButtons.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.currentFilter = btn.dataset.filter;
                this.renderLiveResults();
            });
        });
    }

    async loadData() {
        try {
            const [racesRes, resultsRes] = await Promise.all([Api.getRaces(), Api.getResults()]);
            this.races = racesRes.races || [];
            this.results = resultsRes.results || [];
            this.updateLiveBadge();
            this.renderLiveResults();
        } catch (err) {
            console.error('Fehler beim Laden der Live-Ergebnisse:', err);
            this.renderLoadError();
        }
    }

    getRaceById(id) {
        return this.races.find(race => race.id === id);
    }

    getUpcomingRaces(limit = 1) {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        return [...this.races]
            .filter(race => new Date(race.start_date) >= today)
            .sort((a, b) => new Date(a.start_date) - new Date(b.start_date))
            .slice(0, limit);
    }

    updateLiveBadge() {
        if (!this.liveBadge) return;
        const liveCount = this.results.filter(r => r.status === 'live').length;
        this.liveBadge.textContent = liveCount;
        this.liveBadge.style.display = liveCount > 0 ? 'inline-block' : 'none';
    }

    getFilteredResults() {
        switch (this.currentFilter) {
            case 'wt':
                return this.results.filter(result => {
                    const race = this.getRaceById(result.race_id);
                    return race && race.category === 'wt';
                });
            case 'pro':
                return this.results.filter(result => {
                    const race = this.getRaceById(result.race_id);
                    return race && race.category === 'pro';
                });
            default:
                return this.results;
        }
    }

    formatTime(timeStr) {
        if (!timeStr) return '-';
        const parts = timeStr.split(':');
        if (parts.length === 3) return `${parts[0]}h ${parts[1]}' ${parts[2]}"`;
        if (parts.length === 2) return `${parts[0]}' ${parts[1]}"`;
        return timeStr;
    }

    formatDate(dateStr) {
        if (!dateStr) return '-';
        return new Date(dateStr).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
    }

    formatTimeOfDay(dateStr) {
        if (!dateStr) return '-';
        return new Date(dateStr).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    }

    getStatusColor(status) {
        switch (status) {
            case 'live': return 'live';
            case 'finished': return 'finished';
            case 'upcoming': return 'upcoming';
            default: return '';
        }
    }

    renderLoadError() {
        if (!this.liveResultsContainer) return;
        this.liveResultsContainer.innerHTML = `
            <div class="no-results">
                <i class="fas fa-exclamation-triangle"></i>
                <p>Live-Ergebnisse konnten nicht geladen werden. Bitte später erneut versuchen.</p>
            </div>
        `;
    }

    renderLiveResults() {
        if (!this.liveResultsContainer) return;
        const results = this.getFilteredResults();
        if (results.length === 0) {
            const nextRace = this.getUpcomingRaces(1)[0];
            this.liveResultsContainer.innerHTML = `
                <div class="no-results">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p>Keine Live-Ergebnisse verfügbar</p>
                    <p>Nächstes Rennen: <strong>${nextRace ? `${escapeHtml(nextRace.name)} (${this.formatDate(nextRace.start_date)})` : '-'}</strong></p>
                </div>
            `;
            return;
        }
        this.liveResultsContainer.innerHTML = results.map(result => {
            const race = this.getRaceById(result.race_id);
            const progress = result.total_km > 0 ? Math.round((result.current_km / result.total_km) * 100) : 0;
            return `
                <div class="live-card" data-race-id="${escapeHtml(result.race_id)}" data-status="${escapeHtml(result.status)}">
                    <div class="live-card-header">
                        <div>
                            <h3>${escapeHtml(race ? race.name : result.race_name)}</h3>
                            ${race ? `<p>${escapeHtml(race.country)} | ${race.type === 'gt' ? 'Grand Tour' : race.stages > 1 ? `Etappe ${result.stage ?? '-'} von ${race.stages}` : 'Eintagesrennen'}</p>` : ''}
                        </div>
                        <span class="live-status ${this.getStatusColor(result.status)}">
                            ${result.status === 'live' ? '🔴 LIVE' : result.status === 'finished' ? '✅ Beendet' : '⏳ Kommt bald'}
                        </span>
                    </div>
                    <div class="live-card-body">
                        ${result.status === 'live' ? `
                            <div class="live-progress">
                                <div class="progress-bar">
                                    <div class="progress-fill" style="width: ${progress}%"></div>
                                </div>
                                <p>${result.current_km ?? '-'} km / ${result.total_km ?? '-'} km (${progress}%)</p>
                            </div>
                            <div class="live-race-info">
                                <span><i class="fas fa-clock"></i> Start: ${this.formatTimeOfDay(result.start_time)}</span>
                                <span><i class="fas fa-flag-checkered"></i> Ziel: ~${this.formatTimeOfDay(result.estimated_finish)}</span>
                            </div>
                        ` : result.status === 'finished' ? `
                            <div class="live-race-info">
                                <span><i class="fas fa-clock"></i> Beendet: ${this.formatTimeOfDay(result.estimated_finish)}</span>
                                <span><i class="fas fa-trophy"></i> Sieger: ${escapeHtml(result.results?.[0]?.rider ?? '-')}</span>
                            </div>
                        ` : `
                            <div class="live-race-info">
                                <span><i class="fas fa-clock"></i> Start: ${this.formatTimeOfDay(result.start_time)}</span>
                                <span><i class="fas fa-calendar"></i> ${this.formatDate(result.start_time)}</span>
                            </div>
                        `}
                        ${result.results && result.results.length > 0 ? `
                            <div class="live-results-list">
                                <h4><i class="fas fa-list-ol"></i> Aktuelle Platzierungen</h4>
                                ${result.results.slice(0, 5).map((riderResult, index) => `
                                    <div class="live-result-item">
                                        <span class="position ${index === 0 ? 'winner' : ''}">${riderResult.position}</span>
                                        <span class="rider">${escapeHtml(riderResult.rider)}</span>
                                        <span class="team">${escapeHtml(riderResult.team)}</span>
                                        <span class="time">${this.formatTime(riderResult.time)}</span>
                                    </div>
                                `).join('')}
                                ${result.results.length > 5 ? `<p class="more-results">+${result.results.length - 5} weitere</p>` : ''}
                            </div>
                        ` : ''}
                    </div>
                </div>
            `;
        }).join('');
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new LiveResultsManager();
});
