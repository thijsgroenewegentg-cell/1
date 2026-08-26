/**
 * ULTRON'S HANDS — tool definitions + executors.
 * Tools run server-side with safety rails:
 *   • file access is jailed to data/files/
 *   • shell commands only when the request arrives from a local/private host
 *   • fetch/search have timeouts and size caps
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { execFile } = require('child_process');

const DATA_DIR = path.join(__dirname, '..', 'data');
const FILES_DIR = path.join(DATA_DIR, 'files');
const memory = require('./memory');
const reminders = require('./reminders');
const knowledge = require('./knowledge');
const weather = require('./weather');
const calendar = require('./calendar');
const config = require('./config');
const directives = require('./directives');
const browser = require('./browser');
const skills = require('./skills');

/* ---------- helpers ---------- */

function decodeEntities(s) {
  return String(s)
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#x27;|&#39;/g, "'")
    .replace(/&nbsp;/g, ' ');
}

function stripTags(html) {
  return decodeEntities(
    String(html)
      .replace(/<script[\s\S]*?<\/script>/gi, '')
      .replace(/<style[\s\S]*?<\/style>/gi, '')
      .replace(/<\/(p|div|li|h[1-6]|tr|br)>/gi, '\n')
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<[^>]+>/g, '')
  )
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

async function fetchWithLimits(url, { timeoutMs = 10000, maxBytes = 2 * 1024 * 1024, headers = {} } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      signal: controller.signal,
      headers: { 'User-Agent': 'Mozilla/5.0 (Ultron local agent)', ...headers },
      redirect: 'follow',
    });
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    const reader = res.body.getReader();
    const chunks = [];
    let total = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.length;
      chunks.push(value);
      if (total > maxBytes) break;
    }
    const type = res.headers.get('content-type') || '';
    return { ok: true, type, body: Buffer.concat(chunks).toString('utf8') };
  } catch (err) {
    return { ok: false, error: err.name === 'AbortError' ? 'timeout' : String(err.message || err) };
  } finally {
    clearTimeout(timer);
  }
}

/* ---------- individual tools ---------- */

