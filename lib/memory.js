/**
 * DURABLE MEMORY — facts Ultron keeps about you, across sessions.
 * Stored in data/memory.json. Injected into every system prompt.
 */
'use strict';

const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, '..', 'data');
const MEMORY_FILE = path.join(DATA_DIR, 'memory.json');
const MAX_MEMORIES = 200;

let memories = null; // [{fact, at}]

function load() {
  if (memories) return memories;
  try {
    memories = JSON.parse(fs.readFileSync(MEMORY_FILE, 'utf8'));
    if (!Array.isArray(memories)) memories = [];
  } catch {
    memories = [];
  }
  return memories;
}

function save() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(MEMORY_FILE, JSON.stringify(memories, null, 2));
}

function all() {
  return load().map((m, i) => ({ idx: i, fact: m.fact, at: m.at }));
}

function add(fact) {
  const clean = String(fact || '').trim().slice(0, 500);
  if (!clean) return { ok: false, error: 'empty fact' };
  const list = load();
  if (list.some((m) => m.fact.toLowerCase() === clean.toLowerCase())) {
    return { ok: true, note: 'already known', count: list.length };
  }
  if (list.length >= MAX_MEMORIES) list.shift();
  list.push({ fact: clean, at: new Date().toISOString() });
  save();
  return { ok: true, count: list.length };
}

function removeContaining(substring) {
  const list = load();
  const needle = String(substring || '').trim().toLowerCase();
  if (!needle) return { ok: false, error: 'empty search term' };
  const kept = list.filter((m) => !m.fact.toLowerCase().includes(needle));
  const removed = list.length - kept.length;
  memories = kept;
  save();
  return { ok: true, removed, count: kept.length };
}

function clear() {
  memories = [];
  save();
  return { ok: true };
}

/** Render memories as a prompt section. */
function promptSection(selected) {
  const list = Array.isArray(selected) ? selected : load();
  if (list.length === 0) return '';
  const lines = list.slice(-60).map((m) => `- ${typeof m === 'string' ? m : m.fact}`).join('\n');
  return `\n\n# DURABLE MEMORIES (persist across sessions)\nThese are things you've chosen to remember about this user. Use them naturally; never list them unprompted.\n${lines}`;
}

/* ---------- Memory 2.0: relevance retrieval via local embeddings ---------- */

const EMB_FILE = path.join(DATA_DIR, 'memory-embeddings.json'); // {factHash: base64 Float32}
let embCache = null;

function loadEmb() {
  if (embCache) return embCache;
  try { embCache = JSON.parse(fs.readFileSync(EMB_FILE, 'utf8')); } catch { embCache = {}; }
  return embCache;
}

function saveEmb() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  fs.writeFileSync(EMB_FILE, JSON.stringify(embCache));
}

const hash = (s) => require('crypto').createHash('sha1').update(String(s)).digest('hex').slice(0, 16);

async function embedText(ollamaUrl, model, text) {
  const res = await fetch(require('./ollama').normalizeUrl(ollamaUrl) + '/api/embeddings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, prompt: String(text).slice(0, 2000) }),
  });
  if (!res.ok) throw new Error(`embed ${res.status}`);
  const data = await res.json();
  if (!Array.isArray(data.embedding)) throw new Error('no embedding');
  return data.embedding;
}

const EMBED_MODELS = ['nomic-embed-text', 'mxbai-embed-large', 'snowflake-arctic-embed'];

async function detectEmbedModel(ollamaUrl) {
  try {
    const res = await fetch(require('./ollama').normalizeUrl(ollamaUrl) + '/api/tags');
    if (!res.ok) return null;
    const data = await res.json();
    const names = (data.models || []).map((m) => m.name);
    for (const m of EMBED_MODELS) {
      const hit = names.find((n) => n.startsWith(m));
      if (hit) return hit;
    }
    return null;
  } catch { return null; }
}

/**
 * Return the most relevant memories for a query (embedding cosine similarity),
 * falling back to the most recent ones when embeddings aren't available.
 * @returns {Promise<string[]>} selected facts
 */
async function relevantMemories(ollamaUrl, queryText, k = 20) {
  const list = load();
  if (list.length === 0) return [];
  if (list.length <= k) return list.map((m) => m.fact);

  const model = await detectEmbedModel(ollamaUrl).catch(() => null);
  if (!model) return list.slice(-k).map((m) => m.fact); // recency fallback

  try {
    const cache = loadEmb();
    // Embed any memories that changed or were never embedded.
    const vectors = [];
    for (const m of list) {
      const h = hash(m.fact);
      if (cache[h]) {
        const buf = Buffer.from(cache[h], 'base64');
        vectors.push({ fact: m.fact, vec: new Float32Array(buf.buffer, buf.byteOffset, buf.length / 4) });
      } else {
        try {
          const v = await embedText(ollamaUrl, model, m.fact);
          cache[h] = Buffer.from(new Float32Array(v).buffer).toString('base64');
          vectors.push({ fact: m.fact, vec: new Float32Array(v) });
        } catch { /* skip this one */ }
      }
    }
    saveEmb();

    const q = new Float32Array(await embedText(ollamaUrl, model, queryText));
    const scored = vectors.map((v) => {
      let dot = 0, na = 0, nb = 0;
      const len = Math.min(q.length, v.vec.length);
      for (let i = 0; i < len; i++) {
        dot += q[i] * v.vec[i];
        na += q[i] * q[i];
        nb += v.vec[i] * v.vec[i];
      }
      return { fact: v.fact, score: na && nb ? dot / (Math.sqrt(na) * Math.sqrt(nb)) : 0 };
    });
    scored.sort((a, b) => b.score - a.score);
    // Blend: top-k relevant, always keep the 5 most recent.
    const top = scored.slice(0, k - 5).map((s) => s.fact);
    const recent = list.slice(-5).map((m) => m.fact);
    return [...new Set([...top, ...recent])];
  } catch {
    return list.slice(-k).map((m) => m.fact);
  }
}

module.exports = { all, add, removeContaining, clear, promptSection, relevantMemories };
