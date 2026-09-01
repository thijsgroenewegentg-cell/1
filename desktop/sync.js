/** Copies the web app into desktop/renderer/ so electron-builder can package it. */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const OUT = path.join(__dirname, 'renderer');
const FILES = ['index.html', 'styles.css', 'app.js', 'manifest.webmanifest', 'sw.js'];

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(path.join(OUT, 'icons'), { recursive: true });
for (const f of FILES) fs.copyFileSync(path.join(ROOT, f), path.join(OUT, f));
for (const f of fs.readdirSync(path.join(ROOT, 'icons'))) {
  fs.copyFileSync(path.join(ROOT, 'icons', f), path.join(OUT, 'icons', f));
}
console.log('Synced web app → desktop/renderer/');
