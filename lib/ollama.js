/**
 * Ollama client — talks to a local (or remote) Ollama server.
 * Supports: model listing, streaming chat, tool calling, vision (images).
 * Docs: https://github.com/ollama/ollama/blob/main/docs/api.md
 */
'use strict';

const DEFAULT_OLLAMA_URL = process.env.OLLAMA_URL || 'http://localhost:11434';
const PREFERRED_MODELS = ['llama3.1', 'llama3', 'qwen2.5', 'qwen', 'mistral', 'gemma2', 'gemma', 'phi3', 'deepseek-r1'];

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
async function* streamOllamaChat({ ollamaUrl, model, messages, temperature = 0.7, tools }) {
  const base = normalizeUrl(ollamaUrl || DEFAULT_OLLAMA_URL);
  const body = { model, messages, stream: true, options: { temperature } };
  if (tools && tools.length > 0) body.tools = tools;

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
      if (msg.content) yield { type: 'token', token: msg.content };
      if (evt.done) {
        if (toolCalls.length > 0) yield { type: 'tool_calls', calls: toolCalls };
        return;
      }
    }
  }
  if (toolCalls.length > 0) yield { type: 'tool_calls', calls: toolCalls };
}

module.exports = {
  DEFAULT_OLLAMA_URL,
  getOllamaStatus,
  streamOllamaChat,
  normalizeUrl,
  validUrl,
  pickDefaultModel,
};
