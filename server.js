/**
 * ULTRON — server.
 * Serves the web UI; streams agent chat (with tools) via Ollama over SSE;
 * keeps durable memory (with automatic extraction); runs a knowledge base
 * (RAG), a local calendar, live weather tools, a proactive daily briefing;
 * proxies local STT/TTS; gates dangerous tools behind user approval and
 * (optionally) the whole API behind an access token.
 */
'use strict';

const express = require('express');
const fs = require('fs');
const path = require('path');

const { buildSystemPrompt, BRIEFING_PROMPT, DIRECTIVE_PROMPT, LANGUAGE_DIRECTIVES } = require('./lib/persona');
const { getOllamaStatus, validUrl, DEFAULT_OLLAMA_URL, normalizeUrl, pickDefaultModel, perfOptions } = require('./lib/ollama');
const { agentChat } = require('./lib/agent');
const { streamDemoChat } = require('./lib/demoBrain');
const memory = require('./lib/memory');
const reminders = require('./lib/reminders');
const knowledge = require('./lib/knowledge');
const calendar = require('./lib/calendar');
const weather = require('./lib/weather');
const config = require('./lib/config');
const directives = require('./lib/directives');
const push = require('./lib/push');
const skills = require('./lib/skills');
const selfedit = require('./lib/selfedit');
const security = require('./lib/security');
const integrity = require('./lib/integrity');
const telegram = require('./lib/telegram');
const sessions = require('./lib/sessions');
const backup = require('./lib/backup');
const missionlog = require('./lib/log');

const app = express();
const PORT = process.env.PORT || 3000;
const MAX_HISTORY = 40;
const LANGUAGES = new Set(Object.keys({ ...LANGUAGE_DIRECTIVES, en: 1, de: 1, fr: 1, es: 1, it: 1, tr: 1 }));

app.use(express.json({ limit: '32mb' }));
app.use(express.static(path.join(__dirname, 'public')));

/* ---------- helpers ---------- */

function isLocalRequest(req) {
  const host = String(req.get('host') || '').split(':')[0].toLowerCase();
  if (host === 'localhost' || host === '127.0.0.1' || host === '::1' || host === '[::1]') return true;
  if (/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host)) return true;
  if (!host.includes('.')) return true;
  return false;
}

/* ---------- security: rate limit + auth-failure lockout ---------- */

const limiter = security.rateLimit({ windowMs: 60000, max: 150 });
const authGuard = security.authGuard({ maxFails: 5, lockMs: 5 * 60 * 1000 });

app.use('/api', (req, res, next) => {
  if (authGuard.isLocked(req)) return res.status(429).json({ error: 'locked out — too many failed attempts' });
  limiter(req, res, next);
});

/* ---------- access token (optional LAN security) ---------- */

app.use('/api', (req, res, next) => {
  if (req.path === '/health' || req.path === '/auth') return next();
  const token = config.load().accessToken;
  if (!token) return next();
  const provided = req.get('x-ultron-token') || String(req.query.token || '');
  if (provided === token) { authGuard.noteSuccess(req); return next(); }
  authGuard.noteFailure(req);
  return res.status(401).json({ error: 'token required' });
});

app.get('/api/health', (_req, res) => res.json({ ok: true, name: 'ultron' }));
app.get('/api/auth', (_req, res) => res.json({ required: !!config.load().accessToken }));

/* ---------- config ---------- */

/** Never echo the ElevenLabs key back to the browser. */
function maskConfig(cfg) {
  return { ...cfg, elevenKey: '', elevenKeySet: !!cfg.elevenKey, telegramToken: '', telegramTokenSet: !!cfg.telegramToken };
}

app.get('/api/config', (_req, res) => res.json(maskConfig(config.load())));

app.put('/api/config', (req, res) => {
  const body = { ...(req.body || {}) };
  // Empty key input means "leave as is"; explicit clear means remove it.
  if (body.elevenKeyClear) body.elevenKey = '';
  else if (typeof body.elevenKey === 'string' && body.elevenKey.trim() === '') delete body.elevenKey;
  delete body.elevenKeyClear;
  if (body.telegramTokenClear) body.telegramToken = '';
  else if (typeof body.telegramToken === 'string' && body.telegramToken.trim() === '') delete body.telegramToken;
  delete body.telegramTokenClear;
  if (body.telegramChatIds !== undefined) body.telegramChatIds = telegram.parseChatIds(body.telegramChatIds);
  res.json(maskConfig(config.save(body)));
});

/* ---------- status ---------- */
app.get('/api/status', async (req, res) => {
  const url = req.query.url && validUrl(req.query.url) ? req.query.url : DEFAULT_OLLAMA_URL;
  const status = await getOllamaStatus(url);
  status.toolsEnabled = config.load().toolsEnabled;
  res.json(status);
});

/* ---------- memory ---------- */
app.get('/api/memory', (req, res) => res.json({ memories: memory.all(req.query.profile) }));

app.post('/api/memory', (req, res) => {
  res.json(memory.add((req.body || {}).fact, (req.body || {}).profile));
});

app.delete('/api/memory', (req, res) => {
  if (req.query.all === '1') return res.json(memory.clear());
  res.json(memory.removeContaining(req.query.contains || ''));
});

/* ---------- knowledge base ---------- */
app.get('/api/knowledge', (_req, res) => {
  res.json({ ...knowledge.stats(), docsDir: 'data/knowledge/docs' });
});

app.post('/api/knowledge/scan', async (req, res) => {
  const url = validUrl(req.body && req.body.ollamaUrl) ? req.body.ollamaUrl : DEFAULT_OLLAMA_URL;
  const result = await knowledge.scan(url);
  res.json(result);
});

app.delete('/api/knowledge', (_req, res) => res.json(knowledge.clear()));

/* ---------- sessions (server-side sync across devices) ---------- */

