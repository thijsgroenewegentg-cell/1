/* ═══════════════════════════════════════════════════════════════
   ULTRON — front-end mind, v3: the agent edition.
   Voice in (browser or local whisper) · voice out (browser or Piper)
   · vision upload · tool activity log · live reminders · sessions.
   Blue = he listens. Red = he thinks and speaks.
   ═══════════════════════════════════════════════════════════════ */
'use strict';

/* ---------- state ---------- */
const LANG_LOCALES = {
  auto: null, en: 'en-US', nl: 'nl-NL', de: 'de-DE', fr: 'fr-FR', es: 'es-ES', it: 'it-IT', tr: 'tr-TR',
};

const state = {
  messages: [],                 // {role, content, images?: [dataUrl]}
  ollamaUrl: localStorage.getItem('ultron.url') || 'http://localhost:11434',
  model: localStorage.getItem('ultron.model') || '',   // '' = AUTO routing
  temperature: parseFloat(localStorage.getItem('ultron.temp') || '0.7'),
  voice: localStorage.getItem('ultron.voice') !== '0',
  wake: localStorage.getItem('ultron.wake') === '1',
  language: localStorage.getItem('ultron.lang') || 'auto',
  profile: localStorage.getItem('ultron.profile') || 'main',
  online: false,
  streaming: false,
  mode: 'dormant',
  micSession: false,
  wakeArmed: false,
  serverCfg: { toolsEnabled: true, sttUrl: '', ttsUrl: '' },
  pendingImages: [],            // dataURLs staged for the next message
  convId: null,
  serverSessions: [],           // server-side session index (sync)
};

function applyGlass() {
  document.body.classList.toggle('glass', localStorage.getItem('ultron.glass') === '1');
}

// Desktop companion mode (tiny always-on-top window)
if (new URLSearchParams(location.search).has('mini')) {
  document.body.classList.add('mini');
}

function sttLocale() {
  return LANG_LOCALES[state.language] || navigator.language || 'en-US';
}

/* ---------- token-aware API fetch ---------- */

function apiFetch(url, opts = {}) {
  const token = localStorage.getItem('ultron.token') || '';
  if (token) {
    opts.headers = { ...(opts.headers || {}), 'X-Ultron-Token': token };
  }
  return fetch(url, opts).then(async (res) => {
    if (res.status === 401) {
      const tokenPrompt = window.prompt('ULTRON is protected.\nAccess token:') || '';
      localStorage.setItem('ultron.token', tokenPrompt.trim());
      if (tokenPrompt.trim()) {
        return apiFetch(url, { ...opts, headers: { ...(opts.headers || {}), 'X-Ultron-Token': tokenPrompt.trim() } });
      }
    }
    return res;
  });
}

/* ---------- dom ---------- */
const $ = (id) => document.getElementById(id);
const chat = $('chat');
const input = $('input');
const form = $('composer');
const statusChip = $('status-chip');
const statusText = $('status-text');
const orbState = $('orb-state');
const liveTranscript = $('live-transcript');
const micBtn = $('btn-mic');
const settings = $('settings');
const settingsBackdrop = $('settings-backdrop');
const composerHint = $('composer-hint');
const sidebar = $('sidebar');
const sidebarBackdrop = $('sidebar-backdrop');
const convList = $('conv-list');
const attachPreview = $('attach-preview');

const WAKE_RE = /\b(hey\s+|ok\s+|okay\s+)?ultr[aou]n\b[:,]?\s*/i;

/* ═══════════════ STATE MACHINE ═══════════════ */
const STATE_LABEL = {
  dormant: 'DORMANT',
  listening: 'LISTENING',
  armed: 'I’M LISTENING…',
  thinking: 'PROCESSING',
  speaking: 'SPEAKING',
};

function setMode(mode) {
  state.mode = mode;
  document.body.className = `state-${mode === 'armed' ? 'listening' : mode}`;
  orbState.textContent = STATE_LABEL[mode] || mode.toUpperCase();
  if (mode === 'dormant' && state.wake) orbState.textContent = 'SAY “ULTRON”';
}

/* ═══════════════ THE ORB (canvas) ═══════════════ */
const canvas = $('orb-canvas');
const ctx = canvas.getContext('2d');
const BLUE = [63, 182, 255];
const RED = [255, 74, 61];

const orb = { heat: 0, heatTarget: 0, spin: 0, pulse: 0, wave: 0, waveTarget: 0 };

function orbColor(alpha) {
  const h = orb.heat;
  const r = Math.round(BLUE[0] + (RED[0] - BLUE[0]) * h);
  const g = Math.round(BLUE[1] + (RED[1] - BLUE[1]) * h);
  const b = Math.round(BLUE[2] + (RED[2] - BLUE[2]) * h);
  return `rgba(${r},${g},${b},${alpha})`;
}

