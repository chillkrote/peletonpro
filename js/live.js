// ===== LIVE RESULTS MODULE =====
class LiveResultsManager {
    constructor() {
        this.liveResultsContainer = document.getElementById('live-results');
        this.liveBadge = document.getElementById('live-badge');
        this.filterButtons = document.querySelectorAll('#live .filter-btn');
        this.currentFilter = 'all';
        this.init();
    }

    init() {
        this.setupFilters();
        this.updateLiveBadge();
        this.renderLiveResults();
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

    updateLiveBadge() {
        const liveCount = getLiveResults().length;
        this.liveBadge.textContent = liveCount;
        this.liveBadge.style.display = liveCount > 0 ? 'inline-block' : 'none';
    }

    getFilteredResults() {
        const allResults = [...getLiveResults(), ...getFinishedResults(10), ...getUpcomingResults(10)];
        switch (this.currentFilter) {
            case 'wt':
                return allResults.filter(result => {
                    const race = getRaceById(result.raceId);
                    return race && race.category === 'wt';
                });
            case 'pro':
                return allResults.filter(result => {
                    const race = getRaceById(result.raceId);
                    return race && race.category === 'pro';
                });
            default:
                return allResults;
        }
    }

    formatTime(timeStr) {
        if (!timeStr) return '-';
        const parts = timeStr.split(':');
        if (parts.length === 3) return `${parts[0]}h ${parts[1]}' ${parts[2]}"`;
        else if (parts.length === 2) return `${parts[0]}' ${parts[1]}"`;
        return timeStr;
    }

    formatDate(dateStr) {
        const date = new Date(dateStr);
        return date.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
    }

    formatTimeOfDay(dateStr) {
        const date = new Date(dateStr);
        return date.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    }

    getStatusColor(status) {
        switch (status) {
            case 'live': return 'live';
            case 'finished': return 'finished';
            case 'upcoming': return 'upcoming';
            default: return '';
        }
    }

    renderLiveResults() {
        const results = this.getFilteredResults();
        if (results.length === 0) {
            this.liveResultsContainer.innerHTML = `
                <div class="no-results">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p>Keine Live-Ergebnisse verfügbar</p>
                    <p>Nächstes Rennen: <strong id="next-race-name">-</strong></p>
                </div>
            `;
            const nextRace = getUpcomingRaces(1)[0];
            if (nextRace) document.getElementById('next-race-name').textContent = `${nextRace.name} (${this.formatDate(nextRace.startDate)})`;
            return;
        }
        this.liveResultsContainer.innerHTML = results.map(result => {
            const race = getRaceById(result.raceId);
            const progress = result.totalKm > 0 ? Math.round((result.currentKm / result.totalKm) * 100) : 0;
            return `
                <div class="live-card" data-race-id="${result.raceId}" data-status="${result.status}">
                    <div class="live-card-header">
                        <div>
                            <h3>${race ? race.name : result.raceName}</h3>
                            ${race ? `<p>${race.country} | ${race.type === 'gt' ? 'Grand Tour' : race.stages > 1 ? `Etappe ${result.stage} von ${race.stages}` : 'Eintagesrennen'}</p>` : ''}
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
                                <p>${result.currentKm} km / ${result.totalKm} km (${progress}%)</p>
                            </div>
                            <div class="live-race-info">
                                <span><i class="fas fa-clock"></i> Start: ${this.formatTimeOfDay(result.startTime)}</span>
                                <span><i class="fas fa-flag-checkered"></i> Ziel: ~${this.formatTimeOfDay(result.estimatedFinish)}</span>
                            </div>
                        ` : result.status === 'finished' ? `
                            <div class="live-race-info">
                                <span><i class="fas fa-clock"></i> Beendet: ${this.formatTimeOfDay(result.estimatedFinish)}</span>
                                <span><i class="fas fa-trophy"></i> Sieger: ${result.results[0] ? result.results[0].rider : '-'}</span>
                            </div>
                        ` : `
                            <div class="live-race-info">
                                <span><i class="fas fa-clock"></i> Start: ${this.formatTimeOfDay(result.startTime)}</span>
                                <span><i class="fas fa-calendar"></i> ${this.formatDate(result.startTime)}</span>
                            </div>
                        `}
                        ${result.results && result.results.length > 0 ? `
                            <div class="live-results-list">
                                <h4><i class="fas fa-list-ol"></i> Aktuelle Platzierungen</h4>
                                ${result.results.slice(0, 5).map((riderResult, index) => `
                                    <div class="live-result-item">
                                        <span class="position ${index === 0 ? 'winner' : ''}">${riderResult.position}</span>
                                        <span class="rider">${riderResult.rider}</span>
                                        <span class="team">${riderResult.team}</span>
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