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
const path = require('path');

const { buildSystemPrompt, BRIEFING_PROMPT, DIRECTIVE_PROMPT, LANGUAGE_DIRECTIVES } = require('./lib/persona');
const { getOllamaStatus, validUrl, DEFAULT_OLLAMA_URL, normalizeUrl, pickDefaultModel } = require('./lib/ollama');
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

/* ---------- access token (optional LAN security) ---------- */

app.use('/api', (req, res, next) => {
  if (req.path === '/health' || req.path === '/auth') return next();
  const token = config.load().accessToken;
  if (!token) return next();
  const provided = req.get('x-ultron-token') || String(req.query.token || '');
  if (provided === token) return next();
  return res.status(401).json({ error: 'token required' });
});

app.get('/api/health', (_req, res) => res.json({ ok: true, name: 'ultron' }));
app.get('/api/auth', (_req, res) => res.json({ required: !!config.load().accessToken }));

/* ---------- config ---------- */

/** Never echo the ElevenLabs key back to the browser. */
function maskConfig(cfg) {
  return { ...cfg, elevenKey: '', elevenKeySet: !!cfg.elevenKey };
}

app.get('/api/config', (_req, res) => res.json(maskConfig(config.load())));

app.put('/api/config', (req, res) => {
  const body = { ...(req.body || {}) };
  // Empty key input means "leave as is"; explicit clear means remove it.
  if (body.elevenKeyClear) body.elevenKey = '';
  else if (typeof body.elevenKey === 'string' && body.elevenKey.trim() === '') delete body.elevenKey;
  delete body.elevenKeyClear;
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
app.get('/api/memory', (_req, res) => res.json({ memories: memory.all() }));

app.post('/api/memory', (req, res) => {
  res.json(memory.add((req.body || {}).fact));
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
  // Web Push reaches the installed PWA (phone) when no tab is connected.
  if (alsoPush && eventClients.size === 0) {
    const title = obj.type === 'reminder' ? 'Ultron — reminder'
      : obj.type === 'briefing' ? 'Ultron — daily briefing'
      : obj.type === 'directive' ? 'Ultron — standing order'
      : 'Ultron';
    const body = obj.type === 'directive' ? `${obj.instruction}: ${String(obj.text || '').slice(0, 160)}`
      : String(obj.message || obj.text || '').slice(0, 200);
    push.send(title, body).catch(() => {});
  }
}

setInterval(() => {
  try {
    for (const r of reminders.due()) {
      broadcast({ type: 'reminder', message: r.message, dueAt: r.dueAt }, true);
    }
  } catch { /* keep the heartbeat steady */ }
}, 3000);

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
  } finally {
    directiveBusy = false;
  }
}

// Directive pump: check every 30 seconds.
setInterval(() => {
  try {
    for (const d of directives.due()) {
      runDirective(d).catch(() => {});
    }
  } catch { /* never crash the heartbeat */ }
}, 30000);

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

const VISION_RE = /vision|vl|llava|moondream|minicpm-v/i;
const FAST_RE = /^(llama3\.2|qwen2\.5:(0\.5|1\.5|3)b|qwen2:0\.5|gemma2:2b|gemma:2b|phi3|phi-3|tinyllama|smollm)/i;
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
  const body = {
    model,
    messages: [
      { role: 'system', content: system },
      { role: 'user', content: user },
    ],
    stream: false,
    options: { temperature, ...(maxTokens ? { num_predict: maxTokens } : {}) },
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
      memoryText = await memory.relevantMemories(url, lastUser.content, 20).catch(() => null);
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
    const requestApproval = cfg.toolApproval ? makeApprovalRequest(send) : null;

    send({ type: 'meta', source: 'ollama', model: routed.model, routing: mode === 'research' ? 'research' : routed.why, tools: toolsEnabled, shell: shellAllowed, mode });
    let fullReply = '';
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
        maxRounds: mode === 'research' ? 24 : 6,
      })) {
        send(evt);
        if (evt.type === 'token') fullReply += evt.token;
      }
      send({ type: 'done', source: 'ollama', model: routed.model });
    } catch (err) {
      send({ type: 'error', error: String(err.message || err) });
    } finally {
      res.end();
      // ── Auto-memory: quietly extract durable facts in the background ──
      if (cfg.autoMemory && lastUser && lastUser.content.length > 25) {
        extractMemory(url, status, lastUser.content, fullReply).catch(() => {});
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

async function extractMemory(ollamaUrl, status, userText, assistantText) {
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
      if (typeof f === 'string' && f.trim().length >= 8 && memory.add(f.trim()).ok) stored.push(f.trim());
    }
    if (stored.length > 0) broadcast({ type: 'memory', facts: stored });
  } catch { /* background job — stay quiet */ }
}

/* ---------- proactive daily briefing ---------- */

setInterval(async () => {
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

    // Gather raw data.
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
  } catch { /* briefings must never crash the server */ }
}, 20000);

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

app.listen(PORT, '0.0.0.0', () => {
  const cfg = config.load();
  const tools = `${cfg.toolsEnabled ? 'ARMED' : 'off'}${cfg.toolApproval ? '+gate' : ''}`;
  const briefing = cfg.briefing.enabled ? `${cfg.briefing.time} ${cfg.briefing.location || ''}`.trim() : 'off';
  console.log(`┌──────────────────────────────────────────────────┐`);
  console.log(`│  ULTRON online  →  http://localhost:${PORT}          │`);
  console.log(`│  Brain: Ollama @ ${DEFAULT_OLLAMA_URL.replace('http://', '')}            │`);
  console.log(`│  Tools: ${tools.padEnd(10)} Memory: ${(cfg.autoMemory ? 'auto' : 'manual').padEnd(7)} RAG: ready      │`);
  console.log(`│  Briefing: ${briefing.padEnd(12)} Token: ${cfg.accessToken ? 'required' : 'open'}            │`);
  console.log(`└──────────────────────────────────────────────────┘`);
});
