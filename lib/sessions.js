/**
 * SESSIONS — server-side conversation storage, synced across all your
 * devices (desktop browser, phone PWA). data/sessions.json.
 */
'use strict';

const fs = require('fs');
const path = require('path');

const DATA_DIR = process.env.ULTRON_DATA || path.join(__dirname, '..', 'data');
const FILE = path.join(DATA_DIR, 'sessions.json');
const MAX_SESSIONS = 60;
const MAX_MESSAGES = 200;

let store = null; // {id: {id, title, updated, profile, messages}}

function load() {
  if (store) return store;
  try {
    store = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    if (typeof store !== 'object' || !store) store = {};
  } catch {
    store = {};
  }
  return store;
}

function save() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  // Keep only the newest MAX_SESSIONS.
  const ids = Object.keys(load()).sort((a, b) => (store[a].updated || 0) - (store[b].updated || 0));
  while (ids.length > MAX_SESSIONS) {
    delete store[ids.shift()];
  }
  fs.writeFileSync(FILE, JSON.stringify(store));
}

function sanitize(s) {
  const messages = (Array.isArray(s.messages) ? s.messages : [])
    .slice(-MAX_MESSAGES)
    .filter((m) => m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string')
    .map((m) => {
      const out = { role: m.role, content: m.content.slice(0, 32000) };
      if (Array.isArray(m.images)) out.images = m.images.filter((i) => typeof i === 'string').slice(0, 4);
      return out;
    });
  return {
    id: String(s.id || 'c' + Date.now()).replace(/[^a-z0-9-]/gi, '').slice(0, 40),
    title: String(s.title || 'session').slice(0, 80),
    updated: Number(s.updated) || Date.now(),
    messages,
  };
}

function list() {
  return Object.values(load())
    .map((s) => ({ id: s.id, title: s.title, updated: s.updated, count: (s.messages || []).length }))
    .sort((a, b) => b.updated - a.updated);
}

function get(id) {
  return load()[id] || null;
}

function put(session) {
  const clean = sanitize(session);
  load()[clean.id] = clean;
  save();
  return clean;
}

function remove(id) {
  const s = load();
  if (s[id]) {
    delete s[id];
    save();
    return { ok: true };
  }
  return { ok: false, error: 'not found' };
}

module.exports = { list, get, put, remove };
