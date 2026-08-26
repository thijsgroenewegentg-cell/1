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
