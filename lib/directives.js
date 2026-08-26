/**
 * STANDING ORDERS (directives) — instructions Ultron executes autonomously
 * on a schedule, forever, until you say stop.
 * "Watch this price", "summarize my calendar every evening", "tell me when…"
 * Stored in data/directives.json.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const DATA_DIR = path.join(__dirname, '..', 'data');
const FILE = path.join(DATA_DIR, 'directives.json');
const MAX_DIRECTIVES = 30;

let list = null;

function load() {
  if (list) return list;
  try {
    list = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    if (!Array.isArray(list)) list = [];
  } catch {
    list = [];
  }
  return list;
}

function save() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(FILE, JSON.stringify(list, null, 2));
}

/**
 * @param {object} args { instruction, every_minutes? , at? (daily "HH:MM") }
 */
function add({ instruction, every_minutes, at }) {
  const clean = String(instruction || '').trim().slice(0, 500);
  if (!clean) return { error: 'no instruction given' };

  let schedule;
  if (every_minutes != null && !Number.isNaN(Number(every_minutes))) {
    const mins = Math.max(Number(every_minutes), 1);
    schedule = { type: 'interval', minutes: mins };
  } else if (at && /^\d{1,2}:\d{2}$/.test(String(at))) {
    const [h, m] = String(at).split(':').map(Number);
    schedule = { type: 'daily', time: `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}` };
  } else {
    return { error: 'need every_minutes (number) or at ("HH:MM")' };
  }

  const items = load();
  if (items.length >= MAX_DIRECTIVES) return { error: `too many standing orders (max ${MAX_DIRECTIVES})` };
  if (items.some((d) => d.instruction.toLowerCase() === clean.toLowerCase())) {
    return { ok: true, note: 'already have this order' };
  }
  const d = {
    id: crypto.randomUUID(),
    instruction: clean,
    schedule,
    enabled: true,
    lastRun: 0,
    lastDate: '',
    created: new Date().toISOString(),
  };
  items.push(d);
  save();
  return { ok: true, directive: publicView(d) };
}

function publicView(d) {
  return {
    id: d.id,
    instruction: d.instruction,
    schedule: d.schedule.type === 'interval' ? `every ${d.schedule.minutes} min` : `daily at ${d.schedule.time}`,
    enabled: d.enabled,
    lastRun: d.lastRun ? new Date(d.lastRun).toISOString() : null,
  };
}

function remove({ contains }) {
  const needle = String(contains || '').trim().toLowerCase();
  if (!needle) return { error: 'no search text' };
  const items = load();
  const kept = items.filter((d) => !d.instruction.toLowerCase().includes(needle));
  const removed = items.length - kept.length;
  list = kept;
  save();
  return { ok: true, removed };
}

function setEnabled(id, enabled) {
  const d = load().find((x) => x.id === id);
  if (!d) return { error: 'not found' };
  d.enabled = !!enabled;
  save();
  return { ok: true };
}

function markRun(id) {
  const d = load().find((x) => x.id === id);
  if (!d) return;
  d.lastRun = Date.now();
  d.lastDate = new Date().toISOString().slice(0, 10);
  save();
}

/** Which orders are due right now? */
function due() {
  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  return load().filter((d) => {
    if (!d.enabled) return false;
    if (d.schedule.type === 'interval') {
      return Date.now() - (d.lastRun || 0) >= d.schedule.minutes * 60 * 1000;
    }
    const [h, m] = d.schedule.time.split(':').map(Number);
    const passed = now.getHours() * 60 + now.getMinutes() >= h * 60 + m;
    return passed && d.lastDate !== today;
  });
}

function all() {
  return load().map(publicView);
}

function byId(id) {
  return load().find((d) => d.id === id) || null;
}

module.exports = { add, remove, setEnabled, markRun, due, all, byId };
