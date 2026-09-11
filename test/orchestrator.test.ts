import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { Db } from '../src/store/db.ts';
import { KnowledgeVault } from '../src/memory/vault.ts';
import { GoalTracker } from '../src/goals/goals.ts';
import { Orchestrator } from '../src/agent/orchestrator.ts';
import { OllamaClient } from '../src/llm/ollama.ts';
import { LlmProvider } from '../src/llm/provider.ts';
import { recentEvents } from '../src/events.ts';
import { startMockOllama, testConfig, tmpDir } from './helpers.ts';

function buildApp(ollamaUrl: string) {
  const home = tmpDir();
  const cfg = testConfig(home, ollamaUrl);
  const db = new Db(path.join(cfg.daemon.data_dir, 'jarvis.db'));
  const ollama = new OllamaClient(ollamaUrl);
  const llm = new LlmProvider(ollama, cfg);
  const vault = new KnowledgeVault(db);
  const goals = new GoalTracker(db);
  const orchestrator = new Orchestrator({ cfg, db, llm, vault, goals });
  return { cfg, db, vault, goals, orchestrator };
}

test('plain answer with no tool calls', async () => {
  const mock = await startMockOllama();
  try {
    const { orchestrator } = buildApp(mock.url);
    mock.enqueue({ content: 'Hello! I am fully local.' });
    const result = await orchestrator.run({ userInput: 'hello' });
    assert.equal(result.answer, 'Hello! I am fully local.');
    assert.equal(result.turns, 1);
  } finally {
    await mock.close();
  }
});

test('tool loop: model calls memory_remember then answers', async () => {
  const mock = await startMockOllama();
  try {
    const { orchestrator, vault } = buildApp(mock.url);
    mock.enqueue(
      {
        content: '',
        tool_calls: [
          {
            function: {
              name: 'memory_remember',
              arguments: { title: 'favorite tea', body: 'Earl Grey, hot', kind: 'note' },
            },
          },
        ],
      },
      { content: 'Noted — Earl Grey, hot. I will remember that.' },
    );

    const result = await orchestrator.run({ userInput: 'Remember: I like Earl Grey tea, hot.' });
    assert.match(result.answer, /Earl Grey/);
    assert.equal(result.turns, 2);
    const hits = await vault.search('tea');
    assert.equal(hits.length, 1);
    assert.match(hits[0].body, /Earl Grey/);

    // The second model call must include the tool result in its context.
    const secondCall = mock.requests[1].messages;
    const toolMsg = secondCall.find((m: { role: string }) => m.role === 'tool');
    assert.ok(toolMsg, 'tool result passed back to the model');
    assert.match(String(toolMsg.content), /remembered/);
  } finally {
    await mock.close();
  }
});

test('delegation runs a specialist and returns its answer', async () => {
  const mock = await startMockOllama();
  try {
    const { orchestrator } = buildApp(mock.url);
    mock.enqueue(
      {
        content: '',
        tool_calls: [
          { function: { name: 'delegate', arguments: { role: 'writer', task: 'Write a haiku about servers' } } },
        ],
      },
      { content: 'Fans hum in the dark / small lights blink in orderly rows / the daemon keeps watch' },
      { content: 'Here is your haiku:\nFans hum in the dark…' },
    );

    const result = await orchestrator.run({ userInput: 'Write me a haiku about home servers' });
    assert.match(result.answer, /haiku/);
    // request #2 was the specialist call: its system prompt must be the writer's,
    // and specialists must never receive the delegate tool.
    const specialistCall = mock.requests[1];
    assert.match(JSON.stringify(specialistCall.messages[0]), /writing specialist/);
    const toolNames = (specialistCall.tools ?? []).map((t: { function: { name: string } }) => t.function.name);
    assert.ok(!toolNames.includes('delegate'), 'specialists cannot delegate further');
  } finally {
    await mock.close();
  }
});

test('authority denial is audited and reported back to the model', async () => {
  const mock = await startMockOllama();
  try {
    const { orchestrator, cfg } = buildApp(mock.url);
    cfg.authority.level = 1; // no shell, no network
    mock.enqueue(
      { content: '', tool_calls: [{ function: { name: 'shell', arguments: { command: 'rm -rf /' } } }] },
      { content: 'I am not allowed to run shell commands at this authority level.' },
    );
    const before = recentEvents(1000).length;
    const result = await orchestrator.run({ userInput: 'delete everything' });
    assert.match(result.answer, /not allowed/);
    const after = recentEvents(1000);
    const denied = after.slice(before).find((e) => e.type === 'authority:denied');
    assert.ok(denied, 'denial audited on the event bus');
    const secondCall = mock.requests[1].messages;
    const toolMsg = secondCall.find((m: { role: string }) => m.role === 'tool');
    assert.match(String(toolMsg.content), /DENIED/);
  } finally {
    await mock.close();
  }
});

test('tool-call budget is enforced', async () => {
  const mock = await startMockOllama();
  try {
    const { orchestrator, cfg } = buildApp(mock.url);
    cfg.agent.max_turns = 2;
    for (let i = 0; i < 10; i++) {
      mock.enqueue({ content: '', tool_calls: [{ function: { name: 'notify', arguments: { message: 'again' } } }] });
    }
    const result = await orchestrator.run({ userInput: 'loop forever' });
    assert.equal(result.turns, 2);
    assert.match(result.answer, /budget/);
  } finally {
    await mock.close();
  }
});

test('conversations persist with history', async () => {
  const mock = await startMockOllama();
  try {
    const { orchestrator, db } = buildApp(mock.url);
    mock.enqueue({ content: 'First reply' }, { content: 'Second reply, I remember the first.' });
    const r1 = await orchestrator.run({ userInput: 'message one' });
    const r2 = await orchestrator.run({ conversationId: r1.conversationId, userInput: 'message two' });
    assert.equal(r2.conversationId, r1.conversationId);
    const msgs = db.db.prepare(`SELECT role FROM messages WHERE conversation_id = ? ORDER BY id`).all(r1.conversationId);
    assert.deepEqual(
      msgs.map((m) => m.role),
      ['user', 'assistant', 'user', 'assistant'],
    );
    // second model call must have carried the earlier turn along
    assert.ok(mock.requests[1].messages.some((m: { content: string }) => m.content === 'First reply'));
  } finally {
    await mock.close();
  }
});
