#!/usr/bin/env node
// Lädt jede Seite in Chromium über HTTP und prüft, dass sie wirklich läuft.
//
//   # Backend auf :8001 und statische Dateien auf :8000 starten, dann:
//   node scripts/check-pages.mjs
//   node scripts/check-pages.mjs http://127.0.0.1:8000
//
// Über HTTP, NICHT über file:// - ES-Module unterliegen CORS und laden von
// file:// grundsätzlich nicht. Wer die Seiten per Doppelklick öffnet, sieht
// eine leere Seite und hält das für einen Fehler im Code.
//
// Geprüft wird pro Seite:
//   1. kein JavaScript-Fehler (pageerror) - das fängt fehlgeschlagene
//      Modul-Importe und ReferenceErrors
//   2. kein fehlgeschlagener Request auf eine EIGENE Datei. Externe Quellen
//      (Font-Awesome-CDN, Google Fonts, Wikimedia-Logos) werden übergangen:
//      sie sind in abgeschotteten Umgebungen nicht erreichbar und sagen
//      nichts über den Code. /favicon.ico fragt Chromium von selbst an.
//   3. die Seite hat wirklich gerendert - ein erwarteter Text muss im
//      sichtbaren Text stehen. Ohne diese Prüfung besteht auch eine Seite
//      den Test, die stumm nichts tut.
//   4. kein Helfer hängt mehr am globalen window. Das ist die eigentliche
//      Zusage der Modul-Umstellung.
import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';

const BASIS = process.argv[2] || 'http://127.0.0.1:8000';
const EXTERN = /cdnjs|cdn\.|fonts\.(googleapis|gstatic)|wikimedia|wikipedia|favicon\.ico/;

// Die Erwartungen passen zu den Testdaten aus backend/README.md, Abschnitt
// "Seiten im Browser prüfen".
const SEITEN = [
    { pfad: '/index.html', erwartet: /Teams/ },
    { pfad: '/teams.html', erwartet: /WorldTeams|Teams/ },
    { pfad: '/team.html?id=uae-team-emirates-xrg', erwartet: /UAE Team Emirates/ },
    { pfad: '/rider.html?id=tadej-poga-ar', erwartet: /Poga/ },
    { pfad: '/races.html', erwartet: /Tour de France|Rennen/ },
    { pfad: '/news.html', erwartet: /News|Nachrichten/ },
];

const GLOBALE_HELFER = [
    'escapeHtml', 'safeUrl', 'Api', 'apiGet', 'renderNav', 'renderComingSoonIfWomen',
    'errorPanel', 'loadingPanel', 'statePanel', 'pendingPanel', 'teamInitials',
    'riderInitials', 'formatCalendarDate', 'todayCalendarIso', 'starten',
    'renderTeamRoster', 'initRidersTab', 'formatBirthDate', 'isWomen',
];

const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH
        || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
});
let probleme = 0;

for (const { pfad, erwartet } of SEITEN) {
    const seite = await browser.newPage();
    const jsFehler = [];
    const kaputt = [];
    seite.on('pageerror', (e) => jsFehler.push(e.message.split('\n')[0]));
    seite.on('requestfailed', (r) => {
        if (!EXTERN.test(r.url())) kaputt.push(`${r.url()} (${r.failure()?.errorText})`);
    });
    seite.on('response', (r) => {
        if (r.status() >= 400 && !EXTERN.test(r.url())) kaputt.push(`${r.url()} -> HTTP ${r.status()}`);
    });

    await seite.goto(BASIS + pfad, { waitUntil: 'networkidle' });
    const text = await seite.evaluate(() => document.body.innerText);
    const global = await seite.evaluate(
        (namen) => namen.filter((n) => window[n] !== undefined), GLOBALE_HELFER,
    );

    const fehler = [];
    if (jsFehler.length) fehler.push(`JavaScript-Fehler: ${jsFehler.join(' | ')}`);
    if (kaputt.length) fehler.push(`eigene Requests fehlgeschlagen: ${kaputt.join(' | ')}`);
    if (!erwartet.test(text)) {
        fehler.push(`nicht gerendert - ${erwartet} fehlt. Sichtbar: `
            + `${text.slice(0, 160).replace(/\s+/g, ' ')}`);
    }
    if (global.length) fehler.push(`noch am globalen window: ${global.join(', ')}`);

    if (fehler.length) {
        probleme += 1;
        console.log(`  ${pfad}\n      ` + fehler.join('\n      '));
    } else {
        console.log(`  ${pfad.padEnd(42)} ok`);
    }
    await seite.close();
}
await browser.close();
console.log(probleme === 0
    ? `Alle ${SEITEN.length} Seiten gerendert, ohne JavaScript-Fehler, ohne globale Helfer.`
    : `${probleme} Seite(n) mit Problemen.`);
process.exit(probleme ? 1 : 0);
