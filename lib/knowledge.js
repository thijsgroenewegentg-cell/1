/**
 * KNOWLEDGE — Ultron's personal library (RAG, fully local).
 * Drop documents in data/knowledge/docs/ (txt, md, csv, json, code…),
 * scan them in Settings, and he can answer from YOUR knowledge via
 * embeddings served by Ollama (nomic-embed-text).
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { normalizeUrl } = require('./ollama');

const DATA_DIR = process.env.ULTRON_DATA || path.join(__dirname, '..', 'data');
const KNOW_DIR = path.join(DATA_DIR, 'knowledge');
const DOCS_DIR = path.join(KNOW_DIR, 'docs');
const INDEX_FILE = path.join(KNOW_DIR, 'index.json');
const EMBED_MODELS = ['nomic-embed-text', 'mxbai-embed-large', 'snowflake-arctic-embed'];
const CHUNK_SIZE = 900;
const CHUNK_OVERLAP = 150;
const MAX_FILE_BYTES = 2 * 1024 * 1024;
const TEXT_EXT = new Set(['.txt', '.md', '.markdown', '.csv', '.tsv', '.json', '.log', '.yml', '.yaml', '.js', '.ts', '.py', '.html', '.css', '.xml', '.sh', '.java', '.c', '.cpp', '.go', '.rs', '.php', '.sql', '.pdf']);

/** Extract text from a file — PDFs via pdf-parse (if installed), others raw. */
function extractText(fullPath) {
  const ext = path.extname(fullPath).toLowerCase();
  if (ext === '.pdf') {
    let pdfParse;
    try {
      pdfParse = require('pdf-parse');
    } catch {
      throw new Error('PDF support needs `npm install pdf-parse`');
    }
    const buf = fs.readFileSync(fullPath);
    return pdfParse(buf).then((data) => String(data.text || ''));
  }
  return Promise.resolve(fs.readFileSync(fullPath, 'utf8'));
}

let index = null; // [{id, path, text, emb: base64 Float32}]

function loadIndex() {
  if (index) return index;
  try {
    index = JSON.parse(fs.readFileSync(INDEX_FILE, 'utf8'));
    if (!Array.isArray(index)) index = [];
  } catch {
    index = [];
  }
  return index;
}

function saveIndex() {
  fs.mkdirSync(KNOW_DIR, { recursive: true });
  fs.writeFileSync(INDEX_FILE, JSON.stringify(index));
}

async function detectEmbedModel(ollamaUrl) {
  const base = normalizeUrl(ollamaUrl);
  try {
    const res = await fetch(base + '/api/tags');
    if (!res.ok) return null;
    const data = await res.json();
    const names = (data.models || []).map((m) => m.name);
    for (const m of EMBED_MODELS) {
      const hit = names.find((n) => n.startsWith(m));
      if (hit) return hit;
    }
    return null;
  } catch {
    return null;
  }
}

async function embed(ollamaUrl, model, text) {
  const base = normalizeUrl(ollamaUrl);
  const res = await fetch(base + '/api/embeddings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, prompt: text.slice(0, 4000) }),
  });
  if (!res.ok) throw new Error(`embedding failed (${res.status})`);
  const data = await res.json();
  if (!Array.isArray(data.embedding) || data.embedding.length === 0) throw new Error('empty embedding');
  return data.embedding;
}

function chunkText(text) {
  const chunks = [];
  let start = 0;
  while (start < text.length) {
    let end = Math.min(start + CHUNK_SIZE, text.length);
    if (end < text.length) {
      const cut = text.lastIndexOf('\n', end);
      if (cut > start + CHUNK_SIZE * 0.5) end = cut;
    }
    chunks.push(text.slice(start, end).trim());
    start = end - CHUNK_OVERLAP;
    if (start < 0) start = 0;
    if (end >= text.length) break;
  }
  return chunks.filter((c) => c.length > 20);
}

function walkDocs() {
  fs.mkdirSync(DOCS_DIR, { recursive: true });
  const files = [];
  const walk = (dir, prefix) => {
    let entries = [];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries.slice(0, 500)) {
      if (e.name.startsWith('.')) continue;
      const rel = prefix ? `${prefix}/${e.name}` : e.name;
      if (e.isDirectory()) walk(path.join(dir, e.name), rel);
      else if (TEXT_EXT.has(path.extname(e.name).toLowerCase())) files.push({ full: path.join(dir, e.name), rel });
    }
  };
  walk(DOCS_DIR, '');
  return files;
}

