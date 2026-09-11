// ===== MAIN APP MODULE =====
// Lädt Teams, Rennen und Kalender jetzt asynchron vom Backend (js/api.js)
// statt aus statischen Arrays. escapeHtml/safeUrl (aus api.js) schützen vor
// XSS durch extern gescrapte Inhalte.
const APP_POLL_INTERVAL_MS = 10 * 60 * 1000;

class RadsportApp {
    constructor() {
        this.teamsGrid = document.getElementById('teams-grid');
        this.racesList = document.getElementById('races-list');
        this.calendarGrid = document.getElementById('calendar-grid');
        this.calendarMonth = document.getElementById('current-month');
        this.prevMonthBtn = document.getElementById('prev-month');
        this.nextMonthBtn = document.getElementById('next-month');
        this.searchInput = document.getElementById('search-input');
        this.totalTeamsEl = document.getElementById('total-teams');
        this.totalRacesEl = document.getElementById('total-races');
        this.nextRaceDateEl = document.getElementById('next-race-date');
        this.currentMonth = new Date();
        this.currentTeamFilter = 'all';
        this.currentRaceFilter = 'all';
        this.teams = [];
        this.races = [];
        this.calendarEvents = [];
        this.hasLoadedOnce = false;
        this.init();
    }

    async init() {
        this.setupEventListeners();
        this.setupFilters();
        this.setupSearch();
        await this.loadData();
        setInterval(() => this.loadData(), APP_POLL_INTERVAL_MS);
    }

    async loadData() {
        if (!this.hasLoadedOnce) this.renderLoading();
        try {
            const [teamsRes, racesRes, calendarRes] = await Promise.all([
                Api.getTeams(),
                Api.getRaces(),
                Api.getCalendar(),
            ]);
            this.teams = teamsRes.teams || [];
            this.races = racesRes.races || [];
            this.calendarEvents = calendarRes.events || [];
            this.updateStats();
            this.renderTeams();
            this.renderRaces();
            this.renderCalendar();
            this.hasLoadedOnce = true;
        } catch (err) {
            console.error('Fehler beim Laden der Team-/Renn-Daten:', err);
            this.renderLoadError();
        }
    }

    renderLoading() {
        const loadingHtml = `
            <div class="no-results">
                <i class="fas fa-spinner fa-spin"></i>
                <p>Lade aktuelle Daten…</p>
            </div>
        `;
        if (this.teamsGrid) this.teamsGrid.innerHTML = loadingHtml;
        if (this.racesList) this.racesList.innerHTML = loadingHtml;
    }

    renderLoadError() {
        const errorHtml = `
            <div class="no-results">
                <i class="fas fa-exclamation-triangle"></i>
                <p>Daten konnten nicht geladen werden. Bitte später erneut versuchen.</p>
            </div>
        `;
        if (this.teamsGrid) this.teamsGrid.innerHTML = errorHtml;
        if (this.racesList) this.racesList.innerHTML = errorHtml;
    }

    setupEventListeners() {
        this.prevMonthBtn.addEventListener('click', () => {
            this.currentMonth.setMonth(this.currentMonth.getMonth() - 1);
            this.renderCalendar();
        });
        this.nextMonthBtn.addEventListener('click', () => {
            this.currentMonth.setMonth(this.currentMonth.getMonth() + 1);
            this.renderCalendar();
        });
    }