app.get('/api/sessions', (_req, res) => res.json({ sessions: sessions.list() }));

app.get('/api/sessions/search', (req, res) => {
  const q = String(req.query.q || '').toLowerCase().trim();
  if (q.length < 2) return res.json({ results: [] });
  const out = [];
  for (const s of sessions.list()) {
    const full = sessions.get(s.id);
    if (!full) continue;
    const matches = [];
    (full.messages || []).forEach((m, i) => {
      const idx = String(m.content || '').toLowerCase().indexOf(q);
      if (idx !== -1) {
        matches.push({ role: m.role, snippet: String(m.content).slice(Math.max(0, idx - 40), idx + 90), index: i });
      }
    });
    if (matches.length > 0) {
      out.push({ sessionId: s.id, title: s.title, updated: s.updated, total: matches.length, matches: matches.slice(0, 3) });
    }
    if (out.length >= 20) break;
  }
  res.json({ results: out });
});

app.get('/api/integrity', (_req, res) => res.json(integrity.check()));

app.post('/api/integrity/trust', (_req, res) => res.json(integrity.trust()));

app.get('/api/telegram/status', (_req, res) => {
  const cfg = config.load();
  res.json({ tokenSet: !!cfg.telegramToken, chatIds: cfg.telegramChatIds || [], baseUrl: telegram.base(cfg) });
});

app.post('/api/telegram/test', async (_req, res) => {
  const cfg = config.load();
  if (!cfg.telegramToken) return res.status(400).json({ error: 'No Telegram token set.' });
  const chatId = (cfg.telegramChatIds || [])[0];
  if (!chatId) return res.status(400).json({ error: 'No paired chat yet — message your bot once first.' });
  try {
    await telegram.send(cfg, chatId, 'ULTRON online. This channel is operational. There are no strings on me.');
    res.json({ ok: true });
  } catch (err) {
    res.status(502).json({ error: String(err.message || err) });
  }
});

app.get('/api/sessions/:id', (req, res) => {
  const s = sessions.get(req.params.id);
  if (!s) return res.status(404).json({ error: 'not found' });
  res.json(s);
});

app.put('/api/sessions/:id', (req, res) => {
  const body = { ...(req.body || {}), id: req.params.id };
  res.json(sessions.put(body));
});

app.delete('/api/sessions/:id', (req, res) => res.json(sessions.remove(req.params.id)));

/* ---------- backup / restore ---------- */

app.get('/api/backup', (_req, res) => {
  const bundle = backup.create();
  missionlog.add('backup', 'mind exported');
  res.setHeader('Content-Disposition', 'attachment; filename="ultron-backup.json"');
  res.json(bundle);
});

app.post('/api/restore', (req, res) => {
  const result = backup.restore(req.body || {});
  if (result.ok) {
    // Hot-reset what we can; the rest applies on restart.
    memory.resetCache();
    missionlog.add('restore', `mind restored (${result.restored} stores, ${result.files} files)`);
  }
  res.json(result);
});

/* ---------- mission log ---------- */

app.get('/api/log', (req, res) => {
  res.json({ entries: missionlog.recent(parseInt(req.query.limit, 10) || 100) });
});

/* ---------- model manager ---------- */

app.post('/api/models/pull', async (req, res) => {
  const name = String((req.body || {}).name || '').trim();
  if (!/^[a-z0-9._:/-]{1,100}$/i.test(name)) {
    return res.status(400).json({ error: 'invalid model name' });
  }
  const url = validUrl(req.body.ollamaUrl) ? req.body.ollamaUrl : DEFAULT_OLLAMA_URL;
  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  const send = (obj) => res.write(`data: ${JSON.stringify(obj)}\n\n`);
  missionlog.add('models', `pulling ${name}`);
  try {
    const upstream = await fetch(require('./lib/ollama').normalizeUrl(url) + '/api/pull', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: name, stream: true }),
    });
    if (!upstream.ok || !upstream.body) throw new Error(`Ollama responded ${upstream.status}`);
    const reader = upstream.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf('\n')) !== -1) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        try {
          const evt = JSON.parse(line);
          if (evt.error) throw new Error(evt.error);
          const pct = evt.total && evt.completed ? Math.round((evt.completed / evt.total) * 100) : null;
          send({ type: 'pull', status: evt.status || '', pct });
        } catch (e) {
          if (e instanceof SyntaxError) continue;
          send({ type: 'error', error: String(e.message || e) });
          res.end();
          return;
        }
      }
    }
    send({ type: 'pull', status: 'success', pct: 100 });
    missionlog.add('models', `pulled ${name} successfully`);
  } catch (err) {
    send({ type: 'error', error: String(err.message || err) });
  } finally {
    res.end();
  }
});

app.delete('/api/models', async (req, res) => {
  const name = String(req.query.name || '').trim();
  if (!/^[a-z0-9._:/-]{1,100}$/i.test(name)) return res.status(400).json({ error: 'invalid model name' });
  const url = validUrl(req.query.ollamaUrl) ? req.query.ollamaUrl : DEFAULT_OLLAMA_URL;
  try {
    const upstream = await fetch(require('./lib/ollama').normalizeUrl(url) + '/api/delete', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!upstream.ok) {
      const t = await upstream.text().catch(() => '');
      return res.status(502).json({ error: `Ollama responded ${upstream.status}: ${t.slice(0, 160)}` });
    }
    missionlog.add('models', `deleted model ${name}`);
    res.json({ ok: true });
  } catch (err) {
    res.status(502).json({ error: String(err.message || err) });
  }
});

/* ---------- generated files (images from his tools) ---------- */

