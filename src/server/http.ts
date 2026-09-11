import http from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { App } from '../app.ts';
import { bus, recentEvents, publish } from '../events.ts';
import { createLogger } from '../logger.ts';

const log = createLogger('http');
const PUBLIC_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '../../public');

const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

function json(res: http.ServerResponse, status: number, body: unknown): void {
  const data = JSON.stringify(body);
  res.writeHead(status, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(data) });
  res.end(data);
}

function sseInit(res: http.ServerResponse): void {
  res.writeHead(200, {
    'content-type': 'text/event-stream',
    'cache-control': 'no-cache',
    connection: 'keep-alive',
    'x-accel-buffering': 'no',
  });
  res.write('retry: 2000\n\n');
}

function sseSend(res: http.ServerResponse, event: string, data: unknown): void {
  res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

async function readBody(req: http.IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > 1_000_000) throw new Error('body too large');
    chunks.push(chunk as Buffer);
  }
  if (chunks.length === 0) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>;
  } catch {
    throw new Error('invalid JSON body');
  }
}

export function createServer(app: App): http.Server {
  const { cfg, ollama, vault, goals, orchestrator, routines } = app;

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);
    const p = url.pathname;
    const method = req.method ?? 'GET';
    try {
      // ── static dashboard ──
      if (method === 'GET' && (p === '/' || p === '/index.html')) {
        return serveStatic(res, 'index.html');
      }
      if (method === 'GET' && /^\/[a-zA-Z0-9_.-]+\.(js|css|svg|png|ico)$/.test(p)) {
        return serveStatic(res, p.slice(1));
      }

      // ── system ──
      if (method === 'GET' && p === '/api/health') {
        const reachable = await ollama.ok();
        const alerts = goals.dueAlerts();
        return json(res, 200, {
          status: 'ok',
          uptime_s: Math.round((Date.now() - app.startedAt.getTime()) / 1000),
          ollama: { base_url: cfg.ollama.base_url, reachable },
          model: cfg.ollama.model,
          fast_model: cfg.ollama.fast_model,
          authority: cfg.authority.level,
          deadline_alerts: alerts.length,
          memories: vault.list(1000).length,
          open_goals: goals.list().length,
        });
      }

      if (method === 'GET' && p === '/api/models') {
        try {
          const models = await ollama.listModels();
          return json(res, 200, {
            configured: { model: cfg.ollama.model, fast_model: cfg.ollama.fast_model },
            installed: models.map((m) => ({ name: m.name, size_gb: Math.round((m.size / 1e9) * 10) / 10 })),
          });
        } catch (err) {
          return json(res, 502, { error: String(err instanceof Error ? err.message : err) });
        }
      }

      if (method === 'POST' && p === '/api/models/pull') {
        const body = await readBody(req);
        const model = String(body.model ?? '').trim();
        if (!model) return json(res, 400, { error: 'model is required' });
        publish('pull:started', { model });
        void ollama
          .pull(model, (status) => publish('pull:progress', { model, status }))
          .then(() => publish('pull:done', { model }))
          .catch((err: unknown) => publish('pull:error', { model, error: String(err) }));
        return json(res, 202, { pulling: model, note: 'progress streams on /api/events/stream' });
      }

      if (method === 'PATCH' && p === '/api/authority') {
        const body = await readBody(req);
        const level = Number(body.level);
        if (!Number.isInteger(level) || level < 0 || level > 4) {
          return json(res, 400, { error: 'level must be an integer 0..4' });
        }
        cfg.authority.level = level;
        publish('authority:changed', { level });
        return json(res, 200, { level });
      }

      // ── chat ──
      if (method === 'POST' && p === '/api/chat') {
        const body = await readBody(req);
        const message = String(body.message ?? '').trim();
        if (!message) return json(res, 400, { error: 'message is required' });
        const conversationId = body.conversation_id ? Number(body.conversation_id) : null;
        const stream = body.stream !== false;

        if (stream) {
          sseInit(res);
          try {
            const result = await orchestrator.run({
              conversationId,
              userInput: message,
              onToken: (delta) => sseSend(res, 'token', { delta }),
            });
            sseSend(res, 'done', { conversation_id: result.conversationId, answer: result.answer, turns: result.turns });
          } catch (err) {
            sseSend(res, 'error', { message: err instanceof Error ? err.message : String(err) });
          }
          res.end();
          return;
        }

        try {
          const result = await orchestrator.run({ conversationId, userInput: message });
          return json(res, 200, { conversation_id: result.conversationId, answer: result.answer });
        } catch (err) {
          return json(res, 502, { error: err instanceof Error ? err.message : String(err) });
        }
      }

      // ── conversations ──
      if (method === 'GET' && p === '/api/conversations') {
        const rows = app.db.db
          .prepare(
            `SELECT c.id, c.title, c.created_at, c.updated_at, COUNT(m.id) AS messages
             FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id
             GROUP BY c.id ORDER BY c.updated_at DESC LIMIT 100`,
          )
          .all();
        return json(res, 200, { conversations: rows });
      }
      const convMatch = p.match(/^\/api\/conversations\/(\d+)$/);
      if (method === 'GET' && convMatch) {
        const id = Number(convMatch[1]);
        const rows = app.db.db
          .prepare(`SELECT id, role, agent, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id`)
          .all(id);
        return json(res, 200, { conversation_id: id, messages: rows });
      }

      // ── knowledge vault ──
      if (method === 'GET' && p === '/api/memories') {
        const q = url.searchParams.get('q');
        const items = q ? vault.search(q, 30) : vault.list(50);
        return json(res, 200, { memories: items });
      }
      if (method === 'POST' && p === '/api/memories') {
        const body = await readBody(req);
        if (!body.title) return json(res, 400, { error: 'title is required' });
        const mem = vault.remember({
          title: String(body.title),
          body: String(body.body ?? ''),
          kind: String(body.kind ?? 'note'),
          tags: Array.isArray(body.tags) ? body.tags.map(String) : [],
          source: 'dashboard',
        });
        return json(res, 201, mem);
      }
      const memMatch = p.match(/^\/api\/memories\/(\d+)$/);
      if (method === 'DELETE' && memMatch) {
        vault.delete(Number(memMatch[1]));
        return json(res, 200, { deleted: Number(memMatch[1]) });
      }

      // ── goals ──
      if (method === 'GET' && p === '/api/goals') {
        const list = goals.list(url.searchParams.get('all') === '1').map((g) => ({
          ...g,
          key_results: goals.keyResults(g.id),
        }));
        return json(res, 200, { goals: list });
      }
      if (method === 'POST' && p === '/api/goals') {
        const body = await readBody(req);
        if (!body.title) return json(res, 400, { error: 'title is required' });
        const goal = goals.create({
          title: String(body.title),
          why: String(body.why ?? ''),
          deadline: body.deadline ? String(body.deadline) : undefined,
          key_results: Array.isArray(body.key_results) ? body.key_results.map(String) : [],
        });
        return json(res, 201, goal);
      }
      const goalMatch = p.match(/^\/api\/goals\/(\d+)$/);
      if (method === 'PATCH' && goalMatch) {
        const body = await readBody(req);
        const goal = goals.update(Number(goalMatch[1]), {
          title: body.title !== undefined ? String(body.title) : undefined,
          why: body.why !== undefined ? String(body.why) : undefined,
          status: body.status !== undefined ? String(body.status) : undefined,
          deadline: body.deadline !== undefined ? (body.deadline ? String(body.deadline) : null) : undefined,
        });
        return json(res, 200, goal);
      }
      const krAddMatch = p.match(/^\/api\/goals\/(\d+)\/key-results$/);
      if (method === 'POST' && krAddMatch) {
        const body = await readBody(req);
        if (!body.title) return json(res, 400, { error: 'title is required' });
        const kr = goals.addKeyResult(Number(krAddMatch[1]), String(body.title), Number(body.target ?? 1));
        return json(res, 201, kr);
      }
      const krAdvMatch = p.match(/^\/api\/key-results\/(\d+)\/advance$/);
      if (method === 'POST' && krAdvMatch) {
        const body = await readBody(req);
        const kr = goals.advanceKeyResult(Number(krAdvMatch[1]), Number(body.delta ?? 1));
        return json(res, 200, kr);
      }

      // ── routines ──
      if (method === 'POST' && p === '/api/routines/morning') {
        const plan = await routines.morning();
        return json(res, 200, { plan });
      }
      if (method === 'POST' && p === '/api/routines/evening') {
        const review = await routines.evening();
        return json(res, 200, { review });
      }
      if (method === 'POST' && p === '/api/routines/heartbeat') {
        return json(res, 200, { alerts: routines.hourlyHeartbeat() });
      }

      // ── events / audit trail ──
      if (method === 'GET' && p === '/api/events') {
        return json(res, 200, { events: recentEvents(Number(url.searchParams.get('limit') ?? 100)) });
      }
      if (method === 'GET' && p === '/api/events/stream') {
        sseInit(res);
        const onEvent = (evt: unknown) => sseSend(res, 'event', evt);
        bus.on('event', onEvent);
        const ping = setInterval(() => res.write(': ping\n\n'), 25_000);
        req.on('close', () => {
          clearInterval(ping);
          bus.off('event', onEvent);
        });
        return;
      }

      json(res, 404, { error: `no route: ${method} ${p}` });
    } catch (err) {
      log.error(`${method} ${p}:`, err);
      if (!res.headersSent) json(res, 500, { error: err instanceof Error ? err.message : String(err) });
      else res.end();
    }
  });

  function serveStatic(res: http.ServerResponse, file: string): void {
    const filePath = path.join(PUBLIC_DIR, file);
    if (!existsSync(filePath)) {
      json(res, 404, { error: 'not found' });
      return;
    }
    const content = readFileSync(filePath);
    res.writeHead(200, { 'content-type': MIME[path.extname(file)] ?? 'application/octet-stream' });
    res.end(content);
  }

  return server;
}
