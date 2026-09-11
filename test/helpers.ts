import http from 'node:http';
import { mkdtempSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DEFAULT_CONFIG, type JarvisConfig } from '../src/config.ts';
import type { ChatMessage } from '../src/llm/ollama.ts';

export interface CannedResponse {
  content?: string;
  tool_calls?: { function: { name: string; arguments: Record<string, unknown> } }[];
}

export interface MockOllama {
  url: string;
  port: number;
  /** Responses are consumed FIFO, one per /api/chat call. */
  enqueue: (...responses: CannedResponse[]) => void;
  requests: { messages: ChatMessage[]; tools?: unknown[] }[];
  close: () => Promise<void>;
}

/**
 * A scripted fake Ollama: /api/tags, /api/pull, /api/embed and /api/chat
 * (both streaming ndjson and one-shot JSON), so tests run without a GPU.
 */
export async function startMockOllama(): Promise<MockOllama> {
  const queue: CannedResponse[] = [];
  const requests: MockOllama['requests'] = [];

  const server = http.createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : {};

      if (req.method === 'GET' && req.url === '/api/tags') {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ models: [{ name: 'llama3.2', size: 2_000_000_000 }, { name: 'llama3.2:1b', size: 1_000_000_000 }] }));
        return;
      }
      if (req.method === 'POST' && req.url === '/api/pull') {
        res.writeHead(200, { 'content-type': 'application/x-ndjson' });
        res.write(JSON.stringify({ status: 'pulling manifest' }) + '\n');
        res.end(JSON.stringify({ status: 'success' }) + '\n');
        return;
      }
      if (req.method === 'POST' && req.url === '/api/embed') {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ embeddings: [[0.1, 0.2, 0.3]] }));
        return;
      }
      if (req.method === 'POST' && req.url === '/api/chat') {
        requests.push({ messages: body.messages, tools: body.tools });
        const next = queue.shift() ?? { content: '(mock: no script left)' };
        if (body.stream) {
          res.writeHead(200, { 'content-type': 'application/x-ndjson' });
          const text = next.content ?? '';
          for (const token of text.split(/(?<=\s)/)) {
            res.write(JSON.stringify({ message: { role: 'assistant', content: token }, done: false }) + '\n');
          }
          const last: Record<string, unknown> = { message: { role: 'assistant', content: '' }, done: true };
          if (next.tool_calls) (last.message as Record<string, unknown>).tool_calls = next.tool_calls;
          res.end(JSON.stringify(last) + '\n');
          return;
        }
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(
          JSON.stringify({
            message: { role: 'assistant', content: next.content ?? '', tool_calls: next.tool_calls },
            done: true,
          }),
        );
        return;
      }
      res.writeHead(404);
      res.end('not found');
    });
  });

  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as { port: number }).port;
  return {
    url: `http://127.0.0.1:${port}`,
    port,
    requests,
    enqueue: (...responses) => queue.push(...responses),
    close: () => new Promise((resolve) => server.close(() => resolve())),
  };
}

export function tmpDir(): string {
  return mkdtempSync(path.join(os.tmpdir(), 'jarvis-test-'));
}

export function testConfig(home: string, ollamaUrl: string): JarvisConfig {
  const cfg = structuredClone(DEFAULT_CONFIG);
  cfg.daemon.data_dir = path.join(home, 'data');
  cfg.ollama.base_url = ollamaUrl;
  cfg.cron = { morning: '0 7 * * *', evening: '0 20 * * *', hourly: '37 * * * *' };
  return cfg;
}
