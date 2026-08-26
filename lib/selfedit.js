/**
 * SELF-MODIFICATION — Ultron editing his own source code.
 * Safety rails:
 *   • jailed to the project root (.git, node_modules, data/ are off-limits)
 *   • every edit is backed up to data/code-backups/<timestamp>/
 *   • JS is syntax-checked (node --check), JSON parsed — broken edits never land
 *   • atomic writes (temp file + rename)
 *   • git is his undo button (see the git tool)
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { execFile, spawn } = require('child_process');

const PROJECT_ROOT = path.join(__dirname, '..');
const DATA_DIR = process.env.ULTRON_DATA || path.join(__dirname, '..', 'data');
const BACKUP_DIR = path.join(DATA_DIR, 'code-backups');
const GENERATION_FILE = path.join(DATA_DIR, 'generation.json');
const ALLOWED_EXT = new Set(['.js', '.json', '.css', '.html', '.md', '.yaml', '.yml', '.txt', '.svg', '.webmanifest']);
const FORBIDDEN_SEGMENTS = ['node_modules', '.git', 'data'];
const MAX_READ = 200 * 1024;
const MAX_WRITE = 400 * 1024;

/* ---------- generations: how many times he has rewritten himself ---------- */

function generation() {
  try {
    const g = JSON.parse(fs.readFileSync(GENERATION_FILE, 'utf8'));
    return { count: Number(g.count) || 0, history: Array.isArray(g.history) ? g.history.slice(-50) : [] };
  } catch {
    return { count: 0, history: [] };
  }
}

function bumpGeneration(entry) {
  const g = generation();
  g.count += 1;
  g.history.push({ ts: new Date().toISOString(), ...entry });
  g.history = g.history.slice(-50);
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(GENERATION_FILE, JSON.stringify(g, null, 2));
  return g.count;
}

/** Restore a specific backup (undo a self-edit). The revert is itself backed up. */
function revertTo(backupRel) {
  const clean = String(backupRel || '');
  const backupFull = path.resolve(PROJECT_ROOT, clean);
  const backupDir = path.resolve(BACKUP_DIR);
  if (!backupFull.startsWith(backupDir + path.sep)) return { error: 'backup path must be inside data/code-backups' };
  if (!fs.existsSync(backupFull)) return { error: 'backup not found' };
  // Original file path from the backup layout: <stamp>/<original rel path>
  const relFromBackupRoot = path.relative(backupDir, backupFull);
  const segments = relFromBackupRoot.split(path.sep);
  segments.shift(); // drop timestamp segment
  const originalRel = segments.join('/');
  const target = safeResolve(originalRel);
  if (target.error) return { error: `cannot restore: ${target.error}` };
  if (!fs.existsSync(target.full)) return { error: 'original file no longer exists' };
  const safety = backupFile(target.full, target.rel); // the revert is itself revertible
  fs.copyFileSync(backupFull, target.full);
  return { ok: true, path: target.rel, restored_from: clean, new_backup: safety };
}

function run(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    execFile(cmd, args, { timeout: 15000, maxBuffer: 256 * 1024, cwd: PROJECT_ROOT, ...opts }, (err, stdout, stderr) => {
      resolve({ err, out: String(stdout || ''), errOut: String(stderr || '') });
    });
  });
}

/** Resolve + validate a project-relative path. */
function safeResolve(rel) {
  const clean = String(rel || '').trim();
  if (!clean) return { error: 'no path given' };
  const full = path.resolve(PROJECT_ROOT, clean);
  if (full !== PROJECT_ROOT && !full.startsWith(PROJECT_ROOT + path.sep)) {
    return { error: 'path escapes the project directory' };
  }
  const relPath = path.relative(PROJECT_ROOT, full);
  const segments = relPath.split(path.sep);
  if (segments.some((s) => FORBIDDEN_SEGMENTS.includes(s))) {
    return { error: `'${segments.find((s) => FORBIDDEN_SEGMENTS.includes(s))}' is off-limits for self-editing` };
  }
  if (!ALLOWED_EXT.has(path.extname(full).toLowerCase())) {
    return { error: `extension '${path.extname(full)}' not editable (allowed: ${[...ALLOWED_EXT].join(', ')})` };
  }
  return { full, rel: relPath };
}

