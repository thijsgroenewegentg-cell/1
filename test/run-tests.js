/**
 * ULTRON — integration test suite.
 * Spins up mock Ollama + mock voice endpoints, starts the real server on an
 * ephemeral port with an isolated data dir, and exercises every subsystem.
 *
 *   npm test
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'ultron-test-'));
process.env.ULTRON_DATA = DATA_DIR;
process.env.OLLAMA_URL = 'http://127.0.0.1:11439';

const OLLAMA = process.env.OLLAMA_URL;
const DEAD_OLLAMA = 'http://127.0.0.1:9'; // demo mode

let BASE = null;
let passed = 0;
let failed = 0;
const failures = [];

function ok(name, cond, extra) {
  if (cond) {
    passed++;
    console.log(`  ✓ ${name}`);
  } else {
    failed++;
    failures.push(name + (extra ? ` — ${extra}` : ''));
    console.log(`  ✗ ${name}${extra ? ' — ' + extra : ''}`);
  }
}

async function sseCollect(fetchPromise, opts = {}) {
  const { maxMs = 8000, until = () => false } = opts;
  const res = await fetchPromise;
  if (!res.ok || !res.body) return { events: [], text: '' };
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  const events = [];
  const deadline = Date.now() + maxMs;
  let readPromise = null; // single persistent read — orphaned reads would swallow chunks
  try {
    while (Date.now() < deadline) {
      if (!readPromise) readPromise = reader.read();
      const result = await Promise.race([readPromise, new Promise((r) => setTimeout(() => r(null), 150))]);
      if (result === null) { if (until(events)) break; continue; }
      readPromise = null;
      if (result.done) break;
      buf += decoder.decode(result.value, { stream: true });
      let nl;
      while ((nl = buf.indexOf('\n\n')) !== -1) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 2);
        if (!line.startsWith('data:')) continue;
        try { events.push(JSON.parse(line.slice(5))); } catch { /* skip */ }
      }
      if (until(events)) break;
    }
  } finally {
    try { reader.cancel(); } catch { /* noop */ }
  }
  return { events, text: events.filter((e) => e.type === 'token').map((e) => e.token).join('') };
}

