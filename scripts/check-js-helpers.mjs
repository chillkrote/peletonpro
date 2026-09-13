#!/usr/bin/env node
// Prueft pro HTML-Seite: ruft eines ihrer Skripte einen projekteigenen
// Helfer auf, den keines der von dieser Seite geladenen Skripte definiert?
//
//   node scripts/check-js-helpers.mjs
//
// Hintergrund: die Seiten laden ihre Skripte als klassische <script
// src>-Tags in den globalen Namensraum, ohne Module und ohne Bundler (siehe
// backend/README.md). Ob ein Helfer zur Laufzeit da ist, haengt damit allein
// davon ab, ob die Seite das richtige Skript laedt - und das faellt erst im
// Browser auf, und dort nur, wenn man den betroffenen Zweig ausloest.
//
// Genau so ist es passiert: beim Umbau von js/team.js auf
// /api/teams/{id}/stats entfielen dessen lokale Kopien von errorPanel und
// initials, und team.html laedt kein Skript, das sie mitbringt. Die
// Team-Detailseite lief in einen ReferenceError. `node --check` sieht das
// nicht (die Syntax ist ja in Ordnung).
//
// Betrachtet werden nur Namen, die irgendwo unter js/ als
// `function name(...)` auf oberster Ebene definiert sind. Das haelt deutsche
// Kommentarwoerter und Methoden aus Objektliteralen (Api.getTeams) heraus.
//
// GRENZE: ein Helfer, der im ganzen Baum nirgends mehr definiert ist, steht
// nicht in dieser Namensmenge und faellt damit durch. Die Pruefung findet
// "Helfer verschoben, Seite laedt ihn nicht", nicht "Helfer ganz geloescht".
import { readFileSync, readdirSync } from 'node:fs';

const skriptDateien = readdirSync('js').filter((f) => f.endsWith('.js')).map((f) => `js/${f}`);

// Zeilenkommentare entfernen, damit "siehe errorPanel()" in einem Kommentar
// nicht als Aufruf zaehlt. Blockkommentare kommen im Projekt nicht vor.
const ohneKommentare = (s) =>
    s.split('\n').map((z) => z.replace(/(^|[^:"'`\\])\/\/.*$/, '$1')).join('\n');

const definitionenIn = (quelle) =>
    [...quelle.matchAll(/^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)/gm)].map((m) => m[1]);

const universum = new Set();
for (const f of skriptDateien) definitionenIn(readFileSync(f, 'utf8')).forEach((n) => universum.add(n));

let probleme = 0;
for (const seite of readdirSync('.').filter((f) => f.endsWith('.html')).sort()) {
    const skripte = [...readFileSync(seite, 'utf8').matchAll(/src="(js\/[a-z.]+)"/g)].map((m) => m[1]);
    const definiert = new Set();
    for (const s of skripte) definitionenIn(readFileSync(s, 'utf8')).forEach((n) => definiert.add(n));

    const fehlend = new Map();
    for (const s of skripte) {
        const quelle = ohneKommentare(readFileSync(s, 'utf8'));
        for (const name of universum) {
            if (definiert.has(name)) continue;
            if (new RegExp(`(?<![.\\w$])${name}\\s*\\(`).test(quelle)) {
                if (!fehlend.has(name)) fehlend.set(name, new Set());
                fehlend.get(name).add(s);
            }
        }
    }
    if (fehlend.size === 0) {
        console.log(`  ${seite.padEnd(12)} ok   ${skripte.length} Skripte, ${definiert.size} Helfer verfügbar`);
    } else {
        probleme += fehlend.size;
        console.log(`  ${seite.padEnd(12)} FEHLT:`);
        for (const [name, dateien] of fehlend) {
            console.log(`      ${name}()  aufgerufen in ${[...dateien].join(', ')}`);
        }
    }
}
console.log(probleme === 0
    ? 'Keine unaufgelösten Helfer-Aufrufe.'
    : `${probleme} unaufgelöst - die Seite läuft dort in einen ReferenceError.`);
process.exit(probleme ? 1 : 0);