/** (Re)index every document. Incremental: unchanged files keep their embeddings. */
async function scan(ollamaUrl) {
  const model = await detectEmbedModel(ollamaUrl);
  if (!model) {
    return { ok: false, error: `no embedding model found — run \`ollama pull ${EMBED_MODELS[0]}\` and try again` };
  }
  const files = walkDocs();
  const previous = loadIndex();
  // Group existing chunks by file for reuse.
  const byFile = new Map();
  for (const e of previous) {
    if (!byFile.has(e.path)) byFile.set(e.path, []);
    byFile.get(e.path).push(e);
  }

  const entries = [];
  let id = 0;
  let reused = 0;
  let reembedded = 0;
  for (const f of files) {
    let stat;
    try { stat = fs.statSync(f.full); } catch { continue; }
    if (stat.size > MAX_FILE_BYTES) continue;

    // Incremental: same size + mtime → keep existing chunks.
    const old = byFile.get(f.rel);
    if (old && old.length > 0 && old[0].size === stat.size && old[0].mtime === stat.mtimeMs) {
      for (const e of old) entries.push({ ...e, id: id++ });
      reused++;
      continue;
    }

    let text;
    try {
      text = await extractText(f.full);
    } catch (err) {
      entries.push({ id: id++, path: f.rel, text: `[indexing error: ${String(err.message || err).slice(0, 120)}]`, emb: Buffer.from(new Float32Array([1, 0]).buffer).toString('base64'), mtime: stat.mtimeMs, size: stat.size });
      continue;
    }
    for (const chunk of chunkText(text)) {
      const vector = await embed(ollamaUrl, model, chunk);
      entries.push({
        id: id++,
        path: f.rel,
        text: chunk.slice(0, 1200),
        emb: Buffer.from(new Float32Array(vector).buffer).toString('base64'),
        mtime: stat.mtimeMs,
        size: stat.size,
      });
    }
    reembedded++;
  }
  index = entries;
  saveIndex();
  return { ok: true, files: files.length, chunks: entries.length, reused, reembedded, model };
}

function toFloat(b64) {
  const buf = Buffer.from(b64, 'base64');
  return new Float32Array(buf.buffer, buf.byteOffset, buf.length / 4);
}

function cosine(a, b) {
  let dot = 0, na = 0, nb = 0;
  const len = Math.min(a.length, b.length);
  for (let i = 0; i < len; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  if (na === 0 || nb === 0) return 0;
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

/** Simple keyword overlap score (BM25-lite) for hybrid retrieval. */
function keywordScore(query, text) {
  const terms = String(query).toLowerCase().split(/[^a-z0-9à-ÿ]+/).filter((t) => t.length > 2);
  if (terms.length === 0) return 0;
  const lower = String(text).toLowerCase();
  let hits = 0;
  for (const t of terms) {
    let from = 0;
    let count = 0;
    while ((from = lower.indexOf(t, from)) !== -1 && count < 5) { count++; from += t.length; }
    hits += count > 0 ? 1 : 0;
  }
  return hits / terms.length;
}

/** Hybrid semantic + keyword search over the library. */
async function search(ollamaUrl, query, k = 5) {
  const entries = loadIndex();
  if (entries.length === 0) {
    return { error: 'knowledge base is empty — drop documents in data/knowledge/docs and scan them in SETTINGS' };
  }
  const model = await detectEmbedModel(ollamaUrl);
  let qvec = null;
  if (model) {
    try { qvec = new Float32Array(await embed(ollamaUrl, model, query)); } catch { qvec = null; }
  }
  const scored = entries
    .map((e) => {
      const semantic = qvec ? cosine(qvec, toFloat(e.emb)) : 0;
      const lexical = keywordScore(query, e.text);
      return { path: e.path, text: e.text, score: qvec ? 0.55 * semantic + 0.45 * lexical : lexical };
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, k);
  return { results: scored.map((s) => ({ source: s.path, relevance: Number(s.score.toFixed(3)), excerpt: s.text.slice(0, 700) })) };
}

function stats() {
  const entries = loadIndex();
  const paths = new Set(entries.map((e) => e.path));
  return { chunks: entries.length, documents: paths.size };
}

function clear() {
  index = [];
  try { fs.unlinkSync(INDEX_FILE); } catch { /* noop */ }
  return { ok: true };
}

module.exports = { scan, search, stats, clear, watch, DOCS_DIR, EMBED_MODELS };

/** Watch the docs folder and re-index on change (debounced). */
function watch(ollamaUrl, onChange) {
  try {
    fs.mkdirSync(DOCS_DIR, { recursive: true });
    let timer = null;
    const w = fs.watch(DOCS_DIR, { recursive: true }, () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        try {
          const r = await scan(ollamaUrl);
          if (r && r.ok && onChange) onChange(r);
        } catch { /* stay quiet */ }
      }, 2500);
    });
    if (w.unref) w.unref();
    return w;
  } catch {
    return null;
  }
}
