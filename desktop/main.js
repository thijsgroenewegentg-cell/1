/**
 * VoiceOS Desktop — Electron shell (Windows & Linux).
 * Turns the web app into a real always-on-top, frameless voice bar
 * with a global hotkey (default Ctrl+Space, override via VOICEOS_HOTKEY).
 *
 * Installers are built automatically by GitHub Actions on every v* tag
 * (see .github/workflows/release.yml) and attached to the release.
 * To build locally instead:  cd desktop && npm install && npm run dist
 * → dist/VoiceOS Setup.exe + VoiceOS.exe (portable) + VoiceOS.AppImage + .deb
 */
const { app, BrowserWindow, globalShortcut, screen, ipcMain } = require('electron');
const path = require('path');

const HOTKEY = process.env.VOICEOS_HOTKEY || 'Control+Space';
let win = null;

function createWindow() {
  const { width } = screen.getPrimaryDisplay().workAreaSize;

  win = new BrowserWindow({
    width: Math.min(760, width),
    height: 620,
    x: Math.round((width - Math.min(760, width)) / 2),
    y: 24,                       // floats top-center like a voice bar
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: true,
    fullscreenable: false,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
    },
  });

  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.setAlwaysOnTop(true, 'screen-saver');
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  // Hide instead of close — the notch should feel ever-present.
  win.on('close', e => {
    if (!app.isQuitting) { e.preventDefault(); win.hide(); }
  });
}

function toggle() {
  if (!win) return;
  if (win.isVisible() && win.isFocused()) win.hide();
  else { win.show(); win.focus(); }
}

app.whenReady().then(() => {
  createWindow();
  globalShortcut.register(HOTKEY, toggle);

  ipcMain.on('voiceos:quit', () => { app.isQuitting = true; app.quit(); });

  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on('will-quit', () => globalShortcut.unregisterAll());
app.on('window-all-closed', e => e.preventDefault()); // stay alive as an overlay
