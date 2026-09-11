import http from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { App } from '../app.ts';
import { bus, recentEvents, publish } from '../events.ts';
import { voiceStatus, piperTts, whisperStt } from './voice.ts';
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

/** Raw binary body reader (audio uploads). */
async function readRawBody(req: http.IncomingMessage, maxBytes: number): Promise<Buffer> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > maxBytes) throw new Error('body too large');
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks);
}

export function createServer(app: App): http.Server {
  const { cfg, ollama, vault, goals, orchestrator, routines, approvals, workflows } = app;

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
          embed_model: cfg.ollama.embed_model,
          authority: cfg.authority.level,
          authority_mode: cfg.authority.mode,
          pending_approvals: approvals.pending().length,
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

      // ── approvals ──
      if (method === 'GET' && p === '/api/approvals') {
        return json(res, 200, { pending: approvals.pending(), recent: approvals.recent(20) });
      }
      const approvalMatch = p.match(/^\/api\/approvals\/(\d+)$/);
      if (method === 'POST' && approvalMatch) {
        const body = await readBody(req);
        const decision = body.decision === 'approved' || body.decision === 'denied' ? body.decision : null;
        if (!decision) return json(res, 400, { error: 'decision must be "approved" or "denied"' });
        const resolved = approvals.resolve(Number(approvalMatch[1]), decision);
        return json(res, resolved ? 200 : 404, resolved ? { id: Number(approvalMatch[1]), decision } : { error: 'approval not found or already resolved' });
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
        const items = q ? await vault.search(q, 30) : vault.list(50);
        return json(res, 200, { memories: items });
      }
      if (method === 'POST' && p === '/api/memories/reindex') {
        const body = await readBody(req);
        const count = await vault.backfill(body.all === true);
        return json(res, 200, { embedded: count });
      }
      if (method === 'POST' && p === '/api/memories') {
        const body = await readBody(req);
        if (!body.title) return json(res, 400, { error: 'title is required' });
        const mem = await vault.remember({
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

      // ── workflows ──
      if (method === 'GET' && p === '/api/workflows') {
        return json(res, 200, {
          dir: workflows.dir,
          workflows: workflows.list().map((w) => ({
            id: w.id,
            name: w.name,
            enabled: w.enabled,
            trigger: w.trigger,
            steps: w.steps.map((s) => s.action),
          })),
        });
      }
      if (method === 'POST' && p === '/api/workflows/reload') {
        const list = workflows.start();
        return json(res, 200, { loaded: list.length });
      }
      if (method === 'GET' && p === '/api/workflows/runs') {
        return json(res, 200, { runs: workflows.runs(Number(url.searchParams.get('limit') ?? 30)) });
      }
      const wfRunMatch = p.match(/^\/api\/workflows\/([\w-]+)\/run$/);
      if (method === 'POST' && wfRunMatch) {
        const wf = workflows.get(wfRunMatch[1]);
        if (!wf) return json(res, 404, { error: `workflow "${wfRunMatch[1]}" not found` });
        const run = await workflows.run(wf, { type: 'manual' });
        return json(res, 200, run);
      }
      const hookMatch = p.match(/^\/api\/hooks\/([\w-]+)$/);
      if (method === 'POST' && hookMatch) {
        const body = await readBody(req).catch(() => ({}));
        const result = await workflows.webhook(hookMatch[1], body);
        return json(res, result.ok ? 200 : 404, result);
      }

      // ── voice ──
      if (method === 'GET' && p === '/api/voice/config') {
        return json(res, 200, voiceStatus(cfg));
      }
      if (method === 'POST' && p === '/api/tts') {
        const body = await readBody(req);
        const text = String(body.text ?? '').slice(0, 2000);
        if (!text) return json(res, 400, { error: 'text is required' });
        try {
          const wav = await piperTts(cfg, text);
          res.writeHead(200, { 'content-type': 'audio/wav', 'content-length': wav.length });
          res.end(wav);
        } catch (err) {
          json(res, 503, { error: err instanceof Error ? err.message : String(err) });
        }
        return;
      }
      if (method === 'POST' && p === '/api/stt') {
        const wav = await readRawBody(req, 10_000_000);
        if (wav.length < 44) return json(res, 400, { error: 'empty audio' });
        try {
          const text = await whisperStt(cfg, wav);
          json(res, 200, { text });
        } catch (err) {
          json(res, 503, { error: err instanceof Error ? err.message : String(err) });
        }
        return;
      }

      // ── conversation archive ──
      const archiveMatch = p.match(/^\/api\/conversations\/(\d+)\/archive$/);
      if (method === 'POST' && archiveMatch) {
        const id = Number(archiveMatch[1]);
        const messages = app.db.db
          .prepare(`SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id`)
          .all(id) as { role: string; content: string }[];
        if (messages.length === 0) return json(res, 404, { error: 'conversation not found' });
        const convo = messages
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .map((m) => `${m.role}: ${m.content}`)
          .join('\n')
          .slice(0, 6000);
        const title = (
          app.db.db.prepare(`SELECT title FROM conversations WHERE id = ?`).get(id) as { title?: string } | undefined
        )?.title;
        try {
          const res2 = await app.llm.complete(
            'Summarize this conversation in 2-4 factual sentences, keeping any durable facts, decisions or commitments.',
            [{ role: 'user', content: convo }],
            { tier: 'fast', temperature: 0.3 },
          );
          const mem = await vault.remember({
            kind: 'observation',
            title: `Conversation archived: ${title ?? `#${id}`}`,
            body: res2.content.trim() || convo.slice(0, 400),
            tags: ['conversation', `conv-${id}`],
            source: 'archive',
          });
          return json(res, 200, { memory_id: mem.id, summary: mem.body.slice(0, 300) });
        } catch (err) {
          return json(res, 502, { error: err instanceof Error ? err.message : String(err) });
        }
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