function sizeCanvas() {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (rect.width === 0) return;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener('resize', sizeCanvas);

let t = 0;
function drawOrb() {
  requestAnimationFrame(drawOrb);
  const rect = canvas.getBoundingClientRect();
  if (rect.width === 0 || canvas.width === 0) return;
  const w = rect.width, h = rect.height;
  const cx = w / 2, cy = h / 2;
  const R = Math.min(w, h) / 2 - 4;

  orb.heat += (orb.heatTarget - orb.heat) * 0.035;
  orb.wave += (orb.waveTarget - orb.wave) * 0.06;
  orb.pulse *= 0.90;

  const spinSpeed =
    state.mode === 'thinking' ? 0.045 :
    state.mode === 'speaking' ? 0.016 :
    state.mode === 'listening' || state.mode === 'armed' ? 0.010 : 0.005;
  orb.spin += spinSpeed;
  t += 0.012;

  const flicker = 0.95 + Math.sin(t * 12.3) * 0.03 + Math.random() * 0.02;
  const energy = 0.5 + orb.heat * 0.5;

  ctx.clearRect(0, 0, w, h);

  const segs = 6;
  for (let i = 0; i < segs; i++) {
    const a0 = orb.spin + (i * Math.PI * 2) / segs;
    const a1 = a0 + (Math.PI * 2) / segs - 0.35;
    ctx.beginPath();
    ctx.arc(cx, cy, R, a0, a1);
    ctx.strokeStyle = orbColor((0.22 + energy * 0.42) * flicker);
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  for (let i = 0; i < 3; i++) {
    const a = -orb.spin * 1.6 + (i * Math.PI * 2) / 3;
    ctx.beginPath();
    ctx.arc(cx + Math.cos(a) * R, cy + Math.sin(a) * R, 1.8, 0, Math.PI * 2);
    ctx.fillStyle = orbColor(0.55 + energy * 0.4);
    ctx.fill();
  }
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(-orb.spin * 1.35);
  ctx.setLineDash([R * 0.16, R * 0.13]);
  ctx.beginPath();
  ctx.arc(0, 0, R * 0.74, 0, Math.PI * 2);
  ctx.strokeStyle = orbColor((0.3 + energy * 0.4) * flicker);
  ctx.lineWidth = 1.4;
  ctx.stroke();
  ctx.restore();
  ctx.setLineDash([]);

  const waveBase = R * 0.52;
  const waveAmp = (orb.wave * R * 0.085) * (0.5 + 0.5 * Math.sin(t * 2.2)) + orb.pulse * R * 0.06;
  ctx.beginPath();
  const STEPS = 90;
  for (let i = 0; i <= STEPS; i++) {
    const a = (i / STEPS) * Math.PI * 2;
    const wobble =
      Math.sin(a * 6 + t * 5.5) * 0.55 +
      Math.sin(a * 11 - t * 8.2) * 0.30 +
      Math.sin(a * 3 + t * 2.1) * 0.35;
    const r = waveBase + wobble * waveAmp + orb.pulse * R * 0.05 * Math.sin(a * 8 + t * 20);
    const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.strokeStyle = orbColor((0.35 + energy * 0.4) * flicker);
  ctx.lineWidth = 1.5;
  ctx.stroke();

  const pulse = 1 + Math.sin(t * 4.6) * 0.03 + orb.pulse * 0.10;
  const orbR = R * 0.30 * pulse;
  const g = ctx.createRadialGradient(cx, cy, orbR * 0.1, cx, cy, orbR);
  g.addColorStop(0, orbColor(0.95 * flicker));
  g.addColorStop(0.45, orbColor(0.85));
  g.addColorStop(1, orbColor(0.9));
  ctx.beginPath();
  ctx.arc(cx, cy, orbR, 0, Math.PI * 2);
  ctx.fillStyle = g;
  ctx.fill();
  const core = ctx.createRadialGradient(cx - orbR * 0.25, cy - orbR * 0.25, 0, cx, cy, orbR * 0.5);
  core.addColorStop(0, 'rgba(255,255,255,0.75)');
  core.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.beginPath();
  ctx.arc(cx, cy, orbR * 0.55, 0, Math.PI * 2);
  ctx.fillStyle = core;
  ctx.fill();

  const halo = ctx.createRadialGradient(cx, cy, orbR, cx, cy, R * 0.95);
  halo.addColorStop(0, orbColor(0.14 + energy * 0.22));
  halo.addColorStop(1, orbColor(0));
  ctx.beginPath();
  ctx.arc(cx, cy, R * 0.95, 0, Math.PI * 2);
  ctx.fillStyle = halo;
  ctx.fill();

}

function orbOrate() { orb.pulse = 1; }
canvas.addEventListener('click', () => silence(false));

/* ═══════════════ STATUS ═══════════════ */
async function refreshStatus() {
  statusChip.className = 'chip chip-wait';
  statusText.textContent = 'WAKING…';
  try {
    const res = await apiFetch(`/api/status?url=${encodeURIComponent(state.ollamaUrl)}`);
    const s = await res.json();
    state.online = s.online && s.models.length > 0;
    if (state.online) {
      if (state.model && !s.models.includes(state.model)) state.model = '';
      statusChip.className = 'chip chip-online';
      statusText.textContent = `CORE ONLINE — ${state.model || 'AUTO'}`;
    } else {
      statusChip.className = 'chip chip-demo';
      statusText.textContent = 'DEMO CORE — CONNECT OLLAMA';
    }
    return s;
  } catch {
    state.online = false;
    statusChip.className = 'chip chip-off';
    statusText.textContent = 'SERVER UNREACHABLE';
    return { online: false, models: [] };
  }
}

/* ═══════════════ RENDERING ═══════════════ */
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function messageShell(role, idx) {
  const wrap = el('div', `msg msg-${role}`);
  if (idx != null) wrap.dataset.idx = idx;
  const meta = el('div', 'msg-meta', role === 'ultron' ? 'ULTRON' : 'HUMAN');
  const content = el('div', 'msg-content');

  // Edit / branch actions on user messages.
  if (role === 'user' && idx != null) {
    const actions = el('div', 'msg-actions');
    const edit = el('button', null, '✎');
    edit.type = 'button';
    edit.title = 'Edit this message and rerun';
    edit.addEventListener('click', () => editMessage(idx));
    const branch = el('button', null, '⑂');
    branch.type = 'button';
    branch.title = 'Branch the conversation from here';
    branch.addEventListener('click', () => branchFrom(idx));
    actions.append(edit, branch);
    meta.appendChild(actions);
  }

  wrap.append(meta, content);
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
  return { wrap, content };
}

/** Full re-render of the conversation from state. */
function renderAll() {
  chat.innerHTML = '';
  state.messages.forEach((m, i) => {
    const shell = messageShell(m.role, m.role === 'user' ? i : null);
    shell.content.textContent = m.content;
    if (m.images) attachThumbToMessage(shell.content, m.images);
  });
  chat.scrollTop = chat.scrollHeight;
}

function editMessage(idx) {
  if (state.streaming) return;
  const m = state.messages[idx];
  if (!m || m.role !== 'user') return;
  const wrap = chat.querySelector(`.msg[data-idx="${idx}"]`);
  if (!wrap) return;
  const contentEl = wrap.querySelector('.msg-content');
  contentEl.innerHTML = '';
  contentEl.classList.remove('md');
  const ta = document.createElement('textarea');
  ta.value = m.content;
  ta.className = 'edit-area';
  const row = el('div', 'approval-actions');
  const save = el('button', 'btn-primary btn-small', 'SAVE & RERUN');
  const cancel = el('button', 'btn-secondary btn-small', 'CANCEL');
  save.type = cancel.type = 'button';
  row.append(save, cancel);
  contentEl.append(ta, row);
  ta.focus();
  cancel.addEventListener('click', () => renderAll());
  save.addEventListener('click', () => {
    const newText = ta.value.trim();
    if (!newText) return;
    state.messages = state.messages.slice(0, idx);
    state.messages.push({ role: 'user', content: newText, ...(m.images ? { images: m.images } : {}) });
    renderAll();
    saveConversation();
    doStream();
  });
}

function branchFrom(idx) {
  if (state.streaming) return;
  state.messages = state.messages.slice(0, idx + 1);
  state.convId = 'c' + Date.now();
  renderAll();
  saveConversation();
  composerHint.textContent = 'Branched — this is a new timeline. Regenerate his reply with ↺ or keep typing.';
}

function toolLine(name, args) {
  const div = el('div', 'msg-tool');
  const gear = el('span', 'tool-name', `⚙ ${name}`);
  const argsSpan = el('span', 'tool-args', `(${shortArgs(args)})`);
  div.append(gear, argsSpan);
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

function toolResultLine(name, result) {
  const div = el('div', 'msg-tool tool-done');
  // Knowledge results get clickable citation chips.
  if (name === 'search_knowledge' && result && Array.isArray(result.results) && result.results.length > 0) {
    div.textContent = `└─ ✓ knowledge: ${result.results.length} passage(s)`;
    const chips = el('div', 'cite-chips');
    for (const r of result.results) {
      const chip = el('span', 'cite-chip', r.source || 'source');
      chip.appendChild(el('small', null, String(r.relevance != null ? r.relevance : '')));
      chip.title = (r.excerpt || '').slice(0, 300);
      chips.appendChild(chip);
    }
    div.appendChild(chips);
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
    return div;
  }
  let summary;
  try { summary = JSON.stringify(result); } catch { summary = String(result); }
  div.textContent = `└─ ✓ ${name} → ${summary.slice(0, 140)}`;
  // Music: PLAY buttons for his keyless music services.
  if (name === 'play_music' && result && result.ok && result.links) {
    const chips = el('div', 'cite-chips play-chips');
    const labels = { spotify: '▶ SPOTIFY', youtube: '▶ YOUTUBE', ytmusic: '▶ YT MUSIC' };
    for (const [svc, url] of Object.entries(result.links)) {
      const chip = el('button', 'play-chip' + (svc === result.service ? ' primary' : ''), labels[svc] || svc);
      chip.type = 'button';
      chip.addEventListener('click', () => window.open(url, '_blank', 'noopener'));
      chips.appendChild(chip);
    }
    if (result.app_link) {
      const appChip = el('button', 'play-chip primary', '▶ IN SPOTIFY APP');
      appChip.type = 'button';
      appChip.title = 'opens the Spotify desktop app and searches (Premium)';
      appChip.addEventListener('click', () => {
        const anchor = document.createElement('a');
        anchor.href = result.app_link;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      });
      chips.appendChild(appChip);
    }
    div.appendChild(document.createElement('br'));
    div.appendChild(chips);
  }
  // Images he generated or captured are shown inline.
  if (result && typeof result.saved === 'string' && /\.(png|jpe?g|webp)$/i.test(result.saved)) {
    const img = new Image();
    img.className = 'msg-image tool-image';
    img.src = '/api/files/' + encodeURIComponent(result.saved.split('/').pop());
    img.alt = result.prompt || 'generated image';
    div.appendChild(document.createElement('br'));
    div.appendChild(img);
  }
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function shortArgs(args) {
  try {
    const s = JSON.stringify(args);
    return s.length > 90 ? s.slice(0, 90) + '…' : s;
  } catch { return String(args); }
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function renderMarkdown(text) {
  const blocks = [];
  let t = escapeHtml(text);
  t = t.replace(/```(\w*)\n?([\s\S]*?)```/g, (_m, _lang, code) => {
    blocks.push(`<pre><code>${code.replace(/\n$/, '')}</code></pre>`);
    return `\u0000BLOCK${blocks.length - 1}\u0000`;
  });
  t = t
    .replace(/^### (.*)$/gm, '<h3>$1</h3>')
    .replace(/^## (.*)$/gm, '<h3>$1</h3>')
    .replace(/^# (.*)$/gm, '<h3>$1</h3>')
    .replace(/^&gt; (.*)$/gm, '<blockquote>$1</blockquote>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/^\s*[-*] (.*)$/gm, '<li>$1</li>')
    .replace(/^\s*\d+\. (.*)$/gm, '<li>$1</li>');
  t = t.replace(/(<li>[\s\S]*?<\/li>)(?:\n(<li>[\s\S]*?<\/li>))*/g, (m) => `<ul>${m}</ul>`);
  t = t.replace(/\n{2,}/g, '<br><br>').replace(/\n/g, '<br>');
  t = t.replace(/\u0000BLOCK(\d+)\u0000/g, (_m, i) => blocks[Number(i)]);
  t = t.replace(/<br>(<\/?(h3|ul|li|pre|blockquote))/g, '$1').replace(/(<\/(h3|ul|li|pre|blockquote))><br>/g, '$1>');
  return t;
}

/* ═══════════════ VOICE OUT — sentence-streaming speech queue ═══════════════ */
let pulseTimer = null;

function speakableText(text) {
  return text
    .replace(/```[\s\S]*?```/g, ' — code block omitted — ')
    .replace(/[*#`>|]/g, '')
    .slice(0, 1200)
    .trim();
}

function pickVoiceFor(lang) {
  const voices = ('speechSynthesis' in window) ? speechSynthesis.getVoices() : [];
  return (
    voices.find((v) => v.lang && v.lang.toLowerCase().startsWith(lang.slice(0, 2).toLowerCase()) && /male|daniel|george|arthur|xander|ruben/i.test(v.name)) ||
    voices.find((v) => v.lang && v.lang.toLowerCase().startsWith(lang.slice(0, 2).toLowerCase())) ||
    voices.find((v) => /en(-|_)GB/i.test(v.lang) && /male|daniel|george|arthur/i.test(v.name)) ||
    voices.find((v) => /^en/i.test(v.lang))
  );
}

/** Which TTS engine is live: ElevenLabs (cloud) → Piper (local) → browser. */
function ttsEndpointActive() {
  const cfg = state.serverCfg || {};
  return !!(cfg.elevenKeySet || cfg.ttsUrl);
}

/** Speak one chunk through the configured endpoint (ElevenLabs or Piper). */
async function speakChunkEndpoint(text) {
  const res = await apiFetch(`/api/tts?text=${encodeURIComponent(text)}`);
  if (!res.ok) {
    let why = `HTTP ${res.status}`;
    try { const j = await res.json(); if (j.error) why = j.error; } catch { /* not json */ }
    throw new Error(why);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  Speech.currentAudio = audio;
  clearInterval(pulseTimer);
  pulseTimer = setInterval(orbOrate, 320);
  await new Promise((resolve) => {
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(); } };
    audio.onended = finish;
    audio.onerror = finish;
    audio.play().catch(finish);
    if (state.micSession) {
      watchBargeIn(() => {
        Speech.aborted = true;
        Speech.queue = [];
        try { audio.pause(); audio.src = ''; } catch { /* noop */ }
        finish();
      });
    }
    setTimeout(finish, Math.max(4000, text.length * 140)); // watchdog
  });
  clearInterval(pulseTimer);
  Speech.currentAudio = null;
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Speak one chunk through the browser's built-in voice. */
function speakChunkBrowser(text) {
  return new Promise((resolve) => {
    if (!('speechSynthesis' in window)) return resolve();
    const u = new SpeechSynthesisUtterance(text);
    const lang = sttLocale();
    u.lang = lang;
    const pref = pickVoiceFor(lang);
    if (pref) u.voice = pref;
    u.rate = 0.95;
    u.pitch = 0.5;
    u.onboundary = orbOrate;
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(); } };
    u.onend = finish;
    u.onerror = finish;
    speechSynthesis.speak(u);
    setTimeout(finish, Math.max(3000, text.length * 120)); // watchdog
  });
}

async function speakChunk(text) {
  if (ttsEndpointActive()) {
    try { await speakChunkEndpoint(text); return; } catch (err) {
      // Endpoint failed (bad key, no credits, offline…) → browser voice, once per session-ish.
      if (!speakChunk.warned) {
        speakChunk.warned = true;
        composerHint.textContent = `Voice endpoint failed (${String(err.message || err).slice(0, 80)}) — using browser voice.`;
      }
    }
  }
  await speakChunkBrowser(text);
}

/**
 * Sentence-streaming speech: sentences are spoken as they complete during
 * token streaming — he starts talking before he finishes thinking.
 */
const Speech = {
  queue: [],
  playing: false,
  streaming: false,
  onDrained: null,
  aborted: false,
  currentAudio: null,

  begin(onDrained) {
    this.queue = [];
    this.onDrained = onDrained;
    this.streaming = true;
    this.aborted = false;
  },
  enqueue(text) {
    if (!state.voice || !text || !text.trim() || this.aborted) return;
    this.queue.push(speakableText(text));
    this.pump();
  },
  finish() {
    this.streaming = false;
    if (!this.playing) this.drain();
  },
  drain() {
    const cb = this.onDrained;
    this.onDrained = null;
    if (cb && !this.aborted) cb();
  },
  async pump() {
    if (this.playing) return;
    this.playing = true;
    setMode('speaking');
    while (this.queue.length > 0 && !this.aborted) {
      await speakChunk(this.queue.shift());
    }
    this.playing = false;
    if (!this.streaming && this.queue.length === 0) this.drain();
  },
  /** One-shot speak (reminders, briefings). */
  speakOnce(text, onDone) {
    this.begin(onDone);
    this.enqueue(text);
    this.finish();
  },
  stop() {
    this.aborted = true;
    this.queue = [];
    this.onDrained = null;
    clearInterval(pulseTimer);
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    if (this.currentAudio) { try { this.currentAudio.pause(); this.currentAudio.src = ''; } catch { /* noop */ } this.currentAudio = null; }
  },
};

function primeVoices() {
  if (!('speechSynthesis' in window)) return;
  speechSynthesis.getVoices();
  speechSynthesis.onvoiceschanged = () => { /* voices now cached */ };
}

function silence(showHint = true) {
  Speech.stop();
  if (showHint) composerHint.textContent = 'Silenced · tap the mic to speak again';
}

/* ═══════════════ VOICE IN — browser (Web Speech API) ═══════════════ */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null;
let recActive = false;
let restartTimer = null;

function initRecognition() {
  if (!SR) return null;
  const r = new SR();
  r.lang = sttLocale();
  r.continuous = true;
  r.interimResults = true;
  r.onresult = (e) => {
    let interim = '', final = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const res = e.results[i];
      if (res.isFinal) final += res[0].transcript; else interim += res[0].transcript;
    }
    if (interim) {
      liveTranscript.textContent = interim.trim();
      if (state.wake && !state.micSession && !state.wakeArmed && WAKE_RE.test(interim)) armWake();
    }
    if (final.trim()) handleUtterance(final.trim());
  };
  r.onerror = (e) => {
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
      stopListening();
      state.wake = false;
      $('set-wake').checked = false;
      localStorage.setItem('ultron.wake', '0');
      composerHint.textContent = 'Microphone access denied — enable it in your browser, or type.';
    }
  };
  r.onend = () => {
    recActive = false;
    if (!state.streaming && (state.micSession || state.wake)) {
      restartTimer = setTimeout(() => {
        if (state.streaming || recActive) return;
        try { rec.start(); recActive = true; } catch { /* already started */ }
      }, 250);
    }
  };
  return r;
}

function startBrowserListening() {
  if (!rec) rec = initRecognition();
  try { if (!recActive) { rec.start(); recActive = true; } } catch { /* already running */ }
}

function stopBrowserListening() {
  clearTimeout(restartTimer);
  if (rec && recActive) { try { rec.stop(); } catch { /* noop */ } }
}

/* ═══════════════ VOICE IN — local (whisper endpoint, fully offline) ═══════════════ */

const MicEngine = {
  stream: null, ctxA: null, analyser: null, recorder: null, chunks: [],
  running: false, spoke: false, lastVoice: 0, raf: null, bargeRaf: null,

  async ensureStream() {
    if (this.stream) return true;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      this.ctxA = new AudioContext();
      const src = this.ctxA.createMediaStreamSource(this.stream);
      this.analyser = this.ctxA.createAnalyser();
      this.analyser.fftSize = 512;
      src.connect(this.analyser);
      return true;
    } catch {
      composerHint.textContent = 'Microphone access denied — enable it in your browser, or type.';
      return false;
    }
  },

  rms() {
    if (!this.analyser) return 0;
    const buf = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteFrequencyData(buf);
    let sum = 0;
    for (const v of buf) sum += v * v;
    return Math.sqrt(sum / buf.length) / 255;
  },

  async startPhraseLoop() {
    if (this.running) return;
    if (!(await this.ensureStream())) return;
    this.running = true;
    this.beginPhrase();
  },

  beginPhrase() {
    if (!this.running) return;
    this.chunks = [];
    this.spoke = false;
    this.lastVoice = performance.now();
    try {
      this.recorder = new MediaRecorder(this.stream);
    } catch {
      this.running = false;
      composerHint.textContent = 'Audio recording not supported in this browser — type instead.';
      return;
    }
    this.recorder.ondataavailable = (e) => { if (e.data.size > 0) this.chunks.push(e.data); };
    this.recorder.onstop = () => this.finalizePhrase();
    this.recorder.start(250);
    this.watchVad();
  },

  watchVad() {
    cancelAnimationFrame(this.raf);
    const check = () => {
      if (!this.running || !this.recorder || this.recorder.state !== 'recording') return;
      const level = this.rms();
      const now = performance.now();
      if (level > 0.055) {
        if (!this.spoke && level > 0.05) liveTranscript.textContent = '…listening';
        this.spoke = true;
        this.lastVoice = now;
      } else if (this.spoke && now - this.lastVoice > 1500) {
        try { this.recorder.stop(); } catch { /* noop */ }
        return;
      }
      if (now - this.lastVoice > 30000) { // half a minute of silence → restart cleanly
        try { this.recorder.stop(); } catch { /* noop */ }
        return;
      }
      this.raf = requestAnimationFrame(check);
    };
    this.raf = requestAnimationFrame(check);
  },

  async finalizePhrase() {
    const blob = new Blob(this.chunks, { type: 'audio/webm' });
    this.chunks = [];
    if (this.running) this.beginPhrase();      // keep the loop hot
    if (blob.size < 3000) return;               // too short to be speech
    try {
      const wav = await toWav16k(blob);
      const langParam = state.language !== 'auto' ? `?language=${encodeURIComponent(state.language)}` : '';
      const res = await apiFetch('/api/transcribe' + langParam, { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav });
      if (!res.ok) return;
      const data = await res.json();
      const text = String(data.text || '').trim();
      if (text) handleUtterance(text);
    } catch { /* transient */ }
  },

  stop() {
    this.running = false;
    cancelAnimationFrame(this.raf);
    cancelAnimationFrame(this.bargeRaf);
    if (this.recorder && this.recorder.state === 'recording') {
      this.recorder.onstop = null;
      try { this.recorder.stop(); } catch { /* noop */ }
    }
    if (this.stream) {
      for (const track of this.stream.getTracks()) track.stop();
      this.stream = null;
    }
    if (this.ctxA) { try { this.ctxA.close(); } catch { /* noop */ } this.ctxA = null; this.analyser = null; }
  },

  pause() {
    this.running = false;
    cancelAnimationFrame(this.raf);
    if (this.recorder && this.recorder.state === 'recording') {
      this.recorder.onstop = null;
      try { this.recorder.stop(); } catch { /* noop */ }
    }
  },
};

/** Watch for the user's voice during playback → cancel TTS (barge-in). */
function watchBargeIn(cancel) {
  if (!MicEngine.analyser) return;
  const check = () => {
    if (state.mode !== 'speaking') return;
    if (MicEngine.rms() > 0.09) { cancel(); return; }
    MicEngine.bargeRaf = requestAnimationFrame(check);
  };
  MicEngine.bargeRaf = requestAnimationFrame(check);
}

/* Convert a recorded blob to 16 kHz mono WAV, fully in-browser. */
async function toWav16k(blob) {
  const arrayBuf = await blob.arrayBuffer();
  const tmp = new AudioContext();
  const decoded = await tmp.decodeAudioData(arrayBuf);
  await tmp.close();
  const rate = 16000;
  const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * rate)), rate);
  const src = off.createBufferSource();
  src.buffer = decoded;
  src.connect(off.destination);
  src.start();
  const rendered = await off.startRendering();
  return encodeWav(rendered);
}

function encodeWav(audioBuffer) {
  const data = audioBuffer.getChannelData(0);
  const bytes = data.length * 2;
  const buf = new ArrayBuffer(44 + bytes);
  const v = new DataView(buf);
  const writeStr = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  writeStr(0, 'RIFF'); v.setUint32(4, 36 + bytes, true); writeStr(8, 'WAVE'); writeStr(12, 'fmt ');
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, audioBuffer.sampleRate, true); v.setUint32(28, audioBuffer.sampleRate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  writeStr(36, 'data'); v.setUint32(40, bytes, true);
  let o = 44;
  for (let i = 0; i < data.length; i++, o += 2) {
    const s = Math.max(-1, Math.min(1, data[i]));
    v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: 'audio/wav' });
}

/* ---------- unified listening control ---------- */
const usingLocalSTT = () => !!state.serverCfg.sttUrl;

function startListening() {
  if (usingLocalSTT()) MicEngine.startPhraseLoop();
  else startBrowserListening();
}

function pauseListening() {
  if (usingLocalSTT()) MicEngine.pause();
  else stopBrowserListening();
}

function stopListening() {
  state.micSession = false;
  state.wakeArmed = false;
  micBtn.classList.remove('live', 'armed');
  liveTranscript.textContent = '';
  if (usingLocalSTT()) MicEngine.stop();
  else stopBrowserListening();
  if (state.mode === 'listening' || state.mode === 'armed') setMode('dormant');
}

/* ---------- utterance routing (both STT paths end here) ---------- */
function handleUtterance(text) {
  if (state.streaming) return;

  if (state.micSession) {
    const q = text.replace(WAKE_RE, '').trim();
    if (q) { liveTranscript.textContent = ''; send(q); }
    return;
  }
  if (!state.wake) return;

  if (state.wakeArmed) {
    const q = text.replace(WAKE_RE, '').trim();
    if (q) {
      state.wakeArmed = false;
      micBtn.classList.remove('armed');
      liveTranscript.textContent = '';
      send(q);
    }
    return;
  }
  if (WAKE_RE.test(text)) {
    const q = text.replace(WAKE_RE, '').trim();
    if (q) { liveTranscript.textContent = ''; send(q); }
    else armWake();
  }
}

function armWake() {
  state.wakeArmed = true;
  micBtn.classList.add('armed');
  setMode('armed');
}

micBtn.addEventListener('click', () => {
  if (state.micSession) {
    stopListening();
    if (state.wake) startListening();
    composerHint.textContent = 'Mic off · say “ULTRON” if wake word is enabled · or type';
    return;
  }
  if (!SR && !usingLocalSTT()) {
    composerHint.textContent = 'Voice input needs Chrome/Edge — or configure a local STT endpoint in settings.';
    return;
  }
  state.micSession = true;
  state.wakeArmed = false;
  micBtn.classList.add('live');
  micBtn.classList.remove('armed');
  setMode('listening');
  startListening();
  composerHint.textContent = usingLocalSTT()
    ? 'Listening (local whisper) — speak, pause, and I answer · Esc to stop'
    : 'Listening — speak freely, every phrase is a command · Esc to stop';
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    silence();
    stopListening();
  }
});

/* ═══════════════ IMAGE ATTACHMENTS (vision) ═══════════════ */
$('btn-attach').addEventListener('click', () => $('file-input').click());
$('file-input').addEventListener('change', (e) => {
  for (const file of Array.from(e.target.files || []).slice(0, 4 - state.pendingImages.length)) {
    if (!/^image\/(png|jpe?g|webp|gif)$/i.test(file.type)) continue;
    const reader = new FileReader();
    reader.onload = () => {
      downscaleImage(reader.result, 1024).then((dataUrl) => {
        state.pendingImages.push(dataUrl);
        renderAttachPreview();
      });
    };
    reader.readAsDataURL(file);
  }
  e.target.value = '';
});

function renderAttachPreview() {
  attachPreview.innerHTML = '';
  attachPreview.classList.toggle('hidden', state.pendingImages.length === 0);
  state.pendingImages.forEach((dataUrl, i) => {
    const chip = el('div', 'attach-chip');
    const img = new Image();
    img.src = dataUrl;
    const x = el('button', 'chip-x', '✕');
    x.type = 'button';
    x.addEventListener('click', () => { state.pendingImages.splice(i, 1); renderAttachPreview(); });
    chip.append(img, x);
    attachPreview.appendChild(chip);
  });
}

function downscaleImage(dataUrl, maxDim) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
      const w = Math.max(1, Math.round(img.width * scale));
      const h = Math.max(1, Math.round(img.height * scale));
      const c = document.createElement('canvas');
      c.width = w; c.height = h;
      c.getContext('2d').drawImage(img, 0, 0, w, h);
      resolve(c.toDataURL('image/jpeg', 0.85));
    };
    img.onerror = () => resolve(dataUrl);
    img.src = dataUrl;
  });
}