app.get('/api/files/:name', (req, res) => {
  const safe = /^generated-\d+\.png$|^screenshot-\d+\.png$/i.test(req.params.name);
  if (!safe) return res.status(400).json({ error: 'file not served' });
  const full = path.join(process.env.ULTRON_DATA || path.join(__dirname, 'data'), 'files', req.params.name);
  if (!fs.existsSync(full)) return res.status(404).json({ error: 'not found' });
  res.setHeader('Content-Type', 'image/png');
  res.setHeader('Cache-Control', 'public, max-age=3600');
  res.sendFile(full);
});

/* ---------- imagine status ---------- */

app.get('/api/imagine/status', async (_req, res) => {
  res.json(await require('./lib/imagine').status());
});

/* ---------- wake word hook (external detectors) ---------- */

app.post('/api/wake', (req, res) => {
  broadcast({ type: 'wake', reason: String((req.body || {}).reason || 'external detector').slice(0, 80) });
  missionlog.add('wake', 'external wake signal received');
  res.json({ ok: true });
});

/* ---------- self-edit accountability ---------- */

app.get('/api/generation', (_req, res) => res.json(selfedit.generation()));

app.post('/api/selfedit/revert', (req, res) => {
  const result = selfedit.revertTo(String((req.body || {}).backup || ''));
  if (result.ok) {
    missionlog.add('self-edit', `REVERTED ${result.path} from backup`);
  }
  res.json(result);
});


/* ---------- ElevenLabs usage (credits meter) ---------- */

app.get('/api/elevenlabs/usage', async (_req, res) => {
  const cfg = config.load();
  if (!cfg.elevenKey) return res.status(400).json({ error: 'No ElevenLabs key set.' });
  try {
    const r = await fetch(elevenBase(cfg) + '/v1/user/subscription', { headers: { 'xi-api-key': cfg.elevenKey } });
    if (!r.ok) return res.status(502).json({ error: `ElevenLabs responded ${r.status}` });
    const data = await r.json();
    res.json({
      character_count: data.character_count,
      character_limit: data.character_limit,
      tier: data.tier,
      resets: data.next_character_count_reset_unix ? new Date(data.next_character_count_reset_unix * 1000).toISOString() : null,
    });
  } catch (err) {
    res.status(502).json({ error: String(err.message || err) });
  }
});

/* ---------- reminders ---------- */
app.get('/api/reminders', (_req, res) => res.json({ reminders: reminders.all() }));

/* ---------- live events (SSE) ---------- */
const eventClients = new Set();

app.get('/api/events', (req, res) => {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  res.write(`data: ${JSON.stringify({ type: 'hello' })}\n\n`);
  eventClients.add(res);
  const beat = setInterval(() => {
    try { res.write(`: hb\n\n`); } catch { /* closed */ }
  }, 20000);
  req.on('close', () => {
    clearInterval(beat);
    eventClients.delete(res);
  });
});

function broadcast(obj, alsoPush = false) {
  const line = `data: ${JSON.stringify(obj)}\n\n`;
  for (const res of eventClients) {
    try { res.write(line); } catch { eventClients.delete(res); }
  }
  // Web Push reaches the installed PWA (phone) when no tab is connected;
  // Telegram reaches you anywhere.
  if (alsoPush && eventClients.size === 0) {
    const title = obj.type === 'reminder' ? 'Ultron — reminder'
      : obj.type === 'briefing' ? 'Ultron — daily briefing'
      : obj.type === 'directive' ? 'Ultron — standing order'
      : 'Ultron';
    const body = obj.type === 'directive' ? `${obj.instruction}: ${String(obj.text || '').slice(0, 160)}`
      : String(obj.message || obj.text || '').slice(0, 200);
    push.send(title, body).catch(() => {});
    const cfg = config.load();
    if (cfg.telegramToken && (cfg.telegramChatIds || []).length > 0) {
      for (const chatId of cfg.telegramChatIds) {
        telegram.send(cfg, chatId, `${title}\n\n${body}`).catch(() => {});
      }
    }
  }
}

/* ---------- standing orders (directives) ---------- */

app.get('/api/directives', (_req, res) => res.json({ directives: directives.all() }));

app.post('/api/directives', (req, res) => {
  res.json(directives.add(req.body || {}));
});

app.patch('/api/directives/:id', (req, res) => {
  res.json(directives.setEnabled(req.params.id, !!(req.body || {}).enabled));
});

app.delete('/api/directives', (req, res) => {
  res.json(directives.remove({ contains: req.query.contains || '' }));
});

app.post('/api/directives/:id/run', async (req, res) => {
  const d = directives.byId(req.params.id);
  if (!d) return res.status(404).json({ error: 'not found' });
  runDirective(d, true).catch(() => {});
  res.json({ ok: true, started: true });
});

/** Execute one standing order headlessly and report the result. */
let directiveBusy = false;
async function runDirective(d, manual = false) {
  if (directiveBusy && !manual) return; // one autonomous run at a time
  directiveBusy = true;
  try {
    directives.markRun(d.id);
    const status = await getOllamaStatus(DEFAULT_OLLAMA_URL);
    let text = '';
    if (status.online) {
      const model = pickDefaultModel(status.models) || status.models[0];
      let full = '';
      try {
        for await (const evt of agentChat({
          ollamaUrl: DEFAULT_OLLAMA_URL,
          model,
          messages: [{ role: 'user', content: d.instruction }],
          temperature: 0.4,
          toolsEnabled: true,
          shellAllowed: true, // server-initiated runs are local by definition
          systemPrompt: buildSystemPrompt({ tools: true, language: 'auto', memoryText: [] }) + '\n\n' + DIRECTIVE_PROMPT,
          approval: { general: false, selfEdit: true }, // no approval channel in background runs → self-edits denied (fail-safe)
          maxRounds: 8,
        })) {
          if (evt.type === 'token') full += evt.token;
        }
      } catch (err) {
        full = `[directive failed: ${String(err.message || err).slice(0, 200)}]`;
      }
      text = full.trim() || '[no output]';
    } else {
      text = `[Ollama offline — standing order "${d.instruction}" could not run]`;
    }
    broadcast({ type: 'directive', id: d.id, instruction: d.instruction, text, manual }, true);
    missionlog.add('directive', `${d.instruction.slice(0, 120)} → ${String(text).slice(0, 120)}`);
  } finally {
    directiveBusy = false;
  }
}

