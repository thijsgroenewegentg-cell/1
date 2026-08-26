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

const DATA_DIR = process.env.ULTRON_DATA || path.join(__dirname, '..', 'data');
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
 * @param {object} args { instruction, every_minutes?, at? (daily "HH:MM"), once_at? (one-shot datetime) }
 */
function add({ instruction, every_minutes, at, once_at }) {
  const clean = String(instruction || '').trim().slice(0, 500);
  if (!clean) return { error: 'no instruction given' };

  let schedule;
  if (once_at) {
    const d = new Date(String(once_at).replace(' ', 'T'));
    if (Number.isNaN(d.getTime()) || d.getTime() < Date.now() - 60000) {
      return { error: `once_at must be a future datetime (got "${once_at}")` };
    }
    schedule = { type: 'once', runAt: d.toISOString() };
  } else if (every_minutes != null && !Number.isNaN(Number(every_minutes))) {
    const mins = Math.max(Number(every_minutes), 1);
    schedule = { type: 'interval', minutes: mins };
  } else if (at && /^\d{1,2}:\d{2}$/.test(String(at))) {
    const [h, m] = String(at).split(':').map(Number);
    schedule = { type: 'daily', time: `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}` };
  } else {
    return { error: 'need every_minutes (number), at ("HH:MM") or once_at (datetime)' };
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
    schedule: d.schedule.type === 'interval' ? `every ${d.schedule.minutes} min`
      : d.schedule.type === 'once' ? `once at ${new Date(d.schedule.runAt).toLocaleString()}`
      : `daily at ${d.schedule.time}`,
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
  const list = load();
  const d = list.find((x) => x.id === id);
  if (!d) return;
  if (d.schedule.type === 'once') {
    // One-shot orders fire once and are gone.
    directives_list_remove(list, id);
    save();
    return;
  }
  d.lastRun = Date.now();
  d.lastDate = new Date().toISOString().slice(0, 10);
  save();
}

function directives_list_remove(list, id) {
  const i = list.findIndex((x) => x.id === id);
  if (i !== -1) list.splice(i, 1);
}

/** Which orders are due right now? */
function due() {
  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  return load().filter((d) => {
    if (!d.enabled) return false;
    if (d.schedule.type === 'once') {
      return new Date(d.schedule.runAt).getTime() <= Date.now();
    }
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
