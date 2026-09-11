// ===== MAIN APP MODULE =====
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
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.updateStats();
        this.renderTeams();
        this.renderRaces();
        this.renderCalendar();
        this.setupFilters();
        this.setupSearch();
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

    updateStats() {
        this.totalTeamsEl.textContent = TEAMS.length;
        this.totalRacesEl.textContent = RACES.length;
        const nextRace = getUpcomingRaces(1)[0];
        if (nextRace) {
            const nextRaceDate = new Date(nextRace.startDate);
            this.nextRaceDateEl.textContent = nextRaceDate.toLocaleDateString('de-DE', {
                day: '2-digit',
                month: 'long',
                year: 'numeric'
            });
        }
    }

    getFilteredTeams() {
        let teams = [...TEAMS];
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
            <div class="team-card" data-team-id="${team.id}" data-category="${team.category}">
                <div class="team-logo">
                    <img src="${team.logo}" alt="${team.name}" onerror="this.src='https://via.placeholder.com/100x100/333/fff?text=${team.code}'">
                </div>
                <h3>${team.name}</h3>
                <span class="team-category ${team.category}">
                    ${team.category === 'wt' ? 'World Tour' : team.category === 'pro' ? 'ProTeam' : 'Continental'}
                </span>
                <div class="team-info">
                    <div class="team-info-item">
                        <i class="fas fa-flag"></i>
                        <p>${team.country}</p>
                    </div>
                    <div class="team-info-item">
                        <i class="fas fa-users"></i>
                        <p>${team.riders}</p>
                    </div>
                    <div class="team-info-item">
                        <i class="fas fa-trophy"></i>
                        <p>${team.wins2024}</p>
                    </div>
                </div>
            </div>
        `).join('');
    }

    getFilteredRaces() {
        let races = [...RACES];
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
        const startDate = new Date(race.startDate);
        const endDate = new Date(race.endDate);
        if (startDate.toDateString() === endDate.toDateString()) {
            return startDate.toLocaleDateString('de-DE', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric'
            });
        } else {
            return `${startDate.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })} - ${endDate.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' })}`;
        }
    }

    renderRaces(races = null) {
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
            <div class="race-card" data-race-id="${race.id}" data-category="${race.category}" data-type="${race.type}">
                <div class="race-card-header">
                    <div>
                        <h3>${race.name}</h3>
                        <p>${race.country} | ${this.formatRaceDate(race)}</p>
                    </div>
                    <span class="race-category ${race.category} ${race.type}">
                        ${race.category === 'wt' ? 'World Tour' : race.category === 'pro' ? 'ProSeries' : race.category}
                        ${race.type === 'monument' ? '| Monument' : race.type === 'gt' ? '| Grand Tour' : ''}
                    </span>
                </div>
                <div class="race-card-body">
                    <div class="race-info">
                        <span><i class="fas fa-road"></i> ${race.distance}</span>
                        <span><i class="fas fa-flag-checkered"></i> ${race.stages} Etappe${race.stages !== 1 ? 'n' : ''}</span>
                    </div>
                    <div class="race-info">
                        <span><i class="fas fa-trophy"></i> Sieger 2023: ${race.winner2023}</span>
                    </div>
                    <div class="race-info">
                        <span><i class="fas fa-building"></i> ${race.winnerTeam2023}</span>
                    </div>
                </div>
            </div>
        `).join('');
    }

    renderCalendar() {
        const year = this.currentMonth.getFullYear();
        const month = this.currentMonth.getMonth();
        this.calendarMonth.textContent = this.currentMonth.toLocaleDateString('de-DE', {
            month: 'long',
            year: 'numeric'
        });
        const firstDay = new Date(year, month, 1).getDay();
        const daysInMonth = new Date(year, month + 1, 0).getDate();
        const daysInPrevMonth = new Date(year, month, 0).getDate();
        let calendarHTML = '';
        for (let i = 0; i < firstDay; i++) {
            calendarHTML += `<div class="calendar-day empty"></div>`;
        }
        for (let day = 1; day <= daysInMonth; day++) {
            const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
            const today = new Date();
            const isToday = year === today.getFullYear() && month === today.getMonth() && day === today.getDate();
            const isPast = new Date(dateStr) < new Date(today.getFullYear(), today.getMonth(), today.getDate());
            const racesOnDay = CALENDAR.filter(event => event.date === dateStr);
            calendarHTML += `
                <div class="calendar-day ${isPast ? 'past' : ''} ${isToday ? 'today' : ''}" data-date="${dateStr}">
                    <div class="day-number">${day}</div>
                    ${racesOnDay.length > 0 ? `
                        <div class="races">
                            ${racesOnDay.map(event => {
                                const race = getRaceById(event.raceId);
                                return race ? `<span class="race-badge" title="${race.name}">${race.code || race.name.substring(0, 3)}</span>` : '';
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