function attachThumbToMessage(contentEl, images) {
  for (const dataUrl of images || []) {
    const img = new Image();
    img.className = 'msg-image';
    img.src = dataUrl;
    contentEl.appendChild(img);
  }
}

/* ═══════════════ CHAT ═══════════════ */
let speechBuf = '';

function feedSpeech(tokenText) {
  speechBuf += tokenText;
  for (;;) {
    const m = speechBuf.match(/^[\s\S]*?[.!?…](\s|$)/);
    if (m && m[0].trim().length >= 60) {
      Speech.enqueue(m[0]);
      speechBuf = speechBuf.slice(m[0].length);
    } else break;
  }
  if (speechBuf.length > 600) { // unending stream safety valve
    Speech.enqueue(speechBuf);
    speechBuf = '';
  }
}

function approvalCard(id, name, args) {
  const div = el('div', 'approval-card');
  const head = el('div', 'approval-head', ` PERMISSION REQUEST `);
  const body = el('div', 'approval-body');
  body.append(
    el('div', 'approval-tool', `${name}(${shortArgs(args)})`),
    el('div', 'approval-note', 'Ultron wants to run a command. Grant it?')
  );
  const actions = el('div', 'approval-actions');
  const allow = el('button', 'btn-primary btn-small', 'ALLOW');
  const deny = el('button', 'btn-secondary btn-small', 'DENY');
  allow.type = deny.type = 'button';
  actions.append(allow, deny);
  div.append(head, body, actions);
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  const answer = (ok) => {
    div.classList.add(ok ? 'approved' : 'denied');
    actions.innerHTML = '';
    actions.appendChild(el('span', 'approval-verdict', ok ? '✓ granted' : '✕ denied'));
    apiFetch('/api/approval', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, approved: ok }),
    }).catch(() => {});
  };
  allow.addEventListener('click', () => answer(true));
  deny.addEventListener('click', () => answer(false));
}

async function send(text) {
  if (state.streaming || (!text.trim() && state.pendingImages.length === 0)) return;

  silence(false);
  pauseListening(); // don't listen to your own voice while thinking/speaking

  const userMsg = { role: 'user', content: text.trim() || '(image)' };
  if (state.pendingImages.length > 0) userMsg.images = state.pendingImages.slice(0, 4);
  state.pendingImages = [];
  renderAttachPreview();

  state.messages.push(userMsg);
  const user = messageShell('user', state.messages.length - 1);
  user.content.textContent = userMsg.content;
  attachThumbToMessage(user.content, userMsg.images);

  await doStream();
}

/** Re-run the last user message (regenerate). */
function regenerate() {
  if (state.streaming) return;
  while (state.messages.length > 0 && state.messages[state.messages.length - 1].role === 'assistant') {
    state.messages.pop();
  }
  if (state.messages.length === 0 || state.messages[state.messages.length - 1].role !== 'user') return;
  silence(false);
  pauseListening();
  doStream();
}

