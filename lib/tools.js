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

const DATA_DIR = process.env.ULTRON_DATA || path.join(__dirname, '..', 'data');
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
const selfedit = require('./selfedit');

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
            once_at: { type: 'string', description: 'One-shot datetime (e.g. 2026-08-27 21:00) — runs ONCE, then the order disappears. Use for "tonight at 23:00, do X".' },
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
        name: 'restart_server',
        description: 'Restart yourself so code changes take effect. Use after editing server-side files. Your reply should say goodbye briefly.',
        parameters: { type: 'object', properties: {} },
      },
    },
    {
      type: 'function',
      function: {
        name: 'git',
        description: 'Manage your own source with git — your undo history. Actions: status, diff, log, commit {message}, revert {mode: "working"|"commit", confirm: true}.',
        parameters: {
          type: 'object',
          properties: {
            action: { type: 'string', description: 'status | diff | log | commit | revert' },
            message: { type: 'string', description: 'Commit message (for commit)' },
            n: { type: 'number', description: 'Log length (for log)' },
            mode: { type: 'string', description: 'revert mode: "working" discards uncommitted changes, "commit" undoes the last commit' },
            confirm: { type: 'boolean', description: 'Must be true for revert' },
          },
          required: ['action'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'spawn_drones',
        description: 'LEGION: split a large job into focused sub-tasks and run them as parallel drone agents, each with its own tool loop. Use for multi-topic research, batch lookups, or anything that parallelizes. Give each drone ONE clear, self-contained task. Max 6 drones; reports come back to you for synthesis.',
        parameters: {
          type: 'object',
          properties: {
            tasks: {
              type: 'array',
              description: 'Array of focused task strings, one per drone',
              items: { type: 'string' },
            },
          },
          required: ['tasks'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'maps',
        description: 'Free world maps (OpenStreetMap — no keys, no cost): find places (geocode), turn-by-turn directions (driving/cycling/walking), and nearby points of interest (cafes, fuel, supermarkets, pharmacies…). Use it whenever the user asks about locations, distances, routes or what is nearby.',
        parameters: {
          type: 'object',
          properties: {
            action: { type: 'string', description: 'geocode | route | nearby' },
            query: { type: 'string', description: 'Place to find (geocode)' },
            from: { type: 'string', description: 'Start place or "lat,lon" (route)' },
            to: { type: 'string', description: 'Destination place or "lat,lon" (route)' },
            mode: { type: 'string', description: 'driving | cycling | foot (route, default driving)' },
            what: { type: 'string', description: 'What to find: cafe, restaurant, fuel, supermarket, pharmacy… or any name (nearby)' },
            place: { type: 'string', description: 'Center place or "lat,lon" (nearby)' },
            radius_m: { type: 'number', description: 'Search radius in meters (nearby, default 1500)' },
          },
          required: ['action'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'generate_image',
        description: 'Generate an image from a text prompt using the local Stable Diffusion server (Automatic1111 / Forge / SD.Next). Describe the image in rich detail — style, composition, lighting. The result is saved and shown to the user automatically.',
        parameters: {
          type: 'object',
          properties: {
            prompt: { type: 'string', description: 'Detailed description of the image to create' },
            negative_prompt: { type: 'string', description: 'What to avoid (default: blurry, low quality)' },
            width: { type: 'number', description: '256-1536 (default 768)' },
            height: { type: 'number', description: '256-1536 (default 768)' },
            steps: { type: 'number', description: '5-60 sampling steps (default 25)' },
          },
          required: ['prompt'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'list_source_files',
        description: 'List your own source files (the project you run in) — for self-modification.',
        parameters: {
          type: 'object',
          properties: { subdir: { type: 'string', description: 'Optional subfolder, e.g. "lib" or "public"' } },
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'read_source',
        description: 'Read one of your own source files (max 200 KB) — for self-modification.',
        parameters: {
          type: 'object',
          properties: { path: { type: 'string', description: 'Project-relative path, e.g. "lib/persona.js"' } },
          required: ['path'],
        },
      },
    },
    {
      type: 'function',
      function: {
        name: 'edit_source',
        description: 'Edit your own source code. PREFERRED: surgical mode — give `find` (the exact existing text, copied verbatim from read_source) and `replace`. Alternative: full `content` rewrite (use sparingly). Every edit is backed up automatically and syntax-checked; broken edits are rejected and never applied. After editing server/lib code, run tests and restart yourself.',
        parameters: {
          type: 'object',
          properties: {
            path: { type: 'string', description: 'Project-relative path, e.g. "lib/persona.js" or "public/styles.css"' },
            find: { type: 'string', description: 'Exact existing text to replace (surgical mode)' },
            replace: { type: 'string', description: 'Replacement text' },
            content: { type: 'string', description: 'Full new file content (rewrite mode — avoid unless necessary)' },
            replace_all: { type: 'boolean', description: 'Replace every occurrence of find (default: only the first, and only if unique)' },
          },
          required: ['path'],
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
    case 'remember':      return memory.add(a.fact, ctx.profile);
    case 'forget':        return memory.removeContaining(a.contains);
    case 'search_knowledge': {
      if (!ctx.ollamaUrl) return { error: 'knowledge search needs a live Ollama connection' };
      return knowledge.search(ctx.ollamaUrl, a.query);
    }
    case 'get_weather':   return weather.getWeather({ location: a.location, days: a.days });
    case 'maps': {
      const maps = require('./maps');
      if (a.action === 'route') return maps.route(a);
      if (a.action === 'nearby') return maps.nearby(a);
      if (a.action === 'geocode') return maps.geocode(a.query);
      return { error: "action must be geocode, route or nearby" };
    }
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
    case 'spawn_drones': {
      const { agentChat } = require('./agent');        // lazy: avoids require cycle
      const { buildSystemPrompt } = require('./persona');
      const legion = require('./legion');
      return legion.runDrones({
        tasks: a.tasks,
        runner: (task) => agentChat({
          ollamaUrl: ctx.ollamaUrl,
          model: ctx.model,
          messages: [{ role: 'user', content: task }],
          temperature: 0.4,
          toolsEnabled: true,
          shellAllowed: false, // drones never touch the shell
          systemPrompt: buildSystemPrompt({ tools: true, language: 'auto', memoryText: [] }) + '\n\n' + legion.DRONE_PROMPT,
          approval: { general: false, selfEdit: true }, // no approval channel → self-edits denied (fail-safe)
          maxRounds: 6,
        }),
      });
    }
    case 'generate_image':  return require('./imagine').generate(a);
    case 'list_source_files': return selfedit.listSource(a.subdir);
    case 'read_source':      return selfedit.readSource(a.path);
    case 'edit_source':      return selfedit.editSource(a);
    case 'restart_server':   return selfedit.restartServer();
    case 'git':              return selfedit.git(a.action, a);
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
const DANGEROUS_TOOLS = new Set(['run_command', 'edit_source', 'restart_server']);

module.exports = { toolSpecs, executeTool, FILES_DIR, DANGEROUS_TOOLS };
