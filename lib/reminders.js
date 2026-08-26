/**
 * REMINDERS — scheduled messages Ultron pushes to the client when due.
 * Stored in data/reminders.json; delivered over the /api/events SSE stream.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const DATA_DIR = process.env.ULTRON_DATA || path.join(__dirname, '..', 'data');
const REMINDERS_FILE = path.join(DATA_DIR, 'reminders.json');
const MAX_REMINDERS = 100;

let reminders = null;

function load() {
  if (reminders) return reminders;
  try {
    reminders = JSON.parse(fs.readFileSync(REMINDERS_FILE, 'utf8'));
    if (!Array.isArray(reminders)) reminders = [];
  } catch {
    reminders = [];
  }
  return reminders;
}

function save() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(REMINDERS_FILE, JSON.stringify(reminders, null, 2));
}

/**
 * Add a reminder.
 * @param {object} args { message, delay_minutes?, at? }
 */
function add({ message, delay_minutes, at }) {
  const msg = String(message || '').trim().slice(0, 500);
  if (!msg) return { ok: false, error: 'no message' };

  let dueAt = null;
  if (delay_minutes != null && !Number.isNaN(Number(delay_minutes))) {
    const mins = Math.max(Number(delay_minutes), 0.02); // floor ≈ 1.2s
    dueAt = new Date(Date.now() + mins * 60 * 1000);
  } else if (at) {
    const d = new Date(at);
    if (Number.isNaN(d.getTime())) return { ok: false, error: `unparseable time "${at}"` };
    dueAt = d;
  } else {
    return { ok: false, error: 'need delay_minutes or at' };
  }

  const list = load();
  if (list.length >= MAX_REMINDERS) list.shift();
  const r = { id: crypto.randomUUID(), message: msg, dueAt: dueAt.toISOString() };
  list.push(r);
  list.sort((a, b) => new Date(a.dueAt) - new Date(b.dueAt));
  save();
  return { ok: true, reminder: r, scheduled_for: r.dueAt, human: `reminder set for ${r.dueAt}` };
}

/** Return and remove all reminders whose time has come. */
function due() {
  const list = load();
  const now = Date.now();
  const ready = list.filter((r) => new Date(r.dueAt).getTime() <= now);
  if (ready.length > 0) {
    reminders = list.filter((r) => new Date(r.dueAt).getTime() > now);
    save();
  }
  return ready;
}

function all() {
  return load().map((r) => ({ message: r.message, dueAt: r.dueAt }));
}

module.exports = { add, due, all };
