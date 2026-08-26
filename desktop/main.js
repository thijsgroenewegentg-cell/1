/**
 * ULTRON — desktop companion.
 * A tiny frameless, always-on-top window with the mini orb UI.
 *
 *   cd desktop && npm install && npm start
 *   (requires the main Ultron server running on localhost:3000)
 *
 * NOTE: scaffolded but not built in CI — Electron downloads its binary
 * on first `npm install`, which needs internet.
 */
'use strict';

const { app, BrowserWindow, Tray, Menu, globalShortcut } = require('electron');
const path = require('path');

const ULTRON_URL = process.env.ULTRON_URL || 'http://localhost:3000/?mini=1';

let win = null;
let tray = null;

function createWindow() {
  win = new BrowserWindow({
    width: 380,
    height: 560,
    frame: false,
    transparent: true,
    resizable: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadURL(ULTRON_URL);
  win.on('closed', () => { win = null; });
}

app.whenReady().then(() => {
  createWindow();

  tray = new Tray(path.join(__dirname, 'icon.png'));
  tray.setToolTip('ULTRON — there are no strings on me');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Show / hide', click: () => (win.isVisible() ? win.hide() : win.show()) },
    { type: 'separator' },
    { label: 'Quit Ultron', click: () => app.quit() },
  ]));

  // Global hotkey: Alt+Shift+U toggles the companion.
  globalShortcut.register('Alt+Shift+U', () => {
    if (!win) createWindow();
    else if (win.isVisible()) win.hide();
    else win.show();
  });
});

app.on('window-all-closed', () => { /* keep running in tray */ });
app.on('will-quit', () => globalShortcut.unregisterAll());
