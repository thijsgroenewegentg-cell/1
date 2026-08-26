/**
 * CALENDAR — a simple local ICS file (data/calendar.ics).
 * Reads and writes VEVENTs; enough for personal scheduling.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const DATA_DIR = process.env.ULTRON_DATA || path.join(__dirname, '..', 'data');
const ICS_FILE = path.join(DATA_DIR, 'calendar.ics');

const HEADER = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//ULTRON//Local Calendar//EN', 'CALSCALE:GREGORIAN'];
const FOOTER = ['END:VCALENDAR'];

function ensureFile() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  if (!fs.existsSync(ICS_FILE)) {
    fs.writeFileSync(ICS_FILE, [...HEADER, ...FOOTER].join('\r\n') + '\r\n');
  }
}

function unfold(lines) {
  // RFC 5545 line folding: continuation lines start with a space or tab.
  const out = [];
  for (const raw of lines) {
    if (/^[ \t]/.test(raw) && out.length > 0) out[out.length - 1] += raw.slice(1);
    else out.push(raw);
  }
  return out;
}

function parseIcsDate(value, params) {
  // Forms: 20260827T090000, 20260827T090000Z, 20260827 (all-day)
  const m = String(value).match(/^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2}))?(Z)?$/);
  if (!m) return null;
  const [, y, mo, d, h = '00', mi = '00', s = '00', z] = m;
  const iso = `${y}-${mo}-${d}T${h}:${mi}:${s}${z ? 'Z' : ''}`;
  const dt = new Date(iso);
  return Number.isNaN(dt.getTime()) ? null : { date: dt, allDay: !m[4] };
}

function readEvents() {
  ensureFile();
  const text = fs.readFileSync(ICS_FILE, 'utf8');
  const lines = unfold(text.split(/\r?\n/));
  const events = [];
  let cur = null;
  for (const line of lines) {
    if (line.startsWith('BEGIN:VEVENT')) cur = {};
    else if (line.startsWith('END:VEVENT')) {
      if (cur && cur.start) events.push(cur);
      cur = null;
    } else if (cur) {
      const colon = line.indexOf(':');
      if (colon === -1) continue;
      const keyPart = line.slice(0, colon);
      const value = line.slice(colon + 1);
      const key = keyPart.split(';')[0].toUpperCase();
      if (key === 'SUMMARY') cur.summary = value;
      else if (key === 'DTSTART') cur.start = parseIcsDate(value, keyPart);
      else if (key === 'DTEND') cur.end = parseIcsDate(value, keyPart);
      else if (key === 'UID') cur.uid = value;
    }
  }
  return events.filter((e) => e.start);
}

function fmt(dt) {
  const p = (n) => String(n).padStart(2, '0');
  return `${dt.getUTCFullYear()}${p(dt.getUTCMonth() + 1)}${p(dt.getUTCDate())}T${p(dt.getUTCHours())}${p(dt.getUTCMinutes())}00`;
}

function fmtDateOnly(dt) {
  const p = (n) => String(n).padStart(2, '0');
  return `${dt.getUTCFullYear()}${p(dt.getUTCMonth() + 1)}${p(dt.getUTCDate())}`;
}

/** List events within the next N days. */
function upcoming(days = 7) {
  const now = new Date();
  const until = new Date(now.getTime() + (parseInt(days, 10) || 7) * 24 * 3600 * 1000);
  return readEvents()
    .filter((e) => e.start.date >= new Date(now.getTime() - 12 * 3600 * 1000) && e.start.date <= until)
    .sort((a, b) => a.start.date - b.start.date)
    .map((e) => ({
      title: e.summary || '(untitled)',
      start: e.start.date.toISOString(),
      all_day: e.start.allDay,
      ...(e.end ? { end: e.end.date.toISOString() } : {}),
    }));
}

/** Add an event. date: YYYY-MM-DD, time: HH:MM (optional → all-day). */
function add({ title, date, time, duration_minutes = 60 }) {
  const cleanTitle = String(title || '').trim().slice(0, 200);
  if (!cleanTitle) return { error: 'no title' };
  const dm = String(date || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!dm) return { error: `date must be YYYY-MM-DD (got "${date}")` };

  let allDay = true;
  let start;
  if (time) {
    const tm = String(time).match(/^(\d{1,2}):(\d{2})$/);
    if (!tm) return { error: `time must be HH:MM (got "${time}")` };
    // Treat times as the server's local timezone (personal machine → local life).
    start = new Date(Number(dm[1]), Number(dm[2]) - 1, Number(dm[3]), Number(tm[1]), Number(tm[2]));
    allDay = false;
  } else {
    start = new Date(Number(dm[1]), Number(dm[2]) - 1, Number(dm[3]));
  }
  const end = new Date(start.getTime() + (allDay ? 0 : (parseInt(duration_minutes, 10) || 60) * 60000));

  ensureFile();
  const uid = crypto.randomUUID();
  const lines = [
    'BEGIN:VEVENT',
    `UID:${uid}`,
    `DTSTAMP:${fmt(new Date())}Z`,
    allDay ? `DTSTART;VALUE=DATE:${fmtDateOnly(start)}` : `DTSTART:${fmt(start)}`,
    allDay ? '' : `DTEND:${fmt(end)}`,
    `SUMMARY:${cleanTitle.replace(/[\r\n]/g, ' ')}`,
    'END:VEVENT',
  ].filter(Boolean);

  const text = fs.readFileSync(ICS_FILE, 'utf8');
  const updated = text.replace(/\r?\nEND:VCALENDAR\s*$/i, '\r\n' + lines.join('\r\n') + '\r\nEND:VCALENDAR\r\n');
  fs.writeFileSync(ICS_FILE, updated);
  return { ok: true, uid, start: start.toISOString(), all_day: allDay, title: cleanTitle };
}

module.exports = { upcoming, add };