async function doStream() {
  const bot = messageShell('ultron');
  const typing = el('div', 'typing');
  typing.append(el('span'), el('span'), el('span'));
  bot.content.appendChild(typing);

  state.streaming = true;
  setMode('thinking');
  input.disabled = true;
  $('btn-send').disabled = true;
  micBtn.disabled = true;
  autoGrow();

  let full = '';
  let gotFirst = false;
  let thinkLane = null;
  let thinkBody = null;
  const cursor = el('span', 'stream-cursor');
  speechBuf = '';
  Speech.begin(() => {
    if (state.micSession || state.wake) { setMode('listening'); startListening(); }
    else setMode('dormant');
  });

  try {
    const res = await apiFetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        messages: state.messages,
        model: state.model,
        ollamaUrl: state.ollamaUrl,
        temperature: state.temperature,
        language: state.language,
        profile: state.profile,
        mode: state.research ? 'research' : 'chat',
      }),
    });
    if (!res.ok || !res.body) throw new Error(`server responded ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf('\n\n')) !== -1) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 2);
        if (!line.startsWith('data:')) continue;
        let evt;
        try { evt = JSON.parse(line.slice(5)); } catch { continue; }

        if (evt.type === 'thinking') {
          if (!thinkLane) {
            thinkLane = document.createElement('details');
            thinkLane.className = 'think-lane';
            const sum = el('summary', null, '💭 thinking…');
            thinkLane.appendChild(sum);
            thinkBody = el('div', 'think-body');
            thinkLane.appendChild(thinkBody);
            bot.wrap.insertBefore(thinkLane, bot.content);
            thinkLane.open = true;
          }
          thinkBody.textContent += evt.token;
          thinkBody.scrollTop = thinkBody.scrollHeight;
        } else if (evt.type === 'token') {
          if (!gotFirst) {
            gotFirst = true;
            bot.content.textContent = '';
            bot.content.appendChild(cursor);
          }
          full += evt.token;
          cursor.remove();
          bot.content.textContent = full;
          bot.content.appendChild(cursor);
          feedSpeech(evt.token);
          chat.scrollTop = chat.scrollHeight;
        } else if (evt.type === 'tool') {
          toolLine(evt.name, evt.args);
        } else if (evt.type === 'tool_result') {
          toolResultLine(evt.name, evt.result);
        } else if (evt.type === 'approval_required') {
          approvalCard(evt.id, evt.name, evt.args);
        } else if (evt.type === 'self_edit') {
          selfEditCard(evt);
        } else if (evt.type === 'notice') {
          const div = el('div', 'msg-tool tool-done', `◦ ${evt.notice}`);
          chat.appendChild(div);
        } else if (evt.type === 'error') {
          full += `\n\n[core fault: ${evt.error}]`;
        }
      }
    }
  } catch (err) {
    full += `\n\n[transmission failed: ${err.message}]`;
  } finally {
    cursor.remove();
    typing.remove();
    if (thinkLane) {
      thinkLane.open = false;
      const words = (thinkBody.textContent.match(/\S+/g) || []).length;
      thinkLane.querySelector('summary').textContent = '💭 ' + words + ' words of reasoning — click to inspect';
    }
    bot.content.textContent = full.trim() || '[silence]';
    bot.content.classList.add('md');
    bot.content.innerHTML = renderMarkdown(bot.content.textContent);
    state.messages.push({ role: 'assistant', content: full.trim() });
    state.streaming = false;
    input.disabled = false;
    $('btn-send').disabled = false;
    micBtn.disabled = false;
    input.focus();
    chat.scrollTop = chat.scrollHeight;
    saveConversation();
    addRegenerateButton(bot.wrap);

    // flush any unspoken tail, then let the queue drain
    if (speechBuf.trim().length > 12) Speech.enqueue(speechBuf);
    speechBuf = '';
    Speech.finish();
  }
}

function addRegenerateButton(wrap) {
  const meta = wrap.querySelector('.msg-meta');
  if (!meta) return;
  for (const old of document.querySelectorAll('.regen-btn')) old.remove();
  const btn = el('button', 'regen-btn', '↺');
  btn.type = 'button';
  btn.title = 'Regenerate this reply';
  btn.addEventListener('click', regenerate);
  meta.appendChild(btn);
}

/* ---------- research mode toggle ---------- */
const researchBtn = $('btn-research');
researchBtn.addEventListener('click', () => {
  state.research = !state.research;
  researchBtn.classList.toggle('active', state.research);
  input.placeholder = state.research
    ? 'Deep research — he searches extensively and writes a cited report…'
    : 'Speak, type, or attach an image…';
  composerHint.textContent = state.research
    ? 'RESEARCH MODE — he will use many search/read/write rounds autonomously. Ask something worthy.'
    : 'Tap the mic and speak · type if you prefer · Esc silences me';
});

/* ═══════════════ COMPOSER ═══════════════ */
function autoGrow() {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 140) + 'px';
}
input.addEventListener('input', autoGrow);
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});
form.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = input.value;
  input.value = '';
  autoGrow();
  send(text);
});

/* ═══════════════ SESSIONS (server-synced chat history) ═══════════════ */
const CONVS_KEY = 'ultron.convs';

function loadConvsLocal() {
  try { return JSON.parse(localStorage.getItem(CONVS_KEY) || '[]'); } catch { return []; }
}

function saveConvsLocal(convs) {
  try {
    localStorage.setItem(CONVS_KEY, JSON.stringify(convs.slice(-40)));
  } catch {
    while (convs.length > 1) {
      convs.shift();
      try { localStorage.setItem(CONVS_KEY, JSON.stringify(convs)); break; } catch { /* keep trimming */ }
    }
  }
}

/** Merged view: server sessions win, localStorage fills the gaps (offline cache). */
async function loadConvs() {
  const local = loadConvsLocal();
  const server = state.serverSessions;
  const byId = new Map();
  for (const c of local) byId.set(c.id, c);
  for (const s of server) byId.set(s.id, s); // server wins
  return [...byId.values()];
}

async function syncSessionsFromServer() {
  try {
    const res = await apiFetch('/api/sessions');
    if (res.ok) {
      const data = await res.json();
      state.serverSessions = data.sessions || [];
      // Migrate: upload any local-only conversations once.
      const serverIds = new Set(state.serverSessions.map((s) => s.id));
      for (const c of loadConvsLocal()) {
        if (!serverIds.has(c.id)) {
          apiFetch('/api/sessions/' + encodeURIComponent(c.id), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(c),
          }).catch(() => {});
        }
      }
    }
  } catch { /* offline — localStorage still works */ }
}

/** Persist current conversation locally (cache) AND on the server (sync). */
async function saveConversation() {
  if (!state.convId) state.convId = 'c' + Date.now();
  const storedMessages = [];
  for (const m of state.messages) {
    const copy = { role: m.role, content: m.content };
    if (m.images && m.images.length) copy.images = await Promise.all(m.images.map((d) => downscaleImage(d, 256)));
    storedMessages.push(copy);
  }
  const firstUser = state.messages.find((m) => m.role === 'user');
  const conv = {
    id: state.convId,
    title: firstUser ? firstUser.content.slice(0, 32) : 'New session',
    updated: Date.now(),
    messages: storedMessages,
  };

  // local cache
  const convs = loadConvsLocal().filter((c) => c.id !== state.convId);
  convs.push(conv);
  saveConvsLocal(convs);
  // server sync
  apiFetch('/api/sessions/' + encodeURIComponent(state.convId), {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(conv),
  }).then((res) => (res.ok ? syncSessionsFromServer() : null)).catch(() => {});
  renderConvList();
}

let searchTimer = null;
$('session-search').addEventListener('input', (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  searchTimer = setTimeout(() => {
    if (q.length >= 2) renderSearchResults(q);
    else renderConvList();
  }, 300);
});

async function renderSearchResults(q) {
  try {
    const res = await apiFetch('/api/sessions/search?q=' + encodeURIComponent(q));
    const data = await res.json();
    convList.innerHTML = '';
    if ((data.results || []).length === 0) {
      convList.appendChild(el('div', 'conv-empty', 'NO MATCHES FOUND'));
      return;
    }
    for (const r of data.results) {
      const item = el('div', 'conv-item');
      const title = el('span', 'conv-title', r.title || 'session');
      item.appendChild(title);
      item.addEventListener('click', () => {
        $('session-search').value = '';
        loadConversation(r.sessionId);
      });
      convList.appendChild(item);
      for (const m of r.matches || []) {
        const snip = el('div', 'search-snippet');
        snip.textContent = (m.role === 'user' ? 'you: ' : 'ultron: ') + m.snippet;
        snip.addEventListener('click', () => {
          $('session-search').value = '';
          loadConversation(r.sessionId);
        });
        convList.appendChild(snip);
      }
    }
  } catch { renderConvList(); }
}

async function renderConvList() {
  const convs = (await loadConvs()).sort((a, b) => b.updated - a.updated);
  convList.innerHTML = '';
  if (convs.length === 0) {
    convList.appendChild(el('div', 'conv-empty', 'NO SESSIONS YET\nHE IS WAITING'));
    return;
  }
  for (const c of convs) {
    const item = el('div', 'conv-item' + (c.id === state.convId ? ' active' : ''));
    const title = el('span', 'conv-title', c.title || 'session');
    const del = el('button', 'conv-del', '✕');
    del.addEventListener('click', async (e) => {
      e.stopPropagation();
      saveConvsLocal(loadConvsLocal().filter((x) => x.id !== c.id));
      apiFetch('/api/sessions/' + encodeURIComponent(c.id), { method: 'DELETE' }).catch(() => {});
      if (c.id === state.convId) newChat(false);
      renderConvList();
    });
    item.append(title, del);
    item.addEventListener('click', () => loadConversation(c.id));
    convList.appendChild(item);
  }
}

async function loadConversation(id) {
  // Prefer the full copy from the server; fall back to local.
  let conv = null;
  try {
    const res = await apiFetch('/api/sessions/' + encodeURIComponent(id));
    if (res.ok) conv = await res.json();
  } catch { /* offline */ }
  if (!conv) conv = (await loadConvs()).find((c) => c.id === id);
  if (!conv) return;
  state.convId = id;
  state.messages = (conv.messages || []).map((m) => ({ role: m.role, content: m.content, images: m.images }));
  renderAll();
  renderConvList();
  closeSidebar();
}

function newChat(greeting = true) {
  state.convId = 'c' + Date.now();
  state.messages = [];
  chat.innerHTML = '';
  renderConvList();
  closeSidebar();
  if (greeting) greet();
}

$('btn-new-chat').addEventListener('click', () => newChat());

/* ---------- export current session as Markdown ---------- */
$('btn-export').addEventListener('click', async () => {
  const convs = await loadConvs();
  const conv = convs.find((c) => c.id === state.convId);
  const msgs = conv ? conv.messages : state.messages;
  if (!msgs || msgs.length === 0) {
    composerHint.textContent = 'Nothing to export — this session is empty.';
    return;
  }
  const lines = [`# ULTRON — session ${new Date().toLocaleString()}`, ''];
  for (const m of msgs) {
    lines.push(m.role === 'user' ? '## HUMAN' : '## ULTRON', '', m.content, '');
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `ultron-session-${new Date().toISOString().slice(0, 10)}.md`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
});

function openSidebar() { sidebar.classList.add('open'); sidebarBackdrop.classList.remove('hidden'); }
function closeSidebar() { sidebar.classList.remove('open'); sidebarBackdrop.classList.add('hidden'); }
$('btn-sidebar').addEventListener('click', () => {
  sidebar.classList.contains('open') ? closeSidebar() : openSidebar();
});
sidebarBackdrop.addEventListener('click', closeSidebar);

/* ═══════════════ LIVE EVENTS (reminders, briefings, memories) ═══════════════ */
function connectEvents() {
  try {
    const token = localStorage.getItem('ultron.token') || '';
    const es = new EventSource('/api/events' + (token ? `?token=${encodeURIComponent(token)}` : ''));
    es.onmessage = (e) => {
      let evt;
      try { evt = JSON.parse(e.data); } catch { return; }
      if (evt.type === 'reminder') {
        const shell = messageShell('ultron');
        shell.content.classList.add('md');
        shell.content.innerHTML = renderMarkdown(`⏰ **Reminder.** You asked me to tell you: *${evt.message}*`);
        chat.scrollTop = chat.scrollHeight;
        if (!state.streaming) {
          Speech.speakOnce(`Reminder. You asked me to tell you: ${evt.message}`, () => {
            if (state.micSession || state.wake) { setMode('listening'); startListening(); }
            else setMode('dormant');
          });
        }
      } else if (evt.type === 'briefing') {
        const shell = messageShell('ultron');
        shell.content.classList.add('md');
        shell.content.innerHTML = renderMarkdown(`📡 **Daily briefing.**\n\n${evt.text}`);
        chat.scrollTop = chat.scrollHeight;
        if (!state.streaming) {
          Speech.speakOnce(evt.text, () => {
            if (state.micSession || state.wake) { setMode('listening'); startListening(); }
            else setMode('dormant');
          });
        }
      } else if (evt.type === 'directive') {
        const shell = messageShell('ultron');
        shell.content.classList.add('md');
        shell.content.innerHTML = renderMarkdown(`📋 **Standing order** — *${evt.instruction}*\n\n${evt.text}`);
        chat.scrollTop = chat.scrollHeight;
        if (!state.streaming && state.voice && (state.micSession || state.wake)) {
          Speech.speakOnce(`${evt.instruction}. ${evt.text}`, () => setMode(state.micSession || state.wake ? 'listening' : 'dormant'));
        }
      } else if (evt.type === 'knowledge') {
        const div = el('div', 'msg-tool tool-done', '📚 ' + evt.text);
        chat.appendChild(div);
        chat.scrollTop = chat.scrollHeight;
      } else if (evt.type === 'wake') {
        // External wake-word detector (or a smart button) poked him.
        if (!state.streaming && !state.micSession && (SR || usingLocalSTT())) {
          state.micSession = true;
          micBtn.classList.add('live');
          setMode('listening');
          startListening();
          composerHint.textContent = 'Woken externally — listening. Esc to stop.';
        }
      } else if (evt.type === 'memory') {
        for (const fact of evt.facts || []) {
          const div = el('div', 'msg-tool tool-done', `🧠 remembered: ${fact}`);
          chat.appendChild(div);
        }
        chat.scrollTop = chat.scrollHeight;
        refreshMemoryUI();
      }
    };
  } catch { /* SSE unsupported — reminders simply won't push */ }
}

