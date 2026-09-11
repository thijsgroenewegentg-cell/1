import { test } from 'node:test';
import assert from 'node:assert/strict';
import { writeFileSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { Db } from '../src/store/db.ts';
import { KnowledgeVault } from '../src/memory/vault.ts';
import { GoalTracker } from '../src/goals/goals.ts';
import { buildTools, executeTool, AUTHORITY_LEVELS, type ToolContext } from '../src/agent/tools.ts';
import { tmpDir } from './helpers.ts';

function makeCtx(authority: number): ToolContext {
  const root = tmpDir();
  const db = new Db(path.join(root, 'db.sqlite'));
  return { authority, rootDir: root, vault: new KnowledgeVault(db), goals: new GoalTracker(db) };
}

const tools = buildTools();

test('read-only tools work at authority 0', async () => {
  const ctx = makeCtx(0);
  writeFileSync(path.join(ctx.rootDir, 'hello.txt'), 'hi jarvis');
  const res = await executeTool(tools, 'read_file', { path: 'hello.txt' }, ctx);
  assert.equal(res.ok, true);
  assert.equal(res.output, 'hi jarvis');
});

test('write tools are denied at authority 0', async () => {
  const ctx = makeCtx(0);
  const res = await executeTool(tools, 'write_file', { path: 'x.txt', content: 'nope' }, ctx);
  assert.equal(res.ok, false);
  assert.equal(res.denied, true);
  assert.match(res.output, /DENIED/);
});

test('shell requires authority 4', async () => {
  const ctx3 = makeCtx(3);
  const denied = await executeTool(tools, 'shell', { command: 'echo pwned' }, ctx3);
  assert.equal(denied.denied, true);

  const ctx4 = makeCtx(4);
  const allowed = await executeTool(tools, 'shell', { command: 'echo hello-from-shell' }, ctx4);
  assert.equal(allowed.ok, true);
  assert.match(allowed.output, /hello-from-shell/);
});

test('write_file is sandboxed to the workspace', async () => {
  const ctx = makeCtx(AUTHORITY_LEVELS.SAFE_WRITE);
  const res = await executeTool(tools, 'write_file', { path: 'sub/dir/note.txt', content: 'sandboxed' }, ctx);
  assert.equal(res.ok, true);
  assert.equal(readFileSync(path.join(ctx.rootDir, 'sub/dir/note.txt'), 'utf8'), 'sandboxed');

  const escape = await executeTool(tools, 'write_file', { path: '../outside.txt', content: 'x' }, ctx);
  assert.equal(escape.ok, false);
  assert.match(escape.output, /escapes workspace/);
});

test('memory tools round-trip through the vault', async () => {
  const ctx = makeCtx(1);
  const put = await executeTool(
    tools,
    'memory_remember',
    { title: 'birthday', body: 'User birthday is March 3', tags: ['prefs'] },
    ctx,
  );
  assert.equal(put.ok, true);
  const found = await executeTool(tools, 'memory_search', { query: 'birthday' }, ctx);
  assert.match(found.output, /March 3/);
});

test('unknown tool fails gracefully', async () => {
  const ctx = makeCtx(4);
  const res = await executeTool(tools, 'teleport', {}, ctx);
  assert.equal(res.ok, false);
  assert.match(res.output, /unknown tool/);
});
