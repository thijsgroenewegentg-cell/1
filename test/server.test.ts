import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { createApp } from '../src/app.ts';
import { createServer } from '../src/server/http.ts';
import { startMockOllama, testConfig, tmpDir } from './helpers.ts';

async function boot() {
  const mock = await startMockOllama();
  const home = tmpDir();
  const prevHome = process.env.JARVIS_HOME;
  process.env.JARVIS_HOME = home; // isolate workflows dir from the repo
  mkdirSync(path.join(home, 'workflows'), { recursive: true });
  const cfg = testConfig(home, mock.url);
  const app = createApp(cfg);
  const server = createServer(app);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as { port: number }).port;
  const base = `http://127.0.0.1:${port}`;
  const close = async () => {
    await new Promise((resolve) => server.close(resolve));
    app.stop();
    await mock.close();
    if (prevHome === undefined) delete process.env.JARVIS_HOME;
    else process.env.JARVIS_HOME = prevHome;
  };
  return { mock, app, home, base, close };
}

async function get(base: string, path: string): Promise<{ status: number; json: Record<string, unknown> }> {
  const res = await fetch(`${base}${path}`);
  return { status: res.status, json: (await res.json()) as Record<string, unknown> };
}

async function post(base: string, path: string, body: unknown): Promise<{ status: number; json: Record<string, unknown> }> {
  const res = await fetch(`${base}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return { status: res.status, json: (await res.json()) as Record<string, unknown> };
}

test('serves the dashboard', async () => {
  const { base, close } = await boot();
  try {
    const res = await fetch(`${base}/`);
    const html = await res.text();
    assert.equal(res.status, 200);
    assert.match(html, /J\.A\.R\.V\.I\.S/);
    const css = await fetch(`${base}/style.css`);
    assert.equal(css.status, 200);
  } finally {
    await close();
  }
});

test('health reports ollama reachable', async () => {
  const { base, close } = await boot();
  try {
    const { status, json } = await get(base, '/api/health');
    assert.equal(status, 200);
    assert.equal(json.status, 'ok');
    assert.equal((json.ollama as { reachable: boolean }).reachable, true);
  } finally {
    await close();
  }
});

test('chat end-to-end (non-streaming) persists a conversation', async () => {
  const { mock, base, close } = await boot();
  try {
    mock.enqueue({ content: 'At your service.' });
    const { status, json } = await post(base, '/api/chat', { message: 'jarvis, are you there?', stream: false });
    assert.equal(status, 200);
    assert.equal(json.answer, 'At your service.');
    assert.ok(Number(json.conversation_id) > 0);

    const convs = await get(base, '/api/conversations');
    assert.equal((convs.json.conversations as unknown[]).length, 1);
  } finally {
    await close();
  }
});

test('chat streams tokens over SSE', async () => {
  const { mock, base, close } = await boot();
  try {
    mock.enqueue({ content: 'streaming works fine' });
    const res = await fetch(`${base}/api/chat`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ message: 'stream test', stream: true }),
    });
    assert.equal(res.status, 200);
    assert.match(res.headers.get('content-type') ?? '', /text\/event-stream/);
    const text = await res.text();
    assert.match(text, /event: token/);
    assert.match(text, /event: done/);
    // tokens must reassemble into the full answer
    const deltas = [...text.matchAll(/data: ({"delta":"[^"]*"})/g)].map((m) => JSON.parse(m[1]).delta);
    assert.equal(deltas.join(''), 'streaming works fine');
  } finally {
    await close();
  }
});

test('memories and goals REST endpoints', async () => {
  const { base, close } = await boot();
  try {
    const mem = await post(base, '/api/memories', { title: 'test fact', body: 'the sky is blue', kind: 'note' });
    assert.equal(mem.status, 201);
    const found = await get(base, '/api/memories?q=sky');
    assert.equal((found.json.memories as unknown[]).length, 1);

    const goal = await post(base, '/api/goals', {
      title: 'Test goal',
      deadline: '2026-12-31',
      key_results: ['step one'],
    });
    assert.equal(goal.status, 201);
    const goals = await get(base, '/api/goals');
    const list = goals.json.goals as { key_results: unknown[] }[];
    assert.equal(list.length, 1);
    assert.equal(list[0].key_results.length, 1);
  } finally {
    await close();
  }
});

test('authority can be changed at runtime', async () => {
  const { app, base, close } = await boot();
  try {
    const res = await fetch(`${base}/api/authority`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ level: 0 }),
    });
    assert.equal(res.status, 200);
    assert.equal(app.cfg.authority.level, 0);
    const bad = await fetch(`${base}/api/authority`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ level: 9 }),
    });
    assert.equal(bad.status, 400);
  } finally {
    await close();
  }
});

test('event stream replays recent events', async () => {
  const { base, close } = await boot();
  try {
    const { json } = await get(base, '/api/events');
    assert.ok(Array.isArray(json.events));
  } finally {
    await close();
  }
});

test('workflow endpoints: list, reload, webhook, runs', async () => {
  const { home, app, base, close } = await boot();
  try {
    writeFileSync(
      path.join(home, 'workflows/hook.yaml'),
      [
        'id: hook',
        'trigger:',
        '  type: webhook',
        'steps:',
        '  - action: memory_remember',
        '    with: { title: "from hook", body: "{{trigger.body.text}}" }',
      ].join('\n'),
    );
    app.workflows.start();

    const list = await get(base, '/api/workflows');
    assert.equal((list.json.workflows as unknown[]).length, 1);

    const hook = await post(base, '/api/hooks/hook', { text: 'remember the milk' });
    assert.equal(hook.status, 200);
    assert.equal(hook.json.ok, true);

    const mems = await get(base, '/api/memories?q=milk');
    assert.equal((mems.json.memories as unknown[]).length, 1);

    const runs = await get(base, '/api/workflows/runs');
    assert.equal((runs.json.runs as unknown[]).length, 1);

    const missing = await post(base, '/api/hooks/ghost', {});
    assert.equal(missing.status, 404);
  } finally {
    await close();
  }
});

test('approval endpoints', async () => {
  const { base, close } = await boot();
  try {
    const list = await get(base, '/api/approvals');
    assert.deepEqual(list.json.pending, []);
    const bogus = await post(base, '/api/approvals/999', { decision: 'approved' });
    assert.equal(bogus.status, 404);
    const bad = await post(base, '/api/approvals/1', { decision: 'maybe' });
    assert.equal(bad.status, 400);
  } finally {
    await close();
  }
});

test('voice endpoints report providers and degrade gracefully', async () => {
  const { base, close } = await boot();
  try {
    const cfg = await get(base, '/api/voice/config');
    assert.equal(cfg.status, 200);
    assert.equal((cfg.json.tts as { provider: string }).provider, 'browser');
    assert.equal((cfg.json.stt as { provider: string }).provider, 'browser');

    const tts = await post(base, '/api/tts', { text: 'hello' });
    assert.equal(tts.status, 503); // piper not configured
    const stt = await fetch(`${base}/api/stt`, { method: 'POST', body: Buffer.alloc(100) });
    assert.equal(stt.status, 503); // whisper not configured
  } finally {
    await close();
  }
});

test('conversation archive summarizes into the vault', async () => {
  const { mock, base, close } = await boot();
  try {
    mock.enqueue({ content: 'First reply' }, { content: 'A short summary of the chat.' });
    const chat = await post(base, '/api/chat', { message: 'hello jarvis', stream: false });
    const convId = Number(chat.json.conversation_id);
    const arch = await post(base, `/api/conversations/${convId}/archive`, {});
    assert.equal(arch.status, 200);
    assert.ok(Number(arch.json.memory_id) > 0);
    const mems = await get(base, '/api/memories?q=summary');
    assert.ok((mems.json.memories as unknown[]).length >= 1);
  } finally {
    await close();
  }
});

test('memory reindex endpoint', async () => {
  const { app, base, close } = await boot();
  try {
    // simulate a memory that predates the embedder (no vector yet)
    app.db.db
      .prepare(`INSERT INTO memories (kind, title, body) VALUES ('note', 'pre-embedding fact', 'old but gold')`)
      .run();
    const re = await post(base, '/api/memories/reindex', {});
    assert.equal(re.status, 200);
    assert.ok(Number(re.json.embedded) >= 1); // embed model present in the mock
  } finally {
    await close();
  }
});
