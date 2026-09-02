'use strict';
/* =========================================================
   VoiceOS — voice-first operating layer
   Turns speech → intent → JSON → action. (Prototype build)
   ========================================================= */

/* ======================== DATA ======================== */

const CONTACTS = {
  john:  { name: 'John',  email: 'john@company.com',  app: 'Mail' },
  sarah: { name: 'Sarah', email: 'sarah@company.com', app: 'Mail' },
  maya:  { name: 'Maya',  email: 'maya@studio.co',    app: 'Messages' },
  maria: { name: 'Maria', email: 'maria@company.com', app: 'Messages' },
  alex:  { name: 'Alex',  email: 'alex@company.com',  app: 'Messages' },
};

const FILES = [
  { icon: '📄', name: 'tax_return_2025.pdf',  meta: 'Documents · Taxes · 2.4 MB',  tags: 'tax return taxes irs finance belastingaangifte belasting aangifte' },
  { icon: '📄', name: 'tax_return_2024.pdf',  meta: 'Documents · Taxes · 2.1 MB',  tags: 'tax return taxes irs finance belastingaangifte belasting aangifte' },
  { icon: '📊', name: 'tax_summary_2025.xlsx', meta: 'Documents · Taxes · 812 KB', tags: 'tax summary taxes spreadsheet finance belastingoverzicht belasting belastingaangifte aangifte' },
  { icon: '🎞️', name: 'project_deck_v7.key',  meta: 'Desktop · Modified yesterday', tags: 'project deck slides presentation keynote presentatie' },
  { icon: '📝', name: 'Q3_roadmap.docx',      meta: 'Drive · Strategy',            tags: 'roadmap strategy doc document q3 routekaart strategie' },
  { icon: '🖼️', name: 'brand_mockups.fig',    meta: 'Design · Shared with Maya',   tags: 'brand mockups design figma ontwerpen merk' },
  { icon: '📦', name: 'invoice_sept.pdf',     meta: 'Downloads · 340 KB',          tags: 'invoice billing finance pdf factuur' },
];

const APPS = {
  Mail:     { icon: '✉️',  name: 'Mail' },
  Calendar: { icon: '📅', name: 'Calendar' },
  Messages: { icon: '💬', name: 'Messages' },
  Notes:    { icon: '📝', name: 'Notes' },
  Files:    { icon: '📁', name: 'Files' },
  Tasks:    { icon: '✅', name: 'Tasks' },
};

const now = new Date();
function at(offsetDays, h, m) {
  const d = new Date(now);
  d.setDate(d.getDate() + offsetDays);
  d.setHours(h, m, 0, 0);
  return d;
}

const store = {
  emails: [
    { from: 'Maya',  subj: 'Design review tomorrow', body: 'Are we still on? I want to walk through the new onboarding flow.', when: '9:41 AM', unread: true },
    { from: 'John',  subj: 'Re: Meeting notes',      body: 'Thanks — can you also attach the deck when you get a chance?',     when: 'Yesterday', unread: false },
    { from: 'Linear', subj: 'VOI-214 moved to Done', body: 'Voice dictation latency fix was merged by Alex.',                  when: 'Yesterday', unread: false },
  ],
  sent: [],
  threads: {
    maya:  [ { from: 'them', text: 'Are we still on for the design review tomorrow?' },
             { from: 'me',   text: 'Yes! I’ll send the deck tonight.' },
             { from: 'them', text: 'Perfect 🙌' } ],
    maria: [ { from: 'them', text: 'Lunch next week? It’s been forever.' } ],
    alex:  [ { from: 'me',   text: 'Shipped the latency fix 🚀' },
             { from: 'them', text: 'Nice. 120ms → 40ms is wild.' } ],
  },
  events: [
    { title: 'Design review',   when: at(1, 14, 0), who: ['Maya'],        fresh: false },
    { title: '1:1 with Alex',   when: at(2, 11, 0), who: ['Alex'],        fresh: false },
    { title: 'Launch retro',    when: at(4, 16, 0), who: ['Whole team'],  fresh: false },
  ],
  notes: [
    { text: 'Launch checklist: changelog, pricing page, announcement email.', fresh: false },
    { text: 'Idea: voice bar should pulse while listening.', fresh: false },
  ],
  reminders: [],
  tasks: [
    { title: 'Review pull request from Alex', done: false, fresh: false },
    { title: 'Draft launch announcement', done: false, fresh: false },
    { title: 'Book flights for offsite', done: true, fresh: false },
  ],
};

/* ======================== STATE ======================== */

const state = {
  activeApp: null,
  pending: null,
  sound: true,
  recognition: null,
  listening: false,
  history: [],
  aliases: {},              // learned corrections: 'sara' -> 'sarah'
  realFiles: [],            // real on-disk files from a connected folder (File System Access)
  realFolderName: null,
};
const openWins = {};        // appName -> win element

/* ======================== SETTINGS & PERSISTENCE ======================== */

const LS_KEYS = { settings: 'voiceos_settings_v1', store: 'voiceos_store_v1' };
function lsOK() { try { return typeof localStorage !== 'undefined'; } catch (_) { return false; } }

const SETTING_DEFAULTS = { voice: null, rate: 'normal', confirmLevel: 'sometimes', verbosity: 'normal', lang: null, bridge: true };
let settings = { ...SETTING_DEFAULTS };
if (!settings.lang) settings.lang = detectLang();

/* UI language helpers */
const T = (en, nl) => (settings.lang === 'nl' ? nl : en);
const UI = () => I18N[settings.lang === 'nl' ? 'nl' : 'en'];
const LBL = k => UI().lbl[k] || k;

function loadSettings() {
  if (!lsOK()) return;
  try {
    const raw = localStorage.getItem(LS_KEYS.settings);
    if (raw) settings = { ...SETTING_DEFAULTS, ...JSON.parse(raw) };
  } catch (_) { /* corrupted → defaults */ }
}
function saveSettings() {
  if (!lsOK()) return;
  try { localStorage.setItem(LS_KEYS.settings, JSON.stringify(settings)); } catch (_) {}
}

/* Confirmation levels (spec: always / sometimes / never) */
const CONFIRM_HIGH = ['send_email', 'reply_email', 'schedule_meeting', 'share_file', 'delete_file'];
const CONFIRM_MED  = ['send_message', 'reply_message', 'close_app', 'create_task'];
function shouldConfirm(action) {
  if (settings.confirmLevel === 'never') return false; // refusals (passwords, mass delete) remain hard refusals
  if (settings.confirmLevel === 'always') return CONFIRM_HIGH.concat(CONFIRM_MED).includes(action);
  return CONFIRM_HIGH.includes(action);                  // 'sometimes' = default
}

/* Store persistence — notes, events, reminders, threads, history survive restarts */
function snapshotStore() {
  return JSON.stringify({
    notes: store.notes, reminders: store.reminders, events: store.events,
    sent: store.sent, threads: store.threads, tasks: store.tasks,
    aliases: state.aliases, history: state.history.slice(-30),
  });
}
function persist() {
  if (!lsOK()) return;
  try { localStorage.setItem(LS_KEYS.store, snapshotStore()); } catch (_) {}
}
function reviveDates(arr, key) { (arr || []).forEach(x => { if (x && x[key]) x[key] = new Date(x[key]); }); }
function loadPersisted() {
  if (!lsOK()) return;
  try {
    const raw = localStorage.getItem(LS_KEYS.store);
    if (!raw) return;
    const d = JSON.parse(raw);
    if (d.notes) store.notes = d.notes;
    if (d.reminders) { store.reminders = d.reminders; reviveDates(store.reminders, 'when'); }
    if (d.events)    { store.events = d.events;       reviveDates(store.events, 'when'); }
    if (d.sent) store.sent = d.sent;
    if (d.threads) store.threads = d.threads;
    if (Array.isArray(d.tasks)) store.tasks = d.tasks;
    if (d.aliases) state.aliases = d.aliases;
    if (Array.isArray(d.history)) state.history = d.history;
  } catch (_) { /* ignore corrupted snapshot */ }
}
function wipeLocal() {
  if (!lsOK()) return;
  localStorage.removeItem(LS_KEYS.store);
  localStorage.removeItem(LS_KEYS.settings);
}

/* ======================== UTILS ======================== */

const $  = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function LOCALE() { return settings.lang === 'nl' ? 'nl-NL' : 'en-US'; }
function fmtDate(d) {
  return d.toLocaleDateString(LOCALE(), { weekday: 'short' }) + ', ' +
         d.toLocaleDateString(LOCALE(), { month: 'short', day: 'numeric' });
}
function fmtTime(d) {
  return d.toLocaleTimeString(LOCALE(), { hour: 'numeric', minute: '2-digit' });
}
function fmtWhen(d) { return fmtDate(d) + ' · ' + fmtTime(d); }

const DAYS = ['sunday','monday','tuesday','wednesday','thursday','friday','saturday'];

