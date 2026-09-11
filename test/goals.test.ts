import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { Db } from '../src/store/db.ts';
import { GoalTracker } from '../src/goals/goals.ts';
import { tmpDir } from './helpers.ts';

function makeGoals() {
  return new GoalTracker(new Db(path.join(tmpDir(), 'test.db')));
}

function isoDaysFromNow(days: number): string {
  return new Date(Date.now() + days * 86_400_000).toISOString();
}

test('create goal with key results', () => {
  const goals = makeGoals();
  const goal = goals.create({ title: 'Ship the MVP', key_results: ['Write tests', 'Cut release'] });
  assert.equal(goal.status, 'open');
  const krs = goals.keyResults(goal.id);
  assert.equal(krs.length, 2);
  assert.equal(krs[0].target, 1);
});

test('status updates', () => {
  const goals = makeGoals();
  const goal = goals.create({ title: 'Temp' });
  goals.update(goal.id, { status: 'done' });
  assert.equal(goals.get(goal.id).status, 'done');
  assert.equal(goals.list().length, 0); // done goals excluded from open list
  assert.equal(goals.list(true).length, 1);
});

test('key result advancement auto-completes at target', () => {
  const goals = makeGoals();
  const goal = goals.create({ title: 'G' });
  const kr = goals.addKeyResult(goal.id, 'Do 3 things', 3);
  goals.advanceKeyResult(kr.id, 2);
  assert.equal(goals.keyResults(goal.id)[0].status, 'open');
  goals.advanceKeyResult(kr.id, 1);
  const updated = goals.keyResults(goal.id)[0];
  assert.equal(updated.status, 'done');
  assert.equal(updated.current, 3);
});

test('heartbeat flags near and overdue deadlines', () => {
  const goals = makeGoals();
  goals.create({ title: 'Due soon', deadline: isoDaysFromNow(2) });
  goals.create({ title: 'Overdue', deadline: isoDaysFromNow(-1) });
  goals.create({ title: 'Far away', deadline: isoDaysFromNow(30) });
  goals.create({ title: 'No deadline' });
  const alerts = goals.heartbeat();
  assert.equal(alerts.length, 2);
  const titles = alerts.map((a) => a.goal.title).sort();
  assert.deepEqual(titles, ['Due soon', 'Overdue']);
});