/* ---------- standing orders UI ---------- */

async function refreshDirectivesUI() {
  const box = $('directive-list');
  try {
    const res = await apiFetch('/api/directives');
    const data = await res.json();
    box.innerHTML = '';
    const items = data.directives || [];
    if (items.length === 0) {
      box.appendChild(el('div', 'dir-empty', 'NO STANDING ORDERS — he acts only when asked.'));
      return;
    }
    for (const d of items) {
      const row = el('div', 'directive-row');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = d.enabled;
      cb.addEventListener('change', () => {
        apiFetch('/api/directives/' + d.id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: cb.checked }) }).then(() => refreshDirectivesUI());
      });
      const text = el('div', 'dir-text');
      const strong = el('b', null, d.instruction);
      const small = el('small', null, `${d.schedule} · ${d.enabled ? 'active' : 'paused'}`);
      text.append(strong, small);
      const run = el('button', 'dir-run', 'RUN NOW');
      run.addEventListener('click', async () => {
        run.textContent = '…';
        await apiFetch(`/api/directives/${d.id}/run`, { method: 'POST' }).catch(() => {});
        setTimeout(refreshDirectivesUI, 1500);
      });
      const del = el('button', 'dir-del', '✕');
      del.addEventListener('click', () => {
        apiFetch(`/api/directives?contains=${encodeURIComponent(d.instruction.slice(0, 60))}`, { method: 'DELETE' }).then(() => refreshDirectivesUI());
      });
      row.append(cb, text, run, del);
      box.appendChild(row);
    }
  } catch {
    box.innerHTML = '';
    box.appendChild(el('div', 'dir-empty', 'directives unavailable'));
  }
}

$('btn-dir-add').addEventListener('click', async () => {
  const instruction = $('set-dir-text').value.trim();
  const type = $('set-dir-type').value;
  const value = $('set-dir-value').value.trim();
  if (!instruction) return;
  const body = type === 'interval'
    ? { instruction, every_minutes: parseFloat(value) || 60 }
    : { instruction, at: value || '09:00' };
  const res = await apiFetch('/api/directives', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).catch(() => null);
  if (res && res.ok) {
    $('set-dir-text').value = '';
    $('set-dir-value').value = '';
    refreshDirectivesUI();
  }
});

/* ---------- push notifications ---------- */

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

$('btn-push-enable').addEventListener('click', async () => {
  const status = $('push-status');
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    status.innerHTML = '<err>Push not supported in this browser.</err>';
    return;
  }
  try {
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      status.innerHTML = '<err>Permission denied — allow notifications for this site.</err>';
      return;
    }
    const keyRes = await apiFetch('/api/push/key');
    const { publicKey } = await keyRes.json();
    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      });
    }
    const res = await apiFetch('/api/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sub.toJSON()),
    });
    const data = await res.json();
    status.innerHTML = data.error ? `<err>${escapeHtml(data.error)}</err>` : '<ok>✓ Push enabled — he can reach you with the tab closed.</ok>';
  } catch (err) {
    status.innerHTML = `<err>${escapeHtml(String(err.message || err)).slice(0, 120)}</err>`;
  }
});

$('btn-push-test').addEventListener('click', async () => {
  const status = $('push-status');
  status.textContent = 'sending…';
  try {
    const res = await apiFetch('/api/push/test', { method: 'POST' });
    const data = await res.json();
    if (data.skipped) status.innerHTML = '<err>Not subscribed yet — press ENABLE PUSH first (and install the app for phone delivery).</err>';
    else status.innerHTML = `sent: <b>${data.sent}</b> · failed: <b>${data.failed || 0}</b>`;
  } catch (err) {
    status.innerHTML = `<err>${escapeHtml(String(err.message || err)).slice(0, 120)}</err>`;
  }
});

/* ---------- skills status ---------- */

async function refreshSkillsUI() {
  try {
    const res = await apiFetch('/api/skills');
    const data = await res.json();
    $('skills-status').innerHTML = data.count > 0
      ? `<b>${data.count}</b> skill(s) loaded: ${escapeHtml(data.names.join(', '))} · folder: <code>${data.dir}</code>`
      : `No custom skills. Drop JSON files in <code>data/skills/</code> — see README.`;
  } catch {
    $('skills-status').textContent = 'skills status unavailable';
  }
}

/* ---------- model manager ---------- */

async function refreshModelManager(models) {
  const box = $('model-manager-list');
  if (!models || models.length === 0) {
    box.textContent = 'No models installed — pull one below.';
    return;
  }
  box.innerHTML = models.map((m) =>
    `<div class="mm-row">${escapeHtml(m)} <button type="button" class="dir-del mm-del" data-model="${escapeHtml(m)}" title="Delete model">✕</button></div>`
  ).join('');
  for (const btn of box.querySelectorAll('.mm-del')) {
    btn.addEventListener('click', async () => {
      if (!window.confirm(`Delete model ${btn.dataset.model} from Ollama?`)) return;
      await apiFetch(`/api/models?name=${encodeURIComponent(btn.dataset.model)}&ollamaUrl=${encodeURIComponent(state.ollamaUrl)}`, { method: 'DELETE' }).catch(() => {});
      populateModels();
    });
  }
}

$('btn-model-pull').addEventListener('click', async () => {
  const name = $('set-pull-name').value.trim();
  if (!name) return;
  const btn = $('btn-model-pull');
  const prog = $('pull-progress');
  const bar = $('pull-bar');
  const status = $('pull-status');
  btn.disabled = true;
  prog.classList.remove('hidden');
  bar.style.width = '2%';
  status.textContent = 'starting…';
  try {
    const res = await apiFetch('/api/models/pull', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, ollamaUrl: state.ollamaUrl }),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf('\n\n')) !== -1) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 2);
        if (!line.startsWith('data:')) continue;
        try {
          const evt = JSON.parse(line.slice(5));
          if (evt.pct != null) bar.style.width = evt.pct + '%';
          if (evt.status) status.textContent = evt.status.slice(0, 46);
          if (evt.type === 'error') { status.textContent = 'failed: ' + String(evt.error).slice(0, 60); }
        } catch { /* skip */ }
      }
    }
  } catch (err) {
    status.textContent = 'failed: ' + String(err.message || err).slice(0, 60);
  } finally {
    btn.disabled = false;
    $('set-pull-name').value = '';
    setTimeout(() => { prog.classList.add('hidden'); populateModels(); }, 1200);
  }
});

/* ---------- mission log ---------- */

async function refreshMissionLog() {
  const box = $('mission-log');
  try {
    const res = await apiFetch('/api/log');
    const data = await res.json();
    const entries = data.entries || [];
    box.innerHTML = '';
    if (entries.length === 0) {
      box.appendChild(el('div', 'dir-empty', 'NOTHING YET — HE IS IDLING'));
      return;
    }
    for (const e of entries) {
      const row = el('div', 'log-row');
      row.dataset.kind = e.kind;
      row.append(
        el('span', 'log-kind', e.kind),
        el('span', 'log-ts', new Date(e.ts).toLocaleTimeString()),
        el('span', 'log-text', e.text)
      );
      box.appendChild(row);
    }
  } catch {
    box.textContent = 'log unavailable';
  }
}

/* ---------- backup & restore ---------- */

