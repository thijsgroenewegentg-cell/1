/**
 * Ollama client — talks to a local (or remote) Ollama server.
 * Supports: model listing, streaming chat, tool calling, vision (images).
 * Docs: https://github.com/ollama/ollama/blob/main/docs/api.md
 */
'use strict';

const DEFAULT_OLLAMA_URL = process.env.OLLAMA_URL || 'http://localhost:11434';
// Modern tool/vision-capable models first — updated for the 2025/26 lineup.
const PREFERRED_MODELS = ['mistral-small3', 'mistral-small', 'qwen3', 'gemma3', 'llama3.1', 'llama3', 'qwen2.5', 'qwen', 'mistral', 'gemma2', 'gemma', 'phi3', 'deepseek-r1'];

/** Performance options from server config: context window + model keep-alive. */
function perfOptions(extra = {}) {
  let cfg = {};
  try { cfg = require('./config').load(); } catch { /* defaults */ }
  const options = { ...extra };
  if (cfg.contextLength > 0) options.num_ctx = cfg.contextLength;
  const keep_alive = cfg.keepAlive && cfg.keepAlive !== '0' ? cfg.keepAlive : undefined;
  return { options, keep_alive };
}

function normalizeUrl(raw) {
  let url = String(raw || '').trim();
  if (!/^https?:\/\//i.test(url)) url = 'http://' + url;
  url = url.replace(/\/+$/, '');
  return url;
}

function validUrl(raw) {
  try {
    const u = new URL(normalizeUrl(raw));
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

function pickDefaultModel(models) {
  for (const pref of PREFERRED_MODELS) {
    const hit = models.find((m) => m.toLowerCase().startsWith(pref));
    if (hit) return hit;
  }
  return models[0] || null;
}

/** Check whether Ollama is reachable; return {online, models, version, error}. */
async function getOllamaStatus(rawUrl) {
  const base = normalizeUrl(rawUrl || DEFAULT_OLLAMA_URL);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 2500);
  try {
    const [tagsRes, verRes] = await Promise.all([
      fetch(base + '/api/tags', { signal: controller.signal }),
      fetch(base + '/api/version', { signal: controller.signal }).catch(() => null),
    ]);
    if (!tagsRes.ok) return { online: false, models: [], error: `Ollama responded ${tagsRes.status}` };
    const data = await tagsRes.json();
    const models = (data.models || []).map((m) => m.name);
    let version = null;
    if (verRes && verRes.ok) {
      try { version = (await verRes.json()).version; } catch { /* ignore */ }
    }
    return { online: true, models, version, defaultModel: pickDefaultModel(models), baseUrl: base };
  } catch (err) {
    return { online: false, models: [], error: err.name === 'AbortError' ? 'timeout' : String(err.message || err) };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Merge tool-call chunks. Some Ollama versions split a call's arguments
 * across chunks with the same index — merge those; new indexes append.
 */
function mergeToolCalls(acc, incoming) {
  for (const tc of incoming || []) {
    const idx = typeof tc.index === 'number' ? tc.index : acc.length;
    const existing = acc[idx];
    if (existing && existing.function && tc.function && existing.function.name === tc.function.name) {
      existing.function.arguments = Object.assign(
        {},
        existing.function.arguments || {},
        tc.function.arguments || {}
      );
    } else {
      acc[idx] = tc;
    }
  }
  return acc.filter(Boolean);
}

/**
 * Stream a chat completion from Ollama.
 * Yields {type:'token', token} and, when the model wants tools,
 * a final {type:'tool_calls', calls:[{function:{name, arguments}}]}.
 *
 * @param {object} opts { ollamaUrl, model, messages, temperature, tools }
 *   messages may contain {role:'user', content, images:[base64...]} (vision)
 *   and {role:'tool', name, content} (tool results).
 */
const THINKING_MODEL_RE = /deepseek-r1|qwen3|thinking|reason|-rwq/i;

/** Split streamed content into visible text and <think> reasoning. */
function makeThinkSplitter() {
  const state = { inThink: false, buf: '' };
  function split(text) {
    let s = state.buf + text;
    state.buf = '';
    let out = '';
    let think = '';
    let i = 0;
    while (i < s.length) {
      if (!state.inThink) {
        const open = s.indexOf('<think>', i);
        if (open === -1) {
          const keep = Math.max(i, s.length - 7); // hold back a possible partial tag
          out += s.slice(i, keep);
          state.buf = s.slice(keep);
          break;
        }
        out += s.slice(i, open);
        i = open + 7;
        state.inThink = true;
      } else {
        const close = s.indexOf('</think>', i);
        if (close === -1) {
          const keep = Math.max(i, s.length - 8);
          think += s.slice(i, keep);
          state.buf = s.slice(keep);
          break;
        }
        think += s.slice(i, close);
        i = close + 8;
        state.inThink = false;
      }
    }
    return { out, think };
  }
  split.flush = () => {
    const rest = state.buf;
    state.buf = '';
    if (!rest) return { out: '', think: '' };
    return state.inThink ? { out: '', think: rest } : { out: rest, think: '' };
  };
  return split;
}

async function* streamOllamaChat({ ollamaUrl, model, messages, temperature = 0.7, tools }) {
  const base = normalizeUrl(ollamaUrl || DEFAULT_OLLAMA_URL);
  const perf = perfOptions({ temperature });
  const body = { model, messages, stream: true, options: perf.options, ...(perf.keep_alive ? { keep_alive: perf.keep_alive } : {}) };
  if (tools && tools.length > 0) body.tools = tools;
  if (THINKING_MODEL_RE.test(String(model))) body.think = true; // Ollama ≥0.9
  const splitThink = makeThinkSplitter();

  const res = await fetch(base + '/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Ollama error ${res.status}: ${text.slice(0, 300)}`);
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let toolCalls = [];

  for await (const chunk of res.body) {
    buffer += decoder.decode(chunk, { stream: true });
    let nl;
    while ((nl = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (!line) continue;
      let evt;
      try { evt = JSON.parse(line); } catch { continue; }
      if (evt.error) throw new Error(evt.error);
      const msg = evt.message || {};
      if (msg.tool_calls && msg.tool_calls.length > 0) {
        toolCalls = mergeToolCalls(toolCalls, msg.tool_calls);
      }
      if (msg.thinking) yield { type: 'thinking', token: msg.thinking };
      if (msg.content) {
        const { out, think } = splitThink(msg.content);
        if (think) yield { type: 'thinking', token: think };
        if (out) yield { type: 'token', token: out };
      }
      if (evt.done) {
        const { out, think } = splitThink.flush();
        if (think) yield { type: 'thinking', token: think };
        if (out) yield { type: 'token', token: out };
        if (toolCalls.length > 0) yield { type: 'tool_calls', calls: toolCalls };
        return;
      }
    }
  }
  if (toolCalls.length > 0) yield { type: 'tool_calls', calls: toolCalls };
}

module.exports = {
  DEFAULT_OLLAMA_URL,
  perfOptions,
  getOllamaStatus,
  streamOllamaChat,
  normalizeUrl,
  validUrl,
  pickDefaultModel,
};
