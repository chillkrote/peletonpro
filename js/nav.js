// ===== SHARED NAVIGATION + GENDER-UMSCHALTER =====
// ES-Modul.
import { escapeHtml } from './api.js';
import { statePanel } from './ui.js';
// Rendert die Top-Nav (Logo, Breadcrumbs, Männer/Frauen-Umschalter) in
// #site-nav auf jeder Seite. Der Umschalter-Zustand liegt in localStorage
// und gilt seitenübergreifend. Das Backend liefert aktuell ausschließlich
// Männer-World-Tour-Daten - bei "Frauen" zeigt jede Seite stattdessen einen
// "kommt bald"-Platzhalter (siehe renderComingSoonIfWomen).
const GENDER_STORAGE_KEY = 'pelotonpro_gender';

function getGender() {
    return localStorage.getItem(GENDER_STORAGE_KEY) === 'women' ? 'women' : 'men';
}

export function isWomen() {
    return getGender() === 'women';
}

function setGender(gender) {
    localStorage.setItem(GENDER_STORAGE_KEY, gender === 'women' ? 'women' : 'men');
}

export function renderNav({ crumbs = [] } = {}) {
    const mount = document.getElementById('site-nav');
    if (!mount) return;

    const crumbsHtml = crumbs.length
        ? `<div class="crumbs">${crumbs
              .map((crumb, index) => {
                  const sep = index > 0 ? '<span class="sep">/</span>' : '';
                  const isLast = index === crumbs.length - 1;
                  const label = escapeHtml(crumb.label);
                  return `${sep}${isLast || !crumb.href ? `<span class="current">${label}</span>` : `<a href="${escapeHtml(crumb.href)}">${label}</a>`}`;
              })
              .join('')}</div>`
        : '';

    const gender = getGender();
    mount.innerHTML = `
        <div class="topnav-left">
            <a href="index.html" class="logo"><span class="logo-mark">P</span>PelotonPro</a>
            ${crumbsHtml}
        </div>
        <div class="gender-toggle">
            <button type="button" data-gender="men" class="${gender === 'men' ? 'active' : ''}">Männer</button>
            <button type="button" data-gender="women" class="${gender === 'women' ? 'active' : ''}">Frauen</button>
        </div>
    `;

    mount.querySelectorAll('.gender-toggle button').forEach((btn) => {
        btn.addEventListener('click', () => {
            if (btn.dataset.gender === gender) return;
            setGender(btn.dataset.gender);
            window.location.reload();
        });
    });
}

// Zeigt einen "kommt bald"-Platzhalter im übergebenen Container, falls
// "Frauen" aktiv ist. Gibt true zurück, wenn der Aufrufer daraufhin das
// Laden der eigentlichen (Männer-)Daten überspringen soll.
export function renderComingSoonIfWomen(container) {
    if (!container || !isWomen()) return false;
    container.innerHTML = statePanel(
        'fas fa-hourglass-half',
        'Frauen World Tour kommt bald',
        "Teams, Rennkalender und Ergebnisse der UCI Women's World Tour sind noch nicht angebunden. Schau bald wieder vorbei.",
        'state-panel coming-soon',
    );
    return true;
}
