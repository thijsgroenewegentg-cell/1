import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createApp } from '../src/app.ts';
import { createServer } from '../src/server/http.ts';
import { startMockOllama, testConfig, tmpDir } from './helpers.ts';

async function boot() {
  const mock = await startMockOllama();
  const cfg = testConfig(tmpDir(), mock.url);
  const app = createApp(cfg);
  const server = createServer(app);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as { port: number }).port;
  const base = `http://127.0.0.1:${port}`;
  const close = async () => {
    await new Promise((resolve) => server.close(resolve));
    app.stop();
    await mock.close();
  };
  return { mock, app, base, close };
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
