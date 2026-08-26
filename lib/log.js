/**
 * MISSION LOG — a rolling record of everything Ultron does:
 * routing decisions, tool calls, directives, briefings, pushes, faults.
 * In-memory ring buffer, surfaced at GET /api/log.
 */
'use strict';

const MAX_ENTRIES = 300;
const log = [];

function add(kind, text, data) {
  log.push({
    ts: new Date().toISOString(),
    kind: String(kind).slice(0, 20),
    text: String(text || '').slice(0, 300),
    ...(data ? { data } : {}),
  });
  if (log.length > MAX_ENTRIES) log.splice(0, log.length - MAX_ENTRIES);
}

function recent(limit = 100) {
  return log.slice(-Math.min(limit, MAX_ENTRIES)).reverse();
}

function clear() {
  log.length = 0;
}

module.exports = { add, recent, clear };