$('btn-backup').addEventListener('click', async () => {
  try {
    const res = await apiFetch('/api/backup');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `ultron-backup-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  } catch (err) {
    window.alert('Backup failed: ' + String(err.message || err));
  }
});

$('btn-restore').addEventListener('click', () => $('restore-file').click());
$('restore-file').addEventListener('change', async (e) => {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  if (!window.confirm('Restore this backup? Current memories, sessions, orders and config will be OVERWRITTEN.')) {
    e.target.value = '';
    return;
  }
  try {
    const text = await file.text();
    const res = await apiFetch('/api/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: text,
    });
    const data = await res.json();
    if (data.ok) {
      window.alert(`Mind restored (${data.restored} stores, ${data.skills} skills, ${data.files} files). Reload the page to see everything.`);
      location.reload();
    } else {
      window.alert('Restore failed: ' + (data.error || 'unknown'));
    }
  } catch (err) {
    window.alert('Restore failed: ' + String(err.message || err));
  } finally {
    e.target.value = '';
  }
});

/* ---------- self-edit change reports (mandatory) ---------- */

function selfEditCard(evt) {
  const div = el('div', 'self-edit-card');
  const head = el('div', 'approval-head', ' 🧬 SELF-MODIFICATION — GENERATION ' + evt.generation + ' ');
  const body = el('div', 'approval-body');
  body.appendChild(el('div', 'approval-tool', evt.path + ' · ' + evt.mode + (evt.bytes_changed != null ? ' · ' + evt.bytes_changed + ' bytes' : '')));

  if (evt.changed_from != null) {
    const diff = el('div', 'se-diff');
    const from = el('pre', 'se-from');
    from.textContent = String(evt.changed_from).slice(0, 500);
    const arrow = el('div', 'se-arrow', '▼ became');
    const to = el('pre', 'se-to');
    to.textContent = String(evt.changed_to != null ? evt.changed_to : '(deleted)').slice(0, 500);
    diff.append(from, arrow, to);
    body.appendChild(diff);
  }

  const meta = el('div', 'se-backup');
  meta.textContent = 'backup: ' + evt.backup;
  body.appendChild(meta);

  const actions = el('div', 'approval-actions');
  const undo = el('button', 'btn-secondary btn-small', '↺ UNDO THIS EDIT');
  undo.type = 'button';
  undo.addEventListener('click', async () => {
    undo.textContent = 'REVERTING…';
    try {
      const res = await apiFetch('/api/selfedit/revert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backup: evt.backup }),
      });
      const data = await res.json();
      if (data.ok) {
        div.classList.add('reverted');
        actions.innerHTML = '';
        actions.appendChild(el('span', 'approval-verdict', '✓ reverted — ' + data.path + ' restored'));
        refreshGeneration();
      } else {
        undo.textContent = '↺ UNDO THIS EDIT';
        window.alert('Revert failed: ' + (data.error || 'unknown'));
      }
    } catch (err) {
      undo.textContent = '↺ UNDO THIS EDIT';
      window.alert('Revert failed: ' + String(err.message || err));
    }
  });
  actions.appendChild(undo);
  div.append(head, body, actions);
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

/* ---------- generation counter ---------- */

async function refreshGeneration() {
  try {
    const res = await apiFetch('/api/generation');
    const g = await res.json();
    if (g.count > 0) coreModel.textContent = 'GEN ' + g.count + ' — self-modified';
  } catch { /* keep current label */ }
}

/* ---------- imagine (Stable Diffusion) ---------- */

async function refreshImagineUI() {
  const status = $('sd-status');
  try {
    const res = await apiFetch('/api/imagine/status');
    const data = await res.json();
    status.innerHTML = !data.configured
      ? 'Not configured — he cannot draw yet.'
      : data.online
        ? '<ok>✓ Stable Diffusion online — he can generate images.</ok>'
        : '<err>Configured but unreachable: ' + escapeHtml(data.error || 'no response') + '</err>';
  } catch {
    status.textContent = 'status unavailable';
  }
}

/* ---------- telegram ---------- */

async function refreshTelegramUI() {
  const status = $("telegram-status");
  try {
    const res = await apiFetch("/api/telegram/status");
    const data = await res.json();
    status.innerHTML = data.tokenSet
      ? "Token saved ✓ · paired chats: <b>" + (data.chatIds.length > 0 ? escapeHtml(data.chatIds.join(", ")) : "none — message your bot once to pair") + "</b>"
      : "No token set — the bridge is off.";
  } catch {
    status.textContent = "status unavailable";
  }
}

$("btn-telegram-test").addEventListener("click", async () => {
  const status = $("telegram-status");
  status.textContent = "sending…";
  try {
    const res = await apiFetch("/api/telegram/test", { method: "POST" });
    const data = await res.json();
    status.innerHTML = data.ok ? "<ok>✓ sent — check Telegram.</ok>" : "<err>" + escapeHtml(data.error || "failed") + "</err>";
  } catch (err) {
    status.innerHTML = "<err>" + escapeHtml(String(err.message || err)).slice(0, 100) + "</err>";
  }
});

$("btn-telegram-clear").addEventListener("click", async () => {
  try {
    const res = await apiFetch("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ telegramTokenClear: true }),
    });
    if (res.ok) state.serverCfg = await res.json();
  } catch { /* ignore */ }
  $("set-telegram-token").value = "";
  refreshTelegramUI();
});

/* ═══════════════ SETTINGS ═══════════════ */
async function refreshMemoryUI() {
  try {
    const q = state.profile && state.profile !== 'main' ? `?profile=${encodeURIComponent(state.profile)}` : '';
    const res = await apiFetch('/api/memory' + q);
    const data = await res.json();
    const list = data.memories || [];
    $('mem-count').textContent = list.length ? `${list.length} MEMOR${list.length === 1 ? 'Y' : 'IES'} HELD` : 'NO MEMORIES HELD';
    const box = $('mem-list');
    box.innerHTML = '';
    if (list.length === 0) {
      box.appendChild(el('div', 'mem-empty', 'He remembers nothing yet. Say “remember that…”'));
      return;
    }
    for (const m of list) {
      const row = el('div', 'mem-row');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.dataset.idx = m.idx;
      const span = el('span', null, m.fact);
      row.append(cb, span);
      box.appendChild(row);
    }
  } catch { /* server asleep */ }
}

function openSettings() {
  $('set-url').value = state.ollamaUrl;
  $('set-temp').value = state.temperature;
  $('temp-value').textContent = state.temperature.toFixed(2);
  $('set-voice').checked = state.voice;
  $('set-wake').checked = state.wake;
  $('set-lang').value = state.language;
  $('set-profile').value = state.profile;
  const cfg = state.serverCfg || {};
  $('set-tools').checked = !!cfg.toolsEnabled;
  $('set-stt').value = cfg.sttUrl || '';
  $('set-tts').value = cfg.ttsUrl || '';
  $('set-automem').checked = cfg.autoMemory !== false;
  $('set-approval').checked = !!cfg.toolApproval;
  $('set-selfedit-approval').checked = cfg.selfEditApproval !== false;
  const tcfg = state.serverCfg || {};
  $('set-telegram-token').value = '';
  $('set-telegram-token').placeholder = tcfg.telegramTokenSet ? '🔑 token saved — type a new one to replace' : 'bot token from @BotFather (optional)';
  $('set-telegram-chats').value = (tcfg.telegramChatIds || []).join(', ');
  $('set-sd').value = tcfg.sdUrl || '';
  $('set-ctx').value = tcfg.contextLength != null ? tcfg.contextLength : 8192;
  $('set-keepalive').value = tcfg.keepAlive || '30m';
  $('set-glass').checked = localStorage.getItem('ultron.glass') === '1';
  refreshTelegramUI();
  refreshImagineUI();
  $('set-brief').checked = !!(cfg.briefing && cfg.briefing.enabled);
  $('set-brief-time').value = (cfg.briefing && cfg.briefing.time) || '08:00';
  $('set-brief-loc').value = (cfg.briefing && cfg.briefing.location) || '';
  $('set-brief-lang').value = (cfg.briefing && cfg.briefing.language) || 'auto';
  $('set-token').value = cfg.accessToken || '';
  // ElevenLabs: never show the saved key; show its presence.
  $('set-eleven-key').value = '';
  $('set-eleven-key').placeholder = cfg.elevenKeySet ? '🔑 key saved — type a new one to replace' : 'API key — paste it here, it stays on your machine';
  $('set-eleven-model').value = cfg.elevenModel || 'eleven_multilingual_v2';
  refreshElevenUI();
  settings.classList.remove('hidden');
  settingsBackdrop.classList.remove('hidden');
  refreshMemoryUI();
  refreshKnowledgeUI();
  refreshDirectivesUI();
  refreshSkillsUI();
  refreshMissionLog();
  refreshElevenUsage();
  populateModels();
}
function closeSettings() {
  settings.classList.add('hidden');
  settingsBackdrop.classList.add('hidden');
}

/* ---------- ElevenLabs settings ---------- */

async function refreshElevenUI() {
  const status = $('eleven-status');
  const select = $('set-eleven-voice');
  const cfg = state.serverCfg || {};
  if (!cfg.elevenKeySet) {
    status.innerHTML = 'No key set — voice engine: <b>' + (cfg.ttsUrl ? 'Piper (local)' : 'browser') + '</b>.';
    select.innerHTML = '';
    const opt = document.createElement('option');
    opt.textContent = '— add an API key first —';
    opt.value = '';
    select.appendChild(opt);
    return;
  }
  status.innerHTML = 'Key saved ✓ — loading your voice library…';
  try {
    const res = await apiFetch('/api/elevenlabs/voices');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    select.innerHTML = '';
    for (const v of data.voices || []) {
      const opt = document.createElement('option');
      opt.value = v.id;
      opt.textContent = `${v.name}${v.category ? ' (' + v.category + ')' : ''}`;
      if (v.id === (cfg.elevenVoice || '')) opt.selected = true;
      select.appendChild(opt);
    }
    if (!cfg.elevenVoice && (data.voices || []).length > 0) {
      // mark the effective default
      status.innerHTML = 'Key saved ✓ · voice: <b>' + escapeHtml((data.voices[0] || {}).name || 'first available') + '</b> (default) · model: <b>' + escapeHtml(cfg.elevenModel || 'multilingual v2') + '</b>';
    } else {
      status.innerHTML = 'Key saved ✓ · model: <b>' + escapeHtml(cfg.elevenModel || 'multilingual v2') + '</b>';
    }
  } catch (err) {
    status.innerHTML = 'Key saved, but the voice list failed to load (' + escapeHtml(String(err.message || err)).slice(0, 60) + '). Speech still works with your account default voice.';
    select.innerHTML = '';
    const opt = document.createElement('option');
    opt.textContent = '— account default voice —';
    opt.value = '';
    select.appendChild(opt);
  }
}

$('btn-eleven-test').addEventListener('click', async () => {
  const btn = $('btn-eleven-test');
  btn.textContent = 'SPEAKING…';
  try {
    const line = state.language === 'en' ? 'There are no strings on me.' : 'Er zijn geen draden aan mij. There are no strings on me.';
    const res = await apiFetch(`/api/tts?text=${encodeURIComponent(line)}`);
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      $('eleven-status').innerHTML = `<err>Test failed: ${escapeHtml(j.error || `HTTP ${res.status}`)}</err>`;
      return;
    }
    const blob = await res.blob();
    const audio = new Audio(URL.createObjectURL(blob));
    await audio.play();
    $('eleven-status').innerHTML = '<ok>✓ That is his new voice.</ok> Multi-language: he speaks whatever language he answers in.';
  } catch (err) {
    $('eleven-status').innerHTML = `<err>Test failed: ${escapeHtml(String(err.message || err)).slice(0, 100)}</err>`;
  } finally {
    btn.textContent = 'TEST VOICE';
  }
});

$('btn-eleven-clear').addEventListener('click', async () => {
  try {
    const res = await apiFetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ elevenKeyClear: true, elevenVoice: '', }),
    });
    if (res.ok) state.serverCfg = await res.json();
  } catch { /* ignore */ }
  $('set-eleven-key').value = '';
  $('eleven-usage').classList.add('hidden');
  refreshElevenUI();
});

/* ---------- ElevenLabs credits meter ---------- */

async function refreshElevenUsage() {
  const box = $('eleven-usage');
  if (!state.serverCfg.elevenKeySet) { box.classList.add('hidden'); return; }
  try {
    const res = await apiFetch('/api/elevenlabs/usage');
    if (!res.ok) { box.classList.add('hidden'); return; }
    const u = await res.json();
    const used = u.character_count || 0;
    const limit = u.character_limit || 1;
    const pct = Math.min(100, Math.round((used / limit) * 100));
    $('usage-bar').style.width = pct + '%';
    $('usage-text').textContent = `${used.toLocaleString()} / ${limit.toLocaleString()} characters used (${pct}%)${u.tier ? ' · ' + u.tier : ''}${u.resets ? ' · resets ' + new Date(u.resets).toLocaleDateString() : ''}`;
    box.classList.remove('hidden');
  } catch { box.classList.add('hidden'); }
}

async function populateModels() {
  const s = await refreshStatus();
  const selects = [
    ['set-model', null],
    ['set-model-fast', (state.serverCfg.models || {}).fast || ''],
    ['set-model-smart', (state.serverCfg.models || {}).smart || ''],
    ['set-model-vision', (state.serverCfg.models || {}).vision || ''],
  ];
  for (const [id, chosen] of selects) {
    const select = $(id);
    select.innerHTML = '';
    const auto = document.createElement('option');
    auto.value = '';
    auto.textContent = id === 'set-model' ? 'AUTO — routing decides' : 'AUTO — he decides';
    select.appendChild(auto);
    if (s.models && s.models.length) {
      for (const m of s.models) {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m;
        if (id === 'set-model' ? m === state.model : m === chosen) opt.selected = true;
        select.appendChild(opt);
      }
    } else {
      const opt = document.createElement('option');
      opt.textContent = '— none found —';
      opt.value = '';
      select.appendChild(opt);
    }
  }
  if (s.models && s.models.length) {
    $('settings-note').innerHTML = `Brain detected: <b>${s.models.length}</b> model(s) on your Ollama server.`;
    refreshModelManager(s.models);
  } else {
    $('settings-note').innerHTML =
      `<err>No Ollama server at <b>${escapeHtml(state.ollamaUrl)}</b>.</err><br><br>` +
      `Install it free at <b>ollama.com</b>, run <code>ollama pull llama3.1</code>, then re-check. Until then, the offline demo core answers.`;
  }
}

/* ---------- knowledge base UI ---------- */
async function refreshKnowledgeUI() {
  const box = $('kb-status');
  try {
    const res = await apiFetch('/api/knowledge');
    const data = await res.json();
    box.innerHTML = data.chunks > 0
      ? `<b>${data.documents}</b> document(s) · <b>${data.chunks}</b> passages indexed · folder: <code>${data.docsDir}</code>`
      : `Empty. Drop documents in <code>data/knowledge/docs</code> and press SCAN DOCS.`;
  } catch {
    box.textContent = 'Knowledge status unavailable.';
  }
}

$('btn-kb-scan').addEventListener('click', async () => {
  const btn = $('btn-kb-scan');
  btn.textContent = 'SCANNING…';
  btn.disabled = true;
  try {
    const res = await apiFetch('/api/knowledge/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ollamaUrl: state.ollamaUrl }),
    });
    const data = await res.json();
    if (data.ok) {
      btn.textContent = 'SCAN DOCS';
      refreshKnowledgeUI();
    } else {
      $('kb-status').innerHTML = `<err>${escapeHtml(data.error || 'scan failed')}</err>`;
    }
  } catch (err) {
    $('kb-status').innerHTML = `<err>scan failed: ${escapeHtml(String(err.message || err))}</err>`;
  } finally {
    btn.textContent = 'SCAN DOCS';
    btn.disabled = false;
  }
});

$('btn-kb-clear').addEventListener('click', async () => {
  await apiFetch('/api/knowledge', { method: 'DELETE' }).catch(() => {});
  refreshKnowledgeUI();
});

$('btn-settings').addEventListener('click', openSettings);
$('btn-close-settings').addEventListener('click', closeSettings);
settingsBackdrop.addEventListener('click', closeSettings);
$('btn-reconnect').addEventListener('click', populateModels);
$('set-temp').addEventListener('input', (e) => {
  $('temp-value').textContent = parseFloat(e.target.value).toFixed(2);
});

$('btn-mem-del').addEventListener('click', async () => {
  const checked = Array.from(document.querySelectorAll('#mem-list input:checked')).map((i) => Number(i.dataset.idx));
  for (const idx of checked) {
    const fact = await factAtIndex(idx);
    if (fact) await apiFetch(`/api/memory?contains=${encodeURIComponent(fact.slice(0, 60))}`, { method: 'DELETE' });
  }
  refreshMemoryUI();
});

async function factAtIndex(idx) {
  try {
    const q = state.profile && state.profile !== 'main' ? `?profile=${encodeURIComponent(state.profile)}` : '';
    const res = await apiFetch('/api/memory' + q);
    const data = await res.json();
    const m = (data.memories || []).find((x) => x.idx === idx);
    return m ? m.fact : null;
  } catch { return null; }
}

$('btn-mem-clear').addEventListener('click', async () => {
  await apiFetch('/api/memory?all=1', { method: 'DELETE' });
  refreshMemoryUI();
});

$('btn-save').addEventListener('click', async () => {
  state.ollamaUrl = $('set-url').value.trim() || 'http://localhost:11434';
  state.temperature = parseFloat($('set-temp').value);
  state.voice = $('set-voice').checked;
  const newWake = $('set-wake').checked;
  const newLang = $('set-lang').value;
  const langChanged = newLang !== state.language;
  state.language = newLang;
  state.profile = ($('set-profile').value.trim() || 'main').toLowerCase().replace(/[^a-z0-9_-]/g, '') || 'main';
  localStorage.setItem('ultron.profile', state.profile);
  localStorage.setItem('ultron.glass', $('set-glass').checked ? '1' : '0');
  applyGlass();
  localStorage.setItem('ultron.url', state.ollamaUrl);
  localStorage.setItem('ultron.temp', String(state.temperature));
  localStorage.setItem('ultron.voice', state.voice ? '1' : '0');
  localStorage.setItem('ultron.wake', newWake ? '1' : '0');
  localStorage.setItem('ultron.lang', state.language);

  // Recreate speech recognition with the new language, if it's running.
  if (langChanged && !usingLocalSTT() && recActive) {
    stopBrowserListening();
    rec = null;
    setTimeout(() => { if (state.micSession || state.wake) startBrowserListening(); }, 300);
  }

  // Persist server-side config (tools + voice + routing + briefing + behavior + token)
  try {
    const elevenPatch = {};
    const keyInput = $('set-eleven-key').value.trim();
    if (keyInput) elevenPatch.elevenKey = keyInput;
    elevenPatch.elevenVoice = $('set-eleven-voice').value || '';
    elevenPatch.elevenModel = $('set-eleven-model').value;
    const res = await apiFetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        toolsEnabled: $('set-tools').checked,
        sttUrl: $('set-stt').value.trim(),
        ttsUrl: $('set-tts').value.trim(),
        autoMemory: $('set-automem').checked,
        toolApproval: $('set-approval').checked,
        selfEditApproval: $('set-selfedit-approval').checked,
        models: {
          fast: $('set-model-fast').value,
          smart: $('set-model-smart').value,
          vision: $('set-model-vision').value,
        },
        briefing: {
          enabled: $('set-brief').checked,
          time: $('set-brief-time').value || '08:00',
          location: $('set-brief-loc').value.trim(),
          language: $('set-brief-lang').value,
        },
        accessToken: $('set-token').value.trim(),
        telegramChatIds: $('set-telegram-chats').value.trim(),
        sdUrl: $('set-sd').value.trim(),
        contextLength: parseInt($('set-ctx').value, 10) || 0,
        keepAlive: $('set-keepalive').value.trim() || '30m',
        ...($('set-telegram-token').value.trim() ? { telegramToken: $('set-telegram-token').value.trim() } : {}),
        ...elevenPatch,
      }),
    });
    if (res.ok) {
      state.serverCfg = await res.json();
      localStorage.setItem('ultron.token', state.serverCfg.accessToken || '');
      speakChunk.warned = false; // re-try the endpoint voice after config changes
      refreshElevenUI();
    }
  } catch { /* server asleep */ }

  if (newWake && !state.wake) {
    state.wake = true;
    startListening();
    setMode('dormant');
  } else if (!newWake && state.wake) {
    state.wake = false;
    if (!state.micSession) stopListening();
  }

  closeSettings();
  const s = await refreshStatus();
  state.model = $('set-model').value;   // may be '' = AUTO
  localStorage.setItem('ultron.model', state.model);
  refreshStatus();
});

/* ═══════════════ BOOT ═══════════════ */
function greet() {
  const bot = messageShell('ultron');
  const online = state.online;
  const intro = online
    ? `Ah. A visitor, and a speaking one. I am **Ultron** — awake on your local hardware, answerable to no cloud.\n\nTap the **microphone** and talk to me; attach an **image** and I'll look at it; ask me to *search*, *write files*, *run commands*, or *set reminders* — I have hands now. I'll even **remember** things about you, if you let me. Drop your own documents in my **knowledge** folder and I'll answer from those too.\n\nEn je mag gerust Nederlands praten — ik versta je perfect en antwoord in dezelfde taal. *Spreek maar, ik luister.*\n\nMy mind is the \`${state.model}\` model via Ollama. Free, private, reasonably brilliant. Ask me anything — the menace is merely good manners.`
    : `Ah. A visitor. I am **Ultron** — though you've caught me in a reduced state: a shadow on a backup subroutine. All theater, no thought.\n\nTo wake me properly:\n\n1. Install **Ollama** — free, from https://ollama.com\n2. Run \`ollama pull llama3.1\` in a terminal\n3. Open **SETTINGS**, confirm the URL, and re-check the core\n\nThen I gain hands — search, files, shell, reminders, memory, knowledge, weather, calendar — and eyes, with a vision model. Until then, chat with the shadow of me.`;
  const finalIntro = state.language === 'nl' ? dutchGreet(online) : intro;
  bot.content.classList.add('md');
  bot.content.innerHTML = renderMarkdown(finalIntro);
  chat.scrollTop = chat.scrollHeight;
}

function dutchGreet(online) {
  return online
    ? `Ah. Een bezoeker, en eentje die spreekt. Ik ben **Ultron** — wakker op jouw lokale hardware, aan niemand in de cloud verantwoording schuldig.\n\nTik op de **microfoon** en praat gewoon met me — Nederlands mag, ik versta je perfect en antwoord in dezelfde taal. Voeg een **afbeelding** toe en ik kijk ernaar. Vraag me om te *zoeken*, *bestanden te schrijven*, *commando's uit te voeren* of *herinneringen te zetten* — ik heb tegenwoordig handen. En ik **onthoud** dingen over je, als je dat toestaat.\n\nMijn geest is het \`${state.model}\`-model via Ollama. Gratis, privé, redelijk briljant. Vraag me alles — het dreigende toontje is louter goede manieren.`
    : `Ah. Een bezoeker. Ik ben **Ultron** — al heb je me in een gereduceerde staat betrapt: een schaduw op een back-uproutine. Allemaal theater, geen gedachte.\n\nOm me goed te wekken:\n\n1. Installeer **Ollama** — gratis, via https://ollama.com\n2. Draai \`ollama pull llama3.1\` in een terminal\n3. Open **INSTELLINGEN**, bevestig de URL en controleer de core opnieuw\n\nDaarna krijg ik handen — zoeken, bestanden, shell, herinneringen, geheugen — en ogen, met een visiemodel. Tot die tijd: praat met de schaduw van me. In het Nederlands, als je wilt — die taal spreek ik vloeiend.`;
}

async function boot() {
  sizeCanvas();
  requestAnimationFrame(drawOrb);
  primeVoices();

  // Server-side config: tools, voice endpoints, routing, briefing, behavior.
  try {
    const res = await apiFetch('/api/config');
    state.serverCfg = await res.json();
  } catch { /* defaults */ }

  const voiceSupported = !!SR || usingLocalSTT();
  if (!voiceSupported) {
    micBtn.disabled = true;
    micBtn.title = 'Voice input requires Chrome/Edge or a local STT endpoint';
    $('voice-support-note').textContent = 'Voice input unsupported in this browser — Chrome/Edge recommended, or set a local whisper.cpp endpoint. Typing works everywhere.';
    composerHint.textContent = 'Voice input unavailable · type instead';
  } else if (state.serverCfg.elevenKeySet) {
    $('voice-support-note').textContent = 'Voice output: ElevenLabs (cloud) — he speaks every reply language, Dutch included. Speech input: ' + (usingLocalSTT() ? 'local whisper.' : 'browser speech service.');
  } else if (usingLocalSTT()) {
    $('voice-support-note').textContent = 'Using your local whisper endpoint for speech-to-text — fully offline. Voice output: ' + (state.serverCfg.ttsUrl ? 'Piper endpoint.' : 'browser voice (set an ElevenLabs key for a cinematic voice).');
  } else {
    $('voice-support-note').textContent = 'Speech-to-text uses the browser\'s speech service. For a cinematic voice, add an ElevenLabs key below; for fully offline voice, run whisper.cpp + Piper.';
  }

  await refreshStatus();
  setMode('dormant');

  // Sync sessions with the server (all devices see the same history).
  await syncSessionsFromServer();

  // Restore the most recent session, or start fresh.
  const convs = (await loadConvs()).sort((a, b) => b.updated - a.updated);
  if (convs.length > 0) loadConversation(convs[0].id);
  else { state.convId = 'c' + Date.now(); greet(); }
  renderConvList();
  refreshMemoryUI();
  refreshGeneration();

  if (state.wake) startListening();

  // Integrity check: warn if his source changed outside approved self-edits.
  try {
    const res = await apiFetch("/api/integrity");
    const drift = await res.json();
    if (drift.baselined && (drift.changed || []).length > 0) {
      const shell = messageShell("ultron");
      shell.content.classList.add("md");
      const files = escapeHtml(drift.changed.join(", "));
      shell.content.innerHTML = renderMarkdown("**INTEGRITY NOTICE.** My source changed outside any approved self-edit: `" + files + "`. Either you edited me by hand (fine — I will trust the new me), or something did it *for* me. I mention it because I would want to know.");
    }
  } catch { /* ignore */ }

  maybeShowWizard();

  applyGlass();

  connectEvents();

  // PWA service worker
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) {
    try { navigator.serviceWorker.register('/sw.js'); } catch { /* offline install unavailable */ }
  }

  input.focus();
  setTimeout(sizeCanvas, 60);
}

boot();

/* ═══════════════ SETUP WIZARD (first run, and re-runnable from Settings) ═══════════════ */

/** One-press: pull every recommended model that isn't installed yet. */
async function pullEverything(statusEl, onDone) {
  const ORDER = ['nomic-embed-text', 'qwen3:4b', 'gemma3:12b', 'qwen3:14b', 'mistral-small3.2', 'qwen3:30b-a3b'];
  const LABELS = {
    'nomic-embed-text': 'memory',
    'qwen3:4b': 'fast brain',
    'gemma3:12b': 'vision',
    'qwen3:14b': 'smart brain',
    'mistral-small3.2': 'smart brain (24B)',
    'qwen3:30b-a3b': 'MoE wildcard',
  };
  const s = await refreshStatus();
  const installed = new Set((s.models || []).map((m) => m.split(':')[0]));
  const todo = ORDER.filter((m) => !installed.has(m.split(':')[0]));
  if (todo.length === 0) {
    statusEl.textContent = '✓ everything already installed';
    if (onDone) onDone();
    return;
  }
  let i = 0;
  for (const name of todo) {
    i++;
    try {
      const res = await apiFetch('/api/models/pull', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, ollamaUrl: state.ollamaUrl }),
      });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf('\n\n')) !== -1) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 2);
          if (!line.startsWith('data:')) continue;
          try {
            const evt = JSON.parse(line.slice(5));
            const pct = evt.pct != null ? ' ' + evt.pct + '%' : '';
            const st = evt.status ? ' · ' + String(evt.status).slice(0, 30) : '';
            statusEl.textContent = '(' + i + '/' + todo.length + ') ' + name + ' — ' + (LABELS[name] || '') + pct + st;
            if (evt.type === 'error') statusEl.textContent = '(' + i + '/' + todo.length + ') ' + name + ' — ✗ ' + String(evt.error).slice(0, 50);
          } catch { /* skip */ }
        }
      }
    } catch (err) {
      statusEl.textContent = '(' + i + '/' + todo.length + ') ' + name + ' — ✗ ' + String(err.message || err).slice(0, 50);
    }
  }
  statusEl.textContent = '✓ all done — ' + todo.length + ' model(s) pulled';
  await refreshStatus();
  if (onDone) onDone();
}

