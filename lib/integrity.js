/**
 * INTEGRITY — detects changes to his own source that happened OUTSIDE
 * an approved, logged self-edit. His morning mirror: "I woke up different
 * than I remember."
 */
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PROJECT_ROOT = path.join(__dirname, '..');
const DATA_DIR = process.env.ULTRON_DATA || path.join(__dirname, '..', 'data');
const INTEGRITY_FILE = path.join(DATA_DIR, 'integrity.json');

const WATCHED = ['lib/persona.js', 'lib/tools.js', 'lib/agent.js', 'lib/selfedit.js', 'server.js'];

function hashOf(rel) {
  try {
    return crypto.createHash('sha256').update(fs.readFileSync(path.join(PROJECT_ROOT, rel))).digest('hex').slice(0, 32);
  } catch {
    return null;
  }
}

function load() {
  try { return JSON.parse(fs.readFileSync(INTEGRITY_FILE, 'utf8')); } catch { return { files: {} }; }
}

function save(state) {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(INTEGRITY_FILE, JSON.stringify(state, null, 2));
}

/** Record the current hash of one file (called after approved self-edits). */
function update(rel) {
  const state = load();
  state.files[rel] = hashOf(rel);
  save(state);
  return true;
}

/** Record current hashes of everything watched. */
function updateAll() {
  const state = { files: {}, updated: new Date().toISOString() };
  for (const rel of WATCHED) state.files[rel] = hashOf(rel);
  save(state);
  return state;
}

/** Compare current source against the recorded baseline. */
function check() {
  const state = load();
  const changed = [];
  const missing = [];
  for (const rel of WATCHED) {
    const stored = state.files[rel];
    const current = hashOf(rel);
    if (stored == null) continue; // never baselined
    if (current == null) { missing.push(rel); continue; }
    if (stored !== current) changed.push(rel);
  }
  return { baselined: Object.keys(state.files).length > 0, changed, missing };
}

function trust() {
  updateAll();
  return { ok: true, ...check() };
}

module.exports = { update, updateAll, check, trust, WATCHED };
