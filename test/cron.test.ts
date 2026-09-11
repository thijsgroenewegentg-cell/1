import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseCron, cronMatches } from '../src/cron.ts';

test('matches specific minute/hour', () => {
  const c = parseCron('37 7 * * *');
  assert.ok(cronMatches(c, new Date(2026, 8, 11, 7, 37)));
  assert.ok(!cronMatches(c, new Date(2026, 8, 11, 7, 38)));
  assert.ok(!cronMatches(c, new Date(2026, 8, 11, 8, 37)));
});

test('supports steps and ranges', () => {
  const c = parseCron('*/15 9-17 * * *');
  assert.ok(cronMatches(c, new Date(2026, 8, 11, 9, 0)));
  assert.ok(cronMatches(c, new Date(2026, 8, 11, 17, 45)));
  assert.ok(!cronMatches(c, new Date(2026, 8, 11, 9, 7)));
  assert.ok(!cronMatches(c, new Date(2026, 8, 11, 18, 0)));
});

test('supports lists and day-of-week', () => {
  const c = parseCron('0 8 * * 1,3,5');
  const monday = new Date(2026, 8, 7, 8, 0); // Sep 7 2026 is a Monday
  assert.equal(monday.getDay(), 1);
  assert.ok(cronMatches(c, monday));
  assert.ok(!cronMatches(c, new Date(2026, 8, 8, 8, 0))); // Tuesday
});

test('rejects bad expressions', () => {
  assert.throws(() => parseCron('* * *'));
  assert.throws(() => parseCron('99 * * * *'));
  assert.throws(() => parseCron('* 25 * * *'));
});