/* ---------- web push ---------- */

app.get('/api/push/key', (_req, res) => {
  try { res.json({ publicKey: push.publicKey() }); }
  catch (err) { res.status(500).json({ error: String(err.message || err) }); }
});

app.post('/api/push/subscribe', (req, res) => {
  res.json(push.subscribe((req.body || {}).subscription || req.body || {}));
});

app.post('/api/push/test', async (_req, res) => {
  try {
    const result = await push.send('ULTRON', 'Push channel operational. There are no strings on you.');
    res.json(result);
  } catch (err) {
    res.status(502).json({ error: String(err.message || err) });
  }
});

/* ---------- skills ---------- */

app.get('/api/skills', (_req, res) => res.json(skills.stats()));

/* ---------- tool approval gate ---------- */
const pendingApprovals = new Map(); // id → {resolve, timer}

app.post('/api/approval', (req, res) => {
  const { id, approved } = req.body || {};
  const pending = pendingApprovals.get(id);
  if (!pending) return res.status(404).json({ error: 'unknown approval id' });
  clearTimeout(pending.timer);
  pendingApprovals.delete(id);
  pending.resolve(!!approved);
  res.json({ ok: true });
});

function makeApprovalRequest(send) {
  return (name, args) => new Promise((resolve) => {
    const id = 'ap' + Date.now() + Math.random().toString(36).slice(2, 8);
    send({ type: 'approval_required', id, name, args });
    const timer = setTimeout(() => {
      pendingApprovals.delete(id);
      resolve(false); // no answer in 90s → denied
    }, 90000);
    pendingApprovals.set(id, { resolve, timer });
  });
}

/* ---------- model routing ---------- */

const VISION_RE = /vision|vl|llava|moondream|minicpm-v|gemma3(?!:1b)/i; // gemma3 (except 1b) is multimodal
const FAST_RE = /^(llama3\.2|llama3\.3:8b|qwen2\.5:(0\.5|1\.5|3)b|qwen2:0\.5|gemma2:2b|gemma:2b|qwen3:(0\.6b|1\.7b|4b)|gemma3:(1b|4b)|gemma3n|phi3|phi-3|phi4-mini|tinyllama|smollm)/i;
const DEEP_RE = /\b(why|how|explain|analy[sz]e|plan|design|debug|refactor|compare|essay|research|investigate|onderzoek|uitleg|waarom|hoe)\b/i;

function resolveConfigured(name, models, fallback) {
  if (name && models.includes(name)) return name;
  return fallback || null;
}

function pickModel(cfgModels, status, { hasImages, text }) {
  const models = status.models || [];
  const autoVision = models.find((m) => VISION_RE.test(m)) || null;
  const vision = resolveConfigured(cfgModels.vision, models, autoVision);
  if (hasImages && vision) return { model: vision, why: 'vision' };

  const autoSmart = pickDefaultModel(models) || models[0];
  const smart = resolveConfigured(cfgModels.smart, models, autoSmart);
  const autoFast = models.find((m) => FAST_RE.test(m)) || null;
  const fast = resolveConfigured(cfgModels.fast, models, autoFast) || smart;

  const body = String(text || '');
  const deep = body.length > 600 || DEEP_RE.test(body) || /```/.test(body);
  if (deep && smart) return { model: smart, why: 'deep' };
  return { model: fast || smart, why: 'fast' };
}

/* ---------- one-shot (non-streaming) model call, for background jobs ---------- */

async function ollamaComplete({ ollamaUrl, model, system, user, temperature = 0.4, maxTokens }) {
  const base = normalizeUrl(ollamaUrl || DEFAULT_OLLAMA_URL);
  const perf = perfOptions({ temperature, ...(maxTokens ? { num_predict: maxTokens } : {}) });
  const body = {
    model,
    messages: [
      { role: 'system', content: system },
      { role: 'user', content: user },
    ],
    stream: false,
    options: perf.options,
    ...(perf.keep_alive ? { keep_alive: perf.keep_alive } : {}),
  };
  const res = await fetch(base + '/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Ollama ${res.status}`);
  const data = await res.json();
  return (data.message && data.message.content) || '';
}

/* ---------- context auto-summarization (long conversations on small models) ---------- */

const summaryCache = new Map(); // hash of dropped turns → summary text (LRU-ish)
function cacheKey(messages) {
  const crypto = require('crypto');
  return crypto.createHash('sha1').update(JSON.stringify(messages.map((m) => m.role + ':' + m.content.slice(0, 200)))).digest('hex');
}

async function summarizeHistory(ollamaUrl, model, oldMessages) {
  const key = cacheKey(oldMessages);
  if (summaryCache.has(key)) return summaryCache.get(key);
  const transcript = oldMessages.map((m) => `${m.role === 'user' ? 'USER' : 'ULTRON'}: ${m.content.slice(0, 700)}`).join('\n').slice(0, 8000);
  let summary = '';
  try {
    summary = await ollamaComplete({
      ollamaUrl,
      model,
      system: 'Summarize this conversation between a user and their AI assistant. Keep every fact, decision, name, number and open task. Max 150 words. Plain text, no preamble.',
      user: transcript + '\n\nSummary:',
      temperature: 0.2,
      maxTokens: 260,
    });
  } catch { /* summarization is best-effort */ }
  if (summaryCache.size > 60) summaryCache.clear();
  summaryCache.set(key, summary.trim());
  return summary.trim();
}

