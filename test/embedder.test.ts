import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Embedder } from '../src/memory/embedder.ts';

test('cosine similarity basics', () => {
  assert.equal(Embedder.cosine([1, 0], [1, 0]), 1);
  assert.equal(Embedder.cosine([1, 0], [0, 1]), 0);
  assert.ok(Math.abs(Embedder.cosine([1, 1], [1, 0]) - Math.SQRT1_2) < 1e-9);
  assert.equal(Embedder.cosine([0, 0], [1, 1]), 0); // zero vector guard
  assert.equal(Embedder.cosine([], [1, 1]), 0);
});

test('buffer round-trip preserves vectors', () => {
  const vec = [0.5, -1.25, 3.75, 0];
  const buf = Embedder.toBuffer(vec);
  assert.equal(buf.byteLength, vec.length * 4);
  const back = Embedder.fromBuffer(buf);
  assert.deepEqual([...back], vec);
});

test('fromBuffer tolerates odd byte lengths', () => {
  const buf = Buffer.alloc(9); // not a multiple of 4
  const back = Embedder.fromBuffer(buf);
  assert.equal(back.length, 2);
});
