// ===== TEAMS DATA =====
const TEAMS = [
    // World Tour Teams (2024)
    {
        id: 1,
        name: "Alpecin-Deceuninck",
        category: "wt",
        country: "Belgien",
        code: "ADC",
        logo: "https://www.procyclingstats.com/images/logos/teams/2024/alpecin-deceuninck.png",
        founded: 2009,
        riders: 28,
        wins2024: 12,
        website: "https://www.alpecindeceuninck.com/"
    },
    {
        id: 2,
        name: "Arkéa-B&B Hotels",
        category: "wt",
        country: "Frankreich",
        code: "ARK",
        logo: "https://www.procyclingstats.com/images/logos/teams/2024/arkea-bb-hotels.png",
        founded: 2005,
        riders: 27,
        wins2024: 8,
        website: "https://www.arkea-samsic.com/"
    },
    {
        id: 3,
        name: "Astana Qazaqstan Team",
        category: "wt",
        country: "Kasachstan",
        code: "AST",
        logo: "https://www.procyclingstats.com/images/logos/teams/2024/astana-qazaqstan.png",
        founded: 2006,
        riders: 28,
        wins2024: 5,
        website: "https://www.astana-qazaqstan.com/"
    },
    {
        id: 4,
        name: "Bahrain Victorious",
        category: "wt",
        country: "Bahrain",
        code: "TBV",
        logo: "https://www.procyclingstats.com/images/logos/teams/2024/bahrain-victorious.png",
        founded: 2017,
        riders: 28,
        wins2024: 15,
        website: "https://www.bahrainvictorious.com/"
    },
    {
        id: 5,
        name: "Bora-Hansgrohe",
        category: "wt",
        country: "Deutschland",
        code: "BOH",
        logo: "https://www.procyclingstats.com/images/logos/teams/2024/bora-hansgrohe.png",
        founded: 2010,
        riders: 28,
        wins2024: 18,
        website: "https://www.bora-hansgrohe.com/"
    },
    {
        id: 6,
        name: "Cofidis",
        category: "wt",
        country: "Frankreich",
        code: "COF",
        logo: "https://www.procyclingstats.com/images/logos/teams/2024/cofidis.png",
        founded: 1996,
        riders: 28,
        wins2024: 6,
        website: "https://www.cofidis-cycling.com/"
    },
    {
        id: 7,
        name: "Decathlon AG2R La Mondiale Team",
        category: "wt",
        country: "Frankreich",
        code: "ALM",
        logo: "https://www.procyclingstats.com/images/logos/teams/2024/ag2r-la-mondiale.png",
        founded: 1992,
        riders: 28,
        wins2024: 7,
        website: "https://www.ag2rlamondiale.fr/"
    },
    {
        id: 8,
        name: "EF Education-EasyPost",
        category: "wt",
        country: "USA",
        code: "EFE",
        logo: "https://www.procyclingstats.com/images/logos/teams/2024/ef-education-easypost.png",
        founded: 2009,
        riders: 28,
        wins2024: 10,
        website: "https://www.efprocycling.com/"
    },
    {
        id: 9,
        name: "Groupama-FDJ",
        category: "wt",
        country: "Frankreich",
        code: "GDJ",
        logo: "https://www.procyclingstats.com/images/logos/teams/2024/groupama-fdj.png",
        founded: 1997,
        riders: 28,
        wins2024: 14,
        website: "https://www.groupama-fdj.fr/"
    },
    {
        id: 10,
        name: "INEOS Grenadiers",
        category: "wt",
        country: "Großbritannien",
        code: "IGD",
        logo: "https://www.procyclingstats.com/images/logos/teams/2024/ineos-grenadiers.png",
        founded: 2010,
        riders: 28,
        wins2024: 22,
        website: "https://www.ineosgrenadiers.com/"
    }
];

