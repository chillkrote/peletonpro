#!/usr/bin/env node
// Prueft die Ergebnisliste auf der Fahrer-Detailseite in Chromium.
//
//   # Backend auf :8001 und statische Dateien auf :8000, dann:
//   node scripts/check-rider-results.mjs
//
// WARUM EIGENES SKRIPT: check-pages.mjs prueft, dass die Seite rendert und
// keinen JavaScript-Fehler wirft. Die Ergebnisliste wird aber NACH dem
// Profil nachgeladen, absichtlich ohne await und mit eigenem catch - ein
// Fehler dort laesst die Seite bestehen und die Liste still fehlen. Genau
// das wuerde check-pages.mjs nicht bemerken.
//
// Geprueft wird:
//   1. die Tabelle erscheint, mit der erwarteten Zeilenzahl der ersten Seite
//   2. Rennname, Etappe, Platz und Zeit stehen drin
//   3. der Sieg traegt das Pokal-Symbol, andere Plaetze nicht
//   4. "Weitere laden" erscheint nur bei mehr Zeilen als einer Seite und
//      haengt die naechste Seite an
//   5. ein Fahrer ohne Ergebnisse bekommt den Hinweis, nicht einen Fehler
//   6. kein JavaScript-Fehler waehrend all dem
import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';

const basis = process.argv[2] || 'http://127.0.0.1:8000';
let fehler = 0;
const meld = (t, s) => console.log(`  ${t.padEnd(56)} ${s}`);
const pruefe = (t, ist, soll) => {
    if (String(ist) === String(soll)) meld(t, 'ok');
    else { meld(t, `FEHLER: '${ist}' != '${soll}'`); fehler++; }
};
const pruefeWahr = (t, ist) => pruefe(t, ist ? 'ja' : 'nein', 'ja');

const browser = await chromium.launch({
    executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
    args: ['--no-sandbox'],
});

async function seite(pfad) {
    const page = await browser.newPage();
    const jsFehler = [];
    page.on('pageerror', (e) => jsFehler.push(e.message));
    await page.goto(`${basis}${pfad}`, { waitUntil: 'networkidle' });
    return { page, jsFehler };
}

console.log('=== 1. Fahrer mit vielen Ergebnissen ===');
{
    const { page, jsFehler } = await seite('/rider.html?id=viele-ergebnisse');
    await page.waitForSelector('table.rider-results', { timeout: 5000 }).catch(() => {});
    const tabelle = await page.$('table.rider-results');
    pruefeWahr('Tabelle erschienen', tabelle !== null);
    if (tabelle) {
        pruefe('erste Seite: 50 Zeilen', (await page.$$('table.rider-results tbody tr')).length, 50);
        pruefe('Zaehlzeile nennt Gesamtzahl',
            (await page.textContent('.rr-count'))?.trim(), '50 von 60 Platzierungen');
        pruefeWahr('Nachladen-Knopf da', (await page.$('#ergebnis-mehr')) !== null);

        await page.click('#ergebnis-mehr');
        await page.waitForFunction(
            () => document.querySelectorAll('table.rider-results tbody tr').length === 60,
            null, { timeout: 5000 },
        ).catch(() => {});
        pruefe('nach dem Klick: 60 Zeilen', (await page.$$('table.rider-results tbody tr')).length, 60);
        pruefe('Zaehlzeile aktualisiert',
            (await page.textContent('.rr-count'))?.trim(), '60 von 60 Platzierungen');
        pruefeWahr('Knopf verschwunden', (await page.$('#ergebnis-mehr')) === null);
    }
    pruefe('kein JavaScript-Fehler', jsFehler.join(' | ') || 'keiner', 'keiner');
    await page.close();
}

console.log('=== 2. Inhalt der Zeilen ===');
{
    const { page, jsFehler } = await seite('/rider.html?id=tadej-pogacar');
    await page.waitForSelector('table.rider-results', { timeout: 5000 }).catch(() => {});
    const text = (await page.textContent('table.rider-results')) || '';
    pruefeWahr('Rennname steht drin', text.includes('Tour de France'));
    pruefeWahr('Etappe benannt', text.includes('Etappe 1') && text.includes('Etappe 2'));
    pruefeWahr('Zeit/Abstand steht drin', text.includes('82h'));
    pruefeWahr('Continental-Rennen dabei', text.includes('Tour of Hellas'));
    // Grand-Tour-Abzeichen nur beim Grand Tour, nicht bei Liege-Bastogne-Liege
    pruefe('GT-Abzeichen genau dreimal (drei TdF-Zeilen)',
        (await page.$$('table.rider-results .gt-badge')).length, 3);
    // Pokal nur bei Platz 1: Gesamtsieg TdF + Etappe 2 = zwei
    pruefe('Pokal genau zweimal (zwei Siege)',
        (await page.$$('table.rider-results .rr-pos .trophy')).length, 2);
    pruefeWahr('kein Nachladen-Knopf bei 5 Zeilen', (await page.$('#ergebnis-mehr')) === null);
    pruefe('kein JavaScript-Fehler', jsFehler.join(' | ') || 'keiner', 'keiner');
    await page.close();
}

console.log('=== 3. Fahrer ohne Ergebnisse ===');
{
    const { page, jsFehler } = await seite('/rider.html?id=ohne-ergebnis');
    await page.waitForSelector('#ergebnis-inhalt', { timeout: 5000 }).catch(() => {});
    const text = (await page.textContent('#ergebnis-inhalt')) || '';
    pruefeWahr('Hinweis statt Tabelle', text.includes('noch keine Ergebnisse erfasst'));
    pruefeWahr('keine Tabelle', (await page.$('table.rider-results')) === null);
    // Der Unterschied, auf den es hier ankommt: "keine Ergebnisse" ist etwas
    // anderes als "konnten nicht geladen werden".
    pruefeWahr('kein Fehlertext', !text.includes('konnten nicht geladen werden'));
    pruefe('kein JavaScript-Fehler', jsFehler.join(' | ') || 'keiner', 'keiner');
    await page.close();
}

console.log('=== 4. Profil bleibt stehen, wenn die Liste scheitert ===');
{
    const page = await browser.newPage();
    const jsFehler = [];
    page.on('pageerror', (e) => jsFehler.push(e.message));
    // Nur den Ergebnis-Endpunkt abwuergen, alles andere durchlassen.
    await page.route('**/api/riders/*/results*', (route) => route.abort('failed'));
    await page.goto(`${basis}/rider.html?id=tadej-pogacar`, { waitUntil: 'networkidle' });
    const profil = (await page.textContent('body')) || '';
    pruefeWahr('Profil trotzdem gerendert', profil.includes('Pogacar'));
    pruefeWahr('Karriere-Abschnitt da', profil.includes('Karriere in der World Tour'));
    const inhalt = (await page.textContent('#ergebnis-inhalt')) || '';
    pruefeWahr('Ergebnisse melden den Fehler', inhalt.includes('konnten nicht geladen werden'));
    pruefeWahr('und sagen, dass das Profil davon unberuehrt ist',
        inhalt.includes('Profil oben ist davon nicht betroffen'));
    pruefe('kein JavaScript-Fehler', jsFehler.join(' | ') || 'keiner', 'keiner');
    await page.close();
}

await browser.close();
console.log('');
if (fehler === 0) console.log('Alle Pruefungen bestanden.');
else console.log(`${fehler} Pruefung(en) fehlgeschlagen.`);
process.exit(fehler === 0 ? 0 : 1);
