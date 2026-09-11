/**
 * A stand-in for the Ollama HTTP API, used to verify jarvis's Ollama path
 * without needing a GPU or a pulled model on the machine running the check.
 *
 * It reproduces the behaviour that matters, taken from Ollama's own docs and
 * server logs:
 *
 *   - the context window defaults to 4096 tokens (4k on machines under
 *     24 GiB of VRAM) unless the request sets `options.num_ctx`;
 *   - a prompt longer than the window is NOT rejected: Ollama warns in its
 *     log (`level=WARN msg="truncating input prompt" limit=... prompt=...`)
 *     and answers anyway with the FRONT of the prompt thrown away, so the
 *     oldest content — jarvis's system prompt — is the first to go;
 *   - `options.num_ctx` on the native /api/chat endpoint raises that window;
 *   - tool calls come back as `message.tool_calls[].function.arguments` with
 *     arguments as an OBJECT (not OpenAI's JSON string);
 *   - streaming is newline-delimited JSON with a terminal `done: true` chunk
 *     carrying `prompt_eval_count` / `eval_count`.
 *
 * Every request is appended to a JSONL log (OLLAMA_STANDIN_LOG) recording what
 * the "server" actually received, which is how the verifier learns whether the
 * system prompt survived — the same thing you would read out of a real Ollama
 * log line.
 *
 * Run: bun verify/ollama-stand-in.ts
 */

import { appendFileSync } from 'node:fs';

const PORT = Number(process.env.OLLAMA_STANDIN_PORT ?? 11500);
const DEFAULT_NUM_CTX = Number(process.env.OLLAMA_STANDIN_DEFAULT_NUM_CTX ?? 4096);
const LOG_PATH = process.env.OLLAMA_STANDIN_LOG ?? '';

type WireMessage = {
  role: string;
  content: string;
  images?: string[];
  tool_calls?: Array<{ function: { name: string; arguments: unknown } }>;
  tool_name?: string;
  tool_call_id?: string;
};

type ChatRequest = {
  model?: string;
  messages?: WireMessage[];
  stream?: boolean;
  tools?: Array<{ type: string; function: { name: string } }>;
  options?: Record<string, unknown>;
};

/** Ollama's own rough accounting is characters/4; good enough for a probe. */
const approxTokens = (s: string) => Math.ceil(s.length / 4);

type Segment = { kind: 'head' | 'message'; tokens: number; message?: WireMessage };

/**
 * Ollama renders the tool schemas into the prompt, and on the templates jarvis
 * talks to they land in the leading system section (they are by far the largest
 * part of it). Model that as one "head" segment — system instructions + tool
 * schemas — followed by the rest of the conversation. The head is what sits at
 * the very front of the templated prompt, so it is what front-truncation eats
 * first, and a head that is clipped in the middle is the classic "the model
 * ignored half its instructions" failure.
 */
function buildSegments(messages: WireMessage[], tools?: ChatRequest['tools']): Segment[] {
  const segments: Segment[] = [];
  const firstSystemIndex = messages.findIndex((m) => m.role === 'system');
  const headMessage = firstSystemIndex >= 0 ? messages[firstSystemIndex] : undefined;

  const headTokens =
    (tools && tools.length > 0 ? approxTokens(JSON.stringify(tools)) : 0) +
    (headMessage ? approxTokens(headMessage.content) : 0);

  if (headTokens > 0) {
    segments.push({ kind: 'head', tokens: headTokens, message: headMessage });
  }

  messages.forEach((m, i) => {
    if (i === firstSystemIndex) return;
    segments.push({
      kind: 'message',
      message: m,
      tokens: approxTokens(m.content) + approxTokens(JSON.stringify(m.tool_calls ?? '')),
    });
  });

  return segments;
}

/**
 * The prompt is flattened through the model's chat template and then clipped
 * to the loaded window, keeping the tail. Emulated at segment granularity:
 * walk from the end, keep whole segments while the budget lasts, drop
 * everything in front of them — tools block first, then the oldest messages.
 */
function applyContextWindow(messages: WireMessage[], tools: ChatRequest['tools'], limit: number) {
  const segments = buildSegments(messages, tools);
  const promptTokens = segments.reduce((n, s) => n + s.tokens, 0);

  if (promptTokens <= limit) {
    return { kept: segments, promptTokens, droppedTokens: 0, truncated: false };
  }

  const kept: Segment[] = [];
  let used = 0;
  for (let i = segments.length - 1; i >= 0; i--) {
    const entry = segments[i]!;
    if (used + entry.tokens > limit) break;
    kept.unshift(entry);
    used += entry.tokens;
  }

  return { kept, promptTokens, droppedTokens: promptTokens - used, truncated: true };
}

