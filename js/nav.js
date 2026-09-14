// ===== SHARED NAVIGATION + GENDER-UMSCHALTER =====
// ES-Modul.
import { escapeHtml } from './api.js';
import { statePanel } from './ui.js';
// Rendert die Top-Nav (Logo, Breadcrumbs, Männer/Frauen-Umschalter) in
// #site-nav auf jeder Seite. Der Umschalter-Zustand liegt in localStorage
// und gilt seitenübergreifend.
//
// Seit der Geschlechts-Dimension (Befund 7) geht der Zustand als
// `gender`-Parameter an jeden API-Aufruf. Das Backend kennt die Dimension,
// hat aber noch keine Frauen-Daten - der Platzhalter entscheidet sich
// deshalb an der ANTWORT (leere Liste ⇒ Platzhalter) und nicht mehr daran,
// dass "Frauen" gewählt ist. Sobald der Frauen-Import Zeilen schreibt,
// verschwindet der Platzhalter von selbst, ohne Code-Änderung.
const GENDER_STORAGE_KEY = 'pelotonpro_gender';

function getGender() {
    return localStorage.getItem(GENDER_STORAGE_KEY) === 'women' ? 'women' : 'men';
}

export function isWomen() {
    return getGender() === 'women';
}

// Der Wert, den die API erwartet ('m'/'w'). Im localStorage steht
// 'men'/'women', weil der Umschalter das schon vorher so ablegte - die
// Übersetzung gehört an eine Stelle und nicht in jeden Aufrufer.
export function apiGender() {
    return isWomen() ? 'w' : 'm';
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

// Zeigt einen "kommt bald"-Platzhalter im übergebenen Container, wenn
// "Frauen" gewählt ist UND das Backend für diese Auswahl nichts liefert.
//
// Vorher hing der Platzhalter allein am Umschalter: `if (isWomen()) return
// true;`. Damit hätte er auch dann noch gestanden, wenn längst
// Frauen-Daten in der Datenbank liegen - und jemand hätte den Aufruf in
// sechs Seiten-Modulen entfernen müssen, um das zu merken. Jetzt
// entscheidet die Antwort.
//
// `istLeer` ist eine Funktion und kein Wert, damit die Seite den Abruf
// nicht machen muss, wenn "Männer" gewählt ist - der häufige Fall.
export async function renderComingSoonIfWomen(container, istLeer) {
    if (!container || !isWomen()) return false;
    if (istLeer) {
        try {
            if (!(await istLeer())) return false;
        } catch (err) {
            // Ein Fehler beim Abruf heisst NICHT "keine Frauen-Daten" - die
            // Seite soll dann ihren eigenen Fehlerpfad gehen und eine
            // Fehlermeldung zeigen, statt "kommt bald" zu behaupten.
            console.error('Prüfung auf Frauen-Daten fehlgeschlagen:', err);
            return false;
        }
    }
    container.innerHTML = statePanel(
        'fas fa-hourglass-half',
        'Frauen World Tour kommt bald',
        "Teams, Rennkalender und Ergebnisse der UCI Women's World Tour sind noch nicht angebunden. Schau bald wieder vorbei.",
        'state-panel coming-soon',
    );
    return true;
}