    setupFilters() {
        document.querySelectorAll('#teams .filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('#teams .filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.currentTeamFilter = btn.dataset.filter;
                this.renderTeams();
            });
        });
        document.querySelectorAll('#races .filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('#races .filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.currentRaceFilter = btn.dataset.filter;
                this.renderRaces();
            });
        });
    }

    setupSearch() {
        this.searchInput.addEventListener('input', (e) => {
            const searchTerm = e.target.value.toLowerCase();
            this.filterTeams(searchTerm);
            this.filterRaces(searchTerm);
        });
    }

    getUpcomingRaces(limit = 5) {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        return [...this.races]
            .filter(race => new Date(race.start_date) >= today)
            .sort((a, b) => new Date(a.start_date) - new Date(b.start_date))
            .slice(0, limit);
    }

    updateStats() {
        if (this.totalTeamsEl) this.totalTeamsEl.textContent = this.teams.length;
        if (this.totalRacesEl) this.totalRacesEl.textContent = this.races.length;
        const nextRace = this.getUpcomingRaces(1)[0];
        if (nextRace && this.nextRaceDateEl) {
            const nextRaceDate = new Date(nextRace.start_date);
            this.nextRaceDateEl.textContent = nextRaceDate.toLocaleDateString('de-DE', {
                day: '2-digit',
                month: 'long',
                year: 'numeric',
            });
        }
    }

    getFilteredTeams() {
        let teams = [...this.teams];
        if (this.currentTeamFilter !== 'all') {
            teams = teams.filter(team => team.category === this.currentTeamFilter);
        }
        return teams;
    }

    filterTeams(searchTerm) {
        if (!searchTerm) {
            this.renderTeams();
            return;
        }
        const filteredTeams = this.getFilteredTeams().filter(team =>
            team.name.toLowerCase().includes(searchTerm) ||
            team.country.toLowerCase().includes(searchTerm) ||
            team.code.toLowerCase().includes(searchTerm)
        );
        this.renderTeams(filteredTeams);
    }

    renderTeams(teams = null) {
        if (!this.teamsGrid) return;
        const teamsToRender = teams || this.getFilteredTeams();
        if (teamsToRender.length === 0) {
            this.teamsGrid.innerHTML = `
                <div class="no-results">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p>Keine Teams gefunden</p>
                </div>
            `;
            return;
        }
        this.teamsGrid.innerHTML = teamsToRender.map(team => `
            <div class="team-card" data-team-id="${escapeHtml(team.id)}" data-category="${escapeHtml(team.category)}">
                <div class="team-logo">
                    <img src="${safeUrl(team.logo)}" alt="${escapeHtml(team.name)}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
                    <i class="fas fa-shield-alt" style="display:none;"></i>
                </div>
                <h3>${escapeHtml(team.name)}</h3>
                <span class="team-category ${escapeHtml(team.category)}">
                    ${team.category === 'wt' ? 'World Tour' : team.category === 'pro' ? 'ProTeam' : 'Continental'}
                </span>
                <div class="team-info">
                    <div class="team-info-item">
                        <i class="fas fa-flag"></i>
                        <p>${escapeHtml(team.country)}</p>
                    </div>
                    <div class="team-info-item">
                        <i class="fas fa-users"></i>
                        <p>${team.riders ?? '-'}</p>
                    </div>
                    <div class="team-info-item">
                        <i class="fas fa-trophy"></i>
                        <p>${team.wins_season ?? '-'}</p>
                    </div>
                </div>
            </div>
        `).join('');
    }

    getFilteredRaces() {
        let races = [...this.races];
        if (this.currentRaceFilter !== 'all') {
            races = races.filter(race => {
                if (this.currentRaceFilter === 'wt') return race.category === 'wt';
                if (this.currentRaceFilter === 'monument') return race.type === 'monument';
                if (this.currentRaceFilter === 'gt') return race.type === 'gt';
                return true;
            });
        }
        return races;
    }

    filterRaces(searchTerm) {
        if (!searchTerm) {
            this.renderRaces();
            return;
        }
        const filteredRaces = this.getFilteredRaces().filter(race =>
            race.name.toLowerCase().includes(searchTerm) ||
            race.country.toLowerCase().includes(searchTerm) ||
            race.type.toLowerCase().includes(searchTerm)
        );
        this.renderRaces(filteredRaces);
    }

    formatRaceDate(race) {
        const startDate = new Date(race.start_date);
        const endDate = new Date(race.end_date);
        if (startDate.toDateString() === endDate.toDateString()) {
            return startDate.toLocaleDateString('de-DE', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric',
            });
        }
        return `${startDate.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })} - ${endDate.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' })}`;
    }

    renderRaces(races = null) {
        if (!this.racesList) return;
        const racesToRender = races || this.getFilteredRaces();
        if (racesToRender.length === 0) {
            this.racesList.innerHTML = `
                <div class="no-results">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p>Keine Rennen gefunden</p>
                </div>
            `;
            return;
        }
        this.racesList.innerHTML = racesToRender.map(race => `
            <div class="race-card" data-race-id="${escapeHtml(race.id)}" data-category="${escapeHtml(race.category)}" data-type="${escapeHtml(race.type)}">
                <div class="race-card-header">
                    <div>
                        <h3>${escapeHtml(race.name)}</h3>
                        <p>${escapeHtml(race.country)} | ${this.formatRaceDate(race)}</p>
                    </div>
                    <span class="race-category ${escapeHtml(race.category)} ${escapeHtml(race.type)}">
                        ${race.category === 'wt' ? 'World Tour' : race.category === 'pro' ? 'ProSeries' : escapeHtml(race.category)}
                        ${race.type === 'monument' ? '| Monument' : race.type === 'gt' ? '| Grand Tour' : ''}
                    </span>
                </div>
                <div class="race-card-body">
                    <div class="race-info">
                        <span><i class="fas fa-road"></i> ${escapeHtml(race.distance ?? '-')}</span>
                        <span><i class="fas fa-flag-checkered"></i> ${race.stages ?? '-'} Etappe${race.stages !== 1 ? 'n' : ''}</span>
                    </div>
                    <div class="race-info">
                        <span><i class="fas fa-trophy"></i> Sieger Vorjahr: ${escapeHtml(race.winner_previous_year ?? '-')}</span>
                    </div>
                    <div class="race-info">
                        <span><i class="fas fa-building"></i> ${escapeHtml(race.winner_team_previous_year ?? '-')}</span>
                    </div>
                </div>
            </div>
        `).join('');
    }

    renderCalendar() {
        if (!this.calendarGrid) return;
        const year = this.currentMonth.getFullYear();
        const month = this.currentMonth.getMonth();
        this.calendarMonth.textContent = this.currentMonth.toLocaleDateString('de-DE', {
            month: 'long',
            year: 'numeric',
        });
        const firstDay = new Date(year, month, 1).getDay();
        const daysInMonth = new Date(year, month + 1, 0).getDate();
        let calendarHTML = '';
        for (let i = 0; i < firstDay; i++) {
            calendarHTML += `<div class="calendar-day empty"></div>`;
        }
        for (let day = 1; day <= daysInMonth; day++) {
            const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
            const today = new Date();
            const isToday = year === today.getFullYear() && month === today.getMonth() && day === today.getDate();
            const isPast = new Date(dateStr) < new Date(today.getFullYear(), today.getMonth(), today.getDate());
            const racesOnDay = this.calendarEvents.filter(event => event.date === dateStr);
            calendarHTML += `
                <div class="calendar-day ${isPast ? 'past' : ''} ${isToday ? 'today' : ''}" data-date="${dateStr}">
                    <div class="day-number">${day}</div>
                    ${racesOnDay.length > 0 ? `
                        <div class="races">
                            ${racesOnDay.map(event => {
                                const race = this.races.find(r => r.id === event.race_id);
                                const label = race ? race.name : event.race_name;
                                return `<span class="race-badge" title="${escapeHtml(label)}">${escapeHtml(label.substring(0, 3))}</span>`;
                            }).join('')}
                        </div>
                    ` : ''}
                </div>
            `;
        }
        const totalCells = Math.ceil((firstDay + daysInMonth) / 7) * 7;
        const remainingCells = totalCells - (firstDay + daysInMonth);
        for (let i = 0; i < remainingCells; i++) {
            calendarHTML += `<div class="calendar-day empty"></div>`;
        }
        this.calendarGrid.innerHTML = calendarHTML;
    }
}

// Initialize the app when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new RadsportApp();
});
