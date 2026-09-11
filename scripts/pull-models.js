#!/usr/bin/env node
/** Pull the models configured in config.yaml from the Ollama registry. */
import { loadConfig } from '../src/config.ts';
import { OllamaClient } from '../src/llm/ollama.ts';

const cfg = loadConfig();
const ollama = new OllamaClient(cfg.ollama.base_url);

if (!(await ollama.ok())) {
  console.error(`Cannot reach Ollama at ${cfg.ollama.base_url} — run \`ollama serve\` first.`);
  process.exit(1);
}

const installed = await ollama.listModels();
for (const model of [cfg.ollama.model, cfg.ollama.fast_model]) {
  if (!model) continue;
  if (ollama.hasModel(installed, model)) {
    console.log(`✓ ${model} already installed`);
    continue;
  }
  console.log(`⬇ pulling ${model}…`);
  await ollama.pull(model, (status) => process.stdout.write(`\r  ${status.padEnd(64)}`));
  console.log(`\n✓ ${model} ready`);
}