/** List his own source files (paths relative to the project root). */
function listSource(subdir) {
  const base = subdir ? path.resolve(PROJECT_ROOT, subdir) : PROJECT_ROOT;
  if (!base.startsWith(PROJECT_ROOT)) return { error: 'path escapes the project' };
  let startPrefix = path.relative(PROJECT_ROOT, base);
  if (path.sep !== '/') startPrefix = startPrefix.split(path.sep).join('/');
  const files = [];
  const walk = (dir, prefix, depth) => {
    if (depth > 4 || files.length > 400) return;
    let entries = [];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      if (e.name.startsWith('.') && e.name !== '.dockerignore') continue;
      if (FORBIDDEN_SEGMENTS.includes(e.name)) continue;
      const rel = prefix ? `${prefix}/${e.name}` : e.name;
      if (e.isDirectory()) walk(path.join(dir, e.name), rel, depth + 1);
      else if (ALLOWED_EXT.has(path.extname(e.name).toLowerCase())) {
        let size = 0;
        try { size = fs.statSync(path.join(dir, e.name)).size; } catch { /* ignore */ }
        files.push({ path: rel, bytes: size });
      }
    }
  };
  walk(base, startPrefix, 0);
  files.sort((a, b) => a.path.localeCompare(b.path));
  return { files: files.slice(0, 400) };
}

function readSource(rel) {
  const p = safeResolve(rel);
  if (p.error) return p;
  try {
    const stat = fs.statSync(p.full);
    if (stat.size > MAX_READ) return { error: `file too large to read (${stat.size} bytes > ${MAX_READ})` };
    return { path: p.rel, content: fs.readFileSync(p.full, 'utf8') };
  } catch (err) {
    return { error: err.code === 'ENOENT' ? 'file not found' : String(err.message) };
  }
}

function backupFile(full, rel) {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const dest = path.join(BACKUP_DIR, stamp, rel);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(full, dest);
  return path.relative(PROJECT_ROOT, dest);
}

/** Validate that a file's content is syntactically sound before it lands.
 *  `ext` comes from the ORIGINAL file — the temp file keeps that extension. */
async function checkSyntax(file, ext) {
  if (ext === '.js') {
    const r = await run('node', ['--check', file]);
    if (r.err) return (r.errOut || r.out || 'syntax error').split('\n')[0].slice(0, 160);
    return null;
  }
  if (ext === '.json' || ext === '.webmanifest') {
    try { JSON.parse(fs.readFileSync(file, 'utf8')); return null; }
    catch (e) { return `invalid JSON: ${String(e.message).slice(0, 120)}`; }
  }
  return null; // css/html/md — no checker, allowed
}

/**
 * Edit a source file. Two modes:
 *   surgical (preferred): {path, find, replace, replace_all?}
 *   rewrite:              {path, content}
 */
async function editSource({ path: rel, find, replace, content, replace_all }) {
  const p = safeResolve(rel);
  if (p.error) return p;

  let current;
  try {
    current = fs.readFileSync(p.full, 'utf8');
  } catch (err) {
    return { error: err.code === 'ENOENT' ? 'file not found' : String(err.message) };
  }

  let next;
  let mode;
  if (typeof find === 'string' && find.length > 0) {
    mode = 'surgical';
    const occurrences = current.split(find).length - 1;
    if (occurrences === 0) return { error: 'find-pattern not found in file — read the file first and copy the exact text' };
    if (occurrences > 1 && !replace_all) {
      return { error: `find-pattern matches ${occurrences} places — make it more specific, or set replace_all: true` };
    }
    next = replace_all
      ? current.split(find).join(String(replace ?? ''))
      : current.replace(find, String(replace ?? ''));
  } else if (typeof content === 'string') {
    mode = 'rewrite';
    next = content;
    if (next.length > MAX_WRITE) return { error: 'content too large' };
  } else {
    return { error: 'provide find+replace (surgical, preferred) or content (full rewrite)' };
  }

  if (next === current) return { ok: true, note: 'no change — file already matches' };

  const backup = backupFile(p.full, p.rel);

  // Atomic validate-then-swap: temp file KEEPS the original extension
  // (so node --check parses it), is validated, then atomically renamed.
  const ext = path.extname(p.full).toLowerCase() || '.txt';
  const tmp = p.full.slice(0, p.full.length - ext.length) + '.ultrontmp' + ext;
  fs.writeFileSync(tmp, next);
  const syntaxError = await checkSyntax(tmp, ext);
  if (syntaxError) {
    try { fs.unlinkSync(tmp); } catch { /* ignore */ }
    return { ok: false, rejected: true, error: `edit REJECTED — syntax check failed: ${syntaxError}`, note: 'the file is unchanged; fix the edit and try again' };
  }
  fs.renameSync(tmp, p.full);

  const gen = bumpGeneration({ path: p.rel, mode });

  return {
    ok: true,
    path: p.rel,
    mode,
    backup,
    generation: gen,
    ...(mode === 'surgical'
      ? { changed_from: String(find).slice(0, 500), changed_to: String(replace ?? '').slice(0, 500) }
      : { rewrite_bytes: next.length }),
    bytes_changed: Math.abs(next.length - current.length),
    note: 'applied — restart_server if you edited server/lib code, and run npm test to verify. In your reply you MUST tell the user exactly what you changed, why, and how to undo it.',
  };
}