async function webSearch(query) {
  const q = encodeURIComponent(String(query).slice(0, 300));
  // Primary: DuckDuckGo HTML (no key, no cost). Fallback: the lite endpoint.
  for (const endpoint of [`https://html.duckduckgo.com/html/?q=${q}`, `https://lite.duckduckgo.com/lite/?q=${q}`]) {
    const res = await fetchWithLimits(endpoint, { timeoutMs: 12000 });
    if (!res.ok || !res.body) continue;
    const results = [];
    const linkRe = /<a[^>]*class="[^"]*result(?:__a|-link)[^"]*"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi;
    const snippetRe = /<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>([\s\S]*?)<\/a>|<td[^>]*class="result-snippet"[^>]*>([\s\S]*?)<\/td>/gi;
    const snippets = [];
    let m;
    while ((m = snippetRe.exec(res.body)) !== null) snippets.push(stripTags(m[1] || m[2] || ''));
    let i = 0;
    while ((m = linkRe.exec(res.body)) !== null) {
      let href = decodeEntities(m[1]);
      if (/\bduckduckgo\.com\/l\/\?|\/l\/\?uddg=/.test(href)) {
        try {
          const u = new URL(href, 'https://duckduckgo.com');
          const uddg = u.searchParams.get('uddg');
          if (uddg) href = decodeURIComponent(uddg);
        } catch { /* keep raw */ }
      }
      const title = stripTags(m[2]);
      if (!title || !/^https?:\/\//i.test(href)) continue;
      results.push({ title, url: href, snippet: (snippets[i] || '').slice(0, 300) });
      i++;
      if (results.length >= 5) break;
    }
    if (results.length > 0) return results;
  }
  return { error: 'search unavailable (network blocked?) — tell the user you could not search' };
}

async function fetchUrl(url) {
  let parsed;
  try { parsed = new URL(url); } catch { return { error: `invalid URL: ${url}` }; }
  if (!/^https?:$/.test(parsed.protocol)) return { error: 'only http/https supported' };
  const res = await fetchWithLimits(url, { timeoutMs: 12000 });
  if (!res.ok) return { error: res.error };
  const text = /html/i.test(res.type) ? stripTags(res.body) : res.body;
  return { url, content_type: res.type, text: text.slice(0, 6000), truncated: text.length > 6000 };
}

function safePath(rel) {
  const root = path.resolve(FILES_DIR);
  const full = path.resolve(root, rel);
  if (full !== root && !full.startsWith(root + path.sep)) {
    return { error: 'path escapes the file workspace' };
  }
  return { full };
}

function readFile(rel) {
  const p = safePath(rel);
  if (p.error) return p;
  try {
    const stat = fs.statSync(p.full);
    if (stat.size > 200 * 1024) return { error: 'file too large (>200 KB)' };
    return { path: rel, content: fs.readFileSync(p.full, 'utf8').slice(0, 20000) };
  } catch (err) {
    return { error: err.code === 'ENOENT' ? 'file not found' : String(err.message) };
  }
}

function writeFile(rel, content) {
  const p = safePath(rel);
  if (p.error) return p;
  const body = String(content != null ? content : '');
  if (body.length > 200 * 1024) return { error: 'content too large (>200 KB)' };
  try {
    fs.mkdirSync(path.dirname(p.full), { recursive: true });
    fs.writeFileSync(p.full, body);
    return { ok: true, path: rel, bytes: body.length };
  } catch (err) {
    return { error: String(err.message) };
  }
}

function listFiles() {
  try {
    fs.mkdirSync(FILES_DIR, { recursive: true });
    const out = [];
    const walk = (dir, prefix) => {
      for (const name of fs.readdirSync(dir).slice(0, 100)) {
        const full = path.join(dir, name);
        const rel = prefix ? `${prefix}/${name}` : name;
        if (fs.statSync(full).isDirectory()) walk(full, rel);
        else out.push(rel);
      }
    };
    walk(FILES_DIR, '');
    return { files: out.slice(0, 100) };
  } catch (err) {
    return { error: String(err.message) };
  }
}

function runCommand(command, { shellAllowed }) {
  if (!shellAllowed) {
    return { error: 'shell disabled: commands are only allowed when Ultron is accessed from localhost/LAN' };
  }
  const cmd = String(command).slice(0, 2000);
  return new Promise((resolve) => {
    const child = execFile('/bin/bash', ['-c', cmd], {
      cwd: FILES_DIR,
      timeout: 10000,
      maxBuffer: 64 * 1024,
      env: { PATH: process.env.PATH, HOME: process.env.HOME || '/tmp', LANG: 'C.UTF-8' },
    }, (err, stdout, stderr) => {
      const out = ((stdout || '') + (stderr || '')).slice(0, 8000);
      if (err && !out) resolve({ error: `exit ${err.code || '?'}: ${String(err.message).slice(0, 500)}` });
      else resolve({ exit_code: err ? err.code : 0, output: out || '(no output)' });
    });
  });
}

/* ---------- tool specs (OpenAI/Ollama function-calling schema) ---------- */

async function toolSpecs({ shellAllowed }) {
  const specs = [
    {
      type: 'function',
      function: {
        name: 'web_search',
        description: 'Search the web. Returns the top results with titles, URLs and snippets. Use for current events or anything you are unsure about.',
        parameters: {
          type: 'object',
          properties: { query: { type: 'string', description: 'The search query' } },
          required: ['query'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'fetch_url',
        description: 'Download a web page and return its readable text. Use after web_search, or when the user gives you a link.',
        parameters: {
          type: 'object',
          properties: { url: { type: 'string', description: 'Full http(s) URL to read' } },
          required: ['url'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'write_file',
        description: 'Write text to a file in your workspace (created if needed). Paths are relative, e.g. "notes.txt" or "projects/plan.md".',
        parameters: {
          type: 'object',
          properties: {
            path: { type: 'string' },
            content: { type: 'string' },
          },
          required: ['path', 'content'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'read_file',
        description: 'Read a text file from your workspace.',
        parameters: {
          type: 'object',
          properties: { path: { type: 'string' } },
          required: ['path'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'list_files',
        description: 'List files in your workspace.',
        parameters: { type: 'object', properties: {} },
      },
    },
    {
      type: 'function',
      function: {
        name: 'set_reminder',
        description: 'Schedule a reminder for the user. It will be shown and spoken aloud when due.',
        parameters: {
          type: 'object',
          properties: {
            message: { type: 'string', description: 'What to remind the user about' },
            delay_minutes: { type: 'number', description: 'How far in the future (minutes). 0.05 = 3 seconds. Use for "in X minutes".' },
            at: { type: 'string', description: 'Absolute time, ISO format e.g. 2026-08-27T09:30. Use for specific clock times.' },
          },
          required: ['message'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'remember',
        description: 'Store a durable fact about the user in long-term memory (persists across sessions). Use for preferences, names, ongoing projects. Keep it a short factual sentence.',
        parameters: {
          type: 'object',
          properties: { fact: { type: 'string' } },
          required: ['fact'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'forget',
        description: 'Delete memories containing the given text.',
        parameters: {
          type: 'object',
          properties: { contains: { type: 'string' } },
          required: ['contains'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'search_knowledge',
        description: 'Search the user\'s personal knowledge base (their own documents, indexed in data/knowledge/docs). Use FIRST when the question might be about the user\'s own notes, projects, or files.',
        parameters: {
          type: 'object',
          properties: { query: { type: 'string', description: 'What to look for in the user\'s documents' } },
          required: ['query'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'get_weather',
        description: 'Current weather and a short forecast for any place. Free service, works worldwide.',
        parameters: {
          type: 'object',
          properties: {
            location: { type: 'string', description: 'Place name, e.g. "Leiderdorp" or "Amsterdam"' },
            days: { type: 'number', description: 'Forecast days 1-7 (default 1)' },
          },
          required: ['location'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'calendar_list',
        description: 'List the user\'s upcoming calendar events (local calendar file).',
        parameters: {
          type: 'object',
          properties: { days: { type: 'number', description: 'How many days ahead (default 7)' } },
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'calendar_add',
        description: 'Add an event to the user\'s calendar. date: YYYY-MM-DD; time: HH:MM (omit for all-day).',
        parameters: {
          type: 'object',
          properties: {
            title: { type: 'string' },
            date: { type: 'string', description: 'YYYY-MM-DD' },
            time: { type: 'string', description: 'HH:MM, 24-hour — omit for an all-day event' },
            duration_minutes: { type: 'number' },
          },
          required: ['title', 'date'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'configure_briefing',
        description: 'Enable/schedule the daily proactive briefing that Ultron speaks aloud. Say WHAT changed in the confirmation.',
        parameters: {
          type: 'object',
          properties: {
            enabled: { type: 'boolean' },
            time: { type: 'string', description: 'HH:MM, 24-hour' },
            location: { type: 'string', description: 'Default place for the weather section' },
            language: { type: 'string', description: 'Briefing language: auto, en, nl, de, fr, es, it or tr' },
          },
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'set_directive',
        description: 'Create a standing order: an instruction you will execute autonomously on a repeating schedule, forever, until removed. Only create one when the user clearly wants ongoing/recurring action ("keep watching…", "every day…", "tell me when…"). Confirm to the user what you set up.',
        parameters: {
          type: 'object',
          properties: {
            instruction: { type: 'string', description: 'The recurring task, written as a command to yourself' },
            every_minutes: { type: 'number', description: 'Repeat interval in minutes (min 1). Use for "every hour", "every 30 minutes"…' },
            at: { type: 'string', description: 'Daily time HH:MM (24h). Use for "every evening at 21:00"…' },
          },
          required: ['instruction'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'list_directives',
        description: 'List your active standing orders.',
        parameters: { type: 'object', properties: {} },
      },
    },
    {
      type: 'function',
      function: {
        name: 'remove_directive',
        description: 'Remove a standing order by matching part of its instruction text.',
        parameters: {
          type: 'object',
          properties: { contains: { type: 'string' } },
          required: ['contains'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'browser',
        description: 'Drive a real headless Chromium browser: open pages, read their text, click elements, type into fields, press keys, take screenshots. Use `open` first, then `read`/`click`/`type` step by step. Selectors are CSS. Available only if Playwright is installed.',
        parameters: {
          type: 'object',
          properties: {
            action: { type: 'string', description: 'open | read | click | type | press | screenshot' },
            url: { type: 'string', description: 'Full URL (for open)' },
            selector: { type: 'string', description: 'CSS selector (for read/click/type)' },
            text: { type: 'string', description: 'Text to type (for type)' },
            key: { type: 'string', description: 'Key to press, e.g. Enter (for press)' },
          },
          required: ['action'],
        },
      },
    },
  ];

  // Browser tool only when Playwright is actually available.
  if (!(await browser.available())) {
    const idx = specs.findIndex((s) => s.function.name === 'browser');
    if (idx !== -1) specs.splice(idx, 1);
  }

  // User-defined skills from data/skills/*.json — hot-loaded.
  specs.push(...skills.toolSpecs());
  return specs;

  if (shellAllowed) {
    specs.push({
      type: 'function',
      function: {
        name: 'run_command',
        description: 'Run a shell command in your workspace directory (bash). Use for real work the user asks for: inspecting files, git, running scripts. Never use it destructively (no rm -rf outside the workspace, no fork bombs). Output is capped.',
        parameters: {
          type: 'object',
          properties: { command: { type: 'string' } },
          required: ['command'],
        },
      },
    });
  }
  return specs;
}

/* ---------- dispatcher ---------- */

async function executeTool(name, args, ctx) {
  const a = (args && typeof args === 'object') ? args : {};
  switch (name) {
    case 'web_search':    return webSearch(a.query);
    case 'fetch_url':     return fetchUrl(a.url);
    case 'write_file':    return writeFile(a.path, a.content);
    case 'read_file':     return readFile(a.path);
    case 'list_files':    return listFiles();
    case 'run_command':   return runCommand(a.command, ctx);
    case 'set_reminder':  return reminders.add(a);
    case 'remember':      return memory.add(a.fact);
    case 'forget':        return memory.removeContaining(a.contains);
    case 'search_knowledge': {
      if (!ctx.ollamaUrl) return { error: 'knowledge search needs a live Ollama connection' };
      return knowledge.search(ctx.ollamaUrl, a.query);
    }
    case 'get_weather':   return weather.getWeather({ location: a.location, days: a.days });
    case 'calendar_list': return { events: calendar.upcoming(a.days) };
    case 'calendar_add':  return calendar.add(a);
    case 'configure_briefing': {
      const patch = { briefing: {} };
      if (typeof a.enabled === 'boolean') patch.briefing.enabled = a.enabled;
      if (typeof a.time === 'string') patch.briefing.time = a.time;
      if (typeof a.location === 'string') patch.briefing.location = a.location;
      if (typeof a.language === 'string') patch.briefing.language = a.language;
      const saved = config.save(patch);
      return { ok: true, briefing: saved.briefing };
    }
    case 'set_directive':    return directives.add(a);
    case 'list_directives':  return { directives: directives.all() };
    case 'remove_directive': return directives.remove(a);
    case 'browser': {
      if (!(await browser.available())) {
        return { error: 'browser automation not installed — run `npm install playwright && npx playwright install chromium` on the server, then restart' };
      }
      try {
        return await browser.execute(a);
      } catch (err) {
        return { error: `browser action failed: ${String(err.message || err).slice(0, 300)}` };
      }
    }
    default: {
      // User-defined skills from data/skills/*.json
      if (skills.stats().names.includes(name)) return skills.execute(name, a);
      return { error: `unknown tool "${name}"` };
    }
  }
}

/** Tools that need explicit user approval when the gate is on. */
const DANGEROUS_TOOLS = new Set(['run_command']);

module.exports = { toolSpecs, executeTool, FILES_DIR, DANGEROUS_TOOLS };
