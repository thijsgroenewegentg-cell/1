/** Copies the web app into desktop/renderer/ so electron-builder can package it.
 *  Also copies the app icon into desktop/build/ (electron-builder's default
 *  build-resources dir, used for the Windows/Linux installer icons). */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const OUT = path.join(__dirname, 'renderer');
const BUILD = path.join(__dirname, 'build');
const FILES = ['index.html', 'styles.css', 'app.js', 'manifest.webmanifest', 'sw.js'];

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(path.join(OUT, 'icons'), { recursive: true });
for (const f of FILES) fs.copyFileSync(path.join(ROOT, f), path.join(OUT, f));
for (const f of fs.readdirSync(path.join(ROOT, 'icons'))) {
  fs.copyFileSync(path.join(ROOT, 'icons', f), path.join(OUT, 'icons', f));
}

fs.mkdirSync(BUILD, { recursive: true });
fs.copyFileSync(path.join(ROOT, 'icons', 'icon-512.png'), path.join(BUILD, 'icon.png'));

console.log('Synced web app → desktop/renderer/ + icon → desktop/build/');
