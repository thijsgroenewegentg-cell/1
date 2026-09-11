import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { Db } from '../src/store/db.ts';
import { KnowledgeVault } from '../src/memory/vault.ts';
import { tmpDir } from './helpers.ts';

function makeVault() {
  return new KnowledgeVault(new Db(path.join(tmpDir(), 'test.db')));
}

test('remember and retrieve', () => {
  const vault = makeVault();
  const mem = vault.remember({ title: 'User prefers dark mode', body: 'Everywhere, always.', tags: ['prefs'] });
  assert.ok(mem.id > 0);
  assert.equal(vault.get(mem.id).title, 'User prefers dark mode');
  assert.equal(vault.list().length, 1);
});

test('search ranks title matches higher', () => {
  const vault = makeVault();
  vault.remember({ title: 'Coffee order', body: 'flat white, oat milk' });
  vault.remember({ title: 'Notes', body: 'user mentioned coffee once in passing' });
  const hits = vault.search('coffee');
  assert.equal(hits[0].title, 'Coffee order');
});

test('search with empty query returns recent list', () => {
  const vault = makeVault();
  vault.remember({ title: 'A' });
  vault.remember({ title: 'B' });
  assert.equal(vault.search('').length, 2);
});

test('contextFor renders a prompt block', () => {
  const vault = makeVault();
  vault.remember({ title: 'Server IP', body: '10.0.0.42', tags: ['infra'] });
  const ctx = vault.contextFor('server');
  assert.match(ctx, /Server IP/);
});

test('delete removes the memory', () => {
  const vault = makeVault();
  const mem = vault.remember({ title: 'temp' });
  vault.delete(mem.id);
  assert.equal(vault.list().length, 0);
});