// ===== RACES DATA (Beispielauswahl) =====
const RACES = [
    {
        id: 1,
        name: "Tour de France",
        category: "wt",
        type: "gt",
        startDate: "2024-06-29",
        endDate: "2024-07-21",
        country: "Frankreich",
        distance: "3498 km",
        stages: 21,
        winner2023: "Jonas Vingegaard",
        winnerTeam2023: "Team Jumbo-Visma",
        logo: "https://www.procyclingstats.com/images/logos/races/tour-de-france.png",
        website: "https://www.letour.fr/"
    },
    {
        id: 2,
        name: "Giro d'Italia",
        category: "wt",
        type: "gt",
        startDate: "2024-05-04",
        endDate: "2024-05-26",
        country: "Italien",
        distance: "3405 km",
        stages: 21,
        winner2023: "Primož Roglič",
        winnerTeam2023: "Team Jumbo-Visma",
        logo: "https://www.procyclingstats.com/images/logos/races/giro-ditalia.png",
        website: "https://www.giroditalia.it/"
    },
    {
        id: 3,
        name: "Vuelta a España",
        category: "wt",
        type: "gt",
        startDate: "2024-08-17",
        endDate: "2024-09-08",
        country: "Spanien",
        distance: "3280 km",
        stages: 21,
        winner2023: "Jonas Vingegaard",
        winnerTeam2023: "Team Jumbo-Visma",
        logo: "https://www.procyclingstats.com/images/logos/races/vuelta-a-espana.png",
        website: "https://www.lavuelta.es/"
    },
    {
        id: 4,
        name: "Mailand-Sanremo",
        category: "wt",
        type: "monument",
        startDate: "2024-03-23",
        endDate: "2024-03-23",
        country: "Italien",
        distance: "294 km",
        stages: 1,
        winner2023: "Mathieu van der Poel",
        winnerTeam2023: "Alpecin-Deceuninck",
        logo: "https://www.procyclingstats.com/images/logos/races/milan-san-remo.png",
        website: "https://www.milanosanremo.it/"
    },
    {
        id: 5,
        name: "Tour der Flandern",
        category: "wt",
        type: "monument",
        startDate: "2024-04-07",
        endDate: "2024-04-07",
        country: "Belgien",
        distance: "270 km",
        stages: 1,
        winner2023: "Mathieu van der Poel",
        winnerTeam2023: "Alpecin-Deceuninck",
        logo: "https://www.procyclingstats.com/images/logos/races/tour-of-flanders.png",
        website: "https://www.rondedevlaanderen.be/"
    }
];

// ===== CALENDAR DATA (2024, Beispiel) =====
const CALENDAR = [
    { id: 1, date: "2024-03-23", raceId: 4, name: "Mailand-Sanremo" },
    { id: 2, date: "2024-04-07", raceId: 5, name: "Tour der Flandern" },
    { id: 3, date: "2024-05-04", raceId: 2, name: "Giro d'Italia" },
    { id: 4, date: "2024-06-29", raceId: 1, name: "Tour de France" },
    { id: 5, date: "2024-08-17", raceId: 3, name: "Vuelta a España" }
];

// ===== LIVE RESULTS MOCK DATA =====
const LIVE_RESULTS = [
    {
        id: 1,
        raceId: 1,
        raceName: "Tour de France",
        stage: 14,
        status: "live",
        currentKm: 120,
        totalKm: 180,
        startTime: "2024-07-14T12:00:00",
        estimatedFinish: "2024-07-14T16:30:00",
        category: "wt",
        results: [
            { position: 1, rider: "Tadej Pogačar", team: "UAE Team Emirates", time: "3h 12' 45\"", gap: "" },
            { position: 2, rider: "Jonas Vingegaard", team: "Team Visma-Lease a Bike", time: "3h 12' 52\"", gap: "+7\"" },
            { position: 3, rider: "Primož Roglič", team: "Bora-Hansgrohe", time: "3h 13' 01\"", gap: "+16\"" }
        ]
    }
];

// ===== HELPER FUNCTIONS =====
function getTeamById(id) {
    return TEAMS.find(team => team.id === id);
}

function getRaceById(id) {
    return RACES.find(race => race.id === id);
}

function getUpcomingRaces(limit = 5) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return RACES
        .filter(race => new Date(race.startDate) >= today)
        .sort((a, b) => new Date(a.startDate) - new Date(b.startDate))
        .slice(0, limit);
}

function getLiveResults() {
    return LIVE_RESULTS.filter(result => result.status === "live");
}

function getFinishedResults(limit = 5) {
    return LIVE_RESULTS
        .filter(result => result.status === "finished")
        .sort((a, b) => new Date(b.estimatedFinish) - new Date(a.estimatedFinish))
        .slice(0, limit);
}

function getUpcomingResults(limit = 5) {
    return LIVE_RESULTS
        .filter(result => result.status === "upcoming")
        .sort((a, b) => new Date(a.startTime) - new Date(b.startTime))
        .slice(0, limit);
}