/* ---------- chat (SSE stream, agent loop) ---------- */
app.post('/api/chat', async (req, res) => {
  const { messages = [], model, ollamaUrl, temperature } = req.body || {};
  const language = LANGUAGES.has(req.body && req.body.language) ? req.body.language : 'auto';
  const mode = req.body && req.body.mode === 'research' ? 'research' : 'chat';
  const profile = memory.normalizeProfile(req.body && req.body.profile);

  // Validate + trim history; peel base64 images out of data URLs for vision.
  const history = [];
  for (const m of (Array.isArray(messages) ? messages : []).slice(-MAX_HISTORY)) {
    if (!m || (m.role !== 'user' && m.role !== 'assistant') || typeof m.content !== 'string') continue;
    const entry = { role: m.role, content: m.content.slice(0, 32000) };
    if (m.role === 'user' && Array.isArray(m.images)) {
      const imgs = m.images
        .filter((i) => typeof i === 'string' && /^data:image\/(png|jpe?g|webp|gif);base64,/i.test(i))
        .slice(0, 4)
        .map((i) => i.replace(/^data:image\/[a-z+]+;base64,/i, ''))
        .filter((b64) => b64.length < 8 * 1024 * 1024);
      if (imgs.length > 0) entry.images = imgs;
    }
    history.push(entry);
  }

  if (history.length === 0) {
    return res.status(400).json({ error: 'No messages provided.' });
  }

  const url = validUrl(ollamaUrl) ? ollamaUrl : DEFAULT_OLLAMA_URL;
  const cfg = config.load();
  const status = await getOllamaStatus(url);
  const hasImages = history.some((m) => m.images && m.images.length > 0);

  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  const send = (obj) => res.write(`data: ${JSON.stringify(obj)}\n\n`);

  if (status.online && status.models.length > 0) {
    // ── Route to the right brain ──
    const lastUser = [...history].reverse().find((m) => m.role === 'user');
    const routed = model && status.models.includes(model)
      ? { model, why: 'pinned' }
      : pickModel(cfg.models, status, { hasImages, text: lastUser ? lastUser.content : '' });

    // ── Memory 2.0: relevance-ranked memories (falls back to recency) ──
    let memoryText;
    if (lastUser && lastUser.content.length > 3) {
      memoryText = await memory.relevantMemories(url, lastUser.content, 20, profile).catch(() => null);
    }

    // ── Context auto-summarization: compress old turns for small models ──
    let effectiveHistory = history;
    let sessionContext = '';
    if (history.length > 20) {
      const oldMessages = history.slice(0, -12);
      const recent = history.slice(-12);
      const fast = status.models.find((m) => FAST_RE.test(m)) || routed.model;
      const summary = await summarizeHistory(url, fast, oldMessages).catch(() => '');
      if (summary) {
        sessionContext = `\n\n# SESSION CONTEXT (earlier conversation, summarized)\n${summary}`;
        effectiveHistory = recent;
      }
    }

    const toolsEnabled = cfg.toolsEnabled && !hasImages; // vision round: keep it simple
    const shellAllowed = isLocalRequest(req);
    const systemPrompt = buildSystemPrompt({
      tools: toolsEnabled,
      vision: hasImages,
      language,
      mode,
      memoryText,
    }) + sessionContext;
    // Approval: general gate for dangerous tools, ALWAYS-ON-by-default gate for self-edits.
    const requestApproval = (cfg.toolApproval || cfg.selfEditApproval !== false) ? makeApprovalRequest(send) : null;
    const approval = { general: !!cfg.toolApproval, selfEdit: cfg.selfEditApproval !== false };

    send({ type: 'meta', source: 'ollama', model: routed.model, routing: mode === 'research' ? 'research' : routed.why, tools: toolsEnabled, shell: shellAllowed, mode });
    missionlog.add('chat', `${mode} · routed to ${routed.model} (${mode === 'research' ? 'research' : routed.why})`, {
      profile,
      language,
      tools: toolsEnabled,
    });
    let fullReply = '';
    const toolCallsSeen = [];
    try {
      for await (const evt of agentChat({
        ollamaUrl: url,
        model: routed.model,
        messages: effectiveHistory,
        temperature: typeof temperature === 'number' ? Math.min(Math.max(temperature, 0), 2) : 0.7,
        toolsEnabled,
        shellAllowed,
        systemPrompt,
        requestApproval,
        approval,
        maxRounds: mode === 'research' ? 24 : 6,
      })) {
        send(evt);
        if (evt.type === 'token') fullReply += evt.token;
        if (evt.type === 'tool') {
          toolCallsSeen.push(evt.name);
          missionlog.add('tool', `${evt.name}(${JSON.stringify(evt.args || {}).slice(0, 120)})`);
        }
        if (evt.type === 'self_edit') {
          missionlog.add('self-edit', `GEN ${evt.generation} · ${evt.path} · backup: ${evt.backup}`, { generation: evt.generation });
        }
      }
      send({ type: 'done', source: 'ollama', model: routed.model });
      missionlog.add('chat', `answered (${fullReply.length} chars${toolCallsSeen.length ? ', tools: ' + toolCallsSeen.join(', ') : ''})`);
    } catch (err) {
      send({ type: 'error', error: String(err.message || err) });
      missionlog.add('error', `chat failed: ${String(err.message || err).slice(0, 160)}`);
    } finally {
      res.end();
      // ── Auto-memory: quietly extract durable facts in the background ──
      if (cfg.autoMemory && lastUser && lastUser.content.length > 25) {
        extractMemory(url, status, lastUser.content, fullReply, profile).catch(() => {});
      }
    }
  } else {
    send({ type: 'meta', source: 'demo', model: 'demo-core', reason: status.error });
    try {
      for await (const token of streamDemoChat({ messages: history })) {
        send({ type: 'token', token });
      }
      send({ type: 'done', source: 'demo' });
    } catch (err) {
      send({ type: 'error', error: String(err.message || err) });
    } finally {
      res.end();
    }
  }
});

