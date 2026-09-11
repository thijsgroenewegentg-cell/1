import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { Db } from '../src/store/db.ts';
import { KnowledgeVault } from '../src/memory/vault.ts';
import { GoalTracker } from '../src/goals/goals.ts';
import { Orchestrator } from '../src/agent/orchestrator.ts';
import { ApprovalManager } from '../src/agent/approvals.ts';
import { OllamaClient } from '../src/llm/ollama.ts';
import { LlmProvider } from '../src/llm/provider.ts';
import { bus } from '../src/events.ts';
import { startMockOllama, testConfig, tmpDir } from './helpers.ts';

function buildApp(ollamaUrl: string) {
  const home = tmpDir();
  const cfg = testConfig(home, ollamaUrl);
  cfg.authority.level = 1; // below shell (4)
  cfg.authority.mode = 'ask';
  cfg.authority.ask_timeout_ms = 5000;
  const db = new Db(path.join(cfg.daemon.data_dir, 'jarvis.db'));
  const ollama = new OllamaClient(ollamaUrl);
  const llm = new LlmProvider(ollama, cfg);
  const vault = new KnowledgeVault(db);
  const goals = new GoalTracker(db);
  const approvals = new ApprovalManager(db, cfg.authority.ask_timeout_ms);
  const orchestrator = new Orchestrator({ cfg, db, llm, vault, goals, approvals });
  return { cfg, approvals, orchestrator };
}

function resolveNextApproval(manager: ApprovalManager, decision: 'approved' | 'denied') {
  return new Promise<void>((resolvePromise) => {
    bus.once('approval:requested', (payload: { id: number }) => {
      assert.equal(manager.resolve(payload.id, decision), true);
      resolvePromise();
    });
  });
}

test('ask mode: approved shell command executes', async () => {
  const mock = await startMockOllama();
  try {
    const { approvals, orchestrator } = buildApp(mock.url);
    mock.enqueue(
      { content: '', tool_calls: [{ function: { name: 'shell', arguments: { command: 'echo approved-run' } } }] },
      { content: 'Done — the command ran.' },
    );
    const approving = resolveNextApproval(approvals, 'approved');
    const result = await orchestrator.run({ userInput: 'please run that echo' });
    await approving;
    assert.match(result.answer, /Done/);
    // the model must have seen the real tool output
    const secondCall = mock.requests[1].messages;
    const toolMsg = secondCall.find((m: { role: string }) => m.role === 'tool');
    assert.match(String(toolMsg.content), /approved-run/);
    assert.equal(approvals.recent()[0].status, 'approved');
  } finally {
    await mock.close();
  }
});

test('ask mode: denied request is reported back to the model', async () => {
  const mock = await startMockOllama();
  try {
    const { approvals, orchestrator } = buildApp(mock.url);
    mock.enqueue(
      { content: '', tool_calls: [{ function: { name: 'shell', arguments: { command: 'echo never' } } }] },
      { content: 'Understood — I will not run it.' },
    );
    const denying = resolveNextApproval(approvals, 'denied');
    const result = await orchestrator.run({ userInput: 'run something risky' });
    await denying;
    assert.match(result.answer, /will not/);
    const secondCall = mock.requests[1].messages;
    const toolMsg = secondCall.find((m: { role: string }) => m.role === 'tool');
    assert.match(String(toolMsg.content), /declined/);
    assert.equal(approvals.recent()[0].status, 'denied');
  } finally {
    await mock.close();
  }
});

test('gate mode still refuses outright (no pause)', async () => {
  const mock = await startMockOllama();
  try {
    const { cfg, approvals, orchestrator } = buildApp(mock.url);
    cfg.authority.mode = 'gate';
    mock.enqueue(
      { content: '', tool_calls: [{ function: { name: 'shell', arguments: { command: 'echo nope' } } }] },
      { content: 'I cannot do that at this authority level.' },
    );
    const result = await orchestrator.run({ userInput: 'try the shell' });
    assert.match(result.answer, /cannot/);
    assert.equal(approvals.pending().length, 0, 'gate mode must never create approvals');
    const secondCall = mock.requests[1].messages;
    const toolMsg = secondCall.find((m: { role: string }) => m.role === 'tool');
    assert.match(String(toolMsg.content), /DENIED/);
  } finally {
    await mock.close();
  }
});
