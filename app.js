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
  { icon: '📄', name: 'tax_return_2025.pdf',  meta: 'Documents · Taxes · 2.4 MB',  tags: 'tax return taxes irs finance' },
  { icon: '📄', name: 'tax_return_2024.pdf',  meta: 'Documents · Taxes · 2.1 MB',  tags: 'tax return taxes irs finance' },
  { icon: '📊', name: 'tax_summary_2025.xlsx', meta: 'Documents · Taxes · 812 KB', tags: 'tax summary taxes spreadsheet finance' },
  { icon: '🎞️', name: 'project_deck_v7.key',  meta: 'Desktop · Modified yesterday', tags: 'project deck slides presentation keynote' },
  { icon: '📝', name: 'Q3_roadmap.docx',      meta: 'Drive · Strategy',            tags: 'roadmap strategy doc document q3' },
  { icon: '🖼️', name: 'brand_mockups.fig',    meta: 'Design · Shared with Maya',   tags: 'brand mockups design figma' },
  { icon: '📦', name: 'invoice_sept.pdf',     meta: 'Downloads · 340 KB',          tags: 'invoice billing finance pdf' },
];

const APPS = {
  Mail:     { icon: '✉️',  name: 'Mail' },
  Calendar: { icon: '📅', name: 'Calendar' },
  Messages: { icon: '💬', name: 'Messages' },
  Notes:    { icon: '📝', name: 'Notes' },
  Files:    { icon: '📁', name: 'Files' },
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
    { text: 'Idea: notch UI should pulse while listening.', fresh: false },
  ],
  reminders: [],
};

/* ======================== STATE ======================== */

const state = {
  activeApp: null,          // currently focused app (context awareness)
  pending: null,            // {type:'confirm',resp,onConfirm} | {type:'collect',field,action,params,prompt}
  sound: true,
  recognition: null,
  listening: false,
  history: [],              // recent commands (context)
};
const openWins = {};        // appName -> win element

/* ======================== SETTINGS & PERSISTENCE ======================== */

const LS_KEYS = { settings: 'voiceos_settings_v1', store: 'voiceos_store_v1' };
function lsOK() { try { return typeof localStorage !== 'undefined'; } catch (_) { return false; } }

const SETTING_DEFAULTS = { voice: null, rate: 'normal', confirmLevel: 'sometimes', verbosity: 'normal' };
let settings = { ...SETTING_DEFAULTS };

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
    sent: store.sent, threads: store.threads, history: state.history.slice(-30),
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