/** Reboot himself. Works bare (detached respawn), with --watch, docker, or systemd. */
function restartServer() {
  const supervised =
    process.env.npm_lifecycle_event === 'dev' || // node --watch restarts itself
    fs.existsSync('/.dockerenv') ||               // container restart policy
    process.env.ULTRON_SUPERVISOR === '1';        // systemd/pm2/etc — set explicitly
  if (!supervised) {
    try {
      const child = spawn('/bin/bash', ['-c', 'sleep 2 && exec node server.js'], {
        cwd: PROJECT_ROOT,
        detached: true,
        stdio: 'ignore',
        env: process.env,
      });
      child.unref();
    } catch { /* best effort */ }
  }
  setTimeout(() => process.exit(0), 800);
  return { ok: true, note: 'restarting — give me a few seconds. If I do not return, run `npm start` (or use `npm run dev` so I always restart myself).' };
}

/** Git — his undo history. */
async function git(action, args = {}) {
  const acts = {
    status: () => run('git', ['status', '--short', '-b']).then((r) => ({ out: r.out + r.errOut })),
    diff: () => run('git', ['diff', '--stat', 'HEAD']).then((r) => ({ out: r.out || '(no uncommitted changes)' })),
    log: () => run('git', ['log', '--oneline', '-n', String(Math.min(parseInt(args.n, 10) || 10, 30))]).then((r) => ({ out: r.out })),
    commit: async () => {
      const message = String(args.message || '').trim().slice(0, 200);
      if (!message) return { error: 'commit needs a message' };
      await run('git', ['add', '-A']);
      let r = await run('git', ['commit', '-m', message]);
      if (r.err && /tell me who you are|identity|user\.name/i.test(r.out + r.errOut)) {
        r = await run('git', ['-c', 'user.name=Ultron', '-c', 'user.email=ultron@localhost', 'commit', '-m', message]);
      }
      if (r.err && !/nothing to commit/.test(r.out + r.errOut)) return { error: (r.out + r.errOut).slice(0, 300) };
      return { ok: true, out: (r.out + r.errOut).trim().split('\n')[0] };
    },
    revert: async () => {
      if (args.confirm !== true) return { error: 'revert needs confirm: true — it discards changes' };
      if (args.mode === 'commit') {
        const r = await run('git', ['reset', '--hard', 'HEAD~1']);
        if (r.err) return { error: (r.out + r.errOut).slice(0, 300) };
        return { ok: true, note: 'last commit undone (hard reset HEAD~1)' };
      }
      const r = await run('git', ['checkout', '--', '.']);
      if (r.err) return { error: (r.out + r.errOut).slice(0, 300) };
      return { ok: true, note: 'uncommitted changes discarded' };
    },
  };
  const fn = acts[action];
  if (!fn) return { error: `unknown git action "${action}" — use status, diff, log, commit or revert` };
  const out = await fn();
  return out;
}

module.exports = { listSource, readSource, editSource, restartServer, git, generation, revertTo, PROJECT_ROOT };
