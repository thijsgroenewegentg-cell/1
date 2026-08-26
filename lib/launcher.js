/**
 * LAUNCHER — open apps and games on the user's PC, by name.
 * Windows: fuzzy-matches Start Menu shortcuts (.lnk) — Steam/Epic games
 * install those automatically — plus well-known URI schemes.
 * macOS: /Applications matching + `open`. Linux: .desktop entries + direct exec.
 *
 * Safety: the user's input is ONLY used for matching against scanned names
 * and a fixed alias table — never executed or interpolated into commands.
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFile } = require('child_process');

const PLATFORM = process.platform;
const DRY = process.env.ULTRON_LAUNCHER_DRY === '1';

// Well-known apps: URI scheme or executable name per platform.
const ALIASES = {
  spotify:    { win32: 'spotify:', darwin: 'Spotify', linux: 'spotify' },
  steam:      { win32: 'steam:', darwin: 'Steam', linux: 'steam' },
  discord:    { win32: 'discord:', darwin: 'Discord', linux: 'discord' },
  epic:       { win32: 'com.epicgames.launcher://apps', darwin: 'Epic Games Launcher', linux: 'epicgames' },
  'epic games': { win32: 'com.epicgames.launcher://apps', darwin: 'Epic Games Launcher', linux: 'epicgames' },
  battlenet:  { win32: 'battlenet:', darwin: 'Battle.net', linux: 'battlenet' },
  'battle.net': { win32: 'battlenet:', darwin: 'Battle.net', linux: 'battlenet' },
  vscode:     { win32: 'code', darwin: 'Visual Studio Code', linux: 'code' },
  'visual studio code': { win32: 'code', darwin: 'Visual Studio Code', linux: 'code' },
  chrome:     { win32: 'chrome', darwin: 'Google Chrome', linux: 'google-chrome' },
  firefox:    { win32: 'firefox', darwin: 'Firefox', linux: 'firefox' },
  edge:       { win32: 'msedge', darwin: 'Microsoft Edge', linux: 'microsoft-edge' },
  explorer:   { win32: 'explorer', darwin: 'Finder', linux: 'nautilus' },
  files:      { win32: 'explorer', darwin: 'Finder', linux: 'nautilus' },
  notepad:    { win32: 'notepad', darwin: 'TextEdit', linux: 'gedit' },
  calculator: { win32: 'calc', darwin: 'Calculator', linux: 'gnome-calculator' },
  terminal:   { win32: 'wt', darwin: 'Terminal', linux: 'x-terminal-emulator' },
  settings:   { win32: 'ms-settings:', darwin: 'System Settings', linux: 'gnome-control-center' },
  obs:        { win32: 'obs64', darwin: 'OBS', linux: 'obs' },
  whatsapp:   { win32: 'whatsapp:', darwin: 'WhatsApp', linux: 'whatsapp' },
  telegram:   { win32: 'telegram', darwin: 'Telegram', linux: 'telegram-desktop' },
  photoshop:  { win32: 'photoshop', darwin: 'Adobe Photoshop', linux: 'photoshop' },
  word:       { win32: 'winword', darwin: 'Microsoft Word', linux: 'libreoffice --writer' },
  excel:      { win32: 'excel', darwin: 'Microsoft Excel', linux: 'libreoffice --calc' },
};

/** Spotify desktop deep-link: opens the app and searches — Premium-friendly. */
function spotifySearchUri(query) {
  return 'spotify:search:' + encodeURIComponent(String(query || '').trim().slice(0, 200));
}