function fmtDate(d) {
  return d.toLocaleDateString('en-US', { weekday: 'short' }) + ', ' +
         d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
function fmtTime(d) {
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}
function fmtWhen(d) { return fmtDate(d) + ' · ' + fmtTime(d); }

const DAYS = ['sunday','monday','tuesday','wednesday','thursday','friday','saturday'];

function resolveDate(t) {
  const d = new Date();
  const dayMatch = t.match(/\b(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/);
  if (/day after tomorrow/.test(t)) { d.setDate(d.getDate() + 2); }
  else if (/tomorrow/.test(t)) { d.setDate(d.getDate() + 1); }
  else if (/next week/.test(t)) {
    const delta = ((1 - d.getDay()) + 7) % 7 || 7; // next Monday
    d.setDate(d.getDate() + delta);
  }
  else if (dayMatch) {
    const target = DAYS.indexOf(dayMatch[2]);
    let delta = (target - d.getDay() + 7) % 7;
    if (dayMatch[1] && delta === 0) delta = 7;
    if (!dayMatch[1] && delta === 0) delta = 0; // same-day weekday = today
    d.setDate(d.getDate() + delta);
  }
  d.setHours(9, 0, 0, 0);
  const tm = t.match(/\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b/);
  if (tm) {
    let h = parseInt(tm[1], 10) % 12;
    if (tm[3] === 'pm') h += 12;
    d.setHours(h, parseInt(tm[2] || '0', 10), 0, 0);
  } else if (/noon/.test(t)) d.setHours(12, 0, 0, 0);
  else if (/tonight|evening/.test(t)) d.setHours(19, 0, 0, 0);
  else if (/afternoon/.test(t)) d.setHours(14, 0, 0, 0);
  return d;
}

function findContact(t) {
  for (const key of Object.keys(CONTACTS)) {
    if (new RegExp('\\b' + key + '\\b', 'i').test(t)) return { key, ...CONTACTS[key] };
  }
  return null;
}

function titleCase(s) { return s.replace(/\b\w/g, c => c.toUpperCase()); }

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
  showCard('Search', esc(resp.response), rows || '<div class="card-sub">No matches.</div>', { autoClose: 12000 });
  $$('#notchBody .result-row').forEach(row => row.addEventListener('click', () => {
    onPick(d.results[+row.dataset.i]);
  }));
}

function optionsCard(resp, onPick) {
  const chips = (resp.options || []).map(o =>
    `<button class="opt-chip" data-v="${esc(o.label)}">${esc(o.label)}</button>`).join('');
  showCard('Clarify', esc(resp.response), `<div>${chips}</div>`);
  $$('#notchBody .opt-chip').forEach(c => c.addEventListener('click', () => onPick(c.dataset.v)));
}

function dictateCard(resp) {
  showCard('Dictation', 'Transcribed', `<div class="dictate-body">${esc(resp.card_data.text)}</div>`, { autoClose: 4500 });
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

  /* --- global cancel --- */
  if (/^\s*(cancel|never ?mind|stop|forget it|nope)\.?!?\s*$/i.test(rawInput)) {
    const had = !!state.pending;
    state.pending = null;
    return makeResponse({ understood: 'Cancel current action', mode: 'agent', action: 'cancel',
      confidence: .98, result: 'Cancelled', response: had ? 'Cancelled. What’s next?' : 'Nothing to cancel.' });
  }

  /* --- pending confirmation? --- */
  if (state.pending?.type === 'confirm') {
    if (/\b(yes|yeah|yep|sure|ok(ay)?|do it|send( it)?|confirm|go ahead|book it)\b/.test(t)) {
      return state.pending.onConfirm(); // returns a handled response
    }
    if (/\b(no|nope|cancel|don'?t|stop)\b/.test(t)) {
      state.pending = null;
      return makeResponse({ understood: 'Cancelled', mode: 'agent', confidence: 1,
        result: 'Cancelled', response: 'Cancelled. Nothing was sent.' });
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
  if (/\bpassword\b/.test(t)) {
    return makeResponse({ understood: 'User asked to handle a password', mode: 'agent',
      action: null, confidence: .95,
      response: 'I can’t handle passwords. Do this manually.',
      ui_state: { notification: 'Sensitive request refused' } });
  }
  if (/\bdelete (all|every)\b/.test(t) && /\b(email|file|photo|message)s?\b/.test(t)) {
    return makeResponse({ understood: 'Mass-delete request', mode: 'agent', confidence: .93,
      response: 'That’s too risky. Use the app’s settings instead.' });
  }

  /* --- REMINDER --- */
  let m = t.match(/\b(?:remind me to|remember to|set (?:a )?reminder(?: to| for)?)\s+(.+?)\s*$/);
  if (m) {
    let task = m[1];
    const when = resolveDate(t);
    task = task.replace(/\b(tomorrow|today|tonight|next week|day after tomorrow|at \d{1,2}(:\d{2})?\s*(am|pm)?|on (next )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b/g, '').trim();
    const heardName = findContact(t);
    return makeResponse({
      understood: `Reminder: ${task}`, mode: 'reminder', action: 'create_reminder',
      confidence: .92, parameters: { task, when: when.toISOString() },
      result: `Reminder set for ${fmtWhen(when)}`,
      response: heardName && Math.random() < .5
        ? `Reminder set to ${task}. Say “cancel” if wrong.`
        : `Reminder set for ${fmtDate(when)} at ${fmtTime(when)}.`,
      card_type: 'event',
      card_data: { title: titleCase(task), when: fmtWhen(when), who: heardName?.name || null },
    });
  }

  /* --- DICTATION --- */
  m = raw.match(/^(?:take a note|note this|note that|write (?:this )?down|jot (?:this )?down|type this|dictate)[,:]?\s*(.*)$/i);
  if (m || /\badd to today'?s note\b/.test(t)) {
    const body = (m ? m[1] : raw.replace(/.*today'?s note[,:]?/i, '')).trim();
    if (!body) {
      state.pending = { type: 'collect', field: 'body', action: 'create_note', params: {}, raw };
      return makeResponse({ understood: 'Dictate a note (waiting for content)', mode: 'dictation',
        confidence: .8, response: 'Listening. What should I write?' });
    }
    return buildAction('create_note', { body }, raw);
  }

  /* --- CALENDAR: next meeting / availability --- */
  if (/\b(what'?s|whats|when'?s)\s+my next (meeting|event|call)\b/.test(t)) {
    return buildAction('find_next_meeting', {}, raw);
  }
  /* --- CALENDAR: availability --- */
  if (/\b(availability|available|free)\b/.test(t)) {
    let mAvail = t.match(/\bavailability\s+(?:for|of)\s+(\w+)\b/);
    if (!mAvail) mAvail = t.match(/\b(?:check\s+|is\s+|when\s+is\s+)?(\w+?)(?:'s)?\s+(?:availability|free|available)\b/);
    if (mAvail && !/^(check|is|my|the|your)$/.test(mAvail[1])) {
      const c = findContact(' ' + mAvail[1] + ' ');
      if (c) return buildAction('check_availability', { contact: c }, raw);
    }
  }

  /* --- CALENDAR: schedule --- */
  if (/\b(schedule|set up|book|arrange)\b/.test(t) && /\b(meeting|call|sync|chat|coffee|lunch)\b/.test(t)
      || /\bmeeting with \w+\b/.test(t)) {
    const c = findContact(t);
    const when = resolveDate(t);
    const kind = (t.match(/\b(meeting|call|sync|coffee|lunch)\b/) || [,'meeting'])[1];
    return buildAction('schedule_meeting', { contact: c, when, kind }, raw);
  }

  /* --- EMAIL search --- */
  if (/\b(search|find|look for)\b/.test(t) && /\b(e-?mails?|mail)\b/.test(t)) {
    const q = (t.match(/\b(?:about|from|for|with)\s+(.+?)\s*$/) || [,''])[1];
    return buildAction('search_emails', { query: q || '' }, raw);
  }

  /* --- EMAIL send --- */
  if (/\b(e-?mail|mail)\b/.test(t) && /\b(send|write|compose|draft)\b/.test(t) || /\bsend .+ an? e-?mail\b/.test(t)) {
    const c = findContact(t);
    const about = (raw.match(/\babout\s+(.+?)(?:\s+saying|\s+at\s+\d|$)/i) || [,''])[1];
    return buildAction('send_email', { contact: c, subject: about ? titleCase(about.trim()) : null }, raw);
  }

  /* --- MESSAGE reply / check / send --- */
  m = t.match(/\breply to (\w+)(?:\s+(?:saying|with|that)\s+(.+?))?\s*$/);
  if (m && !/\b(email|mail)\b/.test(t)) {
    const c = findContact(' ' + m[1] + ' ');
    return buildAction('reply_message', { contact: c, body: m[2] || null }, raw);
  }
  m = t.match(/\b(?:check|show|read)\b.*\bmessages? from (\w+)\b/);
  if (m) {
    const c = findContact(' ' + m[1] + ' ');
    return buildAction('check_messages', { contact: c }, raw);
  }
  m = t.match(/\bsend (?:a )?(message|text)\b/);
  if (m) {
    const c = findContact(t);
    const bodyM = raw.match(/\b(?:saying|that)\s+(.+)$/i);
    if (!c) {
      state.pending = { type: 'collect', field: 'recipient', action: 'send_message',
        params: { body: bodyM ? bodyM[1] : null }, raw };
      return makeResponse({
        understood: 'Send a message — recipient missing', mode: 'agent', action: 'send_message',
        confidence: .55, response: 'To who?',
        options: [{ label: 'Maria' }, { label: 'Alex' }, { label: 'John' }],
        ui_state: { notification: 'Choose a recipient' },
      });
    }
    return buildAction('send_message', { contact: c, body: bodyM ? bodyM[1] : null }, raw);
  }

  /* --- FILES --- */
  if (/\b(find|locate|search for|look for|open)\b/.test(t)
      && (/\b(file|files|document|doc|pdf|deck|slides|spreadsheet|folder|tax|taxes|invoice|return|returns)\b/.test(t) || /\w+\.\w{2,4}\b/.test(t))) {
    let q = t.replace(/\b(find|locate|search for|look for|open|my|the|last year'?s?|this year'?s?|file|files|please|me)\b/g, '').trim();
    if (/tax/.test(t) && !/tax/.test(q)) q = 'tax';
    const openIt = /\bopen\b/.test(t);
    return buildAction(openIt ? 'open_file' : 'find_file', { query: q }, raw);
  }

  /* --- WEB / knowledge --- */
  m = t.match(/\b(?:search (?:the )?web(?: for)?|google|look up|what is|what'?s|who is)\s+(.+?)\s*$/);
  if (m) return buildAction('search_web', { query: m[1] }, raw);

  /* --- APP CONTROL --- */
  m = t.match(/\bopen (\w+)\b/);
  if (m) return buildAction('open_app', { app: titleCase(m[1]) }, raw);
  m = t.match(/\bclose (\w+)\b/);
  if (m) return buildAction('close_app', { app: titleCase(m[1]) }, raw);

  /* --- catch-all generic search --- */
  m = t.match(/\b(?:find|search(?: for)?|look for)\s+(.+?)\s*$/);
  if (m) return buildAction('find_file', { query: m[1] }, raw);

  /* --- UNCLEAR --- */
  return makeResponse({
    understood: `Heard: “${raw}”`, mode: 'unclear', action: null, confidence: .45,
    response: 'I didn’t catch that. Could you repeat?',
    options: [{ label: 'Send an email' }, { label: 'Take a note' }, { label: 'Find a file' }],
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
      const body = `Hi ${params.contact.name},\n\nRe: ${subj.toLowerCase()} — sending this over. Details inside.\n\n— Sent with VoiceOS`;
      const rc = shouldConfirm('send_email');
      return makeResponse({
        understood: `Send email to ${params.contact.name}${params.subject ? ' about ' + params.subject : ''}`,
        mode: 'agent', action, confidence: .93,
        parameters: { to: params.contact.email, subject: subj, body },
        requires_confirmation: rc,
        confirmation_prompt: rc ? `Send email to ${params.contact.email}?` : null,
        response: rc ? `Email to ${params.contact.name}. Confirm?` : `Sending email to ${params.contact.name}.`,
        card_type: 'email',
        card_data: { lines: [['To', params.contact.email], ['Subject', subj]], body, confirmLabel: 'SEND' },
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
      const title = `${titleCase(params.kind)} with ${params.contact.name}`;
      const rc = shouldConfirm('schedule_meeting');
      return makeResponse({
        understood: `Schedule ${params.kind} with ${params.contact.name} — ${fmtWhen(params.when)}`,
        mode: 'agent', action, confidence: .9,
        parameters: { title, attendee: params.contact.email, when: params.when.toISOString() },
        requires_confirmation: rc,
        confirmation_prompt: rc ? `Book ${params.kind} with ${params.contact.name}?` : null,
        response: rc ? `${fmtDate(params.when)} at ${fmtTime(params.when)}. Confirm?`
                     : `Booking ${params.kind} with ${params.contact.name}.`,
        card_type: 'event',
        card_data: { lines: [['What', title], ['When', fmtWhen(params.when)], ['With', params.contact.email]], confirmLabel: 'BOOK' },
        ui_state: { show_confirmation: rc, highlight_app: 'Calendar' },
      });
    }

    case 'find_next_meeting': {
      const next = store.events.filter(e => e.when > new Date()).sort((a, b) => a.when - b.when)[0];
      if (!next) return makeResponse({ understood: 'Next meeting', mode: 'agent', action, confidence: .95,
        response: 'Your calendar is clear. Enjoy the focus time.' });
      return makeResponse({
        understood: 'Next meeting', mode: 'agent', action, confidence: .96,
        parameters: { title: next.title, when: next.when.toISOString() },
        result: next.title, response: `${next.title}, ${fmtWhen(next.when)}.`,
        card_type: 'event',
        card_data: { lines: [['What', next.title], ['When', fmtWhen(next.when)], ['Who', (next.who || []).join(', ')]] },
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
        card_data: { results: hits.map(e => ({ icon: '✉️', name: e.subj, meta: `${e.from} · ${e.when}` })) },
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
          response: `What should I tell ${params.contact.name}?`,
          card_type: 'text',
          card_data: { body: last ? `Last from ${params.contact.name}: “${last.text}”` : null },
          ui_state: { highlight_app: 'Messages' },
        });
      }
      const rc = shouldConfirm('send_message');
      return makeResponse({
        understood: `${action === 'reply_message' ? 'Reply to' : 'Message'} ${params.contact.name}: “${params.body}”`,
        mode: 'agent', action, confidence: .92,
        parameters: { to: params.contact.name, body: params.body },
        requires_confirmation: rc,
        confirmation_prompt: rc ? `Send message to ${params.contact.name}?` : null,
        response: rc ? `Message to ${params.contact.name}. Confirm?` : `Sent to ${params.contact.name}. Done.`,
        result: `Sent to ${params.contact.name}`,
        card_type: rc ? 'text' : null,
        card_data: rc ? { lines: [['To', params.contact.name], ['Message', params.body]], confirmLabel: 'SEND' } : {},
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
      return makeResponse({
        understood: `Find file: ${params.query}`, mode: 'search', action, confidence: hits.length ? .9 : .6,
        parameters: { query: params.query },
        result: hits.length ? `${hits.length} matches` : 'No matches',
        response: hits.length
          ? (hits.length > 1 ? `Found ${hits.length} matches. Showing best first.` : `Found ${hits[0].name}.`)
          : 'Nothing matched. Try different words?',
        card_type: 'search_result',
        card_data: { query: params.query, results: hits.map(f => ({ icon: f.icon, name: f.name, meta: f.meta })) },
        ui_state: { highlight_app: hits.length ? 'Files' : null },
      });
    }

    case 'search_web': {
      const q = params.query;
      return makeResponse({
        understood: `Web search: ${q}`, mode: 'search', action, confidence: .85,
        parameters: { query: q },
        result: 'Web results',
        response: `Here’s what I found for “${q}”.`,
        card_type: 'search_result',
        card_data: { results: [
          { icon: '🌐', name: `${titleCase(q)} — Wikipedia`, meta: 'en.wikipedia.org' },
          { icon: '📰', name: `${titleCase(q)}: latest news`, meta: 'Top stories' },
          { icon: '🎬', name: `${titleCase(q)} — explainer video`, meta: 'youtube.com' },
        ] },
      });
    }

    case 'create_note': {
      const clean = cleanDictation(params.body);
      return makeResponse({
        understood: `Dictate note: “${clean}”`, mode: 'dictation', action, confidence: .94,
        parameters: { content: clean },
        result: 'Added to Notes', response: 'Added to Notes. What’s next?',
        card_type: 'text', card_data: { text: clean },
        ui_state: { highlight_app: 'Notes' },
      });
    }

    case 'create_reminder': break; // handled inline above

    case 'open_app': {
      const name = Object.keys(APPS).find(a => a.toLowerCase() === String(params.app).toLowerCase());
      if (!name) return makeResponse({
        understood: `Open ${params.app}`, mode: 'agent', action, confidence: .7,
        parameters: params, response: `${params.app} isn’t on this Mac. Try Mail, Calendar, Messages, Notes, Files.`,
      });
      return makeResponse({
        understood: `Open ${name}`, mode: 'agent', action, confidence: .97,
        parameters: { app: name }, result: 'Opened', response: `Opening ${name}.`,
        ui_state: { highlight_app: name },
      });
    }

    case 'close_app': {
      const name = Object.keys(APPS).find(a => a.toLowerCase() === String(params.app).toLowerCase());
      return makeResponse({
        understood: `Close ${params.app}`, mode: 'agent', action, confidence: .9,
        parameters: { app: name || params.app },
        result: name ? 'Closed' : `${params.app} isn’t open`,
        response: name ? `Closing ${name}.` : `${params.app} isn’t running.`,
        ui_state: { highlight_app: name || null },
      });
    }
  }
  return makeResponse({ understood: raw, mode: 'unclear', confidence: .3,
    response: 'I didn’t catch that. Could you repeat?' });
}

/* ---------- dictation cleanup: fillers, casing, punctuation ---------- */
function cleanDictation(s) {
  let out = ' ' + s.trim() + ' ';
  out = out.replace(/\b(um+|uh+|erm+|ah+|hmm)\b[,\s]*/gi, ' ');
  out = out.replace(/\byou know\b[,\s]*/gi, ' ');
  out = out.replace(/(,\s*)?\blike\b,\s*/gi, ', ');
  out = out.replace(/\s+/g, ' ').trim();
  out = out.replace(/(^\s*\w|[.!?]\s+\w)/g, c => c.toUpperCase());
  if (out && !/[.!?]$/.test(out)) out += '.';
  return out;
}

/* ======================== EXECUTOR ======================== */

const PERSIST_ACTIONS = new Set(['send_email', 'reply_email', 'schedule_meeting',
  'create_reminder', 'send_message', 'reply_message', 'create_note']);

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
      return { result: `Email sent to ${CONTACTS_BY_EMAIL(p.to)?.name || p.to}` };
    }
    case 'schedule_meeting': {
      store.events.push({ title: p.title, when: new Date(p.when), who: [CONTACTS_BY_EMAIL(p.attendee)?.name || p.attendee], fresh: true });
      openApp('Calendar');
      return { result: 'Meeting confirmed', sub: `${p.title} — ${fmtWhen(new Date(p.when))}` };
    }
    case 'create_reminder': {
      store.reminders.push({ task: p.task, when: new Date(p.when) });
      return { result: 'Reminder set', sub: `${titleCase(p.task)} — ${fmtWhen(new Date(p.when))}` };
    }
    case 'send_message':
    case 'reply_message': {
      const key = p.to.toLowerCase();
      (store.threads[key] = store.threads[key] || []).push({ from: 'me', text: p.body });
      openApp('Messages', { thread: key });
      return { result: resp.result || `Sent to ${p.to}` };
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
  $('#hint').classList.add('hidden');
  notchListening(`“${text.length > 42 ? text.slice(0, 42) + '…' : text}”`);

  setTimeout(() => {
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
      if (resp.requires_confirmation) {
        const doConfirm = () => {
          state.pending = null;
          const r = exec(resp);
          const done = makeResponse({ ...resp, requires_confirmation: false,
            confirmation_prompt: null, result: r.result,
            response: resp.action === 'send_email' ? 'Sent. Done.' : (r.result || 'Done.'),
            ui_state: { ...resp.ui_state, show_confirmation: false }, _handled: true });
          emit(done);
          resultCard(r.result, r.sub || resp.card_data?.lines?.map(l => `${l[0]}: ${l[1]}`).join('  ·  '));
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
          openApp('Files', { highlight: item.name });
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
    const spots = { Mail: [60, 40], Calendar: [150, 90], Messages: [90, 120], Notes: [200, 60], Files: [120, 100] };
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
    body.innerHTML = `<div class="app-list">
      ${FILES.map(f => `
        <div class="app-row ${opts.highlight === f.name ? 'hl' : ''}">
          <span>${f.icon}</span>
          <div class="grow"><div class="name">${esc(f.name)}</div><div class="sub">${esc(f.meta)}</div></div>
          ${opts.highlight === f.name ? '<span class="badge-new">FOUND</span>' : ''}
        </div>`).join('')}
    </div>`;
  }
}

/* --- dock --- */

const dock = $('#dock');
function buildDock() {
  dock.innerHTML = Object.entries(APPS).map(([name, a]) => `
    <div class="dock-item" data-app="${name}">
      ${a.icon}<span class="tip">${name}</span><span class="dot"></span>
    </div>`).join('');
  $$('.dock-item').forEach(d => d.addEventListener('click', () => {
    openWins[d.dataset.app] ? closeApp(d.dataset.app) : openApp(d.dataset.app);
  }));
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
});

/* suggestion chips — straight from the spec's examples */
const CHIPS = [
  'Send email to John about the meeting',
  'Schedule meeting with Sarah next week',
  'Find last year’s tax returns',
  'Reply to Maya',
  'Remind me to call Joan tomorrow at 9am',
  'Take a note: the new onboarding flow tested well',
  'What’s my next meeting?',
  'Send message',           // ambiguity demo
  'Search web for focus timing',
  'Open Notes',
];
$('#chips').innerHTML = CHIPS.map(c => `<button class="chip">${esc(c)}</button>`).join('');
$$('#chips .chip').forEach(c => c.addEventListener('click', () => submit(c.textContent)));

/* --- real mic via Web Speech API, text fallback always available --- */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
function micStart() {
  if (!SR) { notchProcessing('Mic not supported here — type instead'); setTimeout(notchIdle, 1800); return; }
  if (state.listening) { state.recognition.stop(); return; }
  const rec = new SR();
  state.recognition = rec;
  rec.lang = 'en-US'; rec.interimResults = false; rec.maxAlternatives = 1;
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
  $('#clock').textContent = d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }) +
    '  ' + d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}
setInterval(tickClock, 1000); tickClock();

/* ======================== v1.0 INIT: settings, onboarding, PWA ======================== */

function hasVoices() {
  return typeof window !== 'undefined' && 'speechSynthesis' in window &&
         speechSynthesis.getVoices().length > 0;
}

function populateVoices(sel) {
  try {
    const voices = speechSynthesis.getVoices().filter(v => v.lang.startsWith('en'));
    if (!voices.length) { sel.parentElement.style.display = 'none'; return; }
    sel.innerHTML = '<option value="">System default</option>' +
      voices.map(v => `<option value="${esc(v.name)}" ${v.name === settings.voice ? 'selected' : ''}>${esc(v.name)}</option>`).join('');
  } catch (_) { sel.parentElement.style.display = 'none'; }
}

function applySettingsToUI() {
  const rv = $('#setRate');      if (rv) rv.value = settings.rate;
  const cf = $('#setConfirm');   if (cf) cf.value = settings.confirmLevel;
  const vb = $('#setVerbose');   if (vb) vb.value = settings.verbosity;
  const sv = $('#setVoice');     if (sv) sv.value = settings.voice || '';
  const obr = document.querySelector(`input[name="obrate"][value="${settings.rate}"]`);
  const obc = document.querySelector(`input[name="obconfirm"][value="${settings.confirmLevel}"]`);
  if (obr) obr.checked = true;
  if (obc) obc.checked = true;
}

function initProduct() {
  loadSettings();
  loadPersisted();

  /* --- settings drawer --- */
  $('#settingsBtn').addEventListener('click', () => $('#settingsPanel').classList.toggle('visible'));
  $('#setRate').addEventListener('change',    e => { settings.rate = e.target.value; saveSettings(); });
  $('#setConfirm').addEventListener('change', e => { settings.confirmLevel = e.target.value; saveSettings(); });
  $('#setVerbose').addEventListener('change', e => { settings.verbosity = e.target.value; saveSettings(); });
  $('#setVoice').addEventListener('change',   e => { settings.voice = e.target.value || null; saveSettings(); });
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
    settings.voice = $('#obVoice').value || null;
    saveSettings();
    $('#onboarding').classList.remove('show');
    speak('Welcome to VoiceOS.');
    resultCard('VoiceOS is ready', 'Try: “Send email to John about the meeting.”');
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