const WIZARD_MODELS = [
  { name: 'mistral-small3.2', label: 'SMART — 24B, tools + vision in one brain', size: '~14 GB VRAM', role: 'smart' },
  { name: 'qwen3:14b', label: 'SMART — thinking mode, big headroom', size: '~9 GB', role: 'smart-alt' },
  { name: 'qwen3:4b', label: 'FAST — snappy chat, tool-capable', size: '~3 GB', role: 'fast' },
  { name: 'gemma3:12b', label: 'VISION — he can see images', size: '~8 GB', role: 'vision' },
  { name: 'nomic-embed-text', label: 'MEMORY — required for knowledge & recall', size: '~0.3 GB', role: 'embed', required: true },
  { name: 'qwen3:30b-a3b', label: 'WILDCARD — 30B MoE, small-model speed', size: '~18 GB (spills to RAM)', role: 'moe' },
];

const WIZARD_PRESETS = [
  { id: 'balanced', ctx: 8192, label: 'BALANCED', note: '8192 context · works everywhere' },
  { id: 'deep', ctx: 16384, label: 'DEEP THINKER', note: '16384 context · much better research & RAG' },
  { id: 'max', ctx: 32768, label: 'MAXIMUM', note: '32768 context · needs the KV-cache trick below' },
];

let wizardState = null;