/* resolve date/time phrases — English AND Dutch ("morgen om 9 uur", "volgende maandag") */
function resolveDate(t) {
  const d = new Date();
  const dayMatch = t.match(/\b(next|volgende)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag)\b/)
                || t.match(/\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag)\b/);
  if (/day after tomorrow|overmorgen/.test(t)) { d.setDate(d.getDate() + 2); }
  else if (/tomorrow|morgen/.test(t)) { d.setDate(d.getDate() + 1); }
  else if (/next week|volgende week/.test(t)) {
    const delta = ((1 - d.getDay()) + 7) % 7 || 7; // next Monday
    d.setDate(d.getDate() + delta);
  }
  else if (dayMatch) {
    const w = dayMatch[2];
    const target = DAYS.includes(w) ? DAYS.indexOf(w) : (typeof NL_DAYS !== 'undefined' ? NL_DAYS[w] : undefined);
    let delta = ((target ?? d.getDay()) - d.getDay() + 7) % 7;
    if (dayMatch[1] && delta === 0) delta = 7;
    if (!dayMatch[1] && delta === 0) delta = 0; // bare weekday today = today
    d.setDate(d.getDate() + delta);
  }
  d.setHours(9, 0, 0, 0);
  const tm = t.match(/\b(?:at|om)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b/)
          || t.match(/\bom\s+(\d{1,2})[:.](\d{2})\s*uur\b/)
          || t.match(/\bom\s+(\d{1,2})\s*uur\b/)
          || t.match(/\bom\s+(\d{1,2})[:.](\d{2})\b/);
  if (tm) {
    let h = parseInt(tm[1], 10);
    if (tm[3] === 'am' || tm[3] === 'pm') { h = h % 12; if (tm[3] === 'pm') h += 12; }
    else if (/'s middags|namiddag|vanmiddag/.test(t) && h < 12) h += 12;
    else if (/'s avonds|vanavond/.test(t) && h < 12) h += 12;
    d.setHours(Math.min(h, 23), parseInt(tm[2] || '0', 10), 0, 0);
  } else if (/noon|middag uur|'s middags om 12/.test(t)) d.setHours(12, 0, 0, 0);
  else if (/tonight|evening|vanavond|'s avonds/.test(t)) d.setHours(19, 0, 0, 0);
  else if (/afternoon|vanmiddag|namiddag/.test(t)) d.setHours(14, 0, 0, 0);
  return d;
}

/* resolve an app name from any language: "Open Notities" → Notes */
function resolveApp(word) {
  const w = String(word || '').toLowerCase();
  const direct = Object.keys(APPS).find(a => a.toLowerCase() === w);
  if (direct) return direct;
  if (typeof APP_NAMES_NL !== 'undefined' && APP_NAMES_NL[w]) return APP_NAMES_NL[w];
  return null;
}

function findContact(t) {
  for (const alias of Object.keys(state.aliases)) {
    if (new RegExp('\\b' + alias + '\\b', 'i').test(t) && CONTACTS[state.aliases[alias]]) {
      return { key: state.aliases[alias], ...CONTACTS[state.aliases[alias]], viaAlias: alias };
    }
  }
  for (const key of Object.keys(CONTACTS)) {
    if (new RegExp('\\b' + key + '\\b', 'i').test(t)) return { key, ...CONTACTS[key] };
  }
  // fuzzy: typo tolerance ("Jhon" → John) — words of ≥4 chars at edit distance ≤1
  const words = t.match(/[a-z]{4,}/gi) || [];
  let best = null, bestD = 2;
  for (const w of words) {
    for (const key of Object.keys(CONTACTS)) {
      const d = editDist(w, key);
      if (d > 0 && d < bestD) { best = key; bestD = d; }
    }
    for (const alias of Object.keys(state.aliases)) {
      const d = editDist(w, alias);
      if (d > 0 && d < bestD && CONTACTS[state.aliases[alias]]) { best = state.aliases[alias]; bestD = d; }
    }
  }
  if (best) return { key: best, ...CONTACTS[best], viaFuzzy: true };
  return null;
}

function titleCase(s) { return s.replace(/\b\w/g, c => c.toUpperCase()); }

/* ======================== SOUND DESIGN ========================
   Synthesized via WebAudio — zero audio assets, so the product
   stays 100% dependency-free and offline. Honors the 🔊 toggle. */

let audioCtx = null;
function tone(freq, dur = .09, type = 'sine', vol = .05, when = 0) {
  if (!state.sound) return;
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.type = type; o.frequency.value = freq;
    const t0 = audioCtx.currentTime + when;
    g.gain.setValueAtTime(0, t0);
    g.gain.linearRampToValueAtTime(vol, t0 + .012);
    g.gain.exponentialRampToValueAtTime(.0001, t0 + dur);
    o.connect(g).connect(audioCtx.destination);
    o.start(t0); o.stop(t0 + dur + .02);
  } catch (_) { /* no audio device — silent */ }
}
const SFX = {
  listen:  () => tone(520, .08),
  work:    () => tone(660, .06, 'sine', .04),
  card:    () => tone(740, .05, 'triangle', .035),
  send:    () => { tone(523, .07); tone(784, .1, 'sine', .05, .07); },
  success: () => { tone(659, .07); tone(880, .12, 'sine', .05, .08); },
  cancel:  () => tone(280, .12),
};

/* ======================== REAL-WORLD BRIDGE ========================
   Zero-auth integrations that touch the user's REAL apps:
   mailto: drafts (real email client, prefilled), Google Calendar
   template URLs (real event creation), clipboard hand-off for
   messages, and — where the browser grants it — true on-disk file
   search. All degrade silently to the simulated OS. */

const Bridge = {
  mailto(to, subject, body) {
    return 'mailto:' + encodeURIComponent(to).replace(/%40/g, '@')
      + '?subject=' + encodeURIComponent(subject || '')
      + '&body=' + encodeURIComponent(body || '');
  },
  gcalEvent(title, whenISO, attendee) {
    const d = new Date(whenISO);
    const end = new Date(d.getTime() + 30 * 60000);
    const fmt = x => x.toISOString().replace(/[-:]|\.\d{3}/g, '');
    const p = new URLSearchParams({ action: 'TEMPLATE', text: title, dates: fmt(d) + '/' + fmt(end) });
    if (attendee) p.set('add', attendee);
    return 'https://calendar.google.com/calendar/render?' + p.toString();
  },
  async clipboard(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (_) { return false; }
  },
  canRealFiles: () => typeof window !== 'undefined' && 'showDirectoryPicker' in window,
  async pickFolder() {
    if (!Bridge.canRealFiles()) return null;
    try { return await window.showDirectoryPicker(); } catch (_) { return null; }
  },
  async scanFolder(dirHandle, pathPrefix = '', depth = 0, out = []) {
    if (!dirHandle || depth > 2 || out.length > 600) return out;
    try {
      for await (const entry of dirHandle.values()) {
        const p = pathPrefix + entry.name;
        out.push({ name: entry.name, path: p, kind: entry.kind, handle: entry, entry });
        if (entry.kind === 'directory') await Bridge.scanFolder(entry, p + '/', depth + 1, out);
        if (out.length > 600) break;
      }
    } catch (_) { /* permission or transient errors → keep what we have */ }
    return out;
  },
  iconFor(name) {
    const ext = String(name).split('.').pop().toLowerCase();
    return { pdf: '📄', xlsx: '📊', xls: '📊', csv: '📊', docx: '📝', doc: '📝', txt: '📝', md: '📝',
             key: '🎞️', pptx: '🎞️', png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', fig: '🖼️',
             zip: '📦', mp3: '🎵', mp4: '🎬', js: '💻', ts: '💻', py: '🐍', json: '🔧' }[ext] || '📄';
  },
};

/* ======================== TYPO-TOLERANT ENTITIES ======================== */
function editDist(a, b) {
  a = a.toLowerCase(); b = b.toLowerCase();
  const m = a.length, n = b.length;
  if (!m) return n; if (!n) return m;
  if (a === b) return 0;
  // Damerau (OSA): + transposition so "Jhon"→john and "sraah"→sarah are 1 edit
  let d = Array.from({ length: m + 1 }, (_, i) => Array.from({ length: n + 1 }, (_, j) => i === 0 ? j : j === 0 ? i : 0));
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
      }
    }
  }
  return d[m][n];
}

/* ======================== SPEECH OUT ======================== */

const RATES = { slow: 0.85, normal: 1.05, fast: 1.3 };

function speak(text) {
  if (!state.sound || typeof window === 'undefined' || !('speechSynthesis' in window)) return;
  try {
    speechSynthesis.cancel();
    let say = String(text);
    if (settings.verbosity === 'brief') {
      const first = say.match(/^[^.!?]+[.!?]?/);
      if (first) say = first[0];
    }
    const u = new SpeechSynthesisUtterance(say);
    u.rate = RATES[settings.rate] || 1.05;
    if (settings.voice) {
      const v = speechSynthesis.getVoices().find(v => v.name === settings.voice);
      if (v) u.voice = v;
    } else {
      // match the UI language (nl voice for Dutch)
      const want = settings.lang === 'nl' ? 'nl' : 'en';
      const v = speechSynthesis.getVoices().find(v => v.lang.toLowerCase().startsWith(want));
      if (v) u.voice = v;
      u.lang = settings.lang === 'nl' ? 'nl-NL' : 'en-US';
    }
    speechSynthesis.speak(u);
  } catch (_) { /* no-op */ }
}

/* ======================== NOTCH ======================== */

const notch = $('#notch');
const notchBody = $('#notchBody');
let autoCloseTimer = null;

function setNotch(mode, html) {
  clearTimeout(autoCloseTimer);
  notch.className = 'notch ' + mode;
  notchBody.innerHTML = html || '';
}

function notchIdle() {
  setNotch('idle', `<div class="idle-row"><span class="idle-dot"></span><span class="idle-label">VoiceOS</span></div>`);
}

function notchListening(label) {
  setNotch('listening', `
    <div class="listen-row">
      <div class="wave"><i></i><i></i><i></i><i></i><i></i><i></i></div>
      <span>${esc(label || 'Listening…')}</span>
    </div>`);
}

function notchProcessing(label) {
  setNotch('processing', `<div class="proc-row"><div class="spinner"></div><span>${esc(label)}</span></div>`);
}

function cardShell(tag, title, inner) {
  return `
    <div class="card">
      <div class="card-head">
        <span>VoiceOS <span class="tag">· ${esc(tag)}</span></span>
        <button class="card-x" data-close>✕</button>
      </div>
      ${title ? `<div class="card-title">${title}</div>` : ''}
      ${inner}
    </div>`;
}

function showCard(tag, title, inner, opts = {}) {
  SFX.card();
  setNotch('card', cardShell(tag, title, inner));
  const x = notchBody.querySelector('[data-close]');
  if (x) x.addEventListener('click', () => { cancelPending(); notchIdle(); });
  if (opts.autoClose) {
    autoCloseTimer = setTimeout(() => { if (state.pending?.type !== 'confirm') notchIdle(); }, opts.autoClose);
  }
}

/* ---- card variants ---- */

function textCard(resp, autoClose = 3400) {
  showCard(resp.mode === 'agent' ? 'Agent' : titleCase(resp.mode), esc(resp.response),
    resp.card_data?.body ? `<div class="card-sub">${esc(resp.card_data.body)}</div>` : '',
    { autoClose });
}

function resultCard(result, sub) {
  showCard('Done', `<span class="ok">✓</span> ${esc(result)}`,
    sub ? `<div class="card-sub">${esc(sub)}</div>` : '', { autoClose: 3800 });
}

function confirmCard(resp, onConfirm) {
  const d = resp.card_data || {};
  const kvRows = (d.lines || []).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
  showCard('Confirm', esc(resp.confirmation_prompt || 'Proceed?'), `
    ${kvRows ? `<dl class="kv">${kvRows}</dl>` : ''}
    ${d.body ? `<div class="card-sub">${esc(d.body)}</div>` : ''}
    <div class="card-actions">
      <button class="btn primary" data-yes>${esc(d.confirmLabel || 'CONFIRM')}</button>
      <button class="btn danger-ghost" data-no>CANCEL</button>
    </div>`);
  notchBody.querySelector('[data-yes]').addEventListener('click', () => onConfirm());
  notchBody.querySelector('[data-no]').addEventListener('click', () => {
    state.pending = null;
    const r = makeResponse({ understood: 'Cancelled', mode: 'agent', confidence: 1,
      result: 'Cancelled', response: 'Cancelled. Nothing was sent.' });
    emit(r); textCard(r);
  });
}

function searchCard(resp, onPick) {
  const d = resp.card_data || {};
  const rows = (d.results || []).map((r, i) => `
    <div class="result-row" data-i="${i}">
      <div class="result-ico">${r.icon || '📄'}</div>
      <div><div class="result-name">${esc(r.name)}</div><div class="result-meta">${esc(r.meta || '')}</div></div>
      <span class="result-open">OPEN</span>
    </div>`).join('');
  const foot = d.demoNote ? `<div class="card-sub" style="margin-top:8px;opacity:.7">${esc(d.demoNote)}${
    d.canConnect ? ` <button class="btn mini" data-connect>${esc(T('Connect folder…', 'Map koppelen…'))}</button>` : ''
  }</div>` : '';
  showCard('Search', esc(resp.response), (rows || '<div class="card-sub">No matches.</div>') + foot, { autoClose: 12000 });
  $$('#notchBody .result-row').forEach(row => row.addEventListener('click', () => {
    onPick(d.results[+row.dataset.i]);
  }));
  const cb = notchBody.querySelector('[data-connect]');
  if (cb) cb.addEventListener('click', async () => {
    cb.textContent = T('Scanning…', 'Scannen…');
    const dir = await Bridge.pickFolder();
    if (!dir) { cb.textContent = T('Connect folder…', 'Map koppelen…'); return; }
    state.realFolderName = dir.name || 'folder';
    state.realFiles = await Bridge.scanFolder(dir);
    resultCard(T(`Connected ${state.realFolderName}`, `${state.realFolderName} gekoppeld`),
      T(`${state.realFiles.filter(f => f.kind === 'file').length} real files indexed — search again to see them`,
        `${state.realFiles.filter(f => f.kind === 'file').length} echte bestanden geïndexeerd — zoek opnieuw`));
  });
}

function optionsCard(resp, onPick) {
  const chips = (resp.options || []).map(o =>
    `<button class="opt-chip" data-v="${esc(o.label)}">${esc(o.label)}</button>`).join('');
  showCard('Clarify', esc(resp.response), `<div>${chips}</div>`);
  $$('#notchBody .opt-chip').forEach(c => c.addEventListener('click', () => onPick(c.dataset.v)));
}

function dictateCard(resp) {
  // typewriter effect — you SEE VoiceOS typing the cleaned text
  showCard('Dictation', 'Transcribed', `<div class="dictate-body"><span id="typeTarget"></span><span class="caret">▌</span></div>`, { autoClose: 6500 });
  const target = notchBody.querySelector('#typeTarget');
  const text = resp.card_data.text;
  const perChar = Math.max(6, Math.min(28, 900 / Math.max(text.length, 1))); // full text ≤ ~0.9s
  let i = 0;
  const tick = () => {
    if (!target || target.isConnected === false) return; // card closed
    target.textContent = text.slice(0, ++i);
    if (i < text.length) setTimeout(tick, perChar * (0.7 + Math.random() * 0.6));
    else { const c = notchBody.querySelector('.caret'); if (c) c.remove(); }
  };
  tick();
}

