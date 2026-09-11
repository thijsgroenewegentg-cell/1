import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { Db } from '../src/store/db.ts';
import { ApprovalManager } from '../src/agent/approvals.ts';
import { tmpDir } from './helpers.ts';

function makeManager(timeoutMs = 200) {
  const db = new Db(path.join(tmpDir(), 'test.db'));
  return new ApprovalManager(db, timeoutMs);
}

test('approve path resolves the waiting request', async () => {
  const mgr = makeManager();
  const pending = mgr.request({ tool: 'shell', args: { command: 'echo hi' }, reason: 'needs level 4' });
  // resolve shortly after, as the dashboard would
  setTimeout(() => {
    const list = mgr.pending();
    assert.equal(list.length, 1);
    assert.equal(mgr.resolve(list[0].id, 'approved'), true);
  }, 20);
  assert.equal(await pending, 'approved');
  assert.equal(mgr.pending().length, 0);
  assert.equal(mgr.recent()[0].status, 'approved');
});

test('deny path resolves as denied', async () => {
  const mgr = makeManager();
  const pending = mgr.request({ tool: 'shell', args: {}, reason: 'risky' });
  setTimeout(() => mgr.resolve(mgr.pending()[0].id, 'denied'), 20);
  assert.equal(await pending, 'denied');
});

test('unanswered requests time out', async () => {
  const mgr = makeManager(30);
  const decision = await mgr.request({ tool: 'shell', args: {}, reason: 'nobody home' });
  assert.equal(decision, 'timeout');
  assert.equal(mgr.recent()[0].status, 'timeout');
});

test('resolving twice or unknown ids fails cleanly', async () => {
  const mgr = makeManager();
  const pending = mgr.request({ tool: 'shell', args: {}, reason: 'x' });
  setTimeout(() => {
    const id = mgr.pending()[0].id;
    assert.equal(mgr.resolve(id, 'approved'), true);
    assert.equal(mgr.resolve(id, 'denied'), false); // already resolved
    assert.equal(mgr.resolve(9999, 'approved'), false); // unknown
  }, 20);
  assert.equal(await pending, 'approved');
});
