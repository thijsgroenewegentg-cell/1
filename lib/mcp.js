/**
 * MCP — Model Context Protocol client (stdio transport).
 * Connects Ultron to any MCP server: Blender (blender-mcp), filesystem,
 * GitHub, databases… Every tool the server exposes becomes an Ultron tool,
 * automatically named mcp_<server>_<tool>.
 *
 * Config (Settings → MCP servers): { name, command } e.g.
 *   { name: "blender", command: "uvx blender-mcp" }
 */
'use strict';

const { spawn } = require('child_process');
const config = require('./config');

const clients = new Map(); // name → client state

function sanitize(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9_-]/g, '').slice(0, 30);
}

/** Split a command string into argv, respecting simple quotes. */
function parseCommand(str) {
  const parts = String(str || '').match(/"[^"]*"|'[^']*'|\S+/g) || [];
  return parts.map((p) => p.replace(/^["']|["']$/g, ''));
}

function request(client, method, params, timeoutMs = 120000) {
  return new Promise((resolve, reject) => {
    if (client.dead) return reject(new Error('MCP server exited'));
    const id = client.nextId++;
    const timer = setTimeout(() => {
      client.pending.delete(id);
      reject(new Error(`${method} timed out (${timeoutMs / 1000}s)`));
    }, timeoutMs);
    client.pending.set(id, { resolve, reject, timer });
    try {
      client.proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    } catch (err) {
      clearTimeout(timer);
      client.pending.delete(id);
      reject(err);
    }
  });
}

function notify(client, method, params) {
  try { client.proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', method, params }) + '\n'); } catch { /* gone */ }
}

/** Spawn + handshake + tools/list. Cached per server name. */
async function ensureServer(cfgEntry) {
  const name = sanitize(cfgEntry.name);
  if (!name) throw new Error('MCP server needs a name');
  if (clients.has(name)) return clients.get(name);

  const argv = parseCommand(cfgEntry.command);
  if (argv.length === 0) throw new Error('MCP server needs a command');
  const proc = spawn(argv[0], argv.slice(1), { stdio: ['pipe', 'pipe', 'pipe'] });

  const client = {
    name,
    proc,
    tools: [],
    pending: new Map(),
    buffer: '',
    nextId: 1,
    dead: false,
    stderrTail: '',
  };
  clients.set(name, client);

  proc.stdout.on('data', (chunk) => {
    client.buffer += chunk.toString('utf8');
    let nl;
    while ((nl = client.buffer.indexOf('\n')) !== -1) {
      const line = client.buffer.slice(0, nl).trim();
      client.buffer = client.buffer.slice(nl + 1);
      if (!line) continue;
      let msg;
      try { msg = JSON.parse(line); } catch { continue; }
      if (msg && msg.id != null && client.pending.has(msg.id)) {
        const p = client.pending.get(msg.id);
        client.pending.delete(msg.id);
        clearTimeout(p.timer);
        if (msg.error) p.reject(new Error(String(msg.error.message || 'MCP error')));
        else p.resolve(msg.result);
      }
    }
  });
  proc.stderr.on('data', (c) => { client.stderrTail = (client.stderrTail + c.toString()).slice(-400); });
  proc.on('exit', () => { client.dead = true; clients.delete(name); });
  proc.on('error', (err) => { client.dead = true; clients.delete(name); });

  await request(client, 'initialize', {
    protocolVersion: '2024-11-05',
    capabilities: {},
    clientInfo: { name: 'ultron', version: '1.0.0' },
  }, 15000);
  notify(client, 'notifications/initialized', {});
  const res = await request(client, 'tools/list', {}, 15000);
  client.tools = (res && Array.isArray(res.tools) ? res.tools : []).filter((t) => t && t.name);
  return client;
}

/** All configured servers' tools, as Ultron tool specs. */
async function listTools() {
  const cfgs = (config.load().mcps || []).filter((m) => m && m.name && m.command && m.enabled !== false);
  const out = [];
  await Promise.all(cfgs.map(async (m) => {
    try {
      const c = await ensureServer(m);
      for (const t of c.tools) {
        out.push({
          server: sanitize(m.name),
          name: 'mcp_' + sanitize(m.name) + '_' + sanitize(t.name),
          rawName: t.name,
          description: String(t.description || ''),
          schema: t.inputSchema && t.inputSchema.type === 'object'
            ? t.inputSchema
            : { type: 'object', properties: {} },
        });
      }
    } catch { /* unreachable server — skip its tools */ }
  }));
  return out;
}

/** Call a tool by its full Ultron name (mcp_<server>_<tool>). */
async function callTool(fullName, args) {
  const cfgs = config.load().mcps || [];
  for (const m of cfgs) {
    const prefix = 'mcp_' + sanitize(m.name) + '_';
    if (String(fullName).startsWith(prefix)) {
      const raw = sanitize(String(fullName).slice(prefix.length));
      const c = await ensureServer(m);
      const res = await request(c, 'tools/call', { name: raw, arguments: args || {} }, 180000);
      const content = (res && res.content) || [];
      const text = content
        .map((p) => (p.type === 'text' ? p.text : p.type === 'image' ? '[image returned by MCP server]' : JSON.stringify(p)))
        .join('\n')
        .slice(0, 6000);
      return { ok: !res || !res.isError, result: text || '(no output)' };
    }
  }
  return { error: `unknown MCP tool "${fullName}"` };
}

/** Status for the settings UI. */
async function status() {
  const cfgs = (config.load().mcps || []).filter((m) => m && m.name && m.command);
  const out = [];
  for (const m of cfgs) {
    try {
      const c = await ensureServer(m);
      out.push({ name: sanitize(m.name), connected: true, tools: c.tools.length });
    } catch (err) {
      out.push({ name: sanitize(m.name), connected: false, error: String(err.message || err).slice(0, 140) });
    }
  }
  return { servers: out };
}

module.exports = { listTools, callTool, status, ensureServer };
