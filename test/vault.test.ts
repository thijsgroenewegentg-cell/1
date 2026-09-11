import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { Db } from '../src/store/db.ts';
import { KnowledgeVault } from '../src/memory/vault.ts';
import { tmpDir, fakeEmbedder } from './helpers.ts';

function makeVault(withEmbedder = false) {
  const db = new Db(path.join(tmpDir(), 'test.db'));
  const vault = new KnowledgeVault(db);
  if (withEmbedder) vault.setEmbedder(fakeEmbedder() as never);
  return vault;
}

test('remember and retrieve (keyword mode)', async () => {
  const vault = makeVault();
  const mem = await vault.remember({ title: 'User prefers dark mode', body: 'Everywhere, always.', tags: ['prefs'] });
  assert.ok(mem.id > 0);
  assert.equal(vault.get(mem.id).title, 'User prefers dark mode');
  assert.equal(vault.list().length, 1);
});

test('search ranks title matches higher', async () => {
  const vault = makeVault();
  await vault.remember({ title: 'Coffee order', body: 'flat white, oat milk' });
  await vault.remember({ title: 'Notes', body: 'user mentioned coffee once in passing' });
  const hits = await vault.search('coffee');
  assert.equal(hits[0].title, 'Coffee order');
});

test('semantic search finds memories with ZERO token overlap', async () => {
  const vault = makeVault(true);
  await vault.remember({ title: 'Fiets repair shop', body: 'Coolsingel 12, asks for Mevrouw Jansen' });
  await vault.remember({ title: 'Coffee order', body: 'flat white with oat milk' });
  // "two-wheeler" shares no tokens with "fiets repair shop" — embeddings bridge it
  const hits = await vault.search('where do I bring my two-wheeler?');
  assert.ok(hits.length >= 1);
  assert.equal(hits[0].title, 'Fiets repair shop');
});

test('keyword search still works with the embedder attached', async () => {
  const vault = makeVault(true);
  await vault.remember({ title: 'Parking spot', body: 'garage P2, spot 41' });
  const hits = await vault.search('parking');
  assert.equal(hits[0].title, 'Parking spot');
});

test('search with empty query returns recent list', async () => {
  const vault = makeVault();
  await vault.remember({ title: 'A' });
  await vault.remember({ title: 'B' });
  assert.equal((await vault.search('')).length, 2);
});

test('backfill embeds rows that lack vectors', async () => {
  const db = new Db(path.join(tmpDir(), 'test.db'));
  const vault = new KnowledgeVault(db); // no embedder at first
  await vault.remember({ title: 'old memory', body: 'created before embeddings existed' });
  vault.setEmbedder(fakeEmbedder() as never);
  const count = await vault.backfill();
  assert.equal(count, 1);
  // second pass finds nothing left to do
  assert.equal(await vault.backfill(), 0);
});

test('contextFor renders a prompt block', async () => {
  const vault = makeVault();
  await vault.remember({ title: 'Server IP', body: '10.0.0.42', tags: ['infra'] });
  const ctx = await vault.contextFor('server');
  assert.match(ctx, /Server IP/);
});

test('delete removes the memory', async () => {
  const vault = makeVault();
  const mem = await vault.remember({ title: 'temp' });
  vault.delete(mem.id);
  assert.equal(vault.list().length, 0);
});