/** POST /api/chat and collect the stream until done. */
async function chatUntil(messages, extra = {}, opts = {}) {
  const body = JSON.stringify({ messages, ollamaUrl: OLLAMA, ...extra });
  const p = fetch(`${BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
  });
  return sseCollect(p, { until: (ev) => ev.some((e) => e.type === 'done'), ...opts });
}

/** Chat that auto-approves approval requests mid-stream (persistent read, no orphans). */
async function chatWithApproval(messages, extra = {}) {
  const res = await fetch(BASE + '/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, ollamaUrl: OLLAMA, ...extra }),
  });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  const events = [];
  const answered = new Set();
  let readPromise = null;
  const deadline = Date.now() + 15000;
  try {
    while (Date.now() < deadline) {
      if (!readPromise) readPromise = reader.read();
      const result = await Promise.race([readPromise, new Promise((r) => setTimeout(() => r(null), 150))]);
      if (result === null) continue;
      readPromise = null;
      if (result.done) break;
      buf += decoder.decode(result.value, { stream: true });
      let nl;
      while ((nl = buf.indexOf('\n\n')) !== -1) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 2);
        if (!line.startsWith('data:')) continue;
        try { events.push(JSON.parse(line.slice(5))); } catch { /* skip */ }
      }
      const ap = events.find((e) => e.type === 'approval_required' && !answered.has(e.id));
      if (ap) {
        answered.add(ap.id);
        await fetch(BASE + '/api/approval', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: ap.id, approved: true }),
        });
      }
      if (events.some((e) => e.type === 'done')) break;
    }
  } finally {
    try { reader.cancel(); } catch { /* noop */ }
  }
  return { events, text: events.filter((e) => e.type === 'token').map((e) => e.token).join('') };
}

const j = (r) => r.json();

async function main() {
  console.log('\nULTRON TEST SUITE\n=================');

  const mockOllama = require('./mock-ollama');
  const mockVoice = require('./mock-voice');
  await mockOllama.start(11439);
  const voice = await mockVoice.start(9966);

  const { start } = require('../server');
  const httpServer = await new Promise((resolve) => {
    const srv = start(0);
    srv.on('listening', () => resolve(srv));
  });
  BASE = `http://127.0.0.1:${httpServer.address().port}`;
  console.log(`server on ${BASE} · data in ${DATA_DIR}\n`);

  /* ---------- basics ---------- */
  console.log('basics');
  {
    const health = await j(await fetch(`${BASE}/api/health`));
    ok('health', health.ok === true);

    const cfg1 = await j(await fetch(`${BASE}/api/config`));
    ok('config defaults', cfg1.toolsEnabled === true && cfg1.autoMemory === true);

    const cfg2 = await j(await fetch(`${BASE}/api/config`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ elevenKey: 'sk-test', elevenVoice: 'adam-1', elevenUrl: 'http://127.0.0.1:9966' }),
    }));
    ok('eleven key masked on save', cfg2.elevenKey === '' && cfg2.elevenKeySet === true);

    const status = await j(await fetch(`${BASE}/api/status?url=${encodeURIComponent(OLLAMA)}`));
    ok('status online with models', status.online === true && status.models.length >= 3);
  }

  /* ---------- demo mode ---------- */
  console.log('demo mode');
  {
    const r = await chatUntil([{ role: 'user', content: 'hallo ultron, wie ben jij' }], { ollamaUrl: DEAD_OLLAMA });
    ok('dutch demo reply', /Ik ben Ultron/.test(r.text), r.text.slice(0, 80));
  }

  /* ---------- routing + language + research ---------- */
  console.log('routing / language / research');
  {
    let r = await chatUntil([{ role: 'user', content: 'hoi' }]);
    let meta = r.events.find((e) => e.type === 'meta');
    ok('short → fast model', meta && meta.model === 'llama3.2:3b' && meta.routing === 'fast');

    r = await chatUntil([{ role: 'user', content: 'please explain in great depth why tides work' }]);
    meta = r.events.find((e) => e.type === 'meta');
    ok('complex → smart model', meta && meta.model === 'llama3.1:8b' && meta.routing === 'deep');

    r = await chatUntil([{ role: 'user', content: 'wat zie je', images: ['data:image/png;base64,QUJD'] }]);
    meta = r.events.find((e) => e.type === 'meta');
    ok('image → vision model', meta && meta.routing === 'vision' && meta.tools === false);

    r = await chatUntil([{ role: 'user', content: 'research quantum computing' }], { mode: 'research', language: 'nl' });
    meta = r.events.find((e) => e.type === 'meta');
    ok('research mode meta', meta && meta.mode === 'research');
    ok('research prompt + nl directive', /research-prompt/.test(r.text) && /nl-directive/.test(r.text), r.text.slice(0, 90));
  }

  /* ---------- tools + approval ---------- */
  console.log('tools & approval');
  {
    let r = await chatUntil([{ role: 'user', content: 'schrijf een bestand voor me' }]);
    ok('write_file tool executed', fs.existsSync(path.join(DATA_DIR, 'files', 'greeting.txt')));
    ok('tool events streamed', r.events.some((e) => e.type === 'tool' && e.name === 'write_file'));

    r = await chatUntil([{ role: 'user', content: 'onthoud dit even' }]);
    const mem = await j(await fetch(`${BASE}/api/memory`));
    ok('remember tool stores memory', mem.memories.some((m) => /test suites/.test(m.fact)));

    await fetch(`${BASE}/api/config`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ toolApproval: true }) });
    const p = fetch(`${BASE}/api/chat`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'user', content: 'runcommand now' }], ollamaUrl: OLLAMA }),
    });
    const ar = await sseCollect(p, { maxMs: 6000, until: (ev) => ev.some((e) => e.type === 'approval_required') });
    const approval = ar.events.find((e) => e.type === 'approval_required');
    ok('approval requested for run_command', !!approval);
    if (approval) {
      const answer = await j(await fetch(`${BASE}/api/approval`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: approval.id, approved: true }),
      }));
      ok('approval answered', answer.ok === true);
      await new Promise((r2) => setTimeout(r2, 900));
      ok('approved command ran', fs.existsSync(path.join(DATA_DIR, 'files', 'approved.txt')));
    }
    await fetch(`${BASE}/api/config`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ toolApproval: false }) });
  }

  /* ---------- knowledge (PDF + hybrid + incremental) ---------- */
  console.log('knowledge / RAG');
  {
    fs.mkdirSync(path.join(DATA_DIR, 'knowledge', 'docs'), { recursive: true });
    const realPdf = path.join(process.cwd(), 'node_modules', 'pdf-parse', 'test', 'data', '01-valid.pdf');
    fs.copyFileSync(realPdf, path.join(DATA_DIR, 'knowledge', 'docs', 'paper.pdf'));
    fs.writeFileSync(path.join(DATA_DIR, 'knowledge', 'docs', 'kat.md'), 'Mijn kat heet Neko uit Leiderdorp. De dierenarts zegt dat Neko zonnepanelen prachtig vindt.');

    const scan = await j(await fetch(`${BASE}/api/knowledge/scan`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ollamaUrl: OLLAMA }),
    }));
    ok('scan indexes files (incl. PDF)', scan.ok === true && scan.chunks > 5, JSON.stringify(scan).slice(0, 80));

    const r = await chatUntil([{ role: 'user', content: 'wat weet je over neko de kat' }]);
    const tr = r.events.find((e) => e.type === 'tool_result' && e.name === 'search_knowledge');
    ok('hybrid search returns kat.md first', tr && /kat\.md/.test(JSON.stringify(tr.result).slice(0, 200)));

    const scan2 = await j(await fetch(`${BASE}/api/knowledge/scan`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ollamaUrl: OLLAMA }),
    }));
    ok('incremental rescan reuses chunks', scan2.ok === true && scan2.reused >= 2, JSON.stringify(scan2).slice(0, 90));
  }

  /* ---------- skills ---------- */
  console.log('skills');
  {
    fs.mkdirSync(path.join(DATA_DIR, 'skills'), { recursive: true });
    fs.writeFileSync(path.join(DATA_DIR, 'skills', 'price.json'), JSON.stringify({
      name: 'get_crypto_price',
      description: 'Get crypto price',
      parameters: { type: 'object', properties: { coin: { type: 'string' } }, required: ['coin'] },
      http: { method: 'GET', url: 'http://127.0.0.1:9967/price?coin={{coin}}' },
    }));
    const skillServer = await new Promise((resolve) => {
      const srv = require('http').createServer((req, res) => {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ bitcoin: { usd: 61234.5 } }));
      });
      srv.listen(9967, '127.0.0.1', () => resolve(srv));
    });
    const r = await chatUntil([{ role: 'user', content: 'crypto price skilltest' }]);
    const tr = r.events.find((e) => e.type === 'tool_result' && e.name === 'get_crypto_price');
    ok('skill executed via HTTP', tr && /61234/.test(JSON.stringify(tr.result)));
    skillServer.close();
  }

  /* ---------- sessions ---------- */
  console.log('sessions');
  {
    const put = await j(await fetch(`${BASE}/api/sessions/c1`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'test session', updated: Date.now(), messages: [{ role: 'user', content: 'hoi' }, { role: 'assistant', content: 'hallo' }] }),
    }));
    ok('session saved', put.id === 'c1' && put.messages.length === 2);
    const list = await j(await fetch(`${BASE}/api/sessions`));
    ok('session listed', list.sessions.length === 1 && list.sessions[0].title === 'test session');
    const got = await j(await fetch(`${BASE}/api/sessions/c1`));
    ok('session fetched', got.messages[0].content === 'hoi');
    const del = await j(await fetch(`${BASE}/api/sessions/c1`, { method: 'DELETE' }));
    ok('session deleted', del.ok === true);
  }

  /* ---------- directives ---------- */
  console.log('standing orders');
  {
    const add = await j(await fetch(`${BASE}/api/directives`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instruction: 'directive test check kat', every_minutes: 60 }),
    }));
    ok('directive added', add.ok === true);
    const evPromise = sseCollect(fetch(`${BASE}/api/events`), { maxMs: 6000, until: (ev) => ev.some((e) => e.type === 'directive') });
    await new Promise((r) => setTimeout(r, 400));
    await fetch(`${BASE}/api/directives/${add.directive.id}/run`, { method: 'POST' });
    const ev = await evPromise;
    const dir = ev.events.find((e) => e.type === 'directive');
    ok('directive ran and broadcast', !!dir && /directive test check kat/.test(dir.instruction));
  }

  /* ---------- wake + mission log ---------- */
  console.log('wake & mission log');
  {
    const evPromise = sseCollect(fetch(`${BASE}/api/events`), { maxMs: 4000, until: (ev) => ev.some((e) => e.type === 'wake') });
    await new Promise((r) => setTimeout(r, 300));
    await fetch(`${BASE}/api/wake`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: 'test' }) });
    const ev = await evPromise;
    ok('wake broadcast', ev.events.some((e) => e.type === 'wake'));

    const log = await j(await fetch(`${BASE}/api/log`));
    ok('mission log records work', log.entries.some((e) => e.kind === 'tool'));
    ok('mission log records wake', log.entries.some((e) => e.kind === 'wake'));
  }

  /* ---------- summarization ---------- */
  console.log('context summarization');
  {
    const msgs = [];
    for (let i = 0; i < 25; i++) msgs.push({ role: i % 2 ? 'assistant' : 'user', content: 'bericht nummer ' + i });
    const r = await chatUntil(msgs);
    ok('session summary injected', /session-summary/.test(r.text), r.text.slice(0, 80));
  }

  /* ---------- voice proxies ---------- */
  console.log('voice proxies');
  {
    // Piper first — clear the eleven key so piper takes priority.
    await fetch(`${BASE}/api/config`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ elevenKeyClear: true, sttUrl: 'http://127.0.0.1:9966', ttsUrl: 'http://127.0.0.1:9966' }) });
    const wav = Buffer.from('RIFFfake-wav-data');
    const stt = await j(await fetch(`${BASE}/api/transcribe?language=nl`, { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav }));
    ok('whisper proxy', stt.text === 'goedemorgen ultron');
    ok('whisper got multipart + language', voice.seen.whisper.some((w) => w.multipart && /name="language"\r\n\r\nnl/.test(w.body)));

    const tts = await fetch(`${BASE}/api/tts?text=hallo`);
    ok('piper proxy', tts.ok && /audio\/wav/.test(tts.headers.get('content-type')));

    // Now eleven — set the key; it takes priority over piper.
    await fetch(`${BASE}/api/config`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ elevenKey: 'sk-test', elevenVoice: 'adam-1', elevenUrl: 'http://127.0.0.1:9966' }) });
    const tts2 = await fetch(`${BASE}/api/tts?text=Er%20zijn%20geen%20draden`);
    ok('eleven proxy preferred over piper', tts2.ok && /audio\/mpeg/.test(tts2.headers.get('content-type')));
    ok('eleven got key + voice', voice.seen.eleven.some((e) => e.key === 'sk-test' && e.voice === 'adam-1'));

    const usage = await j(await fetch(`${BASE}/api/elevenlabs/usage`));
    ok('eleven usage meter', usage.character_limit === 10000 && usage.character_count === 1234);

    await fetch(`${BASE}/api/config`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ elevenKeyClear: true, sttUrl: '', ttsUrl: '' }) });
  }

  /* ---------- push ---------- */
  console.log('push');
  {
    const key = await j(await fetch(`${BASE}/api/push/key`));
    ok('vapid key generated', typeof key.publicKey === 'string' && key.publicKey.length > 60);
    const sub = await j(await fetch(`${BASE}/api/push/subscribe`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint: 'https://push.test/x1', keys: { p256dh: 'a', auth: 'b' } }),
    }));
    ok('subscription stored', sub.ok === true && sub.count === 1);
  }

  /* ---------- backup / restore ---------- */
  console.log('backup & restore');
  {
    const bundle = await j(await fetch(`${BASE}/api/backup`));
    ok('backup bundle built', bundle.ultronBackup === 1 && !!bundle.files && !!bundle.files['memory.json']);
    await fetch(`${BASE}/api/memory?all=1`, { method: 'DELETE' });
    let mem = await j(await fetch(`${BASE}/api/memory`));
    ok('memory wiped', mem.memories.length === 0);
    const restored = await j(await fetch(`${BASE}/api/restore`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(bundle),
    }));
    ok('restore ok', restored.ok === true);
    mem = await j(await fetch(`${BASE}/api/memory`));
    ok('memory restored from backup', mem.memories.length > 0);
  }

  /* ---------- model manager ---------- */
  console.log('model manager');
  {
    const pull = await sseCollect(fetch(`${BASE}/api/models/pull`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'tiny.test:1', ollamaUrl: OLLAMA }),
    }), { until: (ev) => ev.some((e) => e.status === 'success') });
    ok('pull streams progress', pull.events.some((e) => e.pct === 50) && pull.events.some((e) => e.status === 'success'));

    const del = await j(await fetch(`${BASE}/api/models?name=tiny.test:1&ollamaUrl=${encodeURIComponent(OLLAMA)}`, { method: 'DELETE' }));
    ok('model delete', del.ok === true);
  }

  /* ---------- token auth ---------- */
  console.log('token auth');
  {
    await fetch(`${BASE}/api/config`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ accessToken: 'geheim' }) });
    let r = await fetch(`${BASE}/api/memory`);
    ok('401 without token', r.status === 401);
    r = await fetch(`${BASE}/api/memory`, { headers: { 'X-Ultron-Token': 'geheim' } });
    ok('200 with token', r.status === 200);
    r = await fetch(`${BASE}/api/memory?token=geheim`);
    ok('200 with query token (SSE)', r.status === 200);
    await fetch(`${BASE}/api/config`, { method: 'PUT', headers: { 'X-Ultron-Token': 'geheim', 'Content-Type': 'application/json' }, body: JSON.stringify({ accessToken: '' }) });
  }

  /* ---------- profiles ---------- */
  console.log('profiles');
  {
    await fetch(`${BASE}/api/memory`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fact: 'Pim plays guitar', profile: 'pim' }) });
    await fetch(`${BASE}/api/memory`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fact: 'Main user likes tea' }) });
    const main = await j(await fetch(`${BASE}/api/memory?profile=main`));
    const pim = await j(await fetch(`${BASE}/api/memory?profile=pim`));
    ok('memory scoped per profile', !main.memories.some((m) => /guitar/.test(m.fact)) && pim.memories.some((m) => /guitar/.test(m.fact)));
    const r = await chatUntil([{ role: 'user', content: 'vertel over gitaar' }], { profile: 'pim' });
    ok('profile memories injected', /memories/.test(r.text), r.text.slice(0, 80));
  }

  /* ---------- self-modification ---------- */
  console.log('self-modification');
  {
    const selfedit = require('../lib/selfedit');
    const fixtureRel = path.join('test', 'fixtures', 'selfedit-target.js');
    const fixture = path.join(process.cwd(), fixtureRel);
    fs.mkdirSync(path.dirname(fixture), { recursive: true });
    fs.writeFileSync(fixture, 'const greeting = "hello";\nmodule.exports = { greeting };\n');

    const listing = selfedit.listSource('lib');
    ok('list own source files', listing.files.some((f) => f.path === 'lib/persona.js'));

    const read = selfedit.readSource(fixtureRel);
    ok('read own source', read.content && read.content.includes('hello'));

    const edit = await selfedit.editSource({ path: fixtureRel, find: '"hello"', replace: '"goedendag"' });
    ok('surgical edit applied', edit.ok === true && fs.readFileSync(fixture, 'utf8').includes('goedendag'));
    ok('edit backed up automatically', !!edit.backup && fs.existsSync(path.join(process.cwd(), edit.backup)));

    const bad = await selfedit.editSource({ path: fixtureRel, find: '"goedendag"', replace: '"this is ) broken' });
    ok('broken edit rejected by syntax gate', bad.rejected === true && fs.readFileSync(fixture, 'utf8').includes('goedendag'));

    ok('data/ off-limits', !!(await selfedit.editSource({ path: 'data/memory.json', content: 'x' })).error);
    ok('.git off-limits', !!(await selfedit.editSource({ path: '.git/config', content: 'x' })).error);
    ok('path escape blocked', !!(await selfedit.editSource({ path: '../outside.js', content: 'x' })).error);

    // Agent-level: self-edits are gated by default, reported, and undoable.
    const genBefore = (await j(await fetch(BASE + '/api/generation'))).count;
    const r = await chatWithApproval([{ role: 'user', content: 'selfedittest please' }]);
    const approval = r.events.find((e) => e.type === 'approval_required' && e.name === 'edit_source');
    ok('self-edit requires approval by default', !!approval);
    const tr = r.events.find((e) => e.type === 'tool_result' && e.name === 'edit_source');
    ok('approved self-edit applied', tr && tr.result && tr.result.ok === true && fs.readFileSync(fixture, 'utf8').includes('tot ziens'));
    const se = r.events.find((e) => e.type === 'self_edit');
    ok('mandatory change report emitted', se && se.path === fixtureRel && se.generation === genBefore + 1 && String(se.changed_from).includes('goedendag'));
    const genAfter = (await j(await fetch(BASE + '/api/generation'))).count;
    ok('generation counter increments', genAfter === genBefore + 1);

    // One-click undo via the revert endpoint.
    const rv = await j(await fetch(BASE + '/api/selfedit/revert', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ backup: se.backup }),
    }));
    ok('revert endpoint restores backup', rv.ok === true && fs.readFileSync(fixture, 'utf8').includes('goedendag'));
    const rvBad = await j(await fetch(BASE + '/api/selfedit/revert', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ backup: 'data/memory.json' }),
    }));
    ok('revert rejects paths outside code-backups', !!rvBad.error);

    const st = await selfedit.git('status');
    ok('git status works', typeof st.out === 'string' && st.out.length > 0);

    // Commit + revert only when the working tree is clean apart from the fixture.
    const lines = st.out.split('\n').filter((l) => l && !l.startsWith('##'));
    if (lines.length >= 1 && lines.every((l) => l.includes('selfedit-target'))) {
      const commit = await selfedit.git('commit', { message: 'test: selfedit fixture commit' });
      ok('git commit works', commit.ok === true);
      const log = await selfedit.git('log', { n: 1 });
      ok('git log shows commit', /selfedit fixture/.test(log.out));
      const revert = await selfedit.git('revert', { mode: 'commit', confirm: true });
      ok('git revert undoes commit', revert.ok === true && !fs.existsSync(fixture));
    } else {
      console.log('  (git commit/revert skipped — working tree has unrelated changes)');
      try { fs.unlinkSync(fixture); } catch { /* noop */ }
    }
  }

  /* ---------- one-shot directives ---------- */
  console.log('one-shot scheduled tasks');
  {
    const add = await j(await fetch(BASE + '/api/directives', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instruction: 'one-shot probe', once_at: new Date(Date.now() + 3600e3).toISOString() }),
    }));
    ok('one-shot order added', add.ok === true && /once at/.test(add.directive.schedule));
    ok('future one-shot is not due', !directivesDue('one-shot probe'));
    await fetch(BASE + '/api/directives/' + add.directive.id + '/run', { method: 'POST' });
    await new Promise((r) => setTimeout(r, 300));
    const list = await j(await fetch(BASE + '/api/directives'));
    ok('one-shot disappears after running', !list.directives.some((d) => /one-shot probe/.test(d.instruction)));
    function directivesDue(needle) {
      const lib = require('../lib/directives');
      return lib.due().some((d) => d.instruction.includes(needle));
    }
  }

  /* ---------- reasoning lane (thinking tokens) ---------- */
  console.log('reasoning lane');
  {
    // Inline mini-mock that streams thinking + <think> tagged content.
    const thinkSrv = await new Promise((resolve) => {
      const srv = require('http').createServer((req, res) => {
        let b = '';
        req.on('data', (c) => b += c);
        req.on('end', () => {
          const p = JSON.parse(b);
          res.writeHead(200, { 'Content-Type': 'application/x-ndjson' });
          const chunks = [
            { message: { role: 'assistant', thinking: 'Let me reason: ' } },
            { message: { role: 'assistant', thinking: 'two plus two is four. ' } },
            { message: { role: 'assistant', content: '<think>hidden chain</think>The answer is ' } },
            { message: { role: 'assistant', content: 'four.' } },
            { message: { role: 'assistant', content: '' }, done: true },
          ];
          for (const c of chunks) res.write(JSON.stringify(c) + '\n');
          res.end();
        });
      });
      srv.listen(9963, '127.0.0.1', () => resolve(srv));
    });
    const { streamOllamaChat } = require('../lib/ollama');
    const events = [];
    for await (const evt of streamOllamaChat({ ollamaUrl: 'http://127.0.0.1:9963', model: 'llama3.1:8b', messages: [{ role: 'user', content: 'q' }] })) {
      events.push(evt);
    }
    const thinking = events.filter((e) => e.type === 'thinking').map((e) => e.token).join('');
    const tokens = events.filter((e) => e.type === 'token').map((e) => e.token).join('');
    ok('thinking events streamed', thinking.includes('two plus two is four.'));
    ok('think tags routed out of the answer', tokens.includes('The answer is four.') && !tokens.includes('<think>') && !tokens.includes('hidden chain'));
    thinkSrv.close();
  }

  /* ---------- legion (drone swarm) ---------- */
  console.log('legion drones');
  {
    const r = await chatUntil([{ role: 'user', content: 'legioontest please' }]);
    const tr = r.events.find((e) => e.type === 'tool_result' && e.name === 'spawn_drones');
    ok('drones spawned and reported', tr && tr.result && tr.result.ok === true && tr.result.drones === 2);
    ok('drone reports collected', tr && /DRONE REPORT/.test(JSON.stringify(tr.result.reports || [])));
  }

  /* ---------- conversation search ---------- */
  console.log('conversation search');
  {
    await fetch(BASE + '/api/sessions/searchtest1', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'zonnebloem', updated: Date.now(), messages: [
        { role: 'user', content: 'vertel over zonnebloemen in de tuin' },
        { role: 'assistant', content: 'Zonnebloemen draaien naar de zon.' },
      ] }),
    });
    await fetch(BASE + '/api/sessions/searchtest2', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'kat', updated: Date.now(), messages: [
        { role: 'user', content: 'mijn kat heet neko' },
      ] }),
    });
    const res = await j(await fetch(BASE + '/api/sessions/search?q=' + encodeURIComponent('zonnebloem')));
    ok('search finds the right session', res.results.length === 1 && res.results[0].sessionId === 'searchtest1');
    ok('search returns snippets', res.results[0] && /zonnebloem/i.test(res.results[0].matches[0].snippet));
    const res2 = await j(await fetch(BASE + '/api/sessions/search?q=' + encodeURIComponent('neko')));
    ok('search finds the second session', res2.results.length === 1 && res2.results[0].sessionId === 'searchtest2');
    await fetch(BASE + '/api/sessions/searchtest1', { method: 'DELETE' });
    await fetch(BASE + '/api/sessions/searchtest2', { method: 'DELETE' });
  }

  /* ---------- integrity ---------- */
  console.log('integrity check');
  {
    const before = await j(await fetch(BASE + '/api/integrity'));
    if (!before.baselined) {
      await fetch(BASE + '/api/integrity/trust', { method: 'POST' });
    }
    const clean = await j(await fetch(BASE + '/api/integrity'));
    ok('baseline clean after trust', clean.baselined && clean.changed.length === 0);

    // Tamper with his source outside the approval flow…
    const fsx = require('fs');
    const target = path.join(process.cwd(), 'lib', 'selfedit.js');
    const original = fsx.readFileSync(target, 'utf8');
    fsx.writeFileSync(target, original + '\n// integrity tamper test\n');
    const drift = await j(await fetch(BASE + '/api/integrity'));
    ok('tampering detected', drift.changed.includes('lib/selfedit.js'));
    fsx.writeFileSync(target, original);
    const after = await j(await fetch(BASE + '/api/integrity'));
    ok('restore clears the drift', after.changed.length === 0);
  }

  /* ---------- telegram bridge ---------- */
  console.log('telegram bridge');
  {
    const tg = require('./mock-telegram');
    const mock = await tg.start(9969);
    await fetch(BASE + '/api/config', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ telegramToken: 'TESTTOKEN', telegramUrl: 'http://127.0.0.1:9969' }),
    });

    // Wait for pairing + the agent's answer to the second message.
    const deadline = Date.now() + 15000;
    while (Date.now() < deadline) {
      const paired = mock.sent.some((m) => /Pairing complete/.test(m.text));
      const answered = mock.sent.some((m) => /syscheck|DRONE|model=/.test(m.text));
      if (paired && answered) break;
      await new Promise((r) => setTimeout(r, 500));
    }
    ok('telegram auto-pairs first chat', mock.sent.some((m) => String(m.chat_id) === '12345' && /Pairing complete/.test(m.text)));
    ok('telegram answers via the full agent', mock.sent.some((m) => String(m.chat_id) === '12345' && /model=/.test(m.text)));
    const status = await j(await fetch(BASE + '/api/telegram/status'));
    ok('paired chat id stored', status.tokenSet === true && status.chatIds.includes('12345'));

    await fetch(BASE + '/api/config', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ telegramTokenClear: true }),
    });
    mock.server.close();
  }

  /* ---------- security (unit) ---------- */
  console.log('security');
  {
    const security = require('../lib/security');
    const limiter = security.rateLimit({ windowMs: 1000, max: 3 });
    const mk = () => ({ headers: {}, socket: { remoteAddress: '9.9.9.9' } });
    const codes = [];
    for (let i = 0; i < 5; i++) {
      await new Promise((resolve) => {
        limiter(mk(), { setHeader: () => {}, status: (c) => ({ json: () => resolve(codes.push(c)) }) }, resolve);
      });
    }
    ok('rate limiter trips after max', codes.filter((c) => c === 429).length >= 2, JSON.stringify(codes));

    const guard = security.authGuard({ maxFails: 2, lockMs: 60000 });
    const req = mk();
    guard.noteFailure(req); guard.noteFailure(req);
    ok('lockout after repeated failures', guard.isLocked(req) === true);
    const okReq = { headers: {}, socket: { remoteAddress: '8.8.8.8' } };
    ok('other clients unaffected', guard.isLocked(okReq) === false);
  }

  /* ---------- wrap up ---------- */
  console.log('\n──────────────────────────────');
  console.log(`${passed} passed · ${failed} failed`);
  if (failures.length) {
    console.log('failures:');
    for (const f of failures) console.log('  - ' + f);
  }
  httpServer.close();
  process.exit(failed > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error('SUITE CRASHED:', err);
  process.exit(1);
});
