#!/usr/bin/env node
// Prüft, dass die Modul-Kanten stimmen:
//
//   node scripts/check-js-modules.mjs
//
// 1. Jede HTML-Seite lädt genau ein <script type="module">.
// 2. Jeder import in js/ trifft auf ein passendes export - Node meldet einen
//    falschen Namen beim VERLINKEN des Modulgraphen, also bevor irgendein
//    Modulrumpf läuft. Deshalb funktioniert die Prüfung, obwohl die Module
//    beim Ausführen window und document brauchen, die es in Node nicht gibt.
// 3. Kein Modul exportiert etwas, das niemand importiert (toter Export).
//
// Diese Datei ersetzt scripts/check-js-helpers.mjs: solange die Skripte über
// globale Namen zusammenhingen, musste man prüfen, ob eine Seite das richtige
// Skript lädt. Mit Modulen ist das deklariert, und ein falscher Name ist ein
// harter Fehler statt eines stillen undefined.
import { readFileSync, readdirSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

let probleme = 0;
const melde = (text) => { probleme += 1; console.log(`  FEHLER  ${text}`); };

// --- 1. Ein Modul-Tag pro Seite -------------------------------------------
const seiten = readdirSync('.').filter((f) => f.endsWith('.html')).sort();
const einstiege = [];
for (const seite of seiten) {
    const html = readFileSync(seite, 'utf8');
    const alle = [...html.matchAll(/<script\b[^>]*src="(js\/[^"]+)"[^>]*>/g)];
    const module = alle.filter((m) => /type="module"/.test(m[0]));
    if (alle.length !== 1 || module.length !== 1) {
        melde(`${seite}: ${alle.length} Skript-Tags, davon ${module.length} type="module" `
            + '- erwartet genau ein Modul-Tag');
        continue;
    }
    einstiege.push(module[0][1]);
    console.log(`  ${seite.padEnd(12)} -> ${module[0][1]}`);
}

// --- 2. Importe verlinken --------------------------------------------------
// window/document stubben, damit ein Modulrumpf, der doch laufen sollte,
// nicht an einer fehlenden Browser-API scheitert und den echten Fehler
// verdeckt.
globalThis.window = { location: { hostname: 'localhost', search: '' } };
globalThis.document = {
    readyState: 'loading',
    addEventListener() {},
    getElementById: () => null,
    querySelectorAll: () => [],
};
globalThis.localStorage = { getItem: () => null, setItem() {} };

for (const einstieg of einstiege) {
    try {
        await import(pathToFileURL(einstieg).href);
    } catch (err) {
        if (err instanceof SyntaxError) {
            melde(`${einstieg}: ${err.message}`);
        } else {
            // Laufzeitfehler im Modulrumpf - das Verlinken hat geklappt, und
            // um die Laufzeit kümmert sich der Browser-Test.
            console.log(`  ${einstieg.padEnd(14)} verlinkt (Rumpf lief nicht durch: ${err.message.split('\n')[0]})`);
        }
    }
}

// --- 3. Tote Exporte ------------------------------------------------------
const dateien = readdirSync('js').filter((f) => f.endsWith('.js'));
const exporte = new Map();   // Datei -> Namen
for (const f of dateien) {
    const q = readFileSync(`js/${f}`, 'utf8');
    exporte.set(f, [...q.matchAll(/^export\s+(?:async\s+)?(?:function|const|let|class)\s+([A-Za-z_$][\w$]*)/gm)]
        .map((m) => m[1]));
}
const importiert = new Set();
for (const f of dateien) {
    const q = readFileSync(`js/${f}`, 'utf8');
    for (const m of q.matchAll(/import\s*\{([^}]+)\}\s*from/g)) {
        m[1].split(',').map((n) => n.trim().split(/\s+as\s+/)[0]).filter(Boolean)
            .forEach((n) => importiert.add(n));
    }
}
for (const [f, namen] of exporte) {
    const tot = namen.filter((n) => !importiert.has(n));
    if (tot.length) melde(`js/${f}: exportiert, aber nirgends importiert: ${tot.join(', ')}`);
}

console.log(probleme === 0 ? 'Modulgraph in Ordnung.' : `${probleme} Problem(e).`);
process.exit(probleme ? 1 : 0);