/* --- v1.1: multi-step workflow card with live checklist --- */
function workflowCard(resp, onDone) {
  const steps = resp.workflow_steps || [];
  const rows = s => (resp.workflow_steps || []).map(st => `
    <div class="wf-step ${st.state}" data-step="${st.step}">
      <span class="wf-ico">${st.state === 'done' ? '✓' : st.state === 'active' ? '◐' : '○'}</span>
      <span class="wf-label">${esc(st.label)}</span>
    </div>`).join('');

  showCard('Workflow', esc(resp.confirmation_prompt || resp.response), `
    <div class="wf-list">${rows()}</div>
    ${resp.requires_confirmation ? `
    <div class="card-actions">
      <button class="btn primary" data-yes>${esc(resp.card_data?.confirmLabel || 'RUN')}</button>
      <button class="btn danger-ghost" data-no>CANCEL</button>
    </div>` : ''}`);

  const doIt = () => {
    state.pending = null;
    // animate remaining steps completing, then execute
    const pendingSteps = resp.workflow_steps.filter(s => s.state !== 'done');
    pendingSteps.forEach((s, i) => {
      setTimeout(() => {
        s.state = 'done';
        const list = notchBody.querySelector('.wf-list');
        if (list) list.innerHTML = rows();
        if (i === pendingSteps.length - 1) {
          const r = exec(resp);
          const done = makeResponse({ ...resp, requires_confirmation: false, confirmation_prompt: null,
            result: r.result, response: 'Done.', _handled: true });
          emit(done);
          resultCard(r.result, r.sub || `${resp.parameters.file || ''} → ${resp.parameters.to}`);
          speak('Done.');
          return done;
        }
      }, 380 * (i + 1));
    });
  };

  if (resp.requires_confirmation) {
    state.pending = { type: 'confirm', resp, onConfirm: () => { const d = doIt(); return d || makeResponse({ ...resp, result: 'Done', _handled: true }); } };
    const yes = notchBody.querySelector('[data-yes]');
    const no = notchBody.querySelector('[data-no]');
    if (yes) yes.addEventListener('click', doIt);
    if (no) no.addEventListener('click', () => {
      state.pending = null;
      const r = makeResponse({ understood: 'Cancelled', mode: 'agent', confidence: 1,
        result: 'Cancelled', response: 'Cancelled. Nothing was sent.' });
      emit(r); textCard(r);
    });
  } else {
    setTimeout(doIt, 500);
  }
}

/* --- v1.1: briefing card --- */
function briefingCard(resp) {
  const d = resp.card_data || {};
  const kvRows = (d.lines || []).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
  showCard('Briefing · ' + esc(d.when || ''), `${esc(d.title || 'Briefing')}`,
    `<dl class="kv">${kvRows}</dl>`, { autoClose: 9000 });
}

/* ======================== RESPONSE FACTORY ======================== */

function makeResponse(p) {
  return Object.assign({
    understood: '', mode: 'unknown', action: null, confidence: 0.5,
    parameters: {}, requires_confirmation: false, confirmation_prompt: null,
    result: null, response: '', options: null,
    card_type: null, card_data: {},
    ui_state: { show_confirmation: false, highlight_app: null, notification: null },
  }, p);
}

/* ======================== PARSER ========================
   Speech → intent. Mirrors the intent taxonomy + actions
   from the VoiceOS spec. */