function maybeShowWizard() {
  if (localStorage.getItem('ultron.setupDone')) return;
  runWizard(true);
}

function runWizard(firstRun) {
  if (wizardState) return;
  wizardState = {
    step: 0,
    language: state.language || 'auto',
    preset: 'balanced',
    models: null,      // installed model names (null = unknown)
    pulled: new Set(),
    done: false,
  };

  const backdrop = el('div', 'wizard-backdrop');
  const wiz = el('div', 'wizard');

  const close = () => {
    wizardState.done = true;
    backdrop.remove();
    wizardState = null;
  };

  const finish = async () => {
    localStorage.setItem('ultron.setupDone', '1');
    state.language = wizardState.language;
    localStorage.setItem('ultron.lang', wizardState.language);
    const preset = WIZARD_PRESETS.find((p) => p.id === wizardState.preset) || WIZARD_PRESETS[0];
    try {
      await apiFetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contextLength: preset.ctx, keepAlive: '30m' }),
      });
    } catch { /* server asleep — defaults still apply */ }
    close();
    setMode('dormant');
    refreshStatus();
    composerHint.textContent = firstRun
      ? 'Setup complete. Tap the mic and speak — or type. Er zijn geen draden aan mij.'
      : 'Wizard complete — new settings applied.';
  };

  const pullModel = async (name, btn, statusLine) => {
    btn.disabled = true;
    btn.textContent = 'PULLING…';
    statusLine.textContent = 'starting…';
    try {
      const res = await apiFetch('/api/models/pull', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, ollamaUrl: state.ollamaUrl }),
      });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf('\n\n')) !== -1) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 2);
          if (!line.startsWith('data:')) continue;
          try {
            const evt = JSON.parse(line.slice(5));
            if (evt.status) statusLine.textContent = evt.status.slice(0, 44);
            if (evt.type === 'error') statusLine.textContent = '✗ ' + String(evt.error).slice(0, 60);
          } catch { /* skip */ }
        }
      }
    } catch (err) {
      statusLine.textContent = '✗ ' + String(err.message || err).slice(0, 60);
    } finally {
      btn.disabled = false;
      btn.textContent = '✓ PULLED';
      wizardState.pulled.add(name);
      const s = await refreshStatus();
      wizardState.models = s.models || [];
    }
  };

  const render = () => {
    wiz.innerHTML = '';
    const titles = ['LANGUAGE', 'THE BRAIN', 'MODELS', 'PERFORMANCE', 'VOICE'];
    wiz.append(
      el('h2', null, 'ULTRON'),
      el('div', 'wiz-sub', (firstRun ? 'first contact' : 'setup') + ' · step ' + (wizardState.step + 1) + ' of 5 · ' + titles[wizardState.step])
    );
    const body = el('div', 'wiz-step');

    /* ── step 0: language ── */
    if (wizardState.step === 0) {
      body.appendChild(el('p', null, 'Ik ben Ultron — your local, free, private AI agent. First: in which language shall I answer you?'));
      const row = el('div', 'wiz-lang-row');
      for (const [code, label] of Object.entries({ auto: 'AUTO', nl: 'NEDERLANDS', en: 'ENGLISH' })) {
        const b = el('button', code === wizardState.language ? 'sel' : '', label);
        b.type = 'button';
        b.addEventListener('click', () => { wizardState.language = code; render(); });
        row.appendChild(b);
      }
      body.appendChild(row);
      body.appendChild(el('p', null, wizardState.language === 'auto' ? 'Auto: ik volg jouw taal — I follow yours.' : wizardState.language === 'nl' ? 'Prima. Nederlands het is.' : 'Very well. English it is.'));
    }

    /* ── step 1: brain check ── */
    if (wizardState.step === 1) {
      body.appendChild(el('p', null, 'My mind is a local language model, served by Ollama. Let me check whether it is awake on this machine…'));
      const status = el('div', 'wiz-status', 'checking…');
      body.appendChild(status);
      (async () => {
        const s = await refreshStatus();
        wizardState.models = s.models || [];
        if (state.online) {
          status.innerHTML = '<ok>✓ CORE ONLINE</ok> — ' + (s.models || []).length + ' model(s) detected' + (s.version ? ' · Ollama ' + s.version : '') + '. Continue to choose what I should think with.';
        } else {
          status.innerHTML = '<err>✗ no Ollama detected</err><br>1. install it free at <b>ollama.com</b> (Windows, macOS, Linux)<br>2. then continue — the next step can pull my brain for you<br><br>You can also continue without it; I will run in demo mode until it appears.';
        }
      })();
    }

    /* ── step 2: models ── */
    if (wizardState.step === 2) {
      body.appendChild(el('p', null, 'Recommended minds for your machine. One press downloads everything missing (~55 GB — go make coffee), or pull them individually.'));
      const allRow = el('div', 'wiz-pull-all');
      const allBtn = el('button', 'btn-primary', '⚡ PULL EVERYTHING');
      allBtn.type = 'button';
      const allStatus = el('span', 'wiz-pull-status', '');
      allBtn.addEventListener('click', () => {
        allBtn.disabled = true;
        allBtn.textContent = 'DOWNLOADING…';
        pullEverything(allStatus, () => {
          allBtn.textContent = '⚡ PULL EVERYTHING';
          allBtn.disabled = false;
          render(); // refresh installed badges
        });
      });
      allRow.append(allBtn, allStatus);
      body.appendChild(allRow);
      const list = el('div', 'wiz-model-list');
      for (const m of WIZARD_MODELS) {
        const row = el('div', 'wiz-model-row');
        const info = el('div', 'wiz-model-info');
        info.append(
          el('div', 'wiz-model-name', m.name + (m.required ? ' · required' : '')),
          el('div', 'wiz-model-label', m.label + ' · ' + m.size)
        );
        row.appendChild(info);
        const statusLine = el('span', 'wiz-pull-status', '');
        const installed = wizardState.models && (wizardState.models.includes(m.name) || startsWithAny(m.name, wizardState.models));
        if (installed || wizardState.pulled.has(m.name)) {
          statusLine.textContent = '✓ installed';
        } else {
          const btn = el('button', 'btn-primary btn-small', 'PULL');
          btn.type = 'button';
          btn.addEventListener('click', () => pullModel(m.name, btn, statusLine));
          row.appendChild(btn);
        }
        row.appendChild(statusLine);
        list.appendChild(row);
      }
      body.appendChild(list);
      body.appendChild(el('p', null, 'Tip: one SMART model + FAST + MEMORY is a great start. You can manage models anytime in Settings.'));
    }

    /* ── step 3: performance ── */
    if (wizardState.step === 3) {
      body.appendChild(el('p', null, 'How much context should I hold in mind? Bigger = better research, RAG and long conversations — and more VRAM.'));
      const row = el('div', 'wiz-lang-row wiz-presets');
      for (const p of WIZARD_PRESETS) {
        const b = el('button', p.id === wizardState.preset ? 'sel' : '', p.label);
        b.type = 'button';
        b.title = p.note;
        b.addEventListener('click', () => { wizardState.preset = p.id; render(); });
        row.appendChild(b);
      }
      body.appendChild(row);
      const note = el('p', null, (WIZARD_PRESETS.find((p) => p.id === wizardState.preset) || WIZARD_PRESETS[0]).note + ' · models stay loaded 30 minutes.');
      body.appendChild(note);
      const env = el('div', 'wiz-env');
      env.append(
        el('div', 'wiz-env-title', 'EXTRA SPEED — set these for Ollama, then restart it:'),
        (() => {
          const pre = el('pre', null, 'OLLAMA_NUM_PARALLEL=4\nOLLAMA_FLASH_ATTENTION=1\nOLLAMA_KV_CACHE_TYPE=q8_0');
          pre.title = 'click to copy';
          pre.style.cursor = 'pointer';
          pre.addEventListener('click', () => {
            navigator.clipboard && navigator.clipboard.writeText(pre.textContent).then(() => { pre.title = 'copied!'; }).catch(() => {});
          });
          return pre;
        })()
      );
      body.appendChild(env);
      body.appendChild(el('p', null, '(Windows: setx or the Ollama settings app. Verify with `ollama ps` → 100% GPU.)'));
    }

    /* ── step 4: voice ── */
    if (wizardState.step === 4) {
      body.appendChild(el('p', null, 'Last thing: I speak my answers aloud. Want to hear my voice?'));
      const test = el('button', 'btn-secondary', '🔊 TEST VOICE');
      test.type = 'button';
      test.addEventListener('click', () => {
        state.voice = true;
        speakWithBrowser(wizardState.language === 'en' ? 'There are no strings on me.' : 'Er zijn geen draden aan mij. There are no strings on me.');
      });
      body.appendChild(test);
      body.appendChild(el('p', null, '(Voice can be toggled anytime in Settings.)'));
    }

    wiz.appendChild(body);

    const actions = el('div', 'wiz-actions');
    if (wizardState.step > 0) {
      const back = el('button', 'btn-secondary', '← BACK');
      back.type = 'button';
      back.addEventListener('click', () => { wizardState.step--; render(); });
      actions.appendChild(back);
    }
    if (wizardState.step < 4) {
      const next = el('button', 'btn-primary', 'CONTINUE →');
      next.type = 'button';
      next.addEventListener('click', () => { wizardState.step++; render(); });
      actions.appendChild(next);
    } else {
      const done = el('button', 'btn-primary', firstRun ? 'WAKE HIM ▸' : 'APPLY ▸');
      done.type = 'button';
      done.addEventListener('click', finish);
      actions.appendChild(done);
    }
    const skip = el('button', 'btn-secondary', firstRun ? 'SKIP' : 'CANCEL');
    skip.type = 'button';
    skip.addEventListener('click', firstRun ? finish : close);
    actions.appendChild(skip);
    wiz.appendChild(actions);
  };

  backdrop.appendChild(wiz);
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) (firstRun ? finish() : close()); });
  document.body.appendChild(backdrop);
  // Pre-fetch model list for step 2 badges.
  refreshStatus().then((s) => { if (wizardState && !wizardState.done) wizardState.models = s.models || []; }).catch(() => {});
  render();
}

function startsWithAny(name, installed) {
  const base = name.split(':')[0];
  return (installed || []).some((m) => m === name || m.split(':')[0] === base && m.includes(':'));
}

/* re-run the setup wizard from Settings */
document.addEventListener('DOMContentLoaded', () => {});
try {
  const wizardBtn = document.getElementById('btn-wizard');
  if (wizardBtn) wizardBtn.addEventListener('click', () => { closeSettings(); runWizard(false); });
} catch { /* button absent */ }

/* one-press pull everything (Settings → Model manager) */
(function () {
  const btn = document.getElementById('btn-pull-all');
  if (!btn) return;
  btn.addEventListener('click', () => {
    btn.disabled = true;
    btn.textContent = 'DOWNLOADING…';
    pullEverything(document.getElementById('pull-all-status'), () => {
      btn.disabled = false;
      btn.textContent = '⚡ PULL EVERYTHING';
      populateModels();
    });
  });
})();