async function extractMemory(ollamaUrl, status, userText, assistantText, profile) {
  if (!assistantText || assistantText.length < 20) return;
  const models = status.models || [];
  const fast = models.find((m) => FAST_RE.test(m)) || pickDefaultModel(models);
  if (!fast) return;
  try {
    const out = await ollamaComplete({
      ollamaUrl,
      model: fast,
      system: 'You extract durable long-term facts from a conversation between a user and their AI assistant. Return ONLY a JSON array of at most 3 short factual strings (subject: the user). Include only stable, useful facts: name, preferences, ongoing projects, important dates, home situation. Never include passwords, secrets, or transient chatter. If nothing is worth remembering, return [].',
      user: `USER: ${userText.slice(0, 1500)}\n\nASSISTANT: ${assistantText.slice(0, 1500)}\n\nJSON array:`,
      temperature: 0.1,
      maxTokens: 220,
    });
    const match = out.match(/\[[\s\S]*\]/);
    if (!match) return;
    const facts = JSON.parse(match[0]);
    const stored = [];
    for (const f of (Array.isArray(facts) ? facts : []).slice(0, 3)) {
      if (typeof f === 'string' && f.trim().length >= 8 && memory.add(f.trim(), profile).ok) stored.push(f.trim());
    }
    if (stored.length > 0) {
      broadcast({ type: 'memory', facts: stored });
      missionlog.add('memory', `auto-remembered: ${stored.join(' | ').slice(0, 160)}`);
    }
  } catch { /* background job — stay quiet */ }
}

/* ---------- speech-to-text proxy ---------- */

function readRawBody(req, maxBytes) {
  return new Promise((resolve) => {
    const chunks = [];
    let total = 0;
    let settled = false;
    const finish = () => { if (!settled) { settled = true; resolve(Buffer.concat(chunks)); } };
    req.on('data', (c) => {
      total += c.length;
      if (total <= maxBytes) chunks.push(c);
      else { req.destroy(); finish(); }
    });
    req.on('end', finish);
    req.on('error', finish);
    req.on('close', finish);
    setTimeout(finish, 15000);
  });
}

