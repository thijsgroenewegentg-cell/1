/**
 * End-to-end check of jarvis's Ollama path.
 *
 * It deliberately goes through the SAME code the daemon uses — the provider
 * factory from src/llm/config-binding.ts, the real LLMManager and the real
 * tool definitions — and sends a jarvis-shaped request: a system prompt first
 * (role instructions), then ~4.3k tokens of tool schemas, then the user turn.
 *
 * Run it against verify/ollama-stand-in.ts (the default) for a deterministic
 * verdict, or against a real Ollama with OLLAMA_BASE_URL=http://localhost:11434
 * for a smoke test of chat / streaming / tool calls.
 *
 *   bun live-check.ts
 *
 * Environment:
 *   OLLAMA_BASE_URL   default http://127.0.0.1:11500  (the stand-in)
 *   OLLAMA_MODEL      default qwen2.5:3b
 *   OLLAMA_STANDIN_LOG  JSONL written by the stand-in; when set the check
 *                       also reports whether the system prompt survived.
 */

import { existsSync, readFileSync } from 'node:fs';
import { LLMManager } from './src/llm/index.ts';
import { configureLLMTiers, instantiateProvider } from './src/llm/config-binding.ts';
import { BUILTIN_TOOLS, toolDefToLLMTool } from './src/actions/tools/builtin.ts';
import type { LLMMessage, LLMTool } from './src/llm/provider.ts';

const BASE_URL = process.env.OLLAMA_BASE_URL ?? 'http://127.0.0.1:11500';
const MODEL = process.env.OLLAMA_MODEL ?? 'qwen2.5:3b';
const LOG_PATH = process.env.OLLAMA_STANDIN_LOG ?? '';
const SENTINEL = 'JARVIS-ROLE-INSTRUCTIONS-SENTINEL';

/** The real provider instance the daemon would build from an ollama config entry. */
function buildManager(): LLMManager {
  const provider = instantiateProvider('ollama', { kind: 'ollama', base_url: BASE_URL });
  if (!provider) throw new Error('instantiateProvider returned null for kind=ollama');
  const manager = new LLMManager();
  manager.registerProvider(provider);
  configureLLMTiers(manager, { default: `ollama:${MODEL}` });
  return manager;
}

function jarvisShapedTurn(): { messages: LLMMessage[]; tools: LLMTool[] } {
  // Mirrors the real ordering: instructions first (that is what Ollama's
  // front-truncation deletes), tool schemas on the side.
  const role = [
    `${SENTINEL}`,
    'You are J.A.R.V.I.S., an autonomous assistant. Follow these standing rules:',
    ...Array.from({ length: 120 }, (_, i) =>
      `Rule ${i + 1}: keep working memory consistent, prefer tools over guesswork, and never invent tool output.`,
    ),
  ].join('\n');

  const messages: LLMMessage[] = [
    { role: 'system', content: role, cache: true },
    { role: 'user', content: 'Reply with the single word: READY' },
  ];

  return { messages, tools: BUILTIN_TOOLS.map(toolDefToLLMTool) };
}

function readStandinRecords(): Array<Record<string, unknown>> {
  if (!LOG_PATH || !existsSync(LOG_PATH)) return [];
  return readFileSync(LOG_PATH, 'utf8')
    .split('\n')
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l) as Record<string, unknown>);
}

async function main(): Promise<void> {
  console.log(`target          : ${BASE_URL}`);
  console.log(`model           : ${MODEL}`);
  console.log(`tools advertised: ${BUILTIN_TOOLS.length}\n`);

  const manager = buildManager();

  // 1. Model discovery, through the provider the daemon built.
  const provider = manager.getProvider('ollama')!;
  const models = await provider.listModels();
  console.log(`listModels()    : ${models.join(', ')}`);

  const { messages, tools } = jarvisShapedTurn();

  // 2. Non-streaming chat, with the full jarvis payload.
  const chat = await manager.chatTier('medium', 'verify_ollama_chat', messages, {
    tools,
    max_tokens: 32,
  });
  console.log(`chat()          : "${chat.content}" model=${chat.model}`);

  // 3. Streaming, same payload — the path the daemon actually uses.
  let streamed = '';
  let streamError = '';
  for await (const event of manager.streamTier('medium', 'verify_ollama_stream', messages, {
    tools,
    max_tokens: 32,
  })) {
    if (event.type === 'text') streamed += event.text;
    if (event.type === 'error') streamError = event.error;
  }
  console.log(`stream()        : "${streamed}"${streamError ? ` error=${streamError}` : ''}`);

  // 4. Tool-call round trip: the stand-in answers with a tool call the way
  //    Ollama does (arguments as an object, not a JSON string).
  const toolTurn: LLMMessage[] = [
    { role: 'system', content: `${SENTINEL}\nRules apply.` },
    { role: 'user', content: 'CALL_TOOL please' },
  ];
  const toolReply = await manager.chatTier('medium', 'verify_ollama_tool', toolTurn, { tools, max_tokens: 32 });
  const toolCall = toolReply.tool_calls?.[0];
  console.log(
    `tool call       : ${toolCall ? `${toolCall.name}(${JSON.stringify(toolCall.arguments)})` : 'none'}`,
  );

  // 5. What did the "server" actually receive?
  const records = readStandinRecords();
  let systemIntact: boolean | null = null;

  if (records.length > 0) {
    console.log('\nserver-side request log (what the model really saw):');
    for (const r of records) {
      console.log(
        `  num_ctx_sent=${r.num_ctx_sent ?? 'MISSING'} limit=${r.limit} ` +
          `prompt=${r.prompt_tokens} dropped=${r.dropped_tokens} ` +
          `system_prompt_intact=${r.system_prompt_intact}`,
      );
    }
    systemIntact = records.every((r) => r.system_prompt_intact === true);
  } else {
    console.log('\n(no stand-in log configured — skipping the truncation verdict; smoke test only)');
  }

  const checks = {
    listModels: models.length > 0,
    chat: chat.content.length > 0,
    stream: streamed.length > 0 && !streamError,
    toolCalls: Boolean(toolCall),
    ...(systemIntact === null ? {} : { systemPromptIntact: systemIntact }),
  };
  const ok = Object.values(checks).every(Boolean);

  console.log('');
  for (const [name, pass] of Object.entries(checks)) {
    console.log(`  ${pass ? 'PASS' : 'FAIL'}  ${name}`);
  }
  console.log(`\nVERDICT ${JSON.stringify({ ok, checks })}`);

  // Exit explicitly: the HTTP keep-alive sockets left over from these calls
  // keep the event loop alive for ~90s otherwise, which would make the whole
  // verification look slow for no reason.
  process.exit(ok ? 0 : 1);
}

main().catch((err) => {
  console.error(`verification failed: ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
