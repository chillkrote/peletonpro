// ===== NEWS MODULE =====
// Aggregierter Radsport-Newsfeed vom Backend (RSS-Aggregation), pollt
// periodisch nach neuen Meldungen.
const NEWS_POLL_INTERVAL_MS = 5 * 60 * 1000;

class NewsManager {
    constructor() {
        this.newsGrid = document.getElementById('news-grid');
        this.init();
    }

    async init() {
        if (!this.newsGrid) return;
        await this.loadNews();
        setInterval(() => this.loadNews(), NEWS_POLL_INTERVAL_MS);
    }

    async loadNews() {
        try {
            const { news } = await Api.getNews(9);
            this.renderNews(news || []);
        } catch (err) {
            console.error('Fehler beim Laden der News:', err);
            this.renderError();
        }
    }

    formatDate(dateStr) {
        if (!dateStr) return '';
        return new Date(dateStr).toLocaleDateString('de-DE', {
            day: '2-digit',
            month: 'long',
            year: 'numeric',
        });
    }

    renderNews(news) {
        if (news.length === 0) {
            this.newsGrid.innerHTML = `
                <div class="no-results">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p>Keine News verfügbar</p>
                </div>
            `;
            return;
        }
        this.newsGrid.innerHTML = news.map((item, index) => `
            <article class="news-card ${index === 0 ? 'featured' : ''}">
                <div class="news-image placeholder">
                    <i class="fas fa-image"></i>
                    <span>${escapeHtml(item.source)}</span>
                </div>
                <div class="news-content">
                    <span class="news-category">${escapeHtml(item.source)}</span>
                    <h3><a href="${safeUrl(item.link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a></h3>
                    ${item.summary ? `<p class="news-excerpt">${escapeHtml(item.summary)}</p>` : ''}
                    <div class="news-meta">
                        <span><i class="fas fa-clock"></i> ${escapeHtml(this.formatDate(item.published))}</span>
                    </div>
                </div>
            </article>
        `).join('');
    }

    renderError() {
        this.newsGrid.innerHTML = `
            <div class="no-results">
                <i class="fas fa-exclamation-triangle"></i>
                <p>News konnten nicht geladen werden. Bitte später erneut versuchen.</p>
            </div>
        `;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new NewsManager();
});
