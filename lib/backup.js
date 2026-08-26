/**
 * BACKUP — one-file export/import of Ultron's entire mind:
 * memory, sessions, directives, reminders, config, calendar,
 * knowledge index, skills and workspace files.
 */
'use strict';

const fs = require('fs');
const path = require('path');

const DATA_DIR = process.env.ULTRON_DATA || path.join(__dirname, '..', 'data');

const TEXT_FILES = [
  'memory.json', 'memory-embeddings.json', 'directives.json', 'reminders.json',
  'config.json', 'calendar.ics', 'sessions.json',
];
const NESTED = [
  { dir: 'knowledge', file: 'index.json', as: 'knowledge-index.json' },
];

function readJsonSafe(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return null; }
}

/** Build the full bundle. */
function create() {
  const bundle = {
    ultronBackup: 1,
    exported: new Date().toISOString(),
    files: {},
    skills: {},
    workspace: {},
  };
  for (const name of TEXT_FILES) {
    const data = readJsonSafe(path.join(DATA_DIR, name));
    if (name === 'calendar.ics') {
      try { bundle.files['calendar.ics'] = fs.readFileSync(path.join(DATA_DIR, name), 'utf8'); } catch { /* absent */ }
      continue;
    }
    if (data !== null) bundle.files[name] = data;
  }
  for (const n of NESTED) {
    const data = readJsonSafe(path.join(DATA_DIR, n.dir, n.file));
    if (data !== null) bundle.files[n.as] = data;
  }
  // Skills
  try {
    for (const f of fs.readdirSync(path.join(DATA_DIR, 'skills'))) {
      if (!f.endsWith('.json')) continue;
      const data = readJsonSafe(path.join(DATA_DIR, 'skills', f));
      if (data) bundle.skills[f] = data;
    }
  } catch { /* no skills dir */ }
  // Workspace files (text, small)
  let total = 0;
  try {
    const walk = (dir, prefix) => {
      for (const name of fs.readdirSync(dir).slice(0, 200)) {
        if (name.startsWith('.')) continue;
        const full = path.join(dir, name);
        const rel = prefix ? `${prefix}/${name}` : name;
        let stat;
        try { stat = fs.statSync(full); } catch { continue; }
        if (stat.isDirectory()) { walk(full, rel); continue; }
        if (stat.size > 100 * 1024 || total > 5 * 1024 * 1024) continue;
        try {
          const content = fs.readFileSync(full, 'utf8');
          if (/\u0000/.test(content.slice(0, 500))) continue; // binary
          bundle.workspace[rel] = content;
          total += content.length;
        } catch { /* unreadable */ }
      }
    };
    walk(path.join(DATA_DIR, 'files'), '');
  } catch { /* no files dir */ }
  return bundle;
}

function isBundle(b) {
  return b && typeof b === 'object' && b.ultronBackup === 1 && typeof b.files === 'object';
}

/** Restore a bundle to disk. Returns stats; caller resets in-memory caches. */
function restore(bundle) {
  if (!isBundle(bundle)) return { ok: false, error: 'not an Ultron backup bundle' };
  fs.mkdirSync(DATA_DIR, { recursive: true });

  let restored = 0;
  for (const [name, content] of Object.entries(bundle.files || {})) {
    if (name === 'knowledge-index.json') {
      fs.mkdirSync(path.join(DATA_DIR, 'knowledge'), { recursive: true });
      fs.writeFileSync(path.join(DATA_DIR, 'knowledge', 'index.json'), JSON.stringify(content));
      restored++;
      continue;
    }
    if (!/^[\w.-]+$/.test(name)) continue; // safety: no path tricks
    const target = path.join(DATA_DIR, name);
    if (name === 'calendar.ics') fs.writeFileSync(target, String(content));
    else fs.writeFileSync(target, JSON.stringify(content));
    restored++;
  }
  let skills = 0;
  for (const [name, def] of Object.entries(bundle.skills || {})) {
    if (!/^[\w.-]+\.json$/.test(name)) continue;
    fs.mkdirSync(path.join(DATA_DIR, 'skills'), { recursive: true });
    fs.writeFileSync(path.join(DATA_DIR, 'skills', name), JSON.stringify(def));
    skills++;
  }
  let files = 0;
  for (const [rel, content] of Object.entries(bundle.workspace || {})) {
    if (rel.includes('..') || path.isAbsolute(rel)) continue;
    const target = path.join(DATA_DIR, 'files', rel);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, String(content));
    files++;
  }
  return { ok: true, restored, skills, files, note: 'restart the server to fully apply' };
}

module.exports = { create, restore };
