/**
 * DURABLE MEMORY — facts Ultron keeps about you, across sessions.
 * Stored in data/memory.json. Injected into every system prompt.
 */
'use strict';

const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, '..', 'data');
const MEMORY_FILE = path.join(DATA_DIR, 'memory.json');
const MAX_MEMORIES = 200;

let memories = null; // [{fact, at}]

function load() {
  if (memories) return memories;
  try {
    memories = JSON.parse(fs.readFileSync(MEMORY_FILE, 'utf8'));
    if (!Array.isArray(memories)) memories = [];
  } catch {
    memories = [];
  }
  return memories;
}

function save() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(MEMORY_FILE, JSON.stringify(memories, null, 2));
}

function all() {
  return load().map((m, i) => ({ idx: i, fact: m.fact, at: m.at }));
}

function add(fact) {
  const clean = String(fact || '').trim().slice(0, 500);
  if (!clean) return { ok: false, error: 'empty fact' };
  const list = load();
  if (list.some((m) => m.fact.toLowerCase() === clean.toLowerCase())) {
    return { ok: true, note: 'already known', count: list.length };
  }
  if (list.length >= MAX_MEMORIES) list.shift();
  list.push({ fact: clean, at: new Date().toISOString() });
  save();
  return { ok: true, count: list.length };
}

function removeContaining(substring) {
  const list = load();
  const needle = String(substring || '').trim().toLowerCase();
  if (!needle) return { ok: false, error: 'empty search term' };
  const kept = list.filter((m) => !m.fact.toLowerCase().includes(needle));
  const removed = list.length - kept.length;
  memories = kept;
  save();
  return { ok: true, removed, count: kept.length };
}

function clear() {
  memories = [];
  save();
  return { ok: true };
}

/** Render memories as a prompt section. */
function promptSection() {
  const list = load();
  if (list.length === 0) return '';
  const lines = list.slice(-60).map((m) => `- ${m.fact}`).join('\n');
  return `\n\n# DURABLE MEMORIES (persist across sessions)\nThese are things you've chosen to remember about this user. Use them naturally; never list them unprompted.\n${lines}`;
}

module.exports = { all, add, removeContaining, clear, promptSection };
