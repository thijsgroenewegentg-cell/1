/**
 * SKILLS — user-defined tools, hot-loaded from data/skills/*.json.
 * Give Ultron a new ability by dropping a file, no code changes:
 *
 * {
 *   "name": "get_crypto_price",
 *   "description": "Get the current price of a cryptocurrency in USD",
 *   "parameters": {
 *     "type": "object",
 *     "properties": { "coin": { "type": "string", "description": "e.g. bitcoin" } },
 *     "required": ["coin"]
 *   },
 *   "http": {
 *     "method": "GET",
 *     "url": "https://api.example.com/simple/price?ids={{coin}}&vs_currencies=usd"
 *   }
 * }
 */
'use strict';

const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, '..', 'data');
const SKILLS_DIR = path.join(DATA_DIR, 'skills');

function skillFiles() {
  try {
    return fs.readdirSync(SKILLS_DIR).filter((f) => f.endsWith('.json'));
  } catch {
    return [];
  }
}

/** Load all valid skills (fresh each call → drop a file, it just works). */
function loadSkills() {
  const skills = [];
  for (const file of skillFiles()) {
    try {
      const def = JSON.parse(fs.readFileSync(path.join(SKILLS_DIR, file), 'utf8'));
      if (!def.name || !def.description) continue;
      if (!def.http || !def.http.url) continue;
      if (!/^https?:\/\//i.test(def.http.url)) continue;
      skills.push({ file, ...def });
    } catch { /* malformed skill — ignore quietly */ }
  }
  return skills;
}

/** OpenAI/Ollama tool specs for every loaded skill. */
function toolSpecs() {
  return loadSkills().map((s) => ({
    type: 'function',
    function: {
      name: String(s.name).replace(/[^a-z0-9_]/gi, '_').slice(0, 64),
      description: String(s.description).slice(0, 500),
      parameters: s.parameters && s.parameters.type === 'object'
        ? s.parameters
        : { type: 'object', properties: {} },
    },
  }));
}

/** Execute a skill by substituting {{param}} into the HTTP template. */
async function execute(skillName, args) {
  const skill = loadSkills().find((s) => s.name === skillName);
  if (!skill) return { error: `unknown skill "${skillName}"` };

  const fill = (template) => String(template).replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_m, key) => {
    const value = args && args[key] != null ? String(args[key]) : '';
    return encodeURIComponent(value);
  });

  const method = String(skill.http.method || 'GET').toUpperCase();
  const url = fill(skill.http.url);
  let body;
  const headers = { 'User-Agent': 'Mozilla/5.0 (Ultron skill)' };
  if (method === 'POST' || method === 'PUT') {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(args || {});
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const res = await fetch(url, { method, headers, body, signal: controller.signal });
    const type = res.headers.get('content-type') || '';
    const text = await res.text();
    let out;
    if (/json/i.test(type)) {
      try { out = JSON.stringify(JSON.parse(text)); } catch { out = text; }
    } else {
      out = text;
    }
    return { ok: res.ok, status: res.status, url, response: String(out).slice(0, 4000) };
  } catch (err) {
    return { error: err.name === 'AbortError' ? 'timeout' : String(err.message || err) };
  } finally {
    clearTimeout(timer);
  }
}

function stats() {
  const skills = loadSkills();
  return { count: skills.length, names: skills.map((s) => s.name), dir: 'data/skills' };
}

module.exports = { toolSpecs, execute, stats, SKILLS_DIR };