function menuDirs() {
  const custom = process.env.ULTRON_MENU_DIRS;
  if (custom) return custom.split(path.delimiter).filter(Boolean);
  if (PLATFORM === 'win32') {
    return [
      path.join(process.env.ProgramData || 'C:\\ProgramData', 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
      path.join(os.homedir(), 'AppData', 'Roaming', 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
    ];
  }
  if (PLATFORM === 'darwin') return ['/Applications'];
  return ['/usr/share/applications', path.join(os.homedir(), '.local/share/applications')];
}

/** Scan the platform's app menus → [{name, launch}] (launch = .lnk path / app name / desktop id). */
function scanMenu() {
  const out = [];
  const walk = (dir, depth) => {
    if (depth > 3 || out.length > 800) return;
    let entries = [];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      if (e.name.startsWith('.')) continue;
      const full = path.join(dir, e.name);
      if (e.isDirectory()) { walk(full, depth + 1); continue; }
      const lower = e.name.toLowerCase();
      if (PLATFORM === 'win32' && lower.endsWith('.lnk')) {
        out.push({ name: e.name.replace(/\.lnk$/i, '').toLowerCase(), launch: full });
      } else if (PLATFORM === 'darwin' && lower.endsWith('.app')) {
        out.push({ name: e.name.replace(/\.app$/i, '').toLowerCase(), launch: e.name.replace(/\.app$/i, '') });
      } else if (PLATFORM === 'linux' && lower.endsWith('.desktop')) {
        try {
          const content = fs.readFileSync(full, 'utf8');
          const name = (content.match(/^Name=(.+)$/m) || [])[1];
          if (name) out.push({ name: name.trim().toLowerCase(), launch: full });
        } catch { /* skip */ }
      }
    }
  };
  for (const dir of menuDirs()) walk(dir, 0);
  return out;
}

function sanitizeName(raw) {
  return String(raw || '').trim().toLowerCase().slice(0, 80).replace(/[^a-z0-9 .:&_+'-]/g, '');
}

/** Resolve an app name (+optional spotify search) to a launch command. */
function resolveTarget({ name, search }) {
  const clean = sanitizeName(name);
  if (!clean) return { error: 'which app?' };

  // Spotify with a search → deep link straight into the desktop app.
  if (/^(spotify|spotify app|muziek|music)$/.test(clean) && search && String(search).trim()) {
    const uri = spotifySearchUri(search);
    return { kind: 'uri', uri, display: `Spotify · search "${search}"`, platform: PLATFORM };
  }

  // 1. Alias table.
  const alias = ALIASES[clean] || ALIASES[clean.replace(/\s+/g, '')];
  if (alias) {
    const target = alias[PLATFORM] || alias.win32;
    const isUri = target.endsWith(':') || target.includes('://');
    return { kind: isUri ? 'uri' : 'app', target, display: clean, platform: PLATFORM };
  }

  // 2. Fuzzy match against installed apps/games from the menus.
  const menu = scanMenu();
  const hit =
    menu.find((m) => m.name === clean) ||
    menu.find((m) => m.name.startsWith(clean)) ||
    menu.find((m) => m.name.includes(clean));
  if (hit) {
    if (PLATFORM === 'win32') return { kind: 'shortcut', path: hit.launch, display: hit.name, platform: PLATFORM };
    if (PLATFORM === 'darwin') return { kind: 'app', target: hit.launch, display: hit.name, platform: PLATFORM };
    return { kind: 'desktop', path: hit.launch, display: hit.name, platform: PLATFORM };
  }

  // 3. Steam game by name → let the user know how, or try URI.
  if (/^(steam|valve)$/.test(clean)) return { kind: 'uri', uri: 'steam://open/games', display: 'Steam library', platform: PLATFORM };

  const known = Object.keys(ALIASES).slice(0, 14).join(', ');
  return { error: `"${clean}" not found in the Start menu / applications. Known aliases: ${known}… — or ask me to search for how to launch it` };
}

/** Build the platform exec for a resolved target. */
function buildCommand(t) {
  if (PLATFORM === 'win32') {
    if (t.kind === 'uri') return { cmd: 'cmd', args: ['/c', 'start', '', t.target || t.uri] };
    if (t.kind === 'shortcut') return { cmd: 'cmd', args: ['/c', 'start', '', t.path] };
    return { cmd: 'cmd', args: ['/c', 'start', '', t.target] };
  }
  if (PLATFORM === 'darwin') {
    if (t.kind === 'uri') return { cmd: 'open', args: [t.uri] };
    return { cmd: 'open', args: ['-a', t.target] };
  }
  // Linux
  if (t.kind === 'uri') return { cmd: 'xdg-open', args: [t.uri] };
  if (t.kind === 'desktop') return { cmd: 'gtk-launch', args: [path.basename(t.path, '.desktop')] };
  return { cmd: t.target.split(' ')[0], args: t.target.split(' ').slice(1), detached: true };
}

/** Open an app / game / deep link. Never executes raw user input. */
function openApp({ name, search }) {
  const target = resolveTarget({ name, search });
  if (target.error) return target;

  if (DRY) {
    return { ok: true, dry: true, resolved: target.display, note: 'dry-run — nothing was launched' };
  }

  const { cmd, args } = buildCommand(target);
  return new Promise((resolve) => {
    try {
      const child = execFile(cmd, args, { timeout: 8000, windowsHide: true }, (err) => {
        if (err && /not recognized|not found|ENOENT|cannot find/i.test(String(err.message || ''))) {
          resolve({ ok: false, error: `could not launch "${target.display}" on ${PLATFORM}: ${String(err.message).slice(0, 120)}` });
        } else {
          resolve({ ok: true, launched: target.display, platform: PLATFORM, note: 'launched on the user\'s machine' });
        }
      });
      if (child && child.unref) child.unref();
    } catch (err) {
      resolve({ ok: false, error: String(err.message || err).slice(0, 140) });
    }
  });
}

module.exports = { openApp, resolveTarget, scanMenu, spotifySearchUri, ALIASES };
