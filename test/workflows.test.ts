import { test } from 'node:test';
import assert from 'node:assert/strict';
import { writeFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { Db } from '../src/store/db.ts';
import { OllamaClient } from '../src/llm/ollama.ts';
import { LlmProvider } from '../src/llm/provider.ts';
import { KnowledgeVault } from '../src/memory/vault.ts';
import { GoalTracker } from '../src/goals/goals.ts';
import { Orchestrator } from '../src/agent/orchestrator.ts';
import { CronScheduler } from '../src/cron.ts';
import { WorkflowEngine } from '../src/workflows/engine.ts';
import { renderTemplate, renderArgs, loadWorkflows } from '../src/workflows/loader.ts';
import { startMockOllama, testConfig, tmpDir } from './helpers.ts';

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

test('renderTemplate resolves dotted paths and tolerates misses', () => {
  const ctx = { trigger: { filename: 'note.md' }, steps: [{ output: 'hello' }] };
  assert.equal(renderTemplate('File: {{trigger.filename}}', ctx), 'File: note.md');
  assert.equal(renderTemplate('Out: {{steps.0.output}}!', ctx), 'Out: hello!');
  assert.equal(renderTemplate('Nope: {{trigger.missing}}', ctx), 'Nope: ');
});

test('renderArgs renders strings and string arrays', () => {
  const out = renderArgs(
    { title: 'T: {{trigger.x}}', tags: ['a', '{{trigger.x}}'], level: 3 },
    { trigger: { x: 'yes' } },
  );
  assert.deepEqual(out, { title: 'T: yes', tags: ['a', 'yes'], level: 3 });
});

test('loader validates trigger requirements', () => {
  const dir = tmpDir();
  writeFileSync(path.join(dir, 'bad.yaml'), 'trigger:\n  type: file\nsteps:\n  - action: notify\n');
  writeFileSync(
    path.join(dir, 'good.yaml'),
    'trigger:\n  type: webhook\nsteps:\n  - action: notify\n    with: { message: hi }\n',
  );
  const list = loadWorkflows(dir);
  assert.equal(list.length, 1);
  assert.equal(list[0].id, 'good');
});

function buildEngine(home: string, ollamaUrl: string) {
  // tool sandboxing resolves against JARVIS_HOME — point it at the test home
  process.env.JARVIS_HOME = home;
  const cfg = testConfig(home, ollamaUrl);
  const db = new Db(path.join(cfg.daemon.data_dir, 'jarvis.db'));
  const ollama = new OllamaClient(ollamaUrl);
  const llm = new LlmProvider(ollama, cfg);
  const vault = new KnowledgeVault(db);
  const goals = new GoalTracker(db);
  const orchestrator = new Orchestrator({ cfg, db, llm, vault, goals });
  const cron = new CronScheduler();
  const engine = new WorkflowEngine({ cfg, db, llm, orchestrator, cron, home });
  return { db, vault, engine, cron };
}

test('webhook workflow stores a memory end-to-end', async () => {
  const mock = await startMockOllama();
  const home = tmpDir();
  try {
    mkdirSync(path.join(home, 'workflows'));
    writeFileSync(
      path.join(home, 'workflows/hook.yaml'),
      [
        'id: hook',
        'trigger:',
        '  type: webhook',
        'steps:',
        '  - action: memory_remember',
        '    with:',
        '      title: "hook note"',
        '      body: "{{trigger.body.text}}"',
        '  - action: notify',
        '    with: { message: "stored {{trigger.body.text}}" }',
      ].join('\n'),
    );
    const { db, vault, engine } = buildEngine(home, mock.url);
    engine.start();
    const result = await engine.webhook('hook', { text: 'parking P2 spot 41' });
    assert.equal(result.ok, true);
    const hits = await vault.search('parking');
    assert.equal(hits.length, 1);
    assert.match(hits[0].body, /P2 spot 41/);
    const runs = engine.runs();
    assert.equal(runs[0].status, 'done');
    engine.stop();
    db.close();
  } finally {
    await mock.close();
  }
});

test('file trigger runs the workflow with an LLM step', async () => {
  const mock = await startMockOllama();
  const home = tmpDir();
  try {
    mkdirSync(path.join(home, 'workflows'));
    mkdirSync(path.join(home, 'inbox'));
    writeFileSync(
      path.join(home, 'workflows/inbox.yaml'),
      [
        'id: inbox',
        'trigger:',
        '  type: file',
        '  path: inbox',
        'steps:',
        '  - action: read_file',
        '    with: { path: "{{trigger.relpath}}" }',
        '  - action: llm',
        '    with: { tier: fast, prompt: "Summarize: {{steps.0.output}}" }',
        '  - action: memory_remember',
        '    with: { title: "inbox: {{trigger.filename}}", body: "{{steps.1.output}}" }',
      ].join('\n'),
    );
    const { db, vault, engine } = buildEngine(home, mock.url);
    try {
      engine.start();
      mock.enqueue({ content: 'A two-word summary.' });

      writeFileSync(path.join(home, 'inbox/note.txt'), 'The eagle has landed at dawn.');
      // debounce is 500ms + processing
      for (let i = 0; i < 40 && engine.runs().length === 0; i += 1) await sleep(100);
      await sleep(200); // let steps finish

      const runs = engine.runs();
      assert.equal(runs.length, 1, `expected 1 run, got ${runs.length}`);
      assert.equal(runs[0].status, 'done', runs[0].log);
      // the stored memory holds the LLM step's output, keyed by filename
      const hits = await vault.search('summary');
      assert.equal(hits.length, 1);
      assert.match(hits[0].title, /inbox: note\.txt/);
      assert.match(hits[0].body, /two-word summary/);
    } finally {
      engine.stop(); // must always run — leaked watchers keep the event loop alive
      db.close();
    }
  } finally {
    await mock.close();
  }
});

test('failed step marks the run failed and stops', async () => {
  const mock = await startMockOllama();
  const home = tmpDir();
  try {
    mkdirSync(path.join(home, 'workflows'));
    writeFileSync(
      path.join(home, 'workflows/broken.yaml'),
      [
        'id: broken',
        'trigger:',
        '  type: webhook',
        'steps:',
        '  - action: read_file',
        '    with: { path: "does-not-exist.txt" }',
        '  - action: notify',
        '    with: { message: "never reached" }',
      ].join('\n'),
    );
    const { db, engine } = buildEngine(home, mock.url);
    engine.start();
    const result = await engine.webhook('broken', {});
    assert.equal(result.ok, false);
    const runs = engine.runs();
    assert.equal(runs[0].status, 'failed');
    assert.match(runs[0].log, /read_file/);
    engine.stop();
    db.close();
  } finally {
    await mock.close();
  }
});

test('unknown webhook id is rejected', async () => {
  const mock = await startMockOllama();
  const home = tmpDir();
  try {
    const { db, engine } = buildEngine(home, mock.url);
    engine.start();
    const result = await engine.webhook('ghost', {});
    assert.equal(result.ok, false);
    assert.match(result.error ?? '', /no webhook workflow/);
    engine.stop();
    db.close();
  } finally {
    await mock.close();
  }
});