function record(entry: Record<string, unknown>): void {
  if (!LOG_PATH) return;
  try {
    appendFileSync(LOG_PATH, `${JSON.stringify({ ts: new Date().toISOString(), ...entry })}\n`);
  } catch {
    // A missing log file is not the request's problem.
  }
}

function warnTruncation(limit: number, prompt: number, dropped: number): void {
  // Wording mirrors Ollama's runner log so it is recognisable in the output.
  console.log(
    `level=WARN source=runner.go msg="truncating input prompt" limit=${limit} ` +
      `prompt=${prompt} keep=${prompt - dropped}`,
  );
}

function pickToolCall(messages: WireMessage[], tools?: ChatRequest['tools']) {
  if (!tools || tools.length === 0) return undefined;
  const lastUser = [...messages].reverse().find((m) => m.role === 'user');
  if (!lastUser || !lastUser.content.includes('CALL_TOOL')) return undefined;
  return [
    {
      function: {
        name: tools[0]!.function.name,
        // Object, matching the native API — the whole point of the round-trip test.
        arguments: { probe: 'stand-in', echoed: true },
      },
    },
  ];
}

const server = Bun.serve({
  port: PORT,
  hostname: '0.0.0.0',
  async fetch(req) {
    const url = new URL(req.url);

    if (url.pathname === '/api/tags') {
      return Response.json({
        models: [
          { name: 'qwen2.5:3b', model: 'qwen2.5:3b', modified_at: '', size: 1, digest: 'a' },
          { name: 'llama3.1:8b', model: 'llama3.1:8b', modified_at: '', size: 1, digest: 'b' },
        ],
      });
    }

    if (url.pathname !== '/api/chat') {
      return new Response('not found', { status: 404 });
    }

    const body = (await req.json()) as ChatRequest;
    const messages = body.messages ?? [];
    const numCtxSent = body.options?.num_ctx;
    const limit = typeof numCtxSent === 'number' ? numCtxSent : DEFAULT_NUM_CTX;
    const { kept, promptTokens, droppedTokens, truncated } = applyContextWindow(messages, body.tools, limit);

    // Did the leading block — jarvis's role instructions and tool schemas —
    // survive whole? It does not when the window clips the front of the prompt.
    const head = buildSegments(messages, body.tools).find((s) => s.kind === 'head');
    const systemIntact = head ? kept.some((k) => k.kind === 'head') : true;

    record({
      model: body.model,
      stream: body.stream === true,
      num_ctx_sent: numCtxSent ?? null,
      limit,
      prompt_tokens: promptTokens,
      dropped_tokens: droppedTokens,
      truncated,
      system_prompt_intact: systemIntact,
      kept_messages: kept.length,
      sent_messages: messages.length,
      tools_advertised: body.tools?.length ?? 0,
    });

    if (truncated) warnTruncation(limit, promptTokens, droppedTokens);

    const toolCalls = pickToolCall(messages, body.tools);
    const model = body.model ?? 'stand-in';
    const createdAt = new Date().toISOString();
    const promptEvalCount = promptTokens - droppedTokens;

    if (body.stream !== true) {
      return Response.json({
        model,
        created_at: createdAt,
        message: {
          role: 'assistant',
          content: toolCalls ? '' : 'stand-in ok',
          ...(toolCalls ? { tool_calls: toolCalls } : {}),
        },
        done: true,
        prompt_eval_count: promptEvalCount,
        eval_count: 5,
      });
    }

    const assistantStream = toolCalls
      ? { role: 'assistant', content: '', tool_calls: toolCalls }
      : { role: 'assistant', content: 'stand-in ok' };
    const chunks: Array<Record<string, unknown>> = [
      { model, created_at: createdAt, message: assistantStream, done: false },
      {
        model,
        created_at: createdAt,
        message: { role: 'assistant', content: '' },
        done: true,
        prompt_eval_count: promptEvalCount,
        eval_count: 5,
      },
    ];

    const encoder = new TextEncoder();
    return new Response(
      new ReadableStream({
        start(controller) {
          for (const chunk of chunks) controller.enqueue(encoder.encode(`${JSON.stringify(chunk)}\n`));
          controller.close();
        },
      }),
      { headers: { 'Content-Type': 'application/x-ndjson' } },
    );
  },
});

console.log(`Ollama stand-in listening on http://0.0.0.0:${server.port}`);
console.log(`default num_ctx: ${DEFAULT_NUM_CTX} (override with OLLAMA_STANDIN_DEFAULT_NUM_CTX)`);
console.log(`request log: ${LOG_PATH || '(disabled)'}`);