function parse(rawInput) {
  const t = ' ' + rawInput.toLowerCase().trim()
    .replace(/[“”]/g, '"').replace(/[’‘]/g, "'").replace(/\s+/g, ' ') + ' ';

  /* --- global cancel (EN + NL) --- */
  if (/^\s*(cancel|never ?mind|stop|forget it|nope|annuleer(?:en)?|laat maar|vergeet het|hoeft niet)\.?!?\s*$/i.test(rawInput)) {
    const had = !!state.pending;
    state.pending = null;
    return makeResponse({ understood: 'Cancel current action', mode: 'agent', action: 'cancel',
      confidence: .98, result: 'Cancelled',
      response: had ? T('Cancelled. What’s next?', 'Geannuleerd. Wat nu?') : T('Nothing to cancel.', 'Niets om te annuleren.') });
  }

  /* --- learning: "I meant Sarah, not Sara" / "ik bedoel Sarah, niet Sara" --- */
  const mCorr = t.match(/\b(?:actually,? |no,? )?i meant (\w+)(?:\s*,?\s*not\s+(\w+))?\b/)
             || t.match(/\bit'?s (\w+),?\s*not\s+(\w+)\b/)
             || t.match(/\bik bedoel (\w+)(?:\s*,?\s*niet\s+(\w+))?\b/);
  if (mCorr) {
    const meant = mCorr[1], wrong = mCorr[2];
    const target = CONTACTS[meant.toLowerCase()];
    if (target) {
      if (wrong) state.aliases[wrong.toLowerCase()] = meant.toLowerCase();
      state.aliases[meant.toLowerCase()] = meant.toLowerCase();
      persist();
      return makeResponse({
        understood: `Correction: “${wrong || meant}” means ${target.name}`,
        mode: 'agent', action: 'learn_alias', confidence: .95,
        parameters: { alias: wrong || meant, contact: target.name },
        result: 'Learned',
        response: T(`Got it — I’ll use ${target.name} from now on.`,
                    `Begrepen — ik gebruik voortaan ${target.name}.`),
        card_type: 'text',
        card_data: { body: wrong ? T(`“${titleCase(wrong)}” → ${target.name}, saved for next time.`,
                                     `“${titleCase(wrong)}” → ${target.name}, opgeslagen voor de volgende keer.`) : null },
      });
    }
  }

  /* --- pending confirmation? (EN + NL) --- */
  if (state.pending?.type === 'confirm') {
    if (/\b(yes|yeah|yep|sure|ok(ay)?|do it|send( it)?|confirm|go ahead|book it|ja|jazeker|doe het|ga door|stuur|verstuur|bevestig|oké|prima|doe maar)\b/.test(t)) {
      return state.pending.onConfirm(); // returns a handled response
    }
    if (/\b(no|nope|cancel|don'?t|stop|nee|nee hoor|annuleer|niet doen)\b/.test(t)) {
      state.pending = null;
      return makeResponse({ understood: 'Cancelled', mode: 'agent', confidence: 1,
        result: 'Cancelled',
        response: T('Cancelled. Nothing was sent.', 'Geannuleerd. Er is niets verstuurd.') });
    }
  }

  /* --- pending field collection? --- */
  if (state.pending?.type === 'collect') {
    const p = state.pending;
    const c = findContact(t);
    if (p.field === 'recipient' && c) {
      state.pending = null;
      p.params.contact = c;
      return buildAction(p.action, p.params, p.raw);
    }
    if (p.field === 'body' || p.field === 'title') {
      state.pending = null;
      p.params[p.field] = rawInput.trim();
      return buildAction(p.action, p.params, p.raw);
    }
  }

  return routeFresh(rawInput, t);
}

function routeFresh(raw, t) {

  /* --- safety refusals (spec edge cases) --- */
  if (/\bpassword\b|\bwachtwoord\b/.test(t)) {
    return makeResponse({ understood: 'User asked to handle a password', mode: 'agent',
      action: null, confidence: .95,
      response: T('I can’t handle passwords. Do this manually.',
                  'Wachtwoorden kan ik niet afhandelen. Doe dit handmatig.'),
      ui_state: { notification: 'Sensitive request refused' } });
  }
  if ((/\bdelete (all|every)\b/.test(t) && /\b(email|file|photo|message)s?\b/.test(t))
      || (/\bverwijder (alles|alle)\b/.test(t) && /\b(e-?mails?|bestanden|foto'?s|berichten)\b/.test(t))) {
    return makeResponse({ understood: 'Mass-delete request', mode: 'agent', confidence: .93,
      response: T('That’s too risky. Use the app’s settings instead.',
                  'Dat is te riskant. Gebruik de instellingen van de app.') });
  }

  /* --- DAILY BRIEFING (multi-source workflow) — EN + NL --- */
  if (/\b(morning|daily) (briefing|routine)\b|\bstart my (day|morning)\b|\bbrief me\b/.test(t)
      || /\b(ochtend|dag)(briefing|overzicht|routine)\b|\bstart mijn (dag|ochtend)\b|\bbrief me\b/.test(t)) {
    return buildAction('daily_briefing', {}, raw);
  }

  /* --- WORKFLOW: send a file to a contact (spec's multi-step example) ---
     "Send John the latest project deck" / "Stuur John de nieuwste presentatie" */
  const FILE_NOUNS = '(deck|slides|presentat\\w*|spreadsheet|document\\w*|doc|rapport\\w*|invoice|factu\\w*|notes?|notities)';
  if (/\b(send|share|forward|stuur|stuur door|deel|verstuur)\b/.test(t)
      && new RegExp(`\\b(latest|newest|recent|the|nieuwste|laatste|recente|de)\\b.+${FILE_NOUNS}`).test(t)
      && findContact(t) && !/\b(?:send|stuur|verstuur)\s+(?:een\s+)?e-?mail\b/.test(t)) {
    const c = findContact(t);
    const noun = (t.match(new RegExp(FILE_NOUNS)) || [, 'file'])[1];
    return buildAction('send_file_workflow', { contact: c, noun }, raw);
  }

  /* --- TASKS — EN + NL --- */
  let mTask = raw.match(/\b(?:create|add|new)(?: a)? tasks?[:\s]+(.+)$/i)
           || raw.match(/^(?:to ?do)[:\s]+(.+)$/i)
           || raw.match(/\bput\s+(.+?)\s+on my (?:to ?do|task)(?: list)?\b/i)
           || raw.match(/\b(?:maak|voeg toe|voeg|nieuwe?)(?: een)?\s+(?:taak|taken)[:\s]+(.+)$/i)
           || raw.match(/\b(?:maak|voeg toe)\s+(.+?)\s+als taak\b/i)
           || raw.match(/^taak[:\s]+(.+)$/i);
  if (mTask) return buildAction('create_task', { title: mTask[1].trim() }, raw);
  if (/\b(?:show|what'?s on) my (?:tasks?|to ?do)(?: list)?\b|\btoon mijn taken\b|\bwat staat er op mijn taken\b/.test(t)) {
    return buildAction('list_tasks', {}, raw);
  }

  /* --- NOTES search — EN + NL --- */
  let mNotes = t.match(/\bsearch (?:my )?notes? (?:for|about)\s+(.+?)\s*$/)
            || t.match(/\bfind\s+(.+?)\s+in (?:my )?notes?\b/)
            || t.match(/\bzoek in (?:mijn )?notities naar\s+(.+?)\s*$/)
            || t.match(/\bzoek\s+(.+?)\s+in (?:mijn )?notities\b/);
  if (mNotes) return buildAction('search_notes', { query: mNotes[1] }, raw);

  /* --- REMINDER — EN + NL --- */
  let m = t.match(/\b(?:remind me to|remember to|set (?:a )?reminder(?: to| for)?|herinner me eraan(?: om)?|herinner me om|herinner me aan|onthoud om)\s+(.+?)\s*$/);
  if (m) {
    let task = m[1];
    const when = resolveDate(t);
    task = task.replace(/\b(tomorrow|today|tonight|next week|day after tomorrow|at \d{1,2}(:\d{2})?\s*(am|pm)?|on (next )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b/g, '')
               .replace(/\b(morgen|vandaag|vanavond|vanmiddag|overmorgen|volgende week|te)\b|\bom \d{1,2}(:\d{2})?\s*uur\b|\bom (next )?(maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag)\b/gi, '')
               .replace(/\s{2,}/g, ' ').trim();
    const heardName = findContact(t);
    return makeResponse({
      understood: `Reminder: ${task}`, mode: 'reminder', action: 'create_reminder',
      confidence: .92, parameters: { task, when: when.toISOString() },
      result: `Reminder set for ${fmtWhen(when)}`,
      response: heardName && Math.random() < .5
        ? T(`Reminder set to ${task}. Say “cancel” if wrong.`, `Herinnering gezet: ${task}. Zeg “annuleer” als het fout is.`)
        : T(`Reminder set for ${fmtDate(when)} at ${fmtTime(when)}.`,
            `Herinnering gezet voor ${fmtDate(when)} om ${fmtTime(when)}.`),
      card_type: 'event',
      card_data: { title: titleCase(task), when: fmtWhen(when), who: heardName?.name || null },
    });
  }

  /* --- DICTATION — EN + NL --- */
  m = raw.match(/^(?:take a note|note this|note that|write (?:this )?down|jot (?:this )?down|type this|dictate|maak een notitie|notitie|schrijf(?: dit)? op|noteer|typ dit|dicteer)[,:]?\s*(.*)$/i);
  if (m || /\badd to today'?s note\b|\bvoeg toe aan (?:de )?notitie\b/.test(t)) {
    const body = (m ? m[1] : raw.replace(/.*(?:today'?s note|notitie)[,:]?/i, '')).trim();
    if (!body) {
      state.pending = { type: 'collect', field: 'body', action: 'create_note', params: {}, raw };
      return makeResponse({ understood: 'Dictate a note (waiting for content)', mode: 'dictation',
        confidence: .8, response: T('Listening. What should I write?', 'Ik luister. Wat moet ik noteren?') });
    }
    return buildAction('create_note', { body }, raw);
  }

  /* --- CALENDAR: next meeting / availability — EN + NL --- */
  if (/\b(what'?s|whats|when'?s)\s+my next (meeting|event|call)\b|\bwat is mijn (volgende|eerstvolgende) (vergadering|afspraak|gesprek)\b/.test(t)) {
    return buildAction('find_next_meeting', {}, raw);
  }
  if (/\b(availability|available|free|beschikbaar|beschikbaarheid|vrij)\b/.test(t)) {
    let mAvail = t.match(/\bavailability\s+(?:for|of)\s+(\w+)\b/) || t.match(/\bbeschikbaarheid van\s+(\w+)\b/);
    if (!mAvail) mAvail = t.match(/\b(?:check\s+|is\s+|wanneer is\s+|when\s+is\s+)?(\w+?)(?:'s)?\s+(?:availability|free|available|beschikbaar|vrij)\b/);
    if (mAvail && !/^(check|is|my|the|your|wanneer|wie)$/.test(mAvail[1])) {
      const c = findContact(' ' + mAvail[1] + ' ');
      if (c) return buildAction('check_availability', { contact: c }, raw);
    }
  }

  /* --- CALENDAR: schedule — EN + NL --- */
  if (/\b(schedule|set up|book|arrange|plan|plant|maak)\b/.test(t) && /\b(meeting|call|sync|chat|coffee|lunch|vergadering|gesprek|afspraak)\b/.test(t)
      || /\bmeeting with \w+\b|\b(vergadering|gesprek|afspraak) met \w+\b/.test(t)) {
    const c = findContact(t);
    const when = resolveDate(t);
    const kind = (t.match(/\b(meeting|call|sync|coffee|lunch|vergadering|gesprek|afspraak)\b/) || [,'meeting'])[1];
    return buildAction('schedule_meeting', { contact: c, when, kind: KIND_EN[kind] || kind }, raw);
  }

  /* --- EMAIL search — EN + NL --- */
  if (/\b(search|find|look for|zoek|vind|vindt)\b/.test(t) && /\b(e-?mails?|mail|berichten)\b/.test(t)
      && /\b(e-?mail|mail)\b/.test(t)) {
    const q = (t.match(/\b(?:about|from|for|with|over|van|voor|met)\s+(.+?)\s*$/) || [,''])[1];
    return buildAction('search_emails', { query: q || '' }, raw);
  }

  /* --- EMAIL send — EN + NL --- */
  if (/\b(e-?mail|mail)\b/.test(t) && /\b(send|write|compose|draft|stuur|verstuur|schrijf)\b/.test(t)
      || /\b(send|stuur|verstuur) (\w+) een e-?mail\b/.test(t)) {
    const c = findContact(t);
    const about = (raw.match(/\b(?:about|over)\s+(.+?)(?:\s+saying|\s+met de mededeling|\s+at\s+\d|\s+om\s+\d|$)/i) || [,''])[1];
    return buildAction('send_email', { contact: c, subject: about ? titleCase(about.trim()) : null }, raw);
  }

  /* --- MESSAGE reply / check / send — EN + NL --- */
  m = t.match(/\breply to (\w+)(?:\s+(?:saying|with|that)\s+(.+?))?\s*$/)
      || t.match(/\b(?:beantwoord|antwoord)\s+(\w+)(?:\s+met\s+(.+?))?\s*$/);
  if (m && !/\b(email|mail)\b/.test(t)) {
    const c = findContact(' ' + m[1] + ' ');
    return buildAction('reply_message', { contact: c, body: m[2] || null }, raw);
  }
  m = t.match(/\b(?:check|show|read|toon|laat zien)\b.*\bmessages? from (\w+)\b/)
      || t.match(/\b(?:toon|laat)\s+berichten van\s+(\w+)\b/);
  if (m) {
    const c = findContact(' ' + m[1] + ' ');
    return buildAction('check_messages', { contact: c }, raw);
  }
  m = t.match(/\bsend (?:a )?(message|text)\b/) || t.match(/\bstuur (?:een )?(bericht|appje|sms)\b/) || t.match(/\bapp\s+\w+/);
  if (m) {
    const c = findContact(t);
    const bodyM = raw.match(/\b(?:saying|that|met de tekst|met)\s+(.+)$/i);
    if (!c) {
      state.pending = { type: 'collect', field: 'recipient', action: 'send_message',
        params: { body: bodyM ? bodyM[1] : null }, raw };
      return makeResponse({
        understood: 'Send a message — recipient missing', mode: 'agent', action: 'send_message',
        confidence: .55, response: T('To who?', 'Aan wie?'),
        options: [{ label: 'Maria' }, { label: 'Alex' }, { label: 'John' }],
        ui_state: { notification: 'Choose a recipient' },
      });
    }
    return buildAction('send_message', { contact: c, body: bodyM ? bodyM[1] : null }, raw);
  }

  /* --- APP CONTROL (before file search — "Open Notities" must win over "bestanden") --- */
  m = t.match(/\b(open|sluit|opent|close)\s+(\w+)\b/);
  if (m) {
    const resolved = resolveApp(m[2]);
    if (resolved) {
      const isClose = /^(sluit|close)$/.test(m[1]);
      return buildAction(isClose ? 'close_app' : 'open_app', { app: resolved }, raw);
    }
    if (/^(sluit|close)$/.test(m[1])) return buildAction('close_app', { app: titleCase(m[2]) }, raw);
    // "open X" where X is not an app → fall through to file search
  }

  /* --- FILES — EN + NL --- */
  if (/\b(find|locate|search for|look for|open|zoek|vind)\b/.test(t)
      && (/\b(file|files|document|doc|pdf|deck|slides|spreadsheet|folder|tax|taxes|invoice|return|returns|bestand|bestanden|document|presentatie|spreadsheet|map|factuur)\b|belasting\w*|aangifte/.test(t) || /\w+\.\w{2,4}\b/.test(t))) {
    let q = t.replace(/\b(find|locate|search for|look for|open|zoek|vind|my|mijn|the|de|het|een|last year'?s?|this year'?s?|vorig jaar|dit jaar|file|files|bestand|bestanden|please|alsjeblieft|me)\b/g, '')
             .replace(/\s{2,}/g, ' ').trim();
    if (/tax|belasting|aangifte/.test(t) && !/tax|belasting|aangifte/.test(q)) q = 'tax belasting aangifte';
    const openIt = /\bopen\b/.test(t);
    return buildAction(openIt ? 'open_file' : 'find_file', { query: q }, raw);
  }

  /* --- WEB / knowledge — EN + NL --- */
  m = t.match(/\b(?:search (?:the )?web(?: for)?|google|look up|what is|what'?s|who is|zoek (?:op )?(?:het )?(?:internet|web)(?: naar)?|wat is|wie is)\s+(.+?)\s*$/);
  if (m) return buildAction('search_web', { query: m[1] }, raw);

  /* --- catch-all generic search --- */
  m = t.match(/\b(?:find|search(?: for)?|look for|zoek|vind)\s+(.+?)\s*$/);
  if (m) return buildAction('find_file', { query: m[1] }, raw);

  /* --- UNCLEAR --- */
  return makeResponse({
    understood: `Heard: “${raw}”`, mode: 'unclear', action: null, confidence: .45,
    response: T('I didn’t catch that. Could you repeat?',
                'Ik heb dat niet helemaal verstaan. Kun je het herhalen?'),
    options: [{ label: T('Send an email', 'Stuur een e-mail') }, { label: T('Take a note', 'Maak een notitie') }, { label: T('Find a file', 'Zoek een bestand') }],
    card_type: null,
  });
}

/* ---------- action builders (intent → response JSON) ---------- */

function buildAction(action, params, raw) {
  switch (action) {

    case 'send_email': {
      if (!params.contact) {
        state.pending = { type: 'collect', field: 'recipient', action, params, raw };
        return makeResponse({ understood: 'Send email — recipient missing', mode: 'agent', action,
          confidence: .55, response: 'Email to who?',
          options: [{ label: 'John' }, { label: 'Sarah' }, { label: 'Maya' }] });
      }
      const subj = params.subject || 'Quick note';
      const body = settings.lang === 'nl'
        ? `Hoi ${params.contact.name},\n\nBetreft: ${subj.toLowerCase()} — hierbij de details.\n\n— Verstuurd met VoiceOS`
        : `Hi ${params.contact.name},\n\nRe: ${subj.toLowerCase()} — sending this over. Details inside.\n\n— Sent with VoiceOS`;
      const rc = shouldConfirm('send_email');
      return makeResponse({
        understood: `Send email to ${params.contact.name}${params.subject ? ' about ' + params.subject : ''}`,
        mode: 'agent', action, confidence: .93,
        parameters: { to: params.contact.email, subject: subj, body },
        requires_confirmation: rc,
        confirmation_prompt: rc ? T(`Send email to ${params.contact.email}?`,
                                    `E-mail versturen naar ${params.contact.email}?`) : null,
        response: rc ? T(`Email to ${params.contact.name}. Confirm?`,
                         `E-mail naar ${params.contact.name}. Bevestigen?`)
                     : T(`Sending email to ${params.contact.name}.`,
                         `E-mail naar ${params.contact.name} wordt verstuurd.`),
        card_type: 'email',
        card_data: { lines: [[LBL('to'), params.contact.email], [LBL('subject'), subj]], body, confirmLabel: LBL('send') },
        ui_state: { show_confirmation: rc, highlight_app: 'Mail' },
      });
    }

    case 'schedule_meeting': {
      if (!params.contact) {
        state.pending = { type: 'collect', field: 'recipient', action, params, raw };
        return makeResponse({ understood: `Schedule ${params.kind} — attendee missing`, mode: 'agent',
          action, confidence: .55, response: 'With who?',
          options: [{ label: 'Sarah' }, { label: 'John' }, { label: 'Maya' }] });
      }
      const title = settings.lang === 'nl'
        ? `${titleCase(params.kind)} met ${params.contact.name}`
        : `${titleCase(params.kind)} with ${params.contact.name}`;
      const rc = shouldConfirm('schedule_meeting');
      return makeResponse({
        understood: `Schedule ${params.kind} with ${params.contact.name} — ${fmtWhen(params.when)}`,
        mode: 'agent', action, confidence: .9,
        parameters: { title, attendee: params.contact.email, when: params.when.toISOString() },
        requires_confirmation: rc,
        confirmation_prompt: rc ? T(`Book ${params.kind} with ${params.contact.name}?`,
                                    `${titleCase(params.kind)} met ${params.contact.name} plannen?`) : null,
        response: rc ? T(`${fmtDate(params.when)} at ${fmtTime(params.when)}. Confirm?`,
                         `${fmtDate(params.when)} om ${fmtTime(params.when)}. Bevestigen?`)
                     : T(`Booking ${params.kind} with ${params.contact.name}.`,
                         `${titleCase(params.kind)} met ${params.contact.name} wordt gepland.`),
        card_type: 'event',
        card_data: { lines: [[LBL('what'), title], [LBL('when'), fmtWhen(params.when)], [LBL('with'), params.contact.email]], confirmLabel: LBL('book') },
        ui_state: { show_confirmation: rc, highlight_app: 'Calendar' },
      });
    }

    case 'find_next_meeting': {
      const next = store.events.filter(e => e.when > new Date()).sort((a, b) => a.when - b.when)[0];
      if (!next) return makeResponse({ understood: 'Next meeting', mode: 'agent', action, confidence: .95,
        response: T('Your calendar is clear. Enjoy the focus time.', 'Agenda is leeg. Geniet van de focustijd.') });
      return makeResponse({
        understood: 'Next meeting', mode: 'agent', action, confidence: .96,
        parameters: { title: next.title, when: next.when.toISOString() },
        result: next.title, response: T(`${next.title}, ${fmtWhen(next.when)}.`,
                                        `${next.title}, ${fmtWhen(next.when)}.`),
        card_type: 'event',
        card_data: { lines: [[LBL('what'), next.title], [LBL('when'), fmtWhen(next.when)], [T('Who', 'Wie'), (next.who || []).join(', ')]] },
        ui_state: { highlight_app: 'Calendar' },
      });
    }

    case 'check_availability': {
      return makeResponse({
        understood: `Check ${params.contact.name}’s availability`, mode: 'agent', action, confidence: .9,
        parameters: { person: params.contact.email },
        response: `${params.contact.name} is free Thursday after 2pm.`,
        card_type: 'text',
        card_data: { body: 'Free: Tue 10–12 · Wed all afternoon · Thu after 2pm' },
        ui_state: { highlight_app: 'Calendar' },
      });
    }

    case 'search_emails': {
      const q = (params.query || '').replace(/[^a-z ]/g, '').trim();
      const hits = store.emails.concat(store.sent).filter(e =>
        !q || (e.from + ' ' + e.subj + ' ' + e.body).toLowerCase().includes(q.split(' ')[0] || ''));
      return makeResponse({
        understood: `Search emails${q ? ': ' + q : ''}`, mode: 'search', action, confidence: .88,
        parameters: { query: q }, result: `${hits.length} match${hits.length === 1 ? '' : 'es'}`,
        response: hits.length ? `Found ${hits.length} email${hits.length === 1 ? '' : 's'}.` : 'No emails matched.',
        card_type: 'search_result',
        card_data: { resultApp: 'Mail', results: hits.map(e => ({ icon: '✉️', name: e.subj, meta: `${e.from} · ${e.when}` })) },
        ui_state: { highlight_app: 'Mail' },
      });
    }

    case 'send_message':
    case 'reply_message': {
      if (!params.contact) {
        state.pending = { type: 'collect', field: 'recipient', action, params, raw };
        return makeResponse({ understood: 'Message — recipient missing', mode: 'agent', action,
          confidence: .55, response: 'To who?',
          options: [{ label: 'Maria' }, { label: 'Alex' }, { label: 'John' }] });
      }
        if (!params.body) {
          state.pending = { type: 'collect', field: 'body', action, params, raw };
          const last = (store.threads[params.contact.key || params.contact.name.toLowerCase()] || []).slice(-1)[0];
          return makeResponse({
            understood: `Reply to ${params.contact.name} — waiting for message`, mode: 'agent', action,
            confidence: .85, parameters: { to: params.contact.name },
            response: T(`What should I tell ${params.contact.name}?`,
                        `Wat moet ik tegen ${params.contact.name} zeggen?`),
          card_type: 'text',
          card_data: { body: last ? T(`Last from ${params.contact.name}: “${last.text}”`,
                                      `Laatste van ${params.contact.name}: “${last.text}”`) : null },
          ui_state: { highlight_app: 'Messages' },
        });
      }
      const rc = shouldConfirm('send_message');
      return makeResponse({
        understood: `${action === 'reply_message' ? 'Reply to' : 'Message'} ${params.contact.name}: “${params.body}”`,
        mode: 'agent', action, confidence: .92,
        parameters: { to: params.contact.name, body: params.body },
        requires_confirmation: rc,
        confirmation_prompt: rc ? T(`Send message to ${params.contact.name}?`,
                                    `Bericht versturen naar ${params.contact.name}?`) : null,
        response: rc ? T(`Message to ${params.contact.name}. Confirm?`,
                         `Bericht aan ${params.contact.name}. Bevestigen?`)
                     : T(`Sent to ${params.contact.name}. Done.`,
                         `Verstuurd naar ${params.contact.name}. Klaar.`),
        result: `Sent to ${params.contact.name}`,
        card_type: rc ? 'text' : null,
        card_data: rc ? { lines: [[LBL('to'), params.contact.name], [T('Message', 'Bericht'), params.body]], confirmLabel: LBL('send') } : {},
        ui_state: { show_confirmation: rc, highlight_app: 'Messages' },
      });
    }

    case 'check_messages': {
      const key = params.contact ? (params.contact.key || params.contact.name.toLowerCase()) : null;
      const thread = key && store.threads[key];
      const last = thread ? thread.slice(-1)[0] : null;
      return makeResponse({
        understood: `Check messages from ${params.contact?.name || 'recent chats'}`,
        mode: 'agent', action, confidence: .88,
        parameters: { to: params.contact ? params.contact.name : null },
        response: last ? `Latest from ${params.contact.name}: “${last.text}”` : 'No messages found.',
        card_type: 'text',
        card_data: { body: last ? `${thread.length} messages in thread` : null },
        ui_state: { highlight_app: 'Messages' },
      });
    }

    case 'find_file':
    case 'open_file': {
      const q = (params.query || '').toLowerCase();
      const terms = q.split(/\s+/).filter(Boolean);
      const hits = FILES.filter(f => {
        const hay = (f.name + ' ' + f.tags).toLowerCase();
        return terms.length === 0 || terms.some(term => hay.includes(term));
      }).slice(0, 4);
      // real-disk search when a folder is connected
      const realHits = (state.realFiles || []).filter(f =>
        f.kind === 'file' && terms.some(term => f.name.toLowerCase().includes(term))).slice(0, 4);
      const results = [
        ...realHits.map(f => ({ icon: Bridge.iconFor(f.name), name: f.name, meta: '🖥 ' + f.path, real: true })),
        ...hits.filter(h => !realHits.some(rh => rh.name === h.name))
               .map(f => ({ icon: f.icon, name: f.name, meta: f.meta })),
      ];
      const total = results.length;
      const demoNote = state.realFiles.length ? '' : T('demo data — connect a folder to search real files', 'demodata — koppel een map voor echte bestanden');
      return makeResponse({
        understood: `Find file: ${params.query}`, mode: 'search', action, confidence: total ? .9 : .6,
        parameters: { query: params.query },
        result: total ? `${total} matches` : 'No matches',
        response: total
          ? (total > 1 ? T(`Found ${total} matches. Showing best first.`, `${total} gevonden. Beste eerst.`)
                       : T(`Found ${results[0].name}.`, `${results[0].name} gevonden.`))
          : T('Nothing matched. Try different words?', 'Niets gevonden. Andere woorden proberen?'),
        card_type: 'search_result',
        card_data: { query: params.query, resultApp: 'Files', results,
                     demoNote, canConnect: settings.bridge && Bridge.canRealFiles() },
        ui_state: { highlight_app: total ? 'Files' : null },
      });
    }

    case 'search_web': {
      const q = params.query;
      return makeResponse({
        understood: `Web search: ${q}`, mode: 'search', action, confidence: .85,
        parameters: { query: q },
        result: 'Web results',
        response: T(`Here’s what I found for “${q}”.`, `Dit vond ik voor “${q}”.`),
        card_type: 'search_result',
        card_data: { results: [
          { icon: '🌐', name: `${titleCase(q)} — Wikipedia`, meta: 'en.wikipedia.org' },
          { icon: '📰', name: `${titleCase(q)}: latest news`, meta: 'Top stories' },
          { icon: '🎬', name: `${titleCase(q)} — explainer video`, meta: 'youtube.com' },
        ] },
      });
    }

    /* ---- v1.1: multi-step workflow (spec: "Send John the latest project deck") ---- */
    case 'send_file_workflow': {
      const q = params.noun === 'deck' || params.noun === 'slides' ? 'deck' : params.noun;
      const hits = FILES.filter(f => (f.name + ' ' + f.tags).toLowerCase().includes(q));
      const hit = hits[0];
      if (!hit) {
        return makeResponse({
          understood: `Send latest ${params.noun} to ${params.contact.name} — no matching file`,
          mode: 'agent', action, confidence: .5,
          parameters: { query: params.noun },
          response: `I couldn't find a ${params.noun}. Which file?`,
          ui_state: { highlight_app: 'Files' },
        });
      }
      const rc = shouldConfirm('send_email');
      return makeResponse({
        understood: `Send latest ${params.noun} (${hit.name}) to ${params.contact.name}`,
        mode: 'agent', action, confidence: .9,
        parameters: { to: params.contact.email, file: hit.name,
          subject: `Latest ${params.noun}`, contactName: params.contact.name },
        workflow_steps: [
          { step: 1, action: 'find_file',     label: T(`Found ${hit.name}`, `${hit.name} gevonden`),               state: 'done' },
          { step: 2, action: 'compose_email', label: T(`Compose to ${params.contact.email}`, `Opstellen aan ${params.contact.email}`), state: 'active' },
          { step: 3, action: 'attach_file',   label: T(`Attach ${hit.name}`, `${hit.name} bijvoegen`),              state: 'pending' },
          { step: 4, action: 'send_email',    label: T('Send', 'Versturen'),                                          state: 'pending' },
        ],
        requires_confirmation: rc,
        confirmation_at_step: 2,
        confirmation_prompt: rc ? T(`Email ${hit.name} to ${params.contact.email}?`,
                                    `${hit.name} mailen naar ${params.contact.email}?`) : null,
        response: rc ? T(`Found ${hit.name}. Send to ${params.contact.name}?`,
                         `${hit.name} gevonden. Versturen naar ${params.contact.name}?`)
                     : T(`Sending ${hit.name} to ${params.contact.name}.`,
                         `${hit.name} wordt verstuurd naar ${params.contact.name}.`),
        card_type: 'workflow',
        card_data: { confirmLabel: 'SEND' },
        ui_state: { show_confirmation: rc, highlight_app: 'Mail' },
      });
    }

    /* ---- v1.1: morning briefing ---- */
    case 'daily_briefing': {
      const next = store.events.filter(e => e.when > new Date()).sort((a, b) => a.when - b.when)[0];
      const unread = store.emails.filter(e => e.unread);
      const open = store.tasks.filter(x => !x.done);
      const lines = [
        ...(next ? [[T('Next meeting', 'Volgende afspraak'), `${next.title} — ${fmtWhen(next.when)}`]] : [[T('Meetings', 'Afspraken'), T('Nothing on the calendar', 'Niets op de agenda')]]),
        [T('Mail', 'Mail'), unread.length
          ? T(`${unread.length} unread — latest: ${unread[0].from}, “${unread[0].subj}”`,
              `${unread.length} ongelezen — laatste: ${unread[0].from}, “${unread[0].subj}”`)
          : T('Inbox zero ✨', 'Inbox leeg ✨')],
        ...(store.reminders.length ? [[T('Reminders', 'Herinneringen'), store.reminders.map(r => r.task).join('; ')]] : []),
        [T('Tasks', 'Taken'), open.length
          ? T(`${open.length} open — top: ${open[0].title}`, `${open.length} open — bovenaan: ${open[0].title}`)
          : T('All tasks done 🎉', 'Alle taken af 🎉')],
      ];
      return makeResponse({
        understood: 'Morning briefing', mode: 'agent', action, confidence: .95,
        parameters: {},
        workflow: ['check_availability', 'find_next_meeting', 'search_emails', 'list_tasks'],
        result: 'Briefing ready',
        response: next
          ? T(`Here's your day: ${unread.length} unread, ${open.length} tasks. First up: ${next.title}.`,
              `Je dag op een rij: ${unread.length} ongelezen, ${open.length} taken. Als eerste: ${next.title}.`)
          : T(`Here's your day: ${unread.length} unread, ${open.length} tasks. Clear calendar.`,
              `Je dag op een rij: ${unread.length} ongelezen, ${open.length} taken. Agenda is leeg.`),
        card_type: 'briefing',
        card_data: { title: T('Your day at a glance', 'Je dag in één oogopslag'), lines, when: fmtDate(new Date()) },
        ui_state: { highlight_app: 'Calendar' },
      });
    }

    /* ---- v1.1: tasks & notes search ---- */
    case 'create_task': {
      const rc = shouldConfirm('create_task'); // only fires on 'always'
      return makeResponse({
        understood: `Create task: “${params.title}”`, mode: 'agent', action, confidence: .94,
        parameters: { title: titleCase(params.title) },
        requires_confirmation: rc,
        confirmation_prompt: rc ? T(`Create task “${titleCase(params.title)}”?`,
                                    `Taak “${titleCase(params.title)}” aanmaken?`) : null,
        result: 'Task added',
        response: T(`Added “${titleCase(params.title)}” to Tasks.`,
                    `“${titleCase(params.title)}” toegevoegd aan Taken.`),
        card_data: rc ? { lines: [[LBL('task'), titleCase(params.title)]], confirmLabel: LBL('add') } : {},
        ui_state: { show_confirmation: rc, highlight_app: 'Tasks' },
      });
    }

    case 'list_tasks': {
      const open = store.tasks.filter(x => !x.done);
      return makeResponse({
        understood: 'List open tasks', mode: 'agent', action, confidence: .95,
        parameters: {},
        result: `${open.length} open tasks`,
        response: open.length
          ? T(`${open.length} open. Top: ${open[0].title}.`, `${open.length} open. Bovenaan: ${open[0].title}.`)
          : T('All tasks done. Nice.', 'Alle taken af. Lekker.'),
        card_type: 'search_result',
        card_data: { resultApp: 'Tasks', results: open.map(x => ({ icon: '✅', name: x.title, meta: 'Task · open' })) },
        ui_state: { highlight_app: 'Tasks' },
      });
    }

    case 'search_notes': {
      const q = (params.query || '').toLowerCase();
      const hits = store.notes.filter(n => n.text.toLowerCase().includes(q));
      return makeResponse({
        understood: `Search notes: ${q}`, mode: 'search', action, confidence: .9,
        parameters: { query: q },
        result: hits.length ? `${hits.length} match${hits.length === 1 ? '' : 'es'}` : 'No matches',
        response: hits.length ? T(`Found ${hits.length} note${hits.length === 1 ? '' : 's'}.`,
                                  `${hits.length} notitie${hits.length === 1 ? '' : 's'} gevonden.`)
                              : T('No notes matched. Try different words?', 'Geen notities gevonden. Andere woorden?'),
        card_type: 'search_result',
        card_data: { resultApp: 'Notes', results: hits.map(n => ({ icon: '📝', name: n.text.slice(0, 60), meta: 'Note' })) },
        ui_state: { highlight_app: 'Notes' },
      });
    }

    case 'learn_alias': break; // handled in parse

    case 'create_note': {
      const clean = cleanDictation(params.body);
      return makeResponse({
        understood: `Dictate note: “${clean}”`, mode: 'dictation', action, confidence: .94,
        parameters: { content: clean },
        result: 'Added to Notes',
        response: T('Added to Notes. What’s next?', 'Toegevoegd aan Notities. Wat nu?'),
        card_type: 'text', card_data: { text: clean },
        ui_state: { highlight_app: 'Notes' },
      });
    }

    case 'create_reminder': break; // handled inline above

    case 'open_app': {
      const name = Object.keys(APPS).find(a => a.toLowerCase() === String(params.app).toLowerCase());
      if (!name) return makeResponse({
        understood: `Open ${params.app}`, mode: 'agent', action, confidence: .7,
        parameters: params,
        response: T(`${params.app} isn’t available here. Try Mail, Calendar, Messages, Notes, Files, Tasks.`,
                    `${params.app} is hier niet beschikbaar. Probeer Mail, Calendar, Messages, Notes, Files, Tasks.`),
      });
      return makeResponse({
        understood: `Open ${name}`, mode: 'agent', action, confidence: .97,
        parameters: { app: name }, result: 'Opened',
        response: T(`Opening ${name}.`, `${name} wordt geopend.`),
        ui_state: { highlight_app: name },
      });
    }

    case 'close_app': {
      const name = Object.keys(APPS).find(a => a.toLowerCase() === String(params.app).toLowerCase());
      return makeResponse({
        understood: `Close ${params.app}`, mode: 'agent', action, confidence: .9,
        parameters: { app: name || params.app },
        result: name ? 'Closed' : `${params.app} isn’t open`,
        response: name ? T(`Closing ${name}.`, `${name} wordt gesloten.`)
                       : T(`${params.app} isn’t running.`, `${params.app} draait niet.`),
        ui_state: { highlight_app: name || null },
      });
    }
  }
  return makeResponse({ understood: raw, mode: 'unclear', confidence: .3,
    response: 'I didn’t catch that. Could you repeat?' });
}

/* ---------- dictation cleanup: fillers (EN + NL), casing, punctuation ---------- */
function cleanDictation(s) {
  let out = ' ' + s.trim() + ' ';
  out = out.replace(/\b(um+|uh+|erm+|ah+|hmm|ehm*|eh)\b[,\s]*/gi, ' ');
  out = out.replace(/\byou know\b[,\s]*/gi, ' ');
  out = out.replace(/\bzeg maar\b[,\s]*/gi, ' ');
  out = out.replace(/\bweet je\b[,?]?\s*/gi, ' ');
  out = out.replace(/(,\s*)?\blike\b,\s*/gi, ', ');
  out = out.replace(/\s+/g, ' ').trim();
  out = out.replace(/(^\s*\w|[.!?]\s+\w)/g, c => c.toUpperCase());
  if (out && !/[.!?]$/.test(out)) out += '.';
  return out;
}

/* ======================== EXECUTOR ======================== */

const PERSIST_ACTIONS = new Set(['send_email', 'reply_email', 'schedule_meeting',
  'create_reminder', 'send_message', 'reply_message', 'create_note',
  'send_file_workflow', 'create_task', 'learn_alias']);

function exec(resp) {
  const out = execInner(resp);
  if (PERSIST_ACTIONS.has(resp.action)) persist();
  return out;
}

function execInner(resp) {
  const p = resp.parameters || {};
  switch (resp.action) {
    case 'send_email': {
      openApp('Mail', { compose: { to: p.to, subj: p.subject, body: p.body }, sent: true });
      store.sent.unshift({ from: 'me', to: p.to, subj: p.subject, body: p.body, when: 'Just now' });
      // real-bridge: hand the prefilled draft to the actual mail client
      if (settings.bridge && typeof window !== 'undefined' && window.open) {
        try { window.open(Bridge.mailto(p.to, p.subject, p.body), '_blank', 'noopener'); } catch (_) {}
      }
      return {
        result: `Email sent to ${CONTACTS_BY_EMAIL(p.to)?.name || p.to}`,
        sub: settings.bridge
          ? T('Prefilled draft opened in your mail app too.', 'Ingevuld concept ook geopend in je mail-app.')
          : undefined,
      };
    }
    case 'send_file_workflow': {
      const body = settings.lang === 'nl'
        ? `Hoi ${p.contactName},\n\nHierbij de nieuwste versie. Bestand bijgevoegd.\n\n📎 ${p.file}\n\n— Verstuurd met VoiceOS`
        : `Hi ${p.contactName},\n\nHere's the latest. File attached.\n\n📎 ${p.file}\n\n— Sent with VoiceOS`;
      openApp('Files', { highlight: p.file });
      openApp('Mail', { compose: { to: p.to, subj: p.subject, body }, sent: true });
      store.sent.unshift({ from: 'me', to: p.to, subj: p.subject, body, when: 'Just now' });
      if (settings.bridge && typeof window !== 'undefined' && window.open) {
        try { window.open(Bridge.mailto(p.to, p.subject, body), '_blank', 'noopener'); } catch (_) {}
      }
      return {
        result: `${p.file} sent to ${p.contactName}`,
        sub: `${p.to} · ` + (settings.bridge
          ? T('with attachment · draft in your mail app', 'met bijlage · concept in je mail-app')
          : T('with attachment', 'met bijlage')),
      };
    }
    case 'schedule_meeting': {
      store.events.push({ title: p.title, when: new Date(p.when), who: [CONTACTS_BY_EMAIL(p.attendee)?.name || p.attendee], fresh: true });
      openApp('Calendar');
      if (settings.bridge && typeof window !== 'undefined' && window.open) {
        try { window.open(Bridge.gcalEvent(p.title, p.when, p.attendee), '_blank', 'noopener'); } catch (_) {}
      }
      return {
        result: 'Meeting confirmed',
        sub: `${p.title} — ${fmtWhen(new Date(p.when))}` + (settings.bridge
          ? T(' · Google Calendar opened', ' · Google Agenda geopend') : ''),
      };
    }
    case 'create_task': {
      store.tasks.push({ title: p.title, done: false, fresh: true });
      openApp('Tasks');
      return { result: 'Task added', sub: p.title };
    }
    case 'list_tasks': openApp('Tasks'); return { result: resp.result };
    case 'daily_briefing': return { result: resp.result };
    case 'search_notes': return { result: resp.result }; // card handles Open → Notes
    case 'create_reminder': {
      store.reminders.push({ task: p.task, when: new Date(p.when) });
      return { result: 'Reminder set', sub: `${titleCase(p.task)} — ${fmtWhen(new Date(p.when))}` };
    }
    case 'send_message':
    case 'reply_message': {
      const key = p.to.toLowerCase();
      (store.threads[key] = store.threads[key] || []).push({ from: 'me', text: p.body });
      openApp('Messages', { thread: key });
      // real-bridge: text lands on the clipboard, ready to paste into any messenger
      if (settings.bridge) { try { Bridge.clipboard(p.body); } catch (_) {} }
      return {
        result: resp.result || `Sent to ${p.to}`,
        sub: settings.bridge ? T('Also on your clipboard — paste anywhere to really send.',
                                 'Ook op je klembord — plak overal om echt te versturen.') : undefined,
      };
    }
    case 'check_messages': openApp('Messages', { thread: p.to ? p.to.toLowerCase() : undefined }); return { result: 'Opened Messages' };
    case 'create_note': {
      store.notes.push({ text: p.content, fresh: true });
      openApp('Notes');
      return { result: 'Added to Notes' };
    }
    case 'open_app': openApp(p.app); return { result: `Opened ${p.app}` };
    case 'close_app': closeApp(p.app); return { result: `Closed ${p.app}` };
    case 'find_next_meeting': case 'check_availability': openApp('Calendar'); return { result: resp.result };
    case 'search_emails': openApp('Mail'); return { result: resp.result };
    case 'find_file': case 'open_file': return { result: resp.result }; // search card handles open
    default: return { result: resp.result };
  }
}

function CONTACTS_BY_EMAIL(email) {
  return Object.values(CONTACTS).find(c => c.email === email) || null;
}

/* ======================== FLOW ======================== */

function emit(resp) {
  $('#jsonView').textContent = JSON.stringify(resp, (k, v) =>
    typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v) ? v : v, 2);
}

function logTurn(user, resp) {
  state.history.push({ user, resp: resp.response, at: new Date() });
  persist();
  const list = $('#logList');
  const div = document.createElement('div');
  div.className = 'log-turn';
  div.innerHTML = `<div class="u">“${esc(user)}”</div><div class="a">→ ${esc(resp.response)}</div>`;
  list.prepend(div);
  while (list.children.length > 12) list.lastChild.remove();
}

/* Main entry: user utterance in → notch + OS reaction out */
function handleUtterance(text) {
  if (!text.trim()) return;
  SFX.listen();
  $('#hint').classList.add('hidden');
  notchListening(`“${text.length > 42 ? text.slice(0, 42) + '…' : text}”`);

  setTimeout(() => {
    SFX.work();
    notchProcessing('Working on it…');
    setTimeout(() => {
      const resp = parse(text);
      if (resp._handled) { logTurn(text, resp); return; } // confirm flow already rendered
      emit(resp);
      logTurn(text, resp);
      speak(resp.response);

      if (resp.ui_state?.highlight_app) glowDock(resp.ui_state.highlight_app);
      state.activeApp = resp.ui_state?.highlight_app || state.activeApp;

      /* ---- render by card type ---- */
      if (resp.card_type === 'workflow') { workflowCard(resp); return; }
      if (resp.card_type === 'briefing') { briefingCard(resp); exec(resp); return; }
      if (resp.requires_confirmation) {
        const doConfirm = () => {
          state.pending = null;
          SFX.send();
          const r = exec(resp);
          const done = makeResponse({ ...resp, requires_confirmation: false,
            confirmation_prompt: null, result: r.result,
            response: resp.action === 'send_email' ? 'Sent. Done.' : (r.result || 'Done.'),
            ui_state: { ...resp.ui_state, show_confirmation: false }, _handled: true });
          emit(done);
          resultCard(r.result, r.sub || resp.card_data?.lines?.map(l => `${l[0]}: ${l[1]}`).join('  ·  '));
          SFX.success();
          speak('Done.');
          return done;
        };
        state.pending = { type: 'confirm', resp, onConfirm: doConfirm };
        confirmCard(resp, doConfirm);
        return;
      }
      if (resp.options) { optionsCard(resp, v => handleUtterance(resolveOption(v, resp))); return; }
      if (resp.card_type === 'search_result' && resp.card_data?.results) {
        searchCard(resp, item => {
          const rf = item.real && state.realFiles.find(f => f.name === item.name);
          if (rf) {
            rf.handle.getFile().then(file => {
              const url = URL.createObjectURL(file);
              try { if (typeof window !== 'undefined' && window.open) window.open(url, '_blank'); } catch (_) {}
              setTimeout(() => { try { URL.revokeObjectURL(url); } catch (_) {} }, 30000);
              resultCard(T(`Opening ${file.name} from ${state.realFolderName}`,
                           `${file.name} openen uit ${state.realFolderName}`));
            }).catch(() => resultCard(T('Could not read that file.', 'Kon dat bestand niet lezen.')));
            openApp(resp.card_data?.resultApp || 'Files', { highlight: item.name });
            return;
          }
          openApp(resp.card_data?.resultApp || 'Files', { highlight: item.name });
          resultCard(`Opening ${item.name}`);
        });
        exec(resp);
        return;
      }
      if (resp.mode === 'dictation' && resp.card_data?.text) { exec(resp); dictateCard(resp); return; }
      if (resp.card_type === 'event' && resp.action !== 'create_reminder') {
        const inner = (resp.card_data.lines || []).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
        showCard(resp.result ? 'Result' : 'Card', `${resp.result ? '<span class="ok">✓</span> ' : ''}${esc(resp.response)}`,
          inner ? `<dl class="kv">${inner}</dl>` : '', { autoClose: 4200 });
        exec(resp);
        return;
      }
      if (resp.action === 'create_reminder') { exec(resp); resultCard(resp.result, titleCase(resp.parameters.task)); return; }
      if (state.pending?.type === 'collect' && resp.card_type === 'text') {
        // waiting for follow-up: show card, maybe open the app for context
        if (resp.ui_state?.highlight_app) { const c = resp.parameters.to; openApp(resp.ui_state.highlight_app, { thread: c?.toLowerCase?.() }); }
        textCard(resp, 8000);
        return;
      }
      if (resp.card_type === 'text') { textCard(resp); exec(resp); return; }

      const r = exec(resp);
      resultCard(resp.result || r?.result || 'Done');
    }, 480);
  }, 520);
}

function resolveOption(label, resp) {
  // map clarification chips back into natural follow-ups
  if (state.pending?.type === 'collect' && state.pending.field === 'recipient') return label;
  const map = { 'Send an email': 'send email', 'Take a note': 'take a note', 'Find a file': 'find file' };
  return map[label] || label;
}

/* ======================== WINDOWS (mini desktop) ======================== */

const winLayer = $('#windows');
let winZ = 10, winOffset = 0;

function openApp(name, opts = {}) {
  $('#hint').classList.add('hidden');
  let win = openWins[name];
  if (!win) {
    win = document.createElement('div');
    win.className = 'win';
    win.setAttribute('role', 'dialog');
    win.setAttribute('aria-label', name + ' window');
    const spots = { Mail: [60, 40], Calendar: [150, 90], Messages: [90, 120], Notes: [200, 60], Files: [120, 100], Tasks: [260, 110] };
    const [x, y] = spots[name] || [80 + winOffset, 60 + winOffset];
    win.style.left = x + 'px'; win.style.top = y + 'px';
    win.innerHTML = `
      <div class="win-bar">
        <span class="tl r" data-closewin></span><span class="tl y"></span><span class="tl g"></span>
        <span class="win-title">${APPS[name].icon} ${name}</span>
      </div>
      <div class="win-body"></div>`;
    winLayer.appendChild(win);
    win.querySelector('[data-closewin]').addEventListener('click', () => closeApp(name));
    win.addEventListener('pointerdown', () => { win.style.zIndex = ++winZ; }); // raise on click
    enableDrag(win);
    openWins[name] = win;
    winOffset = (winOffset + 24) % 96;
  }
  win.style.zIndex = ++winZ;
  win.classList.remove('flash'); void win.offsetWidth; win.classList.add('flash');
  state.activeApp = name;
  renderApp(name, opts);
  markDock();
  return win;
}

function closeApp(name) {
  const win = openWins[name];
  if (win) { win.remove(); delete openWins[name]; }
  if (state.activeApp === name) state.activeApp = null;
  markDock();
}

function enableDrag(win) {
  const bar = win.querySelector('.win-bar');
  bar.addEventListener('pointerdown', e => {
    if (e.target.matches('.tl')) return;
    const rect = win.getBoundingClientRect();
    const layerRect = winLayer.getBoundingClientRect();
    const dx = e.clientX - rect.left, dy = e.clientY - rect.top;
    win.style.zIndex = ++winZ;
    const move = ev => {
      win.style.left = Math.max(0, Math.min(ev.clientX - layerRect.left - dx, layerRect.width - 120)) + 'px';
      win.style.top  = Math.max(0, Math.min(ev.clientY - layerRect.top - dy, layerRect.height - 60)) + 'px';
    };
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });
}

/* --- per-app renderers --- */

const mailView = { compose: null, sentFlash: false };

function renderApp(name, opts = {}) {
  const win = openWins[name];
  if (!win) return;
  const body = win.querySelector('.win-body');
  if (name === 'Mail') {
    if (opts.compose !== undefined) mailView.compose = opts.compose;
    if (opts.sent) mailView.sentFlash = true;
    const all = [...store.sent.map(s => ({ ...s, from: `me → ${s.to}`, sent: true })), ...store.emails];
    body.innerHTML = `
      ${mailView.compose ? `
        <div class="compose">
          <div class="c-to">To: ${esc(mailView.compose.to)} ${mailView.sentFlash ? '<span class="badge-new">SENT</span>' : ''}</div>
          <div class="c-subj">${esc(mailView.compose.subj)}</div>
          <div class="c-body">${esc(mailView.compose.body)}</div>
        </div>` : ''}
      <div class="app-list">
        ${all.map(e => `
          <div class="app-row ${e.unread ? 'hl' : ''}">
            <span>✉️</span>
            <div class="grow"><div class="name">${esc(e.from)} — ${esc(e.subj)}</div>
            <div class="sub">${esc(e.body.slice(0, 72))}…</div></div>
            <span class="when">${esc(e.when)}</span>
          </div>`).join('')}
      </div>`;
  }
  if (name === 'Calendar') {
    const evs = [...store.events].sort((a, b) => a.when - b.when);
    body.innerHTML = `<div class="app-list">
      ${evs.map(e => `
        <div class="app-row ${e.fresh ? 'hl' : ''}">
          <span>📅</span>
          <div class="grow"><div class="name">${esc(e.title)} ${e.fresh ? '<span class="badge-new">NEW</span>' : ''}</div>
          <div class="sub">${esc((e.who || []).join(', '))}</div></div>
          <span class="when">${fmtWhen(e.when)}</span>
        </div>`).join('')}
    </div>`;
    store.events.forEach(e => e.fresh = false);
  }
  if (name === 'Messages') {
    const threadKey = opts.thread || state.lastThread || 'maya';
    state.lastThread = threadKey;
    const msgs = store.threads[threadKey] || [];
    body.innerHTML = `
      <div class="card-sub" style="margin-bottom:10px">${CONTACTS[threadKey]?.name || titleCase(threadKey)} · iMessage</div>
      <div class="chat">
        ${msgs.map(mm => `<div class="bubble ${mm.from}">${esc(mm.text)}</div>`).join('')}
      </div>`;
    body.scrollTop = body.scrollHeight;
  }
  if (name === 'Notes') {
    body.innerHTML = `
      <div class="card-sub" style="margin-bottom:8px">Today’s note</div>
      ${store.notes.map(n => `<div class="note-line ${n.fresh ? 'new' : ''}">• ${esc(n.text)}</div>`).join('')}`;
    store.notes.forEach(n => n.fresh = false);
  }
  if (name === 'Files') {
    const realRows = state.realFiles.filter(f => f.kind === 'file').slice(0, 40);
    body.innerHTML = `
      ${Bridge.canRealFiles() ? `
        <div class="real-bar">
          <span>${state.realFolderName
            ? T(`🖥 Connected: ${esc(state.realFolderName)}`, `🖥 Gekoppeld: ${esc(state.realFolderName)}`)
            : T('🖥 Search your real files', '🖥 Zoek in je echte bestanden')}</span>
          <button class="btn mini" data-connect>${state.realFolderName ? T('Rescan', 'Opnieuw scannen') : T('Connect folder', 'Map koppelen')}</button>
        </div>` : ''}
      <div class="app-list">
      ${realRows.map(f => `
        <div class="app-row ${opts.highlight === f.name ? 'hl' : ''}">
          <span>${Bridge.iconFor(f.name)}</span>
          <div class="grow"><div class="name">${esc(f.name)}</div><div class="sub">🖥 ${esc(f.path)}</div></div>
          ${opts.highlight === f.name ? '<span class="badge-new">FOUND</span>' : ''}
        </div>`).join('')}
      ${FILES.filter(f => !realRows.some(r => r.name === f.name)).map(f => `
        <div class="app-row ${opts.highlight === f.name ? 'hl' : ''}">
          <span>${f.icon}</span>
          <div class="grow"><div class="name">${esc(f.name)}</div><div class="sub">${esc(f.meta)}</div></div>
          ${opts.highlight === f.name ? '<span class="badge-new">FOUND</span>' : ''}
        </div>`).join('')}
    </div>`;
    const connectBtn = body.querySelector('[data-connect]');
    if (connectBtn) connectBtn.addEventListener('click', async () => {
      connectBtn.textContent = T('Scanning…', 'Scannen…');
      const dir = await Bridge.pickFolder();
      if (!dir) { connectBtn.textContent = T('Connect folder', 'Map koppelen'); return; }
      state.realFolderName = dir.name || 'folder';
      state.realFiles = await Bridge.scanFolder(dir);
      renderApp('Files', opts);
      resultCard(T(`Connected ${state.realFolderName}`, `${state.realFolderName} gekoppeld`),
        T(`${state.realFiles.filter(f => f.kind === 'file').length} real files indexed`,
          `${state.realFiles.filter(f => f.kind === 'file').length} echte bestanden geïndexeerd`));
    });
  }
  if (name === 'Tasks') {
    body.innerHTML = `<div class="app-list">
      ${store.tasks.map(x => `
        <div class="app-row ${x.fresh ? 'hl' : ''}">
          <span>${x.done ? '✅' : '⬜'}</span>
          <div class="grow">
            <div class="name" ${x.done ? 'style="opacity:.45;text-decoration:line-through"' : ''}>${esc(x.title)}</div>
            <div class="sub">${x.done ? 'Done' : 'Open'}</div>
          </div>
          ${x.fresh ? '<span class="badge-new">NEW</span>' : ''}
        </div>`).join('')}
    </div>`;
    store.tasks.forEach(x => x.fresh = false);
  }
}

/* --- dock --- */

const dock = $('#dock');
function buildDock() {
  dock.innerHTML = Object.entries(APPS).map(([name, a]) => `
    <div class="dock-item" data-app="${name}" role="button" tabindex="0" aria-label="Open ${name}">
      ${a.icon}<span class="tip">${name}</span><span class="dot"></span>
    </div>`).join('');
  $$('.dock-item').forEach(d => {
    const toggle = () => { openWins[d.dataset.app] ? closeApp(d.dataset.app) : openApp(d.dataset.app); };
    d.addEventListener('click', toggle);
    d.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
  });
}
function markDock() {
  $$('.dock-item').forEach(d => d.classList.toggle('open', !!openWins[d.dataset.app]));
}
function glowDock(name) {
  const d = $(`.dock-item[data-app="${name}"]`);
  if (!d) return;
  d.classList.add('glow');
  setTimeout(() => d.classList.remove('glow'), 2200);
}

function cancelPending() { state.pending = null; }

/* ======================== INPUT PLUMBING ======================== */

const input = $('#utterance');

function submit(text) {
  const v = (text ?? input.value).trim();
  if (!v) return;
  input.value = '';
  handleUtterance(v);
}

$('#sendBtn').addEventListener('click', () => submit());
input.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
document.addEventListener('keydown', e => {
  if (e.ctrlKey && e.code === 'Space') { e.preventDefault(); input.focus(); micStart(); }
  if (e.key === 'Escape') {
    $('#helpModal').classList.remove('show');
    $('#settingsPanel').classList.remove('visible');
    if (notch.classList.contains('card')) { cancelPending(); notchIdle(); }
  }
});

/* rotating placeholder — shows a different example command every few seconds */
let phIndex = 0;
setInterval(() => {
  if (typeof document !== 'undefined' && document.activeElement !== input && !input.value) {
    const chips = getChips();
    const prefix = settings.lang === 'nl' ? 'Zeg het één keer… bijv.' : 'Say it once… e.g.';
    input.placeholder = `${prefix} “${chips[phIndex++ % chips.length]}”`;
  }
}, 4500);

/* suggestion chips — language-driven; re-rendered when the UI language changes */
function getChips() { return UI().chips; }
function renderChips() {
  $('#chips').innerHTML = getChips().map(c => `<button class="chip">${esc(c)}</button>`).join('');
  $$('#chips .chip').forEach(c => c.addEventListener('click', () => submit(c.textContent)));
}
renderChips();

/* re-render all language-facing UI when the language changes */
function applyLanguage() {
  renderChips();
  const ui = UI();
  const inputEl = $('#utterance');
  if (inputEl && !inputEl.value) inputEl.placeholder = ui.inputPlaceholder;
  const ht = $('.hint-title'); if (ht) ht.textContent = ui.hintTitle;
  const hs = $('.hint-sub');  if (hs) hs.textContent = '';
  if (hs) hs.innerHTML = esc(ui.hintSub);
  const ch = $('.composer-hint'); if (ch) ch.textContent = ui.composerHint;
  const ls = $('#logPanel .panel-title'); if (ls) ls.textContent = ui.panelSession;
  const jp = $('#jsonPanel .panel-title'); if (jp) jp.innerHTML = esc(ui.panelJson) + ' <span class="panel-note">' + esc(ui.panelJsonNote) + '</span>';
}

/* --- real mic via Web Speech API, text fallback always available --- */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
function micStart() {
  if (!SR) { notchProcessing('Mic not supported here — type instead'); setTimeout(notchIdle, 1800); return; }
  if (state.listening) { state.recognition.stop(); return; }
  const rec = new SR();
  state.recognition = rec;
  rec.lang = settings.lang === 'nl' ? 'nl-NL' : 'en-US';
  rec.interimResults = false; rec.maxAlternatives = 1;
  rec.onstart = () => { state.listening = true; $('#micBtn').classList.add('rec'); notchListening('Listening… speak now'); };
  rec.onend = () => { state.listening = false; $('#micBtn').classList.remove('rec'); };
  rec.onerror = () => { state.listening = false; $('#micBtn').classList.remove('rec');
    setNotch('processing', `<div class="proc-row"><span>Mic unavailable — type your command below</span></div>`);
    setTimeout(notchIdle, 2200); };
  rec.onresult = e => { const text = e.results[0][0].transcript; if (text) handleUtterance(text); };
  try { rec.start(); } catch (_) { /* already started */ }
}
$('#micBtn').addEventListener('click', micStart);

/* --- menu bar extras --- */
$('#soundToggle').addEventListener('click', e => {
  state.sound = !state.sound;
  e.target.textContent = state.sound ? '🔊' : '🔇';
  e.target.classList.toggle('off', !state.sound);
  if (!state.sound && 'speechSynthesis' in window) speechSynthesis.cancel();
});
$('#jsonToggle').addEventListener('click', () => $('#jsonPanel').classList.toggle('visible'));

function tickClock() {
  const d = new Date();
  const loc = (settings && settings.lang === 'nl') ? 'nl-NL' : 'en-US';
  $('#clock').textContent = d.toLocaleDateString(loc, { weekday: 'short', month: 'short', day: 'numeric' }) +
    '  ' + d.toLocaleTimeString(loc, { hour: 'numeric', minute: '2-digit' });
}
setInterval(tickClock, 1000); tickClock();

/* ======================== v1.0 INIT: settings, onboarding, PWA ======================== */

function hasVoices() {
  return typeof window !== 'undefined' && 'speechSynthesis' in window &&
         speechSynthesis.getVoices().length > 0;
}

function populateVoices(sel) {
  try {
    const wantLang = settings.lang === 'nl' ? 'nl' : 'en';
    let voices = speechSynthesis.getVoices().filter(v => v.lang.toLowerCase().startsWith(wantLang));
    if (!voices.length) voices = speechSynthesis.getVoices().filter(v => v.lang.startsWith('en')); // graceful fallback
    if (!voices.length) { sel.parentElement.style.display = 'none'; return; }
    sel.parentElement.style.display = '';
    sel.innerHTML = '<option value="">System default</option>' +
      voices.map(v => `<option value="${esc(v.name)}" ${v.name === settings.voice ? 'selected' : ''}>${esc(v.name)}</option>`).join('');
  } catch (_) { sel.parentElement.style.display = 'none'; }
}

function applySettingsToUI() {
  const rv = $('#setRate');      if (rv) rv.value = settings.rate;
  const cf = $('#setConfirm');   if (cf) cf.value = settings.confirmLevel;
  const vb = $('#setVerbose');   if (vb) vb.value = settings.verbosity;
  const sv = $('#setVoice');     if (sv) sv.value = settings.voice || '';
  const br = $('#setBridge');    if (br) br.checked = settings.bridge !== false;
  const lg = $('#setLang');      if (lg) lg.value = settings.lang || 'en';
  const obr = document.querySelector(`input[name="obrate"][value="${settings.rate}"]`);
  const obc = document.querySelector(`input[name="obconfirm"][value="${settings.confirmLevel}"]`);
  const obl = document.querySelector(`input[name="oblang"][value="${settings.lang}"]`);
  if (obr) obr.checked = true;
  if (obc) obc.checked = true;
  if (obl) obl.checked = true;
  applyLanguage();
}

function initProduct() {
  loadSettings();
  loadPersisted();

  /* --- settings drawer --- */
  $('#settingsBtn').addEventListener('click', () => $('#settingsPanel').classList.toggle('visible'));
  $('#setRate').addEventListener('change',    e => { settings.rate = e.target.value; saveSettings(); });
  $('#setConfirm').addEventListener('change', e => { settings.confirmLevel = e.target.value; saveSettings(); });
  $('#setVerbose').addEventListener('change', e => { settings.verbosity = e.target.value; saveSettings(); });
  $('#setBridge').addEventListener('change', e => {
    settings.bridge = e.target.checked; saveSettings();
    resultCard(settings.bridge
      ? T('Real app bridge on — drafts, calendars & files hand off to your real apps.', 'Echte-app-koppeling aan — concepten, agenda en bestanden gaan naar je echte apps.')
      : T('Bridge off — VoiceOS stays fully simulated.', 'Koppeling uit — VoiceOS blijft volledig gesimuleerd.'));
  });
  $('#setVoice').addEventListener('change',   e => { settings.voice = e.target.value || null; saveSettings(); });
  $('#setLang').addEventListener('change',    e => {
    settings.lang = e.target.value; settings.voice = null; saveSettings();
    applyLanguage();
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      populateVoices($('#obVoice')); populateVoices($('#setVoice'));
    }
    resultCard(settings.lang === 'nl' ? 'Taal gewijzigd naar Nederlands' : 'Language switched to English');
  });
  $('#setReset').addEventListener('click', () => {
    wipeLocal(); settings = { ...SETTING_DEFAULTS };
    $('#settingsPanel').classList.remove('visible');
    $('#onboarding').classList.add('show');
  });
  $('#setWipe').addEventListener('click', () => {
    wipeLocal();
    if (typeof location !== 'undefined') location.reload();
  });

  /* --- help modal --- */
  $('#helpBtn').addEventListener('click', () => $('#helpModal').classList.add('show'));
  $('#helpClose').addEventListener('click', () => $('#helpModal').classList.remove('show'));
  $('#helpModal').addEventListener('click', e => { if (e.target.id === 'helpModal') e.target.classList.remove('show'); });

  /* --- onboarding: first run only --- */
  const firstRun = !lsOK() || !localStorage.getItem(LS_KEYS.settings);
  if (firstRun) $('#onboarding').classList.add('show');
  $('#obStart').addEventListener('click', () => {
    settings.rate = (document.querySelector('input[name="obrate"]:checked') || {}).value || 'normal';
    settings.confirmLevel = (document.querySelector('input[name="obconfirm"]:checked') || {}).value || 'sometimes';
    settings.lang = (document.querySelector('input[name="oblang"]:checked') || {}).value || settings.lang || 'en';
    settings.voice = $('#obVoice').value || null;
    saveSettings();
    applyLanguage();
    $('#onboarding').classList.remove('show');
    speak(T('Welcome to VoiceOS.', 'Welkom bij VoiceOS.'));
    resultCard(UI().welcomeTitle, UI().welcomeSub);
  });

  /* --- voices (async in some browsers) --- */
  if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
    const fill = () => { populateVoices($('#obVoice')); populateVoices($('#setVoice')); };
    fill();
    speechSynthesis.onvoiceschanged = fill;
  } else {
    const f = $('#obVoiceField'); if (f) f.style.display = 'none';
  }

  /* --- PWA: service worker (offline) + install prompt --- */
  if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  }
  let deferredInstall = null;
  window.addEventListener('beforeinstallprompt', e => {
    e.preventDefault();
    deferredInstall = e;
    $('#installBtn').style.display = '';
  });
  $('#installBtn').addEventListener('click', async () => {
    if (!deferredInstall) return;
    deferredInstall.prompt();
    try { await deferredInstall.userChoice; } catch (_) {}
    deferredInstall = null;
    $('#installBtn').style.display = 'none';
  });

  applySettingsToUI();
}

initProduct();

buildDock();
markDock();
input.focus();
