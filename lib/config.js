/**
 * Server-side runtime config, persisted in data/config.json.
 */
'use strict';

const fs = require('fs');
const path = require('path');

const DATA_DIR = process.env.ULTRON_DATA || path.join(__dirname, '..', 'data');
const CONFIG_FILE = path.join(DATA_DIR, 'config.json');

const DEFAULTS = {
  toolsEnabled: process.env.ULTRON_TOOLS !== '0',
  sttUrl: '',   // whisper.cpp server (OpenAI-compatible)
  ttsUrl: '',   // piper-http server
  elevenKey: '',       // ElevenLabs API key (cloud voice — optional)
  elevenVoice: '',     // ElevenLabs voice id (empty = first available)
  elevenModel: 'eleven_multilingual_v2', // supports Dutch out of the box
  elevenUrl: '',       // optional API base override (proxies/testing)
  autoMemory: true,      // extract durable facts automatically after each exchange
  toolApproval: false,   // ask before run_command executes
  selfEditApproval: true, // ALWAYS ask before he edits his own code (until you trust him)
  models: { fast: '', smart: '', vision: '' },  // '' = auto-detect
  briefing: { enabled: false, time: '08:00', location: '', language: 'auto', lastDate: '' },
  accessToken: '',       // when set, all API calls need X-Ultron-Token (or ?token=)
};

const ELEVEN_MODELS = new Set(['eleven_multilingual_v2', 'eleven_turbo_v2_5', 'eleven_v3']);

let cfg = null;

function load() {
  if (cfg) return cfg;
  try {
    const raw = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));
    cfg = {
      ...DEFAULTS,
      ...raw,
      models: { ...DEFAULTS.models, ...(raw.models || {}) },
      briefing: { ...DEFAULTS.briefing, ...(raw.briefing || {}) },
    };
  } catch {
    cfg = JSON.parse(JSON.stringify(DEFAULTS));
  }
  return cfg;
}

function deepMerge(current, patch) {
  const out = JSON.parse(JSON.stringify(current));
  for (const key of Object.keys(patch)) {
    if (patch[key] === undefined || patch[key] === null) continue;
    if (key === 'models' || key === 'briefing') {
      out[key] = { ...out[key], ...(typeof patch[key] === 'object' ? patch[key] : {}) };
    } else if (key in DEFAULTS) {
      out[key] = patch[key];
    }
  }
  return out;
}

function sanitize(cfgObj) {
  const out = { ...cfgObj };
  out.sttUrl = sanitizeUrl(out.sttUrl);
  out.ttsUrl = sanitizeUrl(out.ttsUrl);
  out.accessToken = String(out.accessToken || '').trim().slice(0, 128);
  out.autoMemory = !!out.autoMemory;
  out.toolApproval = !!out.toolApproval;
  out.selfEditApproval = out.selfEditApproval !== false; // default true
  out.toolsEnabled = !!out.toolsEnabled;
  if (out.models) {
    for (const k of ['fast', 'smart', 'vision']) out.models[k] = String(out.models[k] || '').slice(0, 100);
  }
  out.elevenKey = String(out.elevenKey || '').trim().slice(0, 200);
  out.elevenVoice = String(out.elevenVoice || '').trim().slice(0, 100);
  out.elevenModel = ELEVEN_MODELS.has(out.elevenModel) ? out.elevenModel : 'eleven_multilingual_v2';
  out.elevenUrl = /^https?:\/\/.+/i.test(String(out.elevenUrl || '')) ? String(out.elevenUrl).trim().slice(0, 300) : '';
  if (out.briefing) {
    out.briefing.enabled = !!out.briefing.enabled;
    out.briefing.time = /^\d{2}:\d{2}$/.test(out.briefing.time) ? out.briefing.time : '08:00';
    out.briefing.location = String(out.briefing.location || '').slice(0, 120);
    out.briefing.language = ['auto', 'en', 'nl', 'de', 'fr', 'es', 'it', 'tr'].includes(out.briefing.language) ? out.briefing.language : 'auto';
    out.briefing.lastDate = String(out.briefing.lastDate || '').slice(0, 10);
  }
  return out;
}

function save(patch) {
  const next = sanitize(deepMerge(load(), patch || {}));
  cfg = next;
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(CONFIG_FILE, JSON.stringify(next, null, 2));
  return cfg;
}

function sanitizeUrl(raw) {
  const s = String(raw || '').trim().replace(/\/+$/, '');
  if (!s) return '';
  if (!/^https?:\/\//i.test(s)) return '';
  return s.slice(0, 300);
}

module.exports = { load, save };