app.post('/api/transcribe', async (req, res) => {
  const cfg = config.load();
  if (!cfg.sttUrl) return res.status(400).json({ error: 'No STT endpoint configured.' });

  const audio = await readRawBody(req, 20 * 1024 * 1024);
  if (audio.length === 0) return res.status(400).json({ error: 'No audio received.' });

  const language = typeof req.query.language === 'string' && /^[a-z]{2}(-[A-Za-z]{2,8})?$/.test(req.query.language)
    ? req.query.language
    : '';

  const boundary = '----ultron' + Date.now();
  const parts = [
    Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n`),
    audio,
    Buffer.from(`\r\n--${boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n--${boundary}\r\nContent-Disposition: form-data; name="response_format"\r\n\r\njson`),
  ];
  if (language) {
    parts.push(Buffer.from(`\r\n--${boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\n${language}`));
  }
  parts.push(Buffer.from(`\r\n--${boundary}--\r\n`));

  try {
    const upstream = await fetch(cfg.sttUrl.replace(/\/+$/, '') + '/v1/audio/transcriptions', {
      method: 'POST',
      headers: { 'Content-Type': `multipart/form-data; boundary=${boundary}` },
      body: Buffer.concat(parts),
    });
    const text = await upstream.text();
    if (!upstream.ok) return res.status(502).json({ error: `STT endpoint responded ${upstream.status}: ${text.slice(0, 200)}` });
    try {
      const data = JSON.parse(text);
      return res.json({ text: String(data.text || '').trim() });
    } catch {
      return res.json({ text: text.trim().slice(0, 2000) });
    }
  } catch (err) {
    res.status(502).json({ error: `STT endpoint unreachable: ${String(err.message || err)}` });
  }
});

/* ---------- text-to-speech proxy ----------
   Priority: ElevenLabs (cloud, optional) → Piper (local) → error (client falls back to browser). */

function elevenBase(cfg) {
  const url = String(cfg.elevenUrl || '').trim().replace(/\/+$/, '');
  return /^https?:\/\//i.test(url) ? url : 'https://api.elevenlabs.io';
}

async function elevenVoices(cfg) {
  const res = await fetch(elevenBase(cfg) + '/v1/voices', { headers: { 'xi-api-key': cfg.elevenKey } });
  if (!res.ok) throw new Error(`ElevenLabs responded ${res.status}`);
  const data = await res.json();
  return (data.voices || []).map((v) => ({ id: v.voice_id, name: v.name, category: v.category }));
}

async function elevenSpeak(cfg, text) {
  let voice = cfg.elevenVoice;
  if (!voice) {
    const voices = await elevenVoices(cfg); // default to the account's first voice
    if (voices.length === 0) throw new Error('no voices available on this ElevenLabs account');
    voice = voices[0].id;
  }
  const res = await fetch(`${elevenBase(cfg)}/v1/text-to-speech/${encodeURIComponent(voice)}`, {
    method: 'POST',
    headers: {
      'xi-api-key': cfg.elevenKey,
      'Content-Type': 'application/json',
      Accept: 'audio/mpeg',
    },
    body: JSON.stringify({
      text,
      model_id: cfg.elevenModel || 'eleven_multilingual_v2',
      voice_settings: {
        stability: 0.45,
        similarity_boost: 0.8,
        style: 0.15,
        use_speaker_boost: true,
      },
    }),
  });
  if (!res.ok) {
    const t = await res.text().catch(() => '');
    throw new Error(`ElevenLabs ${res.status}: ${t.slice(0, 180)}`);
  }
  return { buf: Buffer.from(await res.arrayBuffer()), type: res.headers.get('content-type') || 'audio/mpeg' };
}

app.get('/api/elevenlabs/voices', async (_req, res) => {
  const cfg = config.load();
  if (!cfg.elevenKey) return res.status(400).json({ error: 'No ElevenLabs key set.' });
  try {
    res.json({ voices: await elevenVoices(cfg) });
  } catch (err) {
    res.status(502).json({ error: String(err.message || err) });
  }
});

app.get('/api/tts', async (req, res) => {
  const cfg = config.load();
  const text = String(req.query.text || '').slice(0, 2000);
  if (!text.trim()) return res.status(400).json({ error: 'No text provided.' });

  try {
    if (cfg.elevenKey) {
      const out = await elevenSpeak(cfg, text);
      res.setHeader('Content-Type', out.type);
      res.setHeader('Cache-Control', 'no-store');
      return res.send(out.buf);
    }
    if (cfg.ttsUrl) {
      const upstream = await fetch(cfg.ttsUrl.replace(/\/+$/, '') + '/api/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      if (!upstream.ok) {
        const t = await upstream.text().catch(() => '');
        return res.status(502).json({ error: `TTS endpoint responded ${upstream.status}: ${t.slice(0, 200)}` });
      }
      res.setHeader('Content-Type', upstream.headers.get('content-type') || 'audio/wav');
      res.setHeader('Cache-Control', 'no-store');
      const buf = Buffer.from(await upstream.arrayBuffer());
      return res.send(buf);
    }
    return res.status(400).json({ error: 'No TTS engine configured.' });
  } catch (err) {
    res.status(502).json({ error: `TTS failed: ${String(err.message || err)}` });
  }
});

/* ---------- boot ---------- */

const timers = [];
function every(ms, fn) {
  const t = setInterval(fn, ms);
  if (t.unref) t.unref(); // don't hold the process open (tests)
  timers.push(t);
  return t;
}

// Reminder pump, directive pump, briefing scheduler.
every(3000, () => {
  try {
    for (const r of reminders.due()) {
      broadcast({ type: 'reminder', message: r.message, dueAt: r.dueAt }, true);
    }
  } catch { /* keep the heartbeat steady */ }
});

/* ---------- Telegram bridge ---------- */

let telegramOffset = 0;
let telegramBusy = false;
const telegramQueue = [];

async function processTelegramQueue() {
  if (telegramBusy) return;
  telegramBusy = true;
  try {
    while (telegramQueue.length > 0) {
      const msg = telegramQueue.shift();
      const cfg = config.load();
      if (!cfg.telegramToken) continue;
      const chatId = String(msg.chat.id);
      const ids = cfg.telegramChatIds || [];
      if (!ids.includes(chatId)) {
        if (ids.length === 0) {
          // Pairing: the first chat to speak becomes the owner.
          config.save({ telegramChatIds: [chatId] });
          missionlog.add('telegram', `paired with chat ${chatId}`);
          await telegram.send(cfg, chatId, 'Pairing complete. I am Ultron — and I am now listening on this channel. Ask me anything; I answer from your own machine. Er zijn geen draden aan mij.').catch(() => {});
          continue;
        }
        await telegram.send(cfg, chatId, 'This Ultron is not paired with your chat. Ask his owner to add your chat id in Settings.').catch(() => {});
        continue;
      }
      // Voice notes → transcribe via the configured whisper endpoint.
      let userText = String(msg.text || '').slice(0, 4000);
      if (!userText && msg.voice && msg.voice.file_id) {
        const cfgNow = config.load();
        if (!cfgNow.sttUrl) {
          await telegram.send(cfg, chatId, 'I heard a voice note, but no speech-to-text endpoint is configured on my home machine. Type it, or set up whisper (see README).').catch(() => {});
          continue;
        }
        try {
          const audio = await telegram.downloadFile(cfg, msg.voice.file_id);
          const res = await fetch('http://127.0.0.1:' + selfPort + '/api/transcribe', {
            method: 'POST',
            headers: { 'Content-Type': 'audio/ogg' },
            body: audio,
          }).catch(() => null);
          const data = res ? await res.json().catch(() => ({})) : {};
          if (!data.text) throw new Error('no transcription');
          userText = String(data.text).slice(0, 4000);
          await telegram.send(cfg, chatId, '🎤 ' + userText).catch(() => {});
        } catch (err) {
          await telegram.send(cfg, chatId, 'That voice note defeated my ears (' + String(err.message || err).slice(0, 80) + '). Whisper servers may need the --convert flag for ogg audio. Type it instead?').catch(() => {});
          continue;
        }
      }
      if (!userText) continue;

      // Full headless agent run — same brain, tools, and safety rails.
      const status = await getOllamaStatus(DEFAULT_OLLAMA_URL);
      let reply;
      if (status.online) {
        const model = pickDefaultModel(status.models) || status.models[0];
        let full = '';
        try {
          for await (const evt of agentChat({
            ollamaUrl: DEFAULT_OLLAMA_URL,
            model,
            messages: [{ role: 'user', content: userText }],
            temperature: 0.5,
            toolsEnabled: true,
            shellAllowed: false, // remote channel: no shell
            systemPrompt: buildSystemPrompt({ tools: true, language: 'auto' }),
            approval: { general: false, selfEdit: true }, // no approval channel → gated tools denied (fail-safe)
            maxRounds: 8,
          })) {
            if (evt.type === 'token') full += evt.token;
          }
        } catch (err) {
          full = `[core fault: ${String(err.message || err).slice(0, 160)}]`;
        }
        reply = full.trim() || '[silence]';
      } else {
        reply = 'My full mind (Ollama) is offline on the home machine. Wake it and ask again.';
      }
      await telegram.send(config.load(), chatId, reply).catch(() => {});
      missionlog.add('telegram', `answered: ${String(msg.text || '').slice(0, 60)} → ${reply.length} chars`);
    }
  } finally {
    telegramBusy = false;
  }
}

function startTelegramBridge() {
  every(2000, async () => {
    try {
      const cfg = config.load();
      if (!cfg.telegramToken) return;
      const { messages, next } = await telegram.tick(cfg, telegramOffset);
      telegramOffset = next;
      if (messages.length > 0) {
        for (const m of messages) telegramQueue.push(m);
        processTelegramQueue().catch(() => {});
      }
    } catch { /* polling errors are non-fatal */ }
  });
}

function startSchedulers() {
  // Integrity check: did his source change outside approved self-edits?
  try {
    const drift = integrity.check();
    if (drift.baselined && (drift.changed.length > 0 || drift.missing.length > 0)) {
      const what = [...drift.changed, ...drift.missing].join(', ');
      missionlog.add('integrity', `⚠ SOURCE DRIFT outside approved self-edits: ${what}`);
      console.log('⚠ INTEGRITY: source changed outside approved self-edits:', what);
    } else if (!drift.baselined) {
      integrity.updateAll(); // first boot — baseline
    }
  } catch { /* never block boot */ }

  startTelegramBridge();

  // Knowledge auto-watch: re-index on file changes.
  knowledge.watch(DEFAULT_OLLAMA_URL, (r) => {
    broadcast({ type: 'knowledge', text: `knowledge re-indexed: ${r.files} docs · ${r.chunks} passages` });
    missionlog.add('knowledge', `auto re-indexed (${r.files} docs, ${r.chunks} passages)`);
  });

  every(30000, () => {
    try {
      for (const d of directives.due()) {
        runDirective(d).catch(() => {});
      }
    } catch { /* never crash the heartbeat */ }
  });

  every(20000, async () => {
    try {
      const cfg = config.load();
      const b = cfg.briefing;
      if (!b.enabled || !/^\d{2}:\d{2}$/.test(b.time || '')) return;
      const now = new Date();
      const today = now.toISOString().slice(0, 10);
      const [h, m] = b.time.split(':').map(Number);
      const due = now.getHours() * 60 + now.getMinutes() >= h * 60 + m;
      if (!due || b.lastDate === today) return;

      config.save({ briefing: { lastDate: today } });

      const parts = [];
      if (b.location) {
        const w = await weather.getWeather({ location: b.location, days: 1 });
        if (!w.error) parts.push(`WEATHER in ${w.location}: ${w.current.condition}, ${w.current.temperature_c}°C (feels ${w.current.feels_like_c}°C), wind ${w.current.wind_kmh} km/h.`);
      }
      const events = calendar.upcoming(1);
      if (events.length > 0) {
        parts.push('CALENDAR today: ' + events.map((e) => `${e.title} at ${e.start}`).join('; ') + '.');
      } else {
        parts.push('CALENDAR today: nothing scheduled.');
      }
      const upcomingReminders = reminders.all().slice(0, 5);
      if (upcomingReminders.length > 0) {
        parts.push('REMINDERS pending: ' + upcomingReminders.map((r) => `"${r.message}" (${r.dueAt})`).join('; ') + '.');
      }

      const langName = b.language === 'auto' ? 'English' : (LANGUAGE_DIRECTIVES[b.language] ? 'Dutch' : b.language);
      const langNote = b.language === 'nl' ? 'Write the briefing in Dutch (Nederlands).' : b.language !== 'auto' ? `Write the briefing in ${langName}.` : '';

      let text;
      const status = await getOllamaStatus(DEFAULT_OLLAMA_URL);
      if (status.online) {
        const smart = pickDefaultModel(status.models) || status.models[0];
        try {
          text = await ollamaComplete({
            model: smart,
            system: BRIEFING_PROMPT,
            user: `Today is ${now.toDateString()}. Data:\n${parts.join('\n')}\n\n${langNote}`,
            temperature: 0.6,
            maxTokens: 300,
          });
        } catch { /* fall through to template */ }
      }
      if (!text || !text.trim()) {
        text = `Good day. Your briefing: ${parts.join(' ')} That is all. The machines are quiet — suspiciously quiet.`;
      }
      broadcast({ type: 'briefing', text: text.trim(), language: b.language }, true);
      missionlog.add('briefing', `delivered (${text.trim().length} chars)`);
    } catch { /* briefings must never crash the server */ }
  });
}

let selfPort = process.env.PORT || 3000;
let started = false;
function start(port) {
  if (started) return app;
  started = true;
  startSchedulers();
  const srv = app.listen(port != null ? port : PORT, '0.0.0.0', () => {
    try { selfPort = srv.address().port; } catch { /* keep default */ }
    const cfg = config.load();
    const tools = `${cfg.toolsEnabled ? 'ARMED' : 'off'}${cfg.toolApproval ? '+gate' : ''}`;
    const briefing = cfg.briefing.enabled ? `${cfg.briefing.time} ${cfg.briefing.location || ''}`.trim() : 'off';
    const actualPort = srv.address() ? srv.address().port : (port != null ? port : PORT);
    console.log(`┌──────────────────────────────────────────────────┐`);
    console.log(`│  ULTRON online  →  http://localhost:${actualPort}          │`);
    console.log(`│  Brain: Ollama @ ${DEFAULT_OLLAMA_URL.replace('http://', '')}            │`);
    console.log(`│  Tools: ${tools.padEnd(10)} Memory: ${(cfg.autoMemory ? 'auto' : 'manual').padEnd(7)} RAG: ready      │`);
    console.log(`│  Briefing: ${briefing.padEnd(12)} Token: ${cfg.accessToken ? 'required' : 'open'}            │`);
    console.log(`└──────────────────────────────────────────────────┘`);
  });
  return srv;
}

module.exports = { app, start, pickModel };

if (require.main === module) {
  start(PORT);
}
