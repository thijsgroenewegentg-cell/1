import { test } from 'node:test';
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import path from 'node:path';
import { loadConfig, DEFAULT_CONFIG } from '../src/config.ts';
import { tmpDir } from './helpers.ts';

test('loadConfig returns defaults when no config.yaml exists', () => {
  const home = tmpDir();
  const cfg = loadConfig(home);
  assert.equal(cfg.daemon.port, 3142);
  assert.equal(cfg.ollama.model, DEFAULT_CONFIG.ollama.model);
  assert.ok(path.isAbsolute(cfg.daemon.data_dir), 'data_dir resolved to absolute');
});

test('loadConfig merges config.yaml over defaults', () => {
  const home = tmpDir();
  writeFileSync(
    path.join(home, 'config.yaml'),
    ['daemon:', '  port: 4242', 'ollama:', '  model: qwen2.5:7b', 'authority:', '  level: 1'].join('\n'),
  );
  const cfg = loadConfig(home);
  assert.equal(cfg.daemon.port, 4242);
  assert.equal(cfg.ollama.model, 'qwen2.5:7b');
  assert.equal(cfg.authority.level, 1);
  assert.equal(cfg.ollama.base_url, 'http://localhost:11434'); // default kept
});

test('env vars override config file', () => {
  const home = tmpDir();
  writeFileSync(path.join(home, 'config.yaml'), 'daemon:\n  port: 4242\n');
  process.env.JARVIS_PORT = '5555';
  process.env.JARVIS_OLLAMA_MODEL = 'mistral';
  try {
    const cfg = loadConfig(home);
    assert.equal(cfg.daemon.port, 5555);
    assert.equal(cfg.ollama.model, 'mistral');
  } finally {
    delete process.env.JARVIS_PORT;
    delete process.env.JARVIS_OLLAMA_MODEL;
  }
});

test('authority level is clamped to 0..4', () => {
  const home = tmpDir();
  writeFileSync(path.join(home, 'config.yaml'), 'authority:\n  level: 99\n');
  assert.equal(loadConfig(home).authority.level, 4);
  writeFileSync(path.join(home, 'config.yaml'), 'authority:\n  level: -3\n');
  assert.equal(loadConfig(home).authority.level, 0);
